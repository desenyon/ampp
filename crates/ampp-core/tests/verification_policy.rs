//! Synthetic certificates test Rust policy only, never claim a real Lean proof.
use ampp_core::{
    state::*,
    store::ProofStore,
    verification::{
        cascade::{PythonVerifyRequest, PythonVerifyResponse},
        VerificationCascade, VerificationResult,
    },
};
use chrono::Utc;
use sha2::{Digest, Sha256};
use std::cell::RefCell;

fn candidate() -> StepCandidate {
    StepCandidate::new(
        "sg",
        ActionType::IntroduceLemma,
        vec![NewClaimSpec {
            statement: "2 + 2 = 4".into(),
            claim_type: "theorem".into(),
        }],
        vec![],
        VerificationPlan {
            stages: vec!["V0".into()],
            success_criteria: Default::default(),
            enumeration_bound: None,
        },
        vec![],
        "by decide",
        StrategyFamily::AlgebraicNormalization,
        "branch",
    )
}
fn response(req: PythonVerifyRequest, outcome: &str) -> PythonVerifyResponse {
    PythonVerifyResponse {
        request_id: req.request_id,
        stage: req.stage,
        passed: outcome == "passed",
        details: serde_json::json!({"outcome": outcome, "reason": "test result"}),
        counterexample: None,
    }
}
fn evidence(statement: &str) -> serde_json::Value {
    let source = "synthetic unit-test certificate";
    serde_json::json!({"outcome": "passed", "policy": "lean-kernel-v1", "lean_result": "compiled", "statement": statement, "lean_source": source, "source_sha256": hex::encode(Sha256::digest(source.as_bytes())), "axioms": []})
}
fn success(req: PythonVerifyRequest) -> anyhow::Result<PythonVerifyResponse> {
    let details = evidence(
        req.candidate_json["new_claims"][0]["statement"]
            .as_str()
            .unwrap(),
    );
    let mut resp = response(req, "passed");
    resp.details = details;
    Ok(resp)
}

#[test]
fn v0_only_plan_still_requires_v5() {
    let store = ProofStore::in_memory().unwrap();
    let calls = RefCell::new(vec![]);
    let cascade = VerificationCascade::new(&store, |req| {
        calls.borrow_mut().push(req.stage.clone());
        Ok(response(req, "unavailable"))
    });
    assert!(matches!(
        cascade.run(&candidate(), "branch").unwrap(),
        VerificationResult::Unverified { .. }
    ));
    assert_eq!(*calls.borrow(), vec!["V5"]);
    assert!(store.get_verified_claims("branch").unwrap().is_empty());
    assert!(!store
        .claim_hash_rejected(&candidate().verification_hash())
        .unwrap());
}

#[test]
fn boolean_success_without_certificate_cannot_commit() {
    let store = ProofStore::in_memory().unwrap();
    let cascade = VerificationCascade::new(&store, |req| Ok(response(req, "passed")));
    assert!(matches!(
        cascade.run(&candidate(), "branch").unwrap(),
        VerificationResult::Unverified { .. }
    ));
    assert!(store.get_verified_claims("branch").unwrap().is_empty());
}

#[test]
fn successful_certificate_commits_and_preserves_type() {
    let store = ProofStore::in_memory().unwrap();
    let cascade = VerificationCascade::new(&store, success);
    let VerificationResult::Verified { claim, .. } = cascade.run(&candidate(), "branch").unwrap()
    else {
        panic!("expected success")
    };
    assert_eq!(claim.claim_type, ClaimType::Theorem);
    assert_eq!(store.get_verified_claims("branch").unwrap().len(), 1);
}

#[test]
fn optional_inconclusive_and_unavailable_stages_do_not_replace_or_block_lean() {
    let store = ProofStore::in_memory().unwrap();
    let mut cand = candidate();
    cand.verification_plan.stages = vec!["V1".into(), "V4".into()];
    let calls = RefCell::new(vec![]);
    let cascade = VerificationCascade::new(&store, |req| {
        calls.borrow_mut().push(req.stage.clone());
        match req.stage.as_str() {
            "V5" => success(req),
            "V4" => Ok(response(req, "unavailable")),
            _ => Ok(response(req, "inconclusive")),
        }
    });
    assert!(matches!(
        cascade.run(&cand, "branch").unwrap(),
        VerificationResult::Verified { .. }
    ));
    assert_eq!(*calls.borrow(), vec!["V1", "V4", "V5"]);
}

#[test]
fn wrong_statement_or_changed_source_cannot_commit() {
    for key in ["statement", "source_sha256", "policy", "lean_result"] {
        let store = ProofStore::in_memory().unwrap();
        let cascade = VerificationCascade::new(&store, |req| {
            let mut resp = success(req)?;
            resp.details[key] = "wrong".into();
            Ok(resp)
        });
        assert!(matches!(
            cascade.run(&candidate(), "branch").unwrap(),
            VerificationResult::Unverified { .. }
        ));
    }
}

#[test]
fn unapproved_axioms_cannot_commit() {
    let store = ProofStore::in_memory().unwrap();
    let cascade = VerificationCascade::new(&store, |req| {
        let mut resp = success(req)?;
        resp.details["axioms"] = serde_json::json!(["sorryAx"]);
        Ok(resp)
    });
    assert!(matches!(
        cascade.run(&candidate(), "branch").unwrap(),
        VerificationResult::Unverified { .. }
    ));
}

#[test]
fn malformed_and_mismatched_responses_fail_closed() {
    for variant in [
        "id",
        "stage",
        "missing",
        "contradictory",
        "unknown",
        "scalar",
        "witness",
    ] {
        let store = ProofStore::in_memory().unwrap();
        let cascade = VerificationCascade::new(&store, |req| {
            let mut resp = success(req)?;
            match variant {
                "id" => resp.request_id = "wrong".into(),
                "stage" => resp.stage = "V0".into(),
                "missing" => resp.details = serde_json::json!({}),
                "contradictory" => resp.passed = false,
                "scalar" => {
                    resp.details = serde_json::json!("invalid");
                    resp.passed = false;
                    resp.counterexample = Some(serde_json::json!({"n": 0}));
                }
                "witness" => resp.counterexample = Some(serde_json::json!({"n": 0})),
                _ => resp.details["outcome"] = "mystery".into(),
            }
            Ok(resp)
        });
        assert!(matches!(
            cascade.run(&candidate(), "branch").unwrap(),
            VerificationResult::Error { .. }
        ));
        assert!(store.get_verified_claims("branch").unwrap().is_empty());
    }
}

#[test]
fn unavailable_and_transport_error_are_retryable() {
    let store = ProofStore::in_memory().unwrap();
    let cand = candidate();
    for outcome in ["unavailable", "inconclusive", "error"] {
        let cascade = VerificationCascade::new(&store, |req| Ok(response(req, outcome)));
        assert!(!matches!(
            cascade.run(&cand, "branch").unwrap(),
            VerificationResult::Verified { .. }
        ));
        assert!(!store
            .claim_hash_rejected(&cand.verification_hash())
            .unwrap());
    }
    let cascade = VerificationCascade::new(&store, |_| anyhow::bail!("worker crashed"));
    assert!(matches!(
        cascade.run(&cand, "branch").unwrap(),
        VerificationResult::Error { .. }
    ));
    assert!(matches!(
        VerificationCascade::new(&store, success)
            .run(&cand, "branch")
            .unwrap(),
        VerificationResult::Verified { .. }
    ));
}

#[test]
fn real_rejection_records_witness_but_repaired_proof_is_not_blacklisted() {
    let store = ProofStore::in_memory().unwrap();
    let mut cand = candidate();
    let cascade = VerificationCascade::new(&store, |req| {
        let mut resp = response(req, "failed");
        resp.counterexample = Some(serde_json::json!({"witness": {"n": 2}}));
        Ok(resp)
    });
    assert!(matches!(
        cascade.run(&cand, "branch").unwrap(),
        VerificationResult::Rejected { .. }
    ));
    assert!(store
        .claim_hash_rejected(&cand.verification_hash())
        .unwrap());
    let attempt = store.get_attempts_for_branch("branch").unwrap().remove(0);
    assert_eq!(
        attempt.raw_output.unwrap()["artifacts"][1]["details"]["counterexample"]["witness"]["n"],
        2
    );
    cand.lean_stub = "by rfl".into();
    assert!(!store
        .claim_hash_rejected(&cand.verification_hash())
        .unwrap());
    assert!(matches!(
        VerificationCascade::new(&store, success)
            .run(&cand, "branch")
            .unwrap(),
        VerificationResult::Verified { .. }
    ));
}

#[test]
fn branch_mismatch_bundled_claims_and_unverified_dependencies_are_structural_failures() {
    for variant in ["branch", "bundle", "dependency"] {
        let store = ProofStore::in_memory().unwrap();
        let mut cand = candidate();
        match variant {
            "branch" => cand.branch_id = "wrong".into(),
            "bundle" => cand.new_claims.push(cand.new_claims[0].clone()),
            _ => cand.dependencies.push("unverified".into()),
        }
        let cascade = VerificationCascade::new(&store, |_| panic!("must not invoke worker"));
        assert!(matches!(
            cascade.run(&cand, "branch").unwrap(),
            VerificationResult::Rejected {
                stage: VerifierStage::V0Structural,
                ..
            }
        ));
    }
}

#[test]
fn supplied_hash_never_controls_verification_and_case_is_preserved() {
    let mut cand = candidate();
    let hash = cand.verification_hash();
    cand.candidate_hash = "attacker-controlled".into();
    assert_eq!(cand.verification_hash(), hash);
    cand.lean_stub = "by rfl".into();
    assert_ne!(cand.verification_hash(), hash);
    assert_ne!(Claim::hash_statement("P"), Claim::hash_statement("p"));
}

#[test]
fn direct_store_and_claim_api_cannot_bypass_evidence_or_rewrite_verified_claim() {
    let store = ProofStore::in_memory().unwrap();
    let mut claim = Claim::new("2 + 2 = 4", ClaimType::Lemma, vec![], "branch");
    let v0 = VerificationArtifact {
        stage: "V0".into(),
        result: "passed".into(),
        details: serde_json::json!({}),
        timestamp: Utc::now(),
    };
    assert!(claim.verify(v0).is_err());
    claim.status = ClaimStatus::Verified;
    assert!(store.insert_claim(&claim).is_err());
    claim.status = ClaimStatus::Proposed;
    store.insert_claim(&claim).unwrap();
    claim
        .verify(VerificationArtifact {
            stage: "V5".into(),
            result: "passed".into(),
            details: evidence(&claim.statement),
            timestamp: Utc::now(),
        })
        .unwrap();
    store.update_claim(&claim).unwrap();
    claim.statement = "False".into();
    assert!(store.update_claim(&claim).is_err());
    assert_eq!(
        store.get_verified_claims("branch").unwrap()[0].statement,
        "2 + 2 = 4"
    );
}

#[test]
fn legacy_verified_rows_do_not_enter_dependency_set() {
    let path = std::env::temp_dir().join(format!("ampp-legacy-{}.db", uuid::Uuid::new_v4()));
    {
        let store = ProofStore::open(&path).unwrap();
        let mut claim = Claim::new("False", ClaimType::Theorem, vec![], "branch");
        claim.status = ClaimStatus::Verified;
        let connection = rusqlite::Connection::open(&path).unwrap();
        connection
            .execute(
                "INSERT INTO claims (id,branch_id,status,proof_hash,data) VALUES (?1,?2,?3,?4,?5)",
                rusqlite::params![
                    claim.id,
                    claim.branch_id,
                    "\"verified\"",
                    claim.proof_hash,
                    serde_json::to_string(&claim).unwrap()
                ],
            )
            .unwrap();
        assert!(store.get_verified_claims("branch").unwrap().is_empty());
        assert!(store.get_claim(&claim.id).unwrap().is_some());
    }
    std::fs::remove_file(path).unwrap();
}

#[test]
fn store_rejects_certificate_with_missing_dependency() {
    let store = ProofStore::in_memory().unwrap();
    let mut claim = Claim::new(
        "2 + 2 = 4",
        ClaimType::Lemma,
        vec!["missing".into()],
        "branch",
    );
    claim
        .verify(VerificationArtifact {
            stage: "V5".into(),
            result: "passed".into(),
            details: evidence(&claim.statement),
            timestamp: Utc::now(),
        })
        .unwrap();
    assert!(store.insert_claim(&claim).is_err());
}
