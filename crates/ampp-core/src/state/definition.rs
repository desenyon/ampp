use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

/// A mathematical definition that anchors terminology used in claims.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Definition {
    pub id: String,
    pub statement: String,
    /// The identifier used in Lean4 theorems (e.g. `Nat.Prime`).
    pub lean_name: String,
    pub canonical_form: String,
    pub hash: String,
}

impl Definition {
    pub fn new(
        statement: impl Into<String>,
        lean_name: impl Into<String>,
        canonical_form: impl Into<String>,
    ) -> Self {
        let stmt = statement.into();
        let mut hasher = Sha256::new();
        hasher.update(stmt.trim().to_lowercase().as_bytes());
        let hash = hex::encode(hasher.finalize());
        Self {
            id: Uuid::new_v4().to_string(),
            statement: stmt,
            lean_name: lean_name.into(),
            canonical_form: canonical_form.into(),
            hash,
        }
    }
}
