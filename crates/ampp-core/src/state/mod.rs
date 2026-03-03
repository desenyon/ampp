/// Core state objects for the AMPP proof pipeline.
/// The state model is append-only and versioned.
pub mod claim;
pub mod definition;
pub mod subgoal;
pub mod counterexample;
pub mod attempt;
pub mod step_candidate;

pub use claim::{Claim, ClaimStatus, ClaimType, VerificationArtifact};
pub use definition::Definition;
pub use subgoal::Subgoal;
pub use counterexample::Counterexample;
pub use attempt::{Attempt, VerifierStage};
pub use step_candidate::{StepCandidate, ActionType, VerificationPlan, NewClaimSpec, SmallCaseTest, StrategyFamily};
