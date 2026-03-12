use crate::state::{Definition, StepCandidate};
use anyhow::Result;
use std::collections::HashSet;

/// V0: Deterministic structural checks run entirely in Rust.
/// No external process calls.
pub struct StructuralChecker;

#[derive(Debug)]
pub struct StructuralCheckResult {
    pub passed: bool,
    pub failures: Vec<String>,
}

impl StructuralChecker {
    /// Run all V0 checks. Returns immediately on first hard failure or collects all warnings.
    pub fn check(
        candidate: &StepCandidate,
        known_definitions: &[Definition],
        verified_claim_ids: &HashSet<String>,
    ) -> Result<StructuralCheckResult> {
        let mut failures = Vec::new();

        // 1. Schema completeness (replicated from StepCandidate::validate)
        if let Err(e) = candidate.validate() {
            failures.push(format!("schema: {e}"));
        }

        // 2. Dependency purity: all listed deps must be in verified set
        for dep in &candidate.dependencies {
            if !verified_claim_ids.contains(dep) {
                failures.push(format!("unverified dependency: {dep}"));
            }
        }

        // 3. Symbol validation: definition names used in lean_stub must exist
        let known_lean_names: HashSet<&str> = known_definitions
            .iter()
            .map(|d| d.lean_name.as_str())
            .collect();
        // Simple heuristic: check that identifiers starting with uppercase that look
        // like namespaced Lean names (Foo.bar) are in a known namespace.
        for token in lean_token_iter(&candidate.lean_stub) {
            if looks_like_lean_name(token) && !known_lean_names.contains(token) {
                // Treat as a warning, not a hard failure (proposer may use stdlib)
                tracing::debug!("V0: unknown lean name reference: {token}");
            }
        }

        // 4. Duplicate hash check is done by the cascade owner via the store.

        // 5. Small-case tests required when enumeration_bound is set
        if candidate.verification_plan.enumeration_bound.is_some()
            && candidate.small_case_tests.is_empty()
        {
            failures.push("enumeration_bound set but small_case_tests is empty".into());
        }

        // 6. Verification stages must be non-empty and contain known stage names
        let valid_stages = ["V0", "V1", "V2", "V3", "V4", "V5"];
        for stage in &candidate.verification_plan.stages {
            if !valid_stages.contains(&stage.as_str()) {
                failures.push(format!("unknown verification stage: {stage}"));
            }
        }

        Ok(StructuralCheckResult {
            passed: failures.is_empty(),
            failures,
        })
    }
}

fn lean_token_iter(stub: &str) -> impl Iterator<Item = &str> {
    stub.split_whitespace()
        .flat_map(|w| w.split(['(', ')', ':', ',', '.']))
        .filter(|s| !s.is_empty())
}

fn looks_like_lean_name(token: &str) -> bool {
    // Namespace-qualified identifiers like `Nat.Prime` or `List.length`
    token.contains('.')
        && token
            .chars()
            .next()
            .map(|c| c.is_uppercase())
            .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{
        ActionType, NewClaimSpec, SmallCaseTest, StepCandidate, StrategyFamily, VerificationPlan,
    };
    use std::collections::HashMap;

    fn dummy_candidate(stages: Vec<&str>, small_cases: Vec<SmallCaseTest>) -> StepCandidate {
        StepCandidate::new(
            "sg-1",
            ActionType::IntroduceLemma,
            vec![NewClaimSpec {
                statement: "2 + 2 = 4".into(),
                claim_type: "lemma".into(),
            }],
            vec![],
            VerificationPlan {
                stages: stages.into_iter().map(|s| s.to_string()).collect(),
                success_criteria: HashMap::new(),
                enumeration_bound: None,
            },
            small_cases,
            "theorem foo : 2 + 2 = 4 := by norm_num",
            StrategyFamily::AlgebraicNormalization,
            "branch-1",
        )
    }

    #[test]
    fn test_valid_candidate_passes() {
        let candidate = dummy_candidate(vec!["V0", "V1", "V5"], vec![]);
        let result = StructuralChecker::check(&candidate, &[], &HashSet::new()).unwrap();
        assert!(result.passed, "{:?}", result.failures);
    }

    #[test]
    fn test_unknown_stage_fails() {
        let candidate = dummy_candidate(vec!["V0", "V99"], vec![]);
        let result = StructuralChecker::check(&candidate, &[], &HashSet::new()).unwrap();
        assert!(!result.passed);
        assert!(result.failures.iter().any(|f| f.contains("V99")));
    }

    #[test]
    fn test_unverified_dependency_fails() {
        let mut candidate = dummy_candidate(vec!["V0", "V5"], vec![]);
        candidate.dependencies.push("nonexistent-claim-id".into());
        let result = StructuralChecker::check(&candidate, &[], &HashSet::new()).unwrap();
        assert!(!result.passed);
        assert!(result
            .failures
            .iter()
            .any(|f| f.contains("unverified dependency")));
    }
}
