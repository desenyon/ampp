use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A record of a failed proof attempt, stored permanently for pattern analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Attempt {
    pub id: String,
    pub branch_id: String,
    pub failed_claim_id: String,
    pub failure_reason: String,
    pub verifier_stage: VerifierStage,
    pub timestamp: DateTime<Utc>,
    /// Raw verifier output for post-mortem.
    pub raw_output: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum VerifierStage {
    V0Structural,
    V1Counterexample,
    V2Symbolic,
    V3Smt,
    V4Atp,
    V5Lean,
    RubricGate,
}

impl std::fmt::Display for VerifierStage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            VerifierStage::V0Structural => write!(f, "V0_STRUCTURAL"),
            VerifierStage::V1Counterexample => write!(f, "V1_COUNTEREXAMPLE"),
            VerifierStage::V2Symbolic => write!(f, "V2_SYMBOLIC"),
            VerifierStage::V3Smt => write!(f, "V3_SMT"),
            VerifierStage::V4Atp => write!(f, "V4_ATP"),
            VerifierStage::V5Lean => write!(f, "V5_LEAN"),
            VerifierStage::RubricGate => write!(f, "RUBRIC_GATE"),
        }
    }
}

impl Attempt {
    pub fn new(
        branch_id: impl Into<String>,
        failed_claim_id: impl Into<String>,
        failure_reason: impl Into<String>,
        verifier_stage: VerifierStage,
        raw_output: Option<serde_json::Value>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            branch_id: branch_id.into(),
            failed_claim_id: failed_claim_id.into(),
            failure_reason: failure_reason.into(),
            verifier_stage,
            timestamp: Utc::now(),
            raw_output,
        }
    }
}
