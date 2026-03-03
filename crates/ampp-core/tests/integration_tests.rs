/// Integration tests for ampp-core.
/// These run with `cargo test -p ampp-core`.
#[cfg(test)]
mod integration {
    use ampp_core::{
        pipeline::{BeamSearchManager, FormalSpec, Planner},
        state::{
            ActionType, Attempt, Claim, ClaimType, Definition, NewClaimSpec, SmallCaseTest,
            StepCandidate, StrategyFamily, VerificationPlan,
        },
        store::ProofStore,
        verification::{
            cascade::{PythonVerifyRequest, PythonVerifyResponse, VerificationCascade},
            VerificationResult,
        },
    };
    use std::collections::HashMap;

    fn make_candidate(branch_id: &str, subgoal_id: &str) -> StepCandidate {
        StepCandidate::new(
            subgoal_id,
            ActionType::IntroduceLemma,
            vec![NewClaimSpec {
                statement: "2 + 2 = 4".into(),
                claim_type: "lemma".into(),
            }],
            vec![],
            VerificationPlan {
                stages: vec!["V0".into(), "V5".into()],
                success_criteria: HashMap::new(),
                enumeration_bound: None,
            },
            vec![
                SmallCaseTest {
                    description: "n=0".into(),
                    parameters: serde_json::json!({"n": 0}),
                    expected: true,
                },
            ],
            "theorem t : 2 + 2 = 4 := by norm_num",
            StrategyFamily::AlgebraicNormalization,
            branch_id,
        )
    }

    fn mock_python_caller(req: PythonVerifyRequest) -> anyhow::Result<PythonVerifyResponse> {
        // Simulates a Python worker that always passes
        Ok(PythonVerifyResponse {
            request_id: req.request_id,
            stage: req.stage,
            passed: true,
            details: serde_json::json!({"mock": true}),
            counterexample: None,
        })
    }

    fn mock_python_caller_fail(req: PythonVerifyRequest) -> anyhow::Result<PythonVerifyResponse> {
        Ok(PythonVerifyResponse {
            request_id: req.request_id,
            stage: req.stage.clone(),
            passed: false,
            details: serde_json::json!({"reason": format!("{} rejected by mock", req.stage)}),
            counterexample: None,
        })
    }

    // ── Store tests ───────────────────────────────────────────────────────────

    #[test]
    fn test_store_claim_lifecycle() {
        let store = ProofStore::in_memory().unwrap();
        let branch = "branch-test";

        let claim = Claim::new("Fermat's Last Theorem", ClaimType::Theorem, vec![], branch);
        store.insert_claim(&claim).unwrap();

        let retrieved = store.get_claim(&claim.id).unwrap().unwrap();
        assert_eq!(retrieved.statement, "Fermat's Last Theorem");

        let verified_before = store.get_verified_claims(branch).unwrap();
        assert!(verified_before.is_empty());
    }

    #[test]
    fn test_attempt_recording() {
        use ampp_core::state::VerifierStage;
        let store = ProofStore::in_memory().unwrap();

        let attempt = Attempt::new(
            "branch-1",
            "claim-1",
            "V1 found counterexample",
            VerifierStage::V1Counterexample,
            None,
        );
        store.insert_attempt(&attempt).unwrap();

        let counts = store.failure_counts_by_stage("branch-1").unwrap();
        assert_eq!(counts.get("V1_COUNTEREXAMPLE").copied().unwrap_or(0), 1);
    }

    #[test]
    fn test_rejected_hash_prevents_retry() {
        let store = ProofStore::in_memory().unwrap();
        let hash = "deadbeef";

        assert!(!store.claim_hash_rejected(hash).unwrap());
        store.register_rejected_hash(hash).unwrap();
        assert!(store.claim_hash_rejected(hash).unwrap());

        // Registering again should not error (INSERT OR IGNORE)
        store.register_rejected_hash(hash).unwrap();
    }

    // ── Verification cascade tests ────────────────────────────────────────────

    #[test]
    fn test_cascade_verified_on_mock_pass() {
        let store = ProofStore::in_memory().unwrap();
        let branch = "branch-cascade";
        let candidate = make_candidate(branch, "sg-1");

        let cascade = VerificationCascade::new(&store, mock_python_caller);
        let result = cascade.run(&candidate, branch).unwrap();

        match result {
            VerificationResult::Verified { claim, .. } => {
                assert_eq!(claim.branch_id, branch);
                assert!(claim.is_verified());
            }
            other => panic!("Expected Verified, got {:?}", other),
        }
    }

    #[test]
    fn test_cascade_rejected_on_mock_fail() {
        let store = ProofStore::in_memory().unwrap();
        let branch = "branch-reject";
        let candidate = make_candidate(branch, "sg-1");

        let cascade = VerificationCascade::new(&store, mock_python_caller_fail);
        let result = cascade.run(&candidate, branch).unwrap();

        match result {
            VerificationResult::Rejected { reason, .. } => {
                assert!(reason.contains("rejected by mock"));
            }
            other => panic!("Expected Rejected, got {:?}", other),
        }
    }

    #[test]
    fn test_cascade_dedup_rejected_hash() {
        let store = ProofStore::in_memory().unwrap();
        let branch = "branch-dedup";
        let candidate = make_candidate(branch, "sg-1");

        // Pre-register the hash as rejected
        store
            .register_rejected_hash(&candidate.candidate_hash)
            .unwrap();

        let cascade = VerificationCascade::new(&store, mock_python_caller);
        let result = cascade.run(&candidate, branch).unwrap();

        match result {
            VerificationResult::Rejected { reason, .. } => {
                assert!(reason.contains("duplicate hash"));
            }
            other => panic!("Expected Rejected for duplicate, got {:?}", other),
        }
    }

    // ── Beam search tests ─────────────────────────────────────────────────────

    #[test]
    fn test_beam_initial_width() {
        let manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
        ]);
        assert_eq!(manager.active_count(), 3);
    }

    #[test]
    fn test_beam_progress_resets_staleness() {
        let mut manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
            StrategyFamily::Constructive,
        ]);
        let branch = manager.states[0].branch_id.clone();

        // Make stale
        for _ in 0..3 {
            manager.record_stale(&branch, 10);
        }
        // Progress resets it
        manager.record_progress(&branch, 1, 1);
        assert_eq!(manager.states[0].stale_iterations, 0);
    }

    #[test]
    fn test_beam_top_states_ordered_by_score() {
        let mut manager = BeamSearchManager::new(vec![
            StrategyFamily::Induction,
            StrategyFamily::ExtremalPrinciple,
            StrategyFamily::DoubleCounting,
        ]);
        let branch2 = manager.states[1].branch_id.clone();
        manager.record_progress(&branch2, 10, 5);

        let top = manager.top_states(1);
        assert_eq!(top[0].branch_id, branch2);
    }

    // ── Planner tests ─────────────────────────────────────────────────────────

    #[test]
    fn test_planner_generates_and_retrieves_subgoals() {
        let store = ProofStore::in_memory().unwrap();
        let planner = Planner::new(&store);
        let branch = "branch-planner";

        let spec = FormalSpec {
            raw_statement: "For all n, n*(n+1) is even".into(),
            canonical_statement: "for all n, n*(n+1) is even".into(),
            variables: Default::default(),
            quantifiers: vec![],
            constraints: vec![],
            target: "for all n, n*(n+1) is even".into(),
            edge_cases: vec!["n=0".into(), "n=1".into()],
            lean_namespace: "EvenProduct".into(),
        };

        let ids = planner
            .generate_initial_subgoals(&spec, "root-claim-id", branch)
            .unwrap();
        assert!(ids.len() >= 1); // at least the top-level target

        // Edge case subgoals + top-level = 3 total
        assert_eq!(ids.len(), 3);

        let next = planner.next_subgoal(branch).unwrap();
        assert!(next.is_some());
    }

    #[test]
    fn test_planner_resolve_removes_from_pending() {
        let store = ProofStore::in_memory().unwrap();
        let planner = Planner::new(&store);
        let branch = "branch-resolve";

        let spec = FormalSpec {
            raw_statement: "test".into(),
            canonical_statement: "test".into(),
            variables: Default::default(),
            quantifiers: vec![],
            constraints: vec![],
            target: "test".into(),
            edge_cases: vec![],
            lean_namespace: "Test".into(),
        };

        let ids = planner
            .generate_initial_subgoals(&spec, "claim-1", branch)
            .unwrap();
        let count_before = store.count_pending_subgoals(branch).unwrap();
        planner.resolve(&ids[0]).unwrap();
        let count_after = store.count_pending_subgoals(branch).unwrap();
        assert_eq!(count_after, count_before - 1);
    }

    // ── Definition tests ──────────────────────────────────────────────────────

    #[test]
    fn test_definition_roundtrip_via_store() {
        let store = ProofStore::in_memory().unwrap();
        let def = Definition::new(
            "A prime p is a natural number > 1 with no divisors other than 1 and p",
            "Nat.Prime",
            "p > 1 ∧ ∀ m, m ∣ p → m = 1 ∨ m = p",
        );
        store.insert_definition(&def).unwrap();
        let defs = store.get_all_definitions().unwrap();
        assert_eq!(defs.len(), 1);
        assert_eq!(defs[0].lean_name, "Nat.Prime");
    }
}
