use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A structured proof step candidate produced by a Proposer.
/// All fields are mandatory; missing fields cause immediate discard.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepCandidate {
    pub id: String,
    pub subgoal_id: String,
    pub action_type: ActionType,
    /// New claims this step asserts.
    pub new_claims: Vec<NewClaimSpec>,
    /// IDs of already-verified claims this step depends on.
    pub dependencies: Vec<String>,
    /// Concrete plan: which verifiers, what success criteria.
    pub verification_plan: VerificationPlan,
    /// Small-case tests to run before full cascade.
    pub small_case_tests: Vec<SmallCaseTest>,
    /// Lean4 theorem stub (may be partial).
    pub lean_stub: String,
    /// Which proposer strategy generated this candidate.
    pub strategy_family: StrategyFamily,
    /// SHA-256 of (subgoal_id + sorted new_claim statements) for dedup.
    pub candidate_hash: String,
    pub branch_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewClaimSpec {
    pub statement: String,
    pub claim_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerificationPlan {
    /// Ordered list of verifier stages to apply.
    pub stages: Vec<String>,
    /// The criterion for success at each stage.
    pub success_criteria: std::collections::HashMap<String, String>,
    /// Upper bound N for exhaustive enumeration.
    pub enumeration_bound: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmallCaseTest {
    pub description: String,
    pub parameters: serde_json::Value,
    pub expected: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum ActionType {
    IntroduceLemma,
    ApplyInduction,
    ConstructWitness,
    CaseSplit,
    ApplyTransform,
    RefuteByCounterexample,
    MineConjecture,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum StrategyFamily {
    Induction,
    StrongInduction,
    MinimalCounterexample,
    ExtremalPrinciple,
    InvariantMonovariant,
    AlgebraicNormalization,
    DoubleCounting,
    Constructive,
    GraphTranslation,
    Contradiction,
}

impl StepCandidate {
    /// Validate all mandatory fields are non-empty.
    pub fn validate(&self) -> anyhow::Result<()> {
        if self.subgoal_id.is_empty() {
            anyhow::bail!("StepCandidate missing subgoal_id");
        }
        if self.new_claims.is_empty() {
            anyhow::bail!("StepCandidate has no new_claims");
        }
        if self.verification_plan.stages.is_empty() {
            anyhow::bail!("StepCandidate missing verification_plan stages");
        }
        if self.lean_stub.trim().is_empty() {
            anyhow::bail!("StepCandidate missing lean_stub");
        }
        for claim in &self.new_claims {
            if claim.statement.trim().is_empty() {
                anyhow::bail!("StepCandidate contains empty claim statement");
            }
        }
        Ok(())
    }

    /// Compute canonical hash for deduplication.
    pub fn compute_hash(subgoal_id: &str, new_claims: &[NewClaimSpec]) -> String {
        use sha2::{Digest, Sha256};
        let mut statements: Vec<&str> = new_claims.iter().map(|c| c.statement.as_str()).collect();
        statements.sort_unstable();
        let mut hasher = Sha256::new();
        hasher.update(subgoal_id.as_bytes());
        for s in statements {
            hasher.update(s.trim().to_lowercase().as_bytes());
        }
        hex::encode(hasher.finalize())
    }

    pub fn new(
        subgoal_id: impl Into<String>,
        action_type: ActionType,
        new_claims: Vec<NewClaimSpec>,
        dependencies: Vec<String>,
        verification_plan: VerificationPlan,
        small_case_tests: Vec<SmallCaseTest>,
        lean_stub: impl Into<String>,
        strategy_family: StrategyFamily,
        branch_id: impl Into<String>,
    ) -> Self {
        let subgoal_id = subgoal_id.into();
        let candidate_hash = Self::compute_hash(&subgoal_id, &new_claims);
        Self {
            id: Uuid::new_v4().to_string(),
            subgoal_id,
            action_type,
            new_claims,
            dependencies,
            verification_plan,
            small_case_tests,
            lean_stub: lean_stub.into(),
            strategy_family,
            candidate_hash,
            branch_id: branch_id.into(),
        }
    }
}
