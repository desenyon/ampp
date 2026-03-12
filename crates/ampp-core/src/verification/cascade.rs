use crate::state::{
    Attempt, Claim, ClaimStatus, ClaimType, StepCandidate, VerificationArtifact, VerifierStage,
};
use crate::store::ProofStore;
use crate::verification::v0_structural::StructuralChecker;
use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Outcome of running one candidate through the full cascade.
#[derive(Debug, Serialize, Deserialize)]
pub enum VerificationResult {
    /// All required stages passed; claim is now verified.
    Verified {
        claim: Claim,
        artifacts: Vec<VerificationArtifact>,
    },
    /// Some stage rejected the candidate.
    Rejected {
        stage: VerifierStage,
        reason: String,
    },
    /// Cascade could not complete (infrastructure error).
    Error { message: String },
}

/// JSON-RPC request sent to the Python worker.
#[derive(Debug, Serialize, Deserialize)]
pub struct PythonVerifyRequest {
    pub request_id: String,
    pub stage: String,
    pub candidate_json: serde_json::Value,
    pub context: serde_json::Value,
}

/// JSON-RPC response from the Python worker.
#[derive(Debug, Serialize, Deserialize)]
pub struct PythonVerifyResponse {
    pub request_id: String,
    pub stage: String,
    pub passed: bool,
    pub details: serde_json::Value,
    pub counterexample: Option<serde_json::Value>,
}

/// Orchestrates all verification stages for a StepCandidate.
///
/// V0 runs in-process (Rust).  
/// V1–V5 are delegated to the Python worker via JSON over stdin/stdout.
pub struct VerificationCascade<'a> {
    store: &'a ProofStore,
    /// Callable that sends a request to the Python worker and returns a response.
    python_caller: Box<dyn Fn(PythonVerifyRequest) -> Result<PythonVerifyResponse> + 'a>,
}

impl<'a> VerificationCascade<'a> {
    pub fn new(
        store: &'a ProofStore,
        python_caller: impl Fn(PythonVerifyRequest) -> Result<PythonVerifyResponse> + 'a,
    ) -> Self {
        Self {
            store,
            python_caller: Box::new(python_caller),
        }
    }

    /// Run the full cascade for a StepCandidate.
    pub fn run(&self, candidate: &StepCandidate, branch_id: &str) -> Result<VerificationResult> {
        // ── Duplicate hash guard ──────────────────────────────────────────────
        if self.store.claim_hash_rejected(&candidate.candidate_hash)? {
            return Ok(VerificationResult::Rejected {
                stage: VerifierStage::V0Structural,
                reason: "duplicate hash: previously rejected".into(),
            });
        }

        // ── Collect verified claim IDs for dependency check ───────────────────
        let verified: HashSet<String> = self
            .store
            .get_verified_claims(branch_id)?
            .into_iter()
            .map(|c| c.id)
            .collect();

        let definitions = self.store.get_all_definitions()?;

        // ── V0: Structural checks (in-process) ────────────────────────────────
        let v0 = StructuralChecker::check(candidate, &definitions, &verified)?;
        if !v0.passed {
            let reason = v0.failures.join("; ");
            self.record_failure(candidate, branch_id, VerifierStage::V0Structural, &reason)?;
            return Ok(VerificationResult::Rejected {
                stage: VerifierStage::V0Structural,
                reason,
            });
        }
        let mut artifacts = vec![VerificationArtifact {
            stage: "V0".into(),
            result: "passed".into(),
            details: serde_json::json!({ "checks": "structural" }),
            timestamp: Utc::now(),
        }];

        // ── V1–V5: Python workers ────────────────────────────────────────────
        let python_stages = [
            ("V1", VerifierStage::V1Counterexample),
            ("V2", VerifierStage::V2Symbolic),
            ("V3", VerifierStage::V3Smt),
            ("V4", VerifierStage::V4Atp),
            ("V5", VerifierStage::V5Lean),
        ];

        let planned_stages: HashSet<&str> = candidate
            .verification_plan
            .stages
            .iter()
            .map(String::as_str)
            .collect();

        for (stage_name, stage_enum) in &python_stages {
            if !planned_stages.contains(stage_name) {
                continue;
            }

            let request = PythonVerifyRequest {
                request_id: uuid::Uuid::new_v4().to_string(),
                stage: stage_name.to_string(),
                candidate_json: serde_json::to_value(candidate)?,
                context: serde_json::json!({
                    "branch_id": branch_id,
                    "verified_claim_ids": verified.iter().collect::<Vec<_>>(),
                }),
            };

            let response = (self.python_caller)(request)?;

            artifacts.push(VerificationArtifact {
                stage: stage_name.to_string(),
                result: if response.passed {
                    "passed".into()
                } else {
                    "failed".into()
                },
                details: response.details.clone(),
                timestamp: Utc::now(),
            });

            if !response.passed {
                let reason = response
                    .details
                    .get("reason")
                    .and_then(|v| v.as_str())
                    .unwrap_or("verifier rejected")
                    .to_string();

                self.record_failure(candidate, branch_id, stage_enum.clone(), &reason)?;
                self.store
                    .register_rejected_hash(&candidate.candidate_hash)?;

                return Ok(VerificationResult::Rejected {
                    stage: stage_enum.clone(),
                    reason,
                });
            }
        }

        // ── Two-phase commit ──────────────────────────────────────────────────
        let mut claim = Claim::new(
            &candidate.new_claims[0].statement,
            ClaimType::Lemma,
            candidate.dependencies.clone(),
            branch_id,
        );
        claim.status = ClaimStatus::Verified;
        claim.verification_artifacts.extend(artifacts.clone());
        self.store.insert_claim(&claim)?;
        tracing::info!(
            claim_id = %claim.id,
            branch_id = %branch_id,
            "✓ Claim verified and committed"
        );

        Ok(VerificationResult::Verified { claim, artifacts })
    }

    fn record_failure(
        &self,
        candidate: &StepCandidate,
        branch_id: &str,
        stage: VerifierStage,
        reason: &str,
    ) -> Result<()> {
        let attempt = Attempt::new(
            branch_id,
            &candidate.id,
            reason,
            stage,
            Some(serde_json::to_value(candidate)?),
        );
        self.store.insert_attempt(&attempt)?;
        Ok(())
    }
}
