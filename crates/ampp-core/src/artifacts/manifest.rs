use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Full run manifest — written to run_manifest.json for reproducibility.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunManifest {
    pub run_id: String,
    pub started_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
    pub problem_fingerprint: String,
    pub problem_statement: String,
    pub rust_version: String,
    pub python_version: String,
    pub lean_version: String,
    pub sympy_version: String,
    pub z3_version: String,
    pub random_seed: u64,
    /// tool_name → version
    pub tool_versions: HashMap<String, String>,
    /// hash of each produced artifact file
    pub artifact_hashes: HashMap<String, String>,
    pub termination_condition: Option<TerminationCondition>,
    pub beam_summary: Vec<BranchSummary>,
    pub total_verified_claims: usize,
    pub total_rejected_claims: usize,
    pub total_attempts: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminationCondition {
    TheoremVerified,
    FiniteExhaustiveVerification,
    Incomplete { reason: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchSummary {
    pub branch_id: String,
    pub strategy: String,
    pub verified_claims: usize,
    pub rejected_claims: usize,
    pub pruned: bool,
}

/// Paths to all required output artifacts.
#[derive(Debug, Clone)]
pub struct ArtifactSet {
    pub output_dir: PathBuf,
}

impl ArtifactSet {
    pub fn new(output_dir: impl Into<PathBuf>) -> Self {
        Self {
            output_dir: output_dir.into(),
        }
    }

    pub fn solution_lean(&self) -> PathBuf {
        self.output_dir.join("solution.lean")
    }

    pub fn solution_md(&self) -> PathBuf {
        self.output_dir.join("solution.md")
    }

    pub fn proof_graph_json(&self) -> PathBuf {
        self.output_dir.join("proof_graph.json")
    }

    pub fn verification_log_json(&self) -> PathBuf {
        self.output_dir.join("verification_log.json")
    }

    pub fn rejected_claims_json(&self) -> PathBuf {
        self.output_dir.join("rejected_claims.json")
    }

    pub fn run_manifest_json(&self) -> PathBuf {
        self.output_dir.join("run_manifest.json")
    }

    /// Ensure output directory exists.
    pub fn create_dirs(&self) -> Result<()> {
        std::fs::create_dir_all(&self.output_dir)?;
        Ok(())
    }

    /// Compute SHA-256 hash of a file's contents.
    pub fn hash_file(path: &Path) -> Result<String> {
        use sha2::{Digest, Sha256};
        let bytes = std::fs::read(path)?;
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        Ok(hex::encode(hasher.finalize()))
    }

    /// Collect all artifact hashes (only for files that exist).
    pub fn collect_hashes(&self) -> Result<HashMap<String, String>> {
        let mut map = HashMap::new();
        for (name, path) in [
            ("solution.lean", self.solution_lean()),
            ("solution.md", self.solution_md()),
            ("proof_graph.json", self.proof_graph_json()),
            ("verification_log.json", self.verification_log_json()),
            ("rejected_claims.json", self.rejected_claims_json()),
        ] {
            if path.exists() {
                map.insert(name.to_string(), Self::hash_file(&path)?);
            }
        }
        Ok(map)
    }
}
