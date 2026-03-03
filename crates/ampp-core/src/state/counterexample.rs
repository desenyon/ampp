use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A concrete counterexample that refutes a claim at V1.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Counterexample {
    pub id: String,
    pub claim_id: String,
    /// The concrete mathematical object that falsifies the claim.
    pub witness_structure: serde_json::Value,
    /// How this counterexample was generated.
    pub generation_method: GenerationMethod,
    pub seed: Option<u64>,
    /// Structural features for guided refinement.
    pub extracted_features: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GenerationMethod {
    ExhaustiveEnumeration,
    RandomPropertyTesting,
    BoundaryTesting,
    SolverModel,
}

impl Counterexample {
    pub fn new(
        claim_id: impl Into<String>,
        witness_structure: serde_json::Value,
        generation_method: GenerationMethod,
        seed: Option<u64>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            claim_id: claim_id.into(),
            witness_structure,
            generation_method,
            seed,
            extracted_features: Vec::new(),
        }
    }
}
