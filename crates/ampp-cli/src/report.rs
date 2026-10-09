//! Run-scoped evidence export. Every branch contributes; versions are observed.
use ampp_core::{
    artifacts::{ArtifactSet, BranchSummary, RunManifest, TerminationCondition},
    pipeline::{BeamSearchManager, FormalSpec},
    state::{Attempt, Claim},
    store::ProofStore,
};
use anyhow::Result;
use chrono::{DateTime, Utc};
use std::collections::HashMap;

pub struct RunInfo {
    pub run_id: String,
    pub started_at: DateTime<Utc>,
    pub seed: u64,
    pub iterations: usize,
    pub formal_target: Option<String>,
    pub versions: HashMap<String, String>,
    pub termination: TerminationCondition,
}

pub fn write(
    store: &ProofStore,
    artifacts: &ArtifactSet,
    spec: &FormalSpec,
    branches: &[String],
    beam: &BeamSearchManager,
    run: RunInfo,
) -> Result<()> {
    let mut claims: Vec<Claim> = vec![];
    let mut attempts: Vec<Attempt> = vec![];
    for branch in branches {
        claims.extend(store.get_all_claims_for_branch(branch)?);
        attempts.extend(store.get_attempts_for_branch(branch)?);
    }
    claims.sort_by(|a, b| a.created_at.cmp(&b.created_at).then(a.id.cmp(&b.id)));
    attempts.sort_by(|a, b| a.timestamp.cmp(&b.timestamp).then(a.id.cmp(&b.id)));
    let rejected: Vec<_> = attempts
        .iter()
        .filter(|a| outcome(a) == "rejected")
        .collect();
    let unverified = attempts
        .iter()
        .filter(|a| outcome(a) == "unverified")
        .count();
    let verified: Vec<_> = claims.iter().filter(|c| c.is_verified()).collect();
    std::fs::write(
        artifacts.proof_graph_json(),
        serde_json::to_string_pretty(&serde_json::json!({"claims": claims}))?,
    )?;
    std::fs::write(
        artifacts.verification_log_json(),
        serde_json::to_string_pretty(&serde_json::json!({
            "verified_claims": verified, "attempts": attempts,
        }))?,
    )?;
    std::fs::write(
        artifacts.rejected_claims_json(),
        serde_json::to_string_pretty(&rejected)?,
    )?;
    let mut md = format!("# AMPP proof exploration\n\n**Problem:** {}\n\n**Result:** {:?}\n\nVerified formal claims: {}. Rejected attempts: {}. Unverified attempts: {}.\n\nNatural-language equivalence is not checked.\n", spec.raw_statement, run.termination, verified.len(), rejected.len(), unverified);
    for claim in &verified {
        md.push_str(&format!(
            "\n## Formal claim {}\n\n```lean\n{}\n```\n",
            claim.id, claim.statement
        ));
    }
    std::fs::write(artifacts.solution_md(), md)?;
    // Export the exact source which V5 compiled, never a placeholder or old file.
    if matches!(run.termination, TerminationCondition::TheoremVerified) {
        let target = run.formal_target.as_deref().unwrap_or_default();
        let certificate = verified
            .iter()
            .filter(|c| c.statement.trim() == target.trim())
            .flat_map(|c| &c.verification_artifacts)
            .find(|a| a.supports_statement(target))
            .ok_or_else(|| anyhow::anyhow!("Verified termination lacks target certificate"))?;
        std::fs::write(
            artifacts.solution_lean(),
            certificate.details["lean_source"].as_str().unwrap(),
        )?;
    }
    let beam_summary = beam
        .states
        .iter()
        .map(|state| BranchSummary {
            branch_id: state.branch_id.clone(),
            strategy: format!("{:?}", state.strategy_family),
            verified_claims: verified
                .iter()
                .filter(|c| c.branch_id == state.branch_id)
                .count(),
            rejected_claims: rejected
                .iter()
                .filter(|a| a.branch_id == state.branch_id)
                .count(),
            pruned: state.pruned,
        })
        .collect();
    let version = |name: &str| {
        run.versions
            .get(name)
            .cloned()
            .unwrap_or_else(|| "unavailable".into())
    };
    let manifest = RunManifest {
        run_id: run.run_id,
        started_at: run.started_at,
        finished_at: Some(Utc::now()),
        problem_fingerprint: spec.fingerprint(),
        problem_statement: spec.raw_statement.clone(),
        rust_version: "not recorded".into(),
        python_version: version("python"),
        lean_version: version("lean"),
        sympy_version: version("sympy"),
        z3_version: version("z3-solver"),
        random_seed: run.seed,
        tool_versions: run.versions.clone(),
        artifact_hashes: artifacts.collect_hashes()?,
        termination_condition: Some(run.termination),
        beam_summary,
        total_verified_claims: verified.len(),
        total_rejected_claims: rejected.len(),
        total_attempts: attempts.len(),
    };
    let mut json = serde_json::to_value(manifest)?;
    json["schema_version"] = serde_json::json!(2);
    json["verification_policy"] = serde_json::json!("lean-kernel-v1");
    json["ampp_version"] = serde_json::json!(env!("CARGO_PKG_VERSION"));
    json["formal_target"] = serde_json::json!(run.formal_target);
    json["iterations"] = serde_json::json!(run.iterations);
    json["total_unverified_attempts"] = serde_json::json!(unverified);
    std::fs::write(
        artifacts.run_manifest_json(),
        serde_json::to_string_pretty(&json)?,
    )?;
    Ok(())
}

fn outcome(attempt: &Attempt) -> &str {
    attempt
        .raw_output
        .as_ref()
        .and_then(|r| r["outcome"].as_str())
        .unwrap_or("legacy")
}
