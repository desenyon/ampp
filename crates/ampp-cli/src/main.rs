use ampp_core::{
    artifacts::{ArtifactSet, RunManifest, TerminationCondition},
    pipeline::{BeamSearchManager, FormalSpec, Planner},
    state::{Claim, ClaimType, StrategyFamily},
    store::ProofStore,
    verification::{VerificationCascade, VerificationResult},
};
use ampp_ipc::PythonWorker;
use anyhow::Result;
use chrono::Utc;
use clap::Parser;
use std::collections::HashMap;
use tracing::{error, info, warn};
use uuid::Uuid;

const MAX_ITERATIONS: usize = 200;
const STALE_THRESHOLD: usize = 10;
const BEAM_WIDTH: usize = 4;

/// Autonomous Mathematical Proof Pipeline
#[derive(Parser, Debug)]
#[command(name = "ampp", version, about)]
struct Cli {
    /// Problem statement (natural language or LaTeX).
    #[arg(short, long)]
    problem: String,

    /// Path to the SQLite state file.
    #[arg(short, long, default_value = "ampp_state.db")]
    db: String,

    /// Path to output artifacts directory.
    #[arg(short, long, default_value = "output")]
    output: String,

    /// Python interpreter path.
    #[arg(long, default_value = "python3")]
    python: String,

    /// Path to the Python worker script.
    #[arg(long, default_value = "ampp/worker.py")]
    worker: String,

    /// Random seed for reproducibility.
    #[arg(long, default_value_t = 42)]
    seed: u64,

    /// Maximum iterations.
    #[arg(long, default_value_t = MAX_ITERATIONS)]
    max_iter: usize,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env().add_directive("ampp=info".parse()?),
        )
        .init();

    let cli = Cli::parse();

    info!("AMPP starting — problem: {}", cli.problem);

    // ── Infrastructure ────────────────────────────────────────────────────────
    let store = ProofStore::open(&cli.db)?;
    let artifacts = ArtifactSet::new(&cli.output);
    artifacts.create_dirs()?;

    let worker = PythonWorker::spawn(&cli.python, &cli.worker)?;

    // ── Formal specification (sent to Python normaliser via IPC) ─────────────
    let spec = request_formal_spec(&worker, &cli.problem)?;
    info!("Formal spec fingerprint: {}", spec.fingerprint());

    // ── Root claim ───────────────────────────────────────────────────────────
    let root_claim = Claim::new(&spec.target, ClaimType::Theorem, vec![], "root");
    store.insert_claim(&root_claim)?;

    // ── Beam search initialisation ───────────────────────────────────────────
    let initial_strategies = vec![
        StrategyFamily::Induction,
        StrategyFamily::ExtremalPrinciple,
        StrategyFamily::DoubleCounting,
        StrategyFamily::Constructive,
    ];
    let mut beam = BeamSearchManager::new(initial_strategies);
    let run_id = Uuid::new_v4().to_string();
    let started_at = Utc::now();

    // Copy the root claim and subgoals into each beam branch
    for state in beam.states.clone() {
        let planner = Planner::new(&store);
        planner.generate_initial_subgoals(&spec, &root_claim.id, &state.branch_id)?;
    }

    // ── Main proof loop ───────────────────────────────────────────────────────
    let mut iteration = 0;
    let mut termination = None;

    'outer: while iteration < cli.max_iter {
        iteration += 1;
        beam.sync_from_store(&store)?;

        let active_branches: Vec<String> = beam
            .top_states(BEAM_WIDTH)
            .iter()
            .map(|s| s.branch_id.clone())
            .collect();

        if active_branches.is_empty() {
            warn!("All beam states pruned — declaring incomplete");
            termination = Some(TerminationCondition::Incomplete {
                reason: "All beam branches exhausted".into(),
            });
            break;
        }

        for branch_id in &active_branches {
            let planner = Planner::new(&store);

            let Some(subgoal) = planner.next_subgoal(branch_id)? else {
                // No pending subgoals → this branch is done
                let verified = store.get_verified_claims(branch_id)?;
                if verified
                    .iter()
                    .any(|c| c.proof_hash == root_claim.proof_hash)
                {
                    info!("✓ Target theorem verified on branch {branch_id}");
                    termination = Some(TerminationCondition::TheoremVerified);
                    break 'outer;
                }
                continue;
            };

            // Request a step candidate from the Python proposer ensemble
            let candidates = request_candidates(&worker, &subgoal.id, branch_id, &spec)?;

            if candidates.is_empty() {
                beam.record_stale(branch_id, STALE_THRESHOLD);
                continue;
            }

            let cascade = VerificationCascade::new(&store, |req| worker.call(req));
            let mut made_progress = false;

            for candidate in candidates {
                match cascade.run(&candidate, branch_id)? {
                    VerificationResult::Verified { claim, .. } => {
                        info!(
                            iter = iteration,
                            branch_id = %branch_id,
                            claim_id = %claim.id,
                            "✓ Verified"
                        );
                        planner.resolve(&subgoal.id)?;
                        beam.record_progress(branch_id, 1, 1);
                        made_progress = true;

                        // Check if root claim is now proved
                        if claim.proof_hash == root_claim.proof_hash {
                            termination = Some(TerminationCondition::TheoremVerified);
                            break 'outer;
                        }
                        break;
                    }
                    VerificationResult::Rejected { stage, reason } => {
                        warn!(
                            iter = iteration,
                            branch_id = %branch_id,
                            stage = ?stage,
                            reason = %reason,
                            "✗ Rejected"
                        );
                    }
                    VerificationResult::Error { message } => {
                        error!("Cascade error: {message}");
                    }
                }
            }

            if !made_progress {
                beam.record_stale(branch_id, STALE_THRESHOLD);
            }
        }
    }

    if termination.is_none() {
        termination = Some(TerminationCondition::Incomplete {
            reason: format!("Reached max iterations ({MAX_ITERATIONS})"),
        });
    }

    // ── Write output artifacts ────────────────────────────────────────────────
    write_artifacts(&store, &artifacts, &spec, termination.as_ref().unwrap())?;

    let artifact_hashes = artifacts.collect_hashes()?;
    let manifest = build_manifest(
        run_id,
        started_at,
        cli.seed,
        &spec,
        termination.unwrap(),
        &beam,
        &store,
        artifact_hashes,
    )?;

    let manifest_json = serde_json::to_string_pretty(&manifest)?;
    std::fs::write(artifacts.run_manifest_json(), &manifest_json)?;
    info!(
        "Run complete. Manifest written to {:?}",
        artifacts.run_manifest_json()
    );

    Ok(())
}

// ── Helper functions ──────────────────────────────────────────────────────────

fn request_formal_spec(worker: &PythonWorker, problem: &str) -> Result<FormalSpec> {
    use ampp_core::verification::cascade::PythonVerifyRequest;
    let req = PythonVerifyRequest {
        request_id: Uuid::new_v4().to_string(),
        stage: "NORMALISE".into(),
        candidate_json: serde_json::json!({}),
        context: serde_json::json!({ "problem": problem }),
    };
    let resp = worker.call(req)?;
    let spec: FormalSpec = serde_json::from_value(resp.details)?;
    Ok(spec)
}

fn request_candidates(
    worker: &PythonWorker,
    subgoal_id: &str,
    branch_id: &str,
    spec: &FormalSpec,
) -> Result<Vec<ampp_core::state::StepCandidate>> {
    use ampp_core::verification::cascade::PythonVerifyRequest;
    let req = PythonVerifyRequest {
        request_id: Uuid::new_v4().to_string(),
        stage: "PROPOSE".into(),
        candidate_json: serde_json::json!({}),
        context: serde_json::json!({
            "subgoal_id": subgoal_id,
            "branch_id": branch_id,
            "spec": spec,
        }),
    };
    let resp = worker.call(req)?;
    let candidates: Vec<ampp_core::state::StepCandidate> =
        serde_json::from_value(resp.details.get("candidates").cloned().unwrap_or_default())
            .unwrap_or_default();
    Ok(candidates)
}

fn write_artifacts(
    store: &ProofStore,
    artifacts: &ArtifactSet,
    spec: &FormalSpec,
    termination: &TerminationCondition,
) -> Result<()> {
    // proof_graph.json
    let all_claims = store.get_all_claims_for_branch("root")?; // simplified
    let graph = serde_json::json!({ "claims": all_claims });
    std::fs::write(
        artifacts.proof_graph_json(),
        serde_json::to_string_pretty(&graph)?,
    )?;

    // verification_log.json
    let attempts = store.get_attempts_for_branch("root")?;
    std::fs::write(
        artifacts.verification_log_json(),
        serde_json::to_string_pretty(&attempts)?,
    )?;

    // rejected_claims.json
    let rejected: Vec<_> = all_claims.iter().filter(|c| c.is_rejected()).collect();
    std::fs::write(
        artifacts.rejected_claims_json(),
        serde_json::to_string_pretty(&rejected)?,
    )?;

    // solution.md
    let md = format!(
        "# AMPP Solution\n\n**Problem:** {}\n\n**Result:** {:?}\n",
        spec.raw_statement, termination
    );
    std::fs::write(artifacts.solution_md(), md)?;

    // solution.lean (placeholder if not yet produced by V5)
    if !artifacts.solution_lean().exists() {
        std::fs::write(
            artifacts.solution_lean(),
            format!(
                "-- Auto-generated stub\nnamespace {}\n-- TODO: fill proof\nend {}\n",
                spec.lean_namespace, spec.lean_namespace
            ),
        )?;
    }

    Ok(())
}

fn build_manifest(
    run_id: String,
    started_at: chrono::DateTime<Utc>,
    seed: u64,
    spec: &FormalSpec,
    termination: TerminationCondition,
    beam: &BeamSearchManager,
    store: &ProofStore,
    artifact_hashes: HashMap<String, String>,
) -> Result<RunManifest> {
    let mut beam_summary = vec![];
    for state in &beam.states {
        let verified = store.get_verified_claims(&state.branch_id)?.len();
        let all = store.get_all_claims_for_branch(&state.branch_id)?;
        let rejected = all.iter().filter(|c| c.is_rejected()).count();
        beam_summary.push(ampp_core::artifacts::BranchSummary {
            branch_id: state.branch_id.clone(),
            strategy: format!("{:?}", state.strategy_family),
            verified_claims: verified,
            rejected_claims: rejected,
            pruned: state.pruned,
        });
    }

    let root_attempts = store.get_attempts_for_branch("root")?;

    Ok(RunManifest {
        run_id,
        started_at,
        finished_at: Some(Utc::now()),
        problem_fingerprint: spec.fingerprint(),
        problem_statement: spec.raw_statement.clone(),
        rust_version: env!("CARGO_PKG_VERSION").into(),
        python_version: "3.11".into(),
        lean_version: "4.x".into(),
        sympy_version: "1.12".into(),
        z3_version: "4.12".into(),
        random_seed: seed,
        tool_versions: HashMap::new(),
        artifact_hashes,
        termination_condition: Some(termination),
        beam_summary,
        total_verified_claims: 0,
        total_rejected_claims: 0,
        total_attempts: root_attempts.len(),
    })
}
