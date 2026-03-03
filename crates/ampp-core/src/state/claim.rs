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

    /// Canonical SHA-256 hash of the trimmed, lowercased statement.
    pub fn hash_statement(statement: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(statement.trim().to_lowercase().as_bytes());
        hex::encode(hasher.finalize())
    }

    /// Attempt to mark this claim as verified. Returns Err if already rejected.
    pub fn verify(&mut self, artifact: VerificationArtifact) -> anyhow::Result<()> {
        if self.status == ClaimStatus::Rejected {
            anyhow::bail!("Cannot verify a rejected claim: {}", self.id);
        }
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
    }

    pub fn is_rejected(&self) -> bool {
        self.status == ClaimStatus::Rejected
    }
}
