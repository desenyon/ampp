use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A proof subgoal in the planner's dependency DAG.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subgoal {
    pub id: String,
    /// ID of the claim this subgoal is working towards.
    pub target_claim_id: String,
    /// impact_score / estimated_complexity — higher is more urgent.
    pub priority_score: f64,
    /// Rough difficulty estimate (0.0 = trivial, 1.0 = very hard).
    pub difficulty_estimate: f64,
    /// IDs of verified claims needed before this can be attempted.
    pub blockers: Vec<String>,
    pub expected_strategy: String,
    pub verification_plan: String,
    pub branch_id: String,
    pub resolved: bool,
}

impl Subgoal {
    pub fn new(
        target_claim_id: impl Into<String>,
        priority_score: f64,
        difficulty_estimate: f64,
        blockers: Vec<String>,
        expected_strategy: impl Into<String>,
        verification_plan: impl Into<String>,
        branch_id: impl Into<String>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            target_claim_id: target_claim_id.into(),
            priority_score,
            difficulty_estimate,
            blockers,
            expected_strategy: expected_strategy.into(),
            verification_plan: verification_plan.into(),
            branch_id: branch_id.into(),
            resolved: false,
        }
    }

    /// Rank used by the planner's priority queue.
    pub fn rank(&self) -> f64 {
        if self.difficulty_estimate == 0.0 {
            f64::MAX
        } else {
            self.priority_score / self.difficulty_estimate
        }
    }
}
