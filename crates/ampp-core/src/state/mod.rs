pub mod attempt;
/// Core state objects for the AMPP proof pipeline.
/// The state model is append-only and versioned.
pub mod claim;
pub mod counterexample;
pub mod definition;
pub mod step_candidate;
pub mod subgoal;

pub use attempt::{Attempt, VerifierStage};
pub use claim::{Claim, ClaimStatus, ClaimType, VerificationArtifact};
pub use counterexample::Counterexample;
pub use definition::Definition;
pub use step_candidate::{
    ActionType, NewClaimSpec, SmallCaseTest, StepCandidate, StrategyFamily, VerificationPlan,
};
pub use subgoal::Subgoal;
