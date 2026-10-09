use crate::state::{Attempt, Claim, ClaimType, StepCandidate, VerificationArtifact, VerifierStage};
use crate::store::ProofStore;
use crate::verification::v0_structural::StructuralChecker;
use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Outcome of a policy-controlled verification attempt.
#[derive(Debug, Serialize, Deserialize)]
pub enum VerificationResult {
    Verified {
        claim: Claim,
        artifacts: Vec<VerificationArtifact>,
    },
    Rejected {
        stage: VerifierStage,
        reason: String,
    },
    /// Missing tools or insufficient evidence; safe to retry after repair.
    Unverified {
        stage: VerifierStage,
        reason: String,
    },
    Error {
        message: String,
    },
}

#[derive(Debug, Serialize, Deserialize)]
pub struct PythonVerifyRequest {
    pub request_id: String,
    pub stage: String,
    pub candidate_json: serde_json::Value,
    pub context: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct PythonVerifyResponse {
    pub request_id: String,
    pub stage: String,
    pub passed: bool,
    pub details: serde_json::Value,
    pub counterexample: Option<serde_json::Value>,
}

/// V0 and V5 are mandatory. Candidate-selected V1–V4 diagnostics may reject,
/// but their absence, success, or inconclusiveness can never substitute for V5.
pub struct VerificationCascade<'a> {
    store: &'a ProofStore,
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

    pub fn run(&self, candidate: &StepCandidate, branch_id: &str) -> Result<VerificationResult> {
        let verification_hash = candidate.verification_hash();
        let verified: HashSet<String> = self
            .store
            .get_verified_claims(branch_id)?
            .into_iter()
            .map(|c| c.id)
            .collect();
        let definitions = self.store.get_all_definitions()?;
        let mut v0 = StructuralChecker::check(candidate, &definitions, &verified)?;
        if candidate.branch_id != branch_id {
            v0.failures
                .push("candidate belongs to a different branch".into());
        }
        if self.store.claim_hash_rejected(&verification_hash)? {
            v0.failures
                .push("duplicate hash: identical verification attempt previously rejected".into());
        }
        let mut artifacts = vec![VerificationArtifact {
            stage: "V0".into(),
            result: if v0.failures.is_empty() {
                "passed"
            } else {
                "failed"
            }
            .into(),
            details: serde_json::json!({"failures": v0.failures}),
            timestamp: Utc::now(),
        }];
        if !v0.failures.is_empty() {
            let reason = v0.failures.join("; ");
            self.record(
                candidate,
                branch_id,
                VerifierStage::V0Structural,
                &reason,
                "rejected",
                &artifacts,
            )?;
            return Ok(VerificationResult::Rejected {
                stage: VerifierStage::V0Structural,
                reason,
            });
        }

        let python_stages = [
            ("V1", VerifierStage::V1Counterexample),
            ("V2", VerifierStage::V2Symbolic),
            ("V3", VerifierStage::V3Smt),
            ("V4", VerifierStage::V4Atp),
            ("V5", VerifierStage::V5Lean),
        ];
        for (name, stage) in python_stages {
            if name != "V5" && !candidate.verification_plan.stages.iter().any(|s| s == name) {
                continue;
            }
            let request_id = uuid::Uuid::new_v4().to_string();
            let request = PythonVerifyRequest {
                request_id: request_id.clone(),
                stage: name.into(),
                candidate_json: serde_json::to_value(candidate)?,
                context: serde_json::json!({"branch_id": branch_id, "verified_claim_ids": verified}),
            };
            let response = match (self.python_caller)(request) {
                Ok(response) => response,
                Err(error) => {
                    let message = format!("{name} worker error: {error}");
                    artifacts.push(VerificationArtifact {
                        stage: name.into(),
                        result: "error".into(),
                        details: serde_json::json!({"reason": message}),
                        timestamp: Utc::now(),
                    });
                    self.record(candidate, branch_id, stage, &message, "error", &artifacts)?;
                    return Ok(VerificationResult::Error { message });
                }
            };
            let outcome = response.details["outcome"].as_str().unwrap_or("error");
            let valid_outcome = matches!(
                outcome,
                "passed" | "failed" | "inconclusive" | "unavailable" | "error"
            );
            if response.request_id != request_id
                || response.stage != name
                || !response.details.is_object()
                || !valid_outcome
                || response.passed != (outcome == "passed")
                || (response.passed && response.counterexample.is_some())
            {
                let message = format!("{name} invalid or mismatched verifier response");
                artifacts.push(VerificationArtifact {
                    stage: name.into(),
                    result: "error".into(),
                    details: serde_json::json!({"reason": message, "response": response}),
                    timestamp: Utc::now(),
                });
                self.record(candidate, branch_id, stage, &message, "error", &artifacts)?;
                return Ok(VerificationResult::Error { message });
            }
            let mut details = response.details.clone();
            if let Some(witness) = response.counterexample {
                details["counterexample"] = witness;
            }
            artifacts.push(VerificationArtifact {
                stage: name.into(),
                result: outcome.into(),
                details,
                timestamp: Utc::now(),
            });
            let reason = response.details["reason"]
                .as_str()
                .unwrap_or("insufficient verification evidence")
                .to_owned();
            if outcome == "failed" {
                self.record(
                    candidate,
                    branch_id,
                    stage.clone(),
                    &reason,
                    "rejected",
                    &artifacts,
                )?;
                self.store.register_rejected_hash(&verification_hash)?;
                return Ok(VerificationResult::Rejected { stage, reason });
            }
            if outcome == "error" {
                self.record(candidate, branch_id, stage, &reason, "error", &artifacts)?;
                return Ok(VerificationResult::Error { message: reason });
            }
            if name == "V5"
                && !artifacts
                    .last()
                    .unwrap()
                    .supports_statement(&candidate.new_claims[0].statement)
            {
                let reason = if outcome == "passed" {
                    "V5 returned no valid statement-bound Lean evidence".into()
                } else {
                    reason
                };
                self.record(
                    candidate,
                    branch_id,
                    stage.clone(),
                    &reason,
                    "unverified",
                    &artifacts,
                )?;
                return Ok(VerificationResult::Unverified { stage, reason });
            }
        }

        let claim_type = match candidate.new_claims[0].claim_type.as_str() {
            "theorem" => ClaimType::Theorem,
            "auxiliary" => ClaimType::Auxiliary,
            _ => ClaimType::Lemma,
        };
        let mut claim = Claim::new(
            &candidate.new_claims[0].statement,
            claim_type,
            candidate.dependencies.clone(),
            branch_id,
        );
        let certificate = artifacts.last().unwrap().clone();
        claim
            .verification_artifacts
            .extend(artifacts[..artifacts.len() - 1].iter().cloned());
        claim.verify(certificate)?;
        self.store.insert_claim(&claim)?;
        Ok(VerificationResult::Verified { claim, artifacts })
    }

    fn record(
        &self,
        candidate: &StepCandidate,
        branch_id: &str,
        stage: VerifierStage,
        reason: &str,
        outcome: &str,
        artifacts: &[VerificationArtifact],
    ) -> Result<()> {
        self.store.insert_attempt(&Attempt::new(branch_id, &candidate.id, reason, stage, Some(serde_json::json!({
            "candidate": candidate, "verification_hash": candidate.verification_hash(), "outcome": outcome, "artifacts": artifacts,
        }))))
    }
}
