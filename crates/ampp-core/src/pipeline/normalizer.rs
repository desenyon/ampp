use serde::{Deserialize, Serialize};

/// Formal specification produced by the Normalizer from a raw problem string.
/// All informal ambiguity is resolved at this stage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FormalSpec {
    /// Human-readable problem statement (original).
    pub raw_statement: String,
    /// Canonicalised statement used downstream.
    pub canonical_statement: String,
    /// Variable declarations: name → domain.
    pub variables: std::collections::HashMap<String, String>,
    /// Quantifiers in order of appearance.
    pub quantifiers: Vec<QuantifierSpec>,
    /// Constraints (preconditions).
    pub constraints: Vec<String>,
    /// The target theorem statement.
    pub target: String,
    /// Known edge cases to test.
    pub edge_cases: Vec<String>,
    /// Lean4 namespace for this problem.
    pub lean_namespace: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuantifierSpec {
    pub quantifier: QuantifierKind,
    pub variable: String,
    pub domain: String,
    pub predicate: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum QuantifierKind {
    ForAll,
    Exists,
    ExistsUnique,
}

impl FormalSpec {
    /// Produce a SHA-256 fingerprint of the canonical statement.
    pub fn fingerprint(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(self.canonical_statement.trim().to_lowercase().as_bytes());
        hex::encode(hasher.finalize())
    }
}
