use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

/// A mathematical claim (lemma, theorem, or auxiliary result).
/// Status follows a strict one-way progression: Proposed → Verified | Rejected.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Claim {
    pub id: String,
    pub statement: String,
    pub claim_type: ClaimType,
    pub status: ClaimStatus,
    /// IDs of verified claims this claim depends on.
    pub dependencies: Vec<String>,
    /// Artifacts produced by each verifier layer.
    pub verification_artifacts: Vec<VerificationArtifact>,
    /// SHA-256 of the canonical statement.
    pub proof_hash: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    /// Which beam branch this claim belongs to.
    pub branch_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ClaimType {
    Lemma,
    Theorem,
    Auxiliary,
    Definition,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ClaimStatus {
    Proposed,
    Verified,
    Rejected,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VerificationArtifact {
    pub stage: String,
    pub result: String,
    pub details: serde_json::Value,
    pub timestamp: DateTime<Utc>,
}

impl VerificationArtifact {
    /// Require an explicit, statement-bound V5 certificate from the trusted worker.
    pub fn supports_statement(&self, statement: &str) -> bool {
        let d = &self.details;
        let Some(source) = d["lean_source"].as_str() else {
            return false;
        };
        let Some(axioms) = d["axioms"].as_array() else {
            return false;
        };
        self.stage == "V5"
            && self.result == "passed"
            && d["outcome"] == "passed"
            && d["policy"] == "lean-kernel-v1"
            && d["lean_result"] == "compiled"
            && d["statement"].as_str() == Some(statement.trim())
            && !source.is_empty()
            && d["source_sha256"].as_str()
                == Some(hex::encode(Sha256::digest(source.as_bytes())).as_str())
            && axioms.iter().all(|a| {
                matches!(
                    a.as_str(),
                    Some("propext" | "Classical.choice" | "Quot.sound")
                )
            })
    }
}

impl Claim {
    pub fn new(
        statement: impl Into<String>,
        claim_type: ClaimType,
        dependencies: Vec<String>,
        branch_id: impl Into<String>,
    ) -> Self {
        let stmt = statement.into();
        let proof_hash = Self::hash_statement(&stmt);
        let now = Utc::now();
        Self {
            id: Uuid::new_v4().to_string(),
            statement: stmt,
            claim_type,
            status: ClaimStatus::Proposed,
            dependencies,
            verification_artifacts: Vec::new(),
            proof_hash,
            created_at: now,
            updated_at: now,
            branch_id: branch_id.into(),
        }
    }

    /// SHA-256 of the trimmed statement; mathematical identifiers are case-sensitive.
    pub fn hash_statement(statement: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(statement.trim().as_bytes());
        hex::encode(hasher.finalize())
    }

    /// Attempt to mark this claim as verified. Returns Err if already rejected.
    pub fn verify(&mut self, artifact: VerificationArtifact) -> anyhow::Result<()> {
        if self.status == ClaimStatus::Rejected {
            anyhow::bail!("Cannot verify a rejected claim: {}", self.id);
        }
        anyhow::ensure!(
            artifact.supports_statement(&self.statement),
            "Claim requires statement-bound Lean evidence"
        );
        self.status = ClaimStatus::Verified;
        self.verification_artifacts.push(artifact);
        self.updated_at = Utc::now();
        Ok(())
    }

    /// Rejected claims are immutable: once rejected, cannot be changed.
    pub fn reject(&mut self, reason: impl Into<String>) -> anyhow::Result<()> {
        if self.status == ClaimStatus::Verified {
            anyhow::bail!("Cannot reject a verified claim: {}", self.id);
        }
        self.status = ClaimStatus::Rejected;
        self.verification_artifacts.push(VerificationArtifact {
            stage: "reject".into(),
            result: "rejected".into(),
            details: serde_json::json!({ "reason": reason.into() }),
            timestamp: Utc::now(),
        });
        self.updated_at = Utc::now();
        Ok(())
    }

    pub fn is_verified(&self) -> bool {
        self.status == ClaimStatus::Verified
            && self
                .verification_artifacts
                .iter()
                .any(|a| a.supports_statement(&self.statement))
    }

    pub fn is_rejected(&self) -> bool {
        self.status == ClaimStatus::Rejected
    }
}
