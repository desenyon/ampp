mod report;

use ampp_core::{
    artifacts::{ArtifactSet, TerminationCondition},
    pipeline::{BeamSearchManager, FormalSpec, Planner},
    state::{
        ActionType, Claim, ClaimType, NewClaimSpec, StepCandidate, StrategyFamily, VerificationPlan,
    },
    store::ProofStore,
    verification::{cascade::PythonVerifyRequest, VerificationCascade, VerificationResult},
};
use ampp_ipc::PythonWorker;
use anyhow::{Context, Result};
use chrono::Utc;
use clap::Parser;
use serde::Deserialize;
use std::{collections::HashMap, time::Duration};
use tracing::{info, warn};
use uuid::Uuid;

/// Explore mathematical proofs with mandatory, statement-bound Lean verification.
#[derive(Parser, Debug)]
#[command(name = "ampp", version, about)]
struct Cli {
    /// Problem statement for research context. Use --formal-target for proof completion.
    #[arg(short, long, required_unless_present = "doctor")]
    problem: Option<String>,
    /// Exact Lean proposition supplied by the user. Natural-language equivalence is not checked.
    #[arg(long)]
    formal_target: Option<String>,
    #[arg(short, long, default_value = "ampp_state.db")]
    db: String,
    /// A fresh output directory; existing run artifacts are never overwritten.
    #[arg(short, long, default_value = "output")]
    output: String,
    #[arg(long, default_value = "python3")]
    python: String,
    /// Installed module (default), or a custom trusted worker script.
    #[arg(long, default_value = "ampp.worker")]
    worker: String,
    #[arg(long, default_value_t = 42)]
    seed: u64,
    #[arg(long, default_value_t = 200)]
    max_iter: usize,
    /// Maximum worker response time in seconds.
    #[arg(long, default_value_t = 300, value_parser = clap::value_parser!(u64).range(1..))]
    worker_timeout: u64,
    /// Disable all LLM calls, even if credentials are present in the environment.
    #[arg(long)]
    offline: bool,
    /// JSON list of {statement, proof, stages?}; replaces LLM proposals for this run.
    #[arg(long)]
    candidate_file: Option<String>,
    /// Print worker health and actual installed tool versions, then exit.
    #[arg(long)]
    doctor: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SubmittedProof {
    statement: String,
    proof: String,
    #[serde(default = "default_stages")]
    stages: Vec<String>,
}
fn default_stages() -> Vec<String> {
    vec!["V0".into(), "V5".into()]
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ampp=info".into()),
        )
        .init();
    let cli = Cli::parse();
    if cli.offline {
        std::env::set_var("AMPP_LLM_PROVIDER", "null");
    }
    std::env::set_var("AMPP_RANDOM_SEED", cli.seed.to_string());
    let worker = PythonWorker::spawn_with_timeout(
        &cli.python,
        &cli.worker,
        Duration::from_secs(cli.worker_timeout),
    )?;
    let health = rpc(&worker, "PING", serde_json::json!({}))?;
    if cli.doctor {
        println!("{}", serde_json::to_string_pretty(&health)?);
        return Ok(());
    }
    let versions: HashMap<String, String> = serde_json::from_value(health["versions"].clone())
        .context("Worker omitted tool versions")?;
    let problem = cli.problem.as_deref().unwrap_or_default();
    anyhow::ensure!(
        !problem.trim().is_empty(),
        "Problem statement must not be empty"
    );
    if let Some(target) = &cli.formal_target {
        anyhow::ensure!(!target.trim().is_empty(), "Formal target must not be empty");
    }
    let submitted: Option<Vec<SubmittedProof>> = cli
        .candidate_file
        .as_ref()
        .map(|path| -> Result<_> {
            let bytes =
                std::fs::read(path).with_context(|| format!("Read candidate file {path}"))?;
            serde_json::from_slice(&bytes).context("Invalid candidate file")
        })
        .transpose()?;
    let artifacts = ArtifactSet::new(&cli.output);
    artifacts.create_dirs()?;
    for name in [
        "run_manifest.json",
        "solution.md",
        "solution.lean",
        "proof_graph.json",
        "verification_log.json",
        "rejected_claims.json",
    ] {
        anyhow::ensure!(
            !artifacts.output_dir.join(name).exists(),
            "Output already contains {name}; use a fresh --output directory"
        );
    }
    let store = ProofStore::open(&cli.db)?;
    let run_id = Uuid::new_v4().to_string();
    let started_at = Utc::now();
    let root_branch = format!("{run_id}-root");
    let mut spec: FormalSpec = serde_json::from_value(rpc(
        &worker,
        "NORMALISE",
        serde_json::json!({"problem": problem}),
    )?)?;
    if let Some(target) = &cli.formal_target {
        spec.target = target.trim().into();
        spec.edge_cases.clear(); // The explicit proposition is the sole completion target.
    }
    let root_claim = Claim::new(&spec.target, ClaimType::Theorem, vec![], &root_branch);
    store.insert_claim(&root_claim)?;
    let mut beam = BeamSearchManager::new(vec![
        StrategyFamily::Induction,
        StrategyFamily::ExtremalPrinciple,
        StrategyFamily::DoubleCounting,
        StrategyFamily::Constructive,
    ]);
    let branches: Vec<String> = std::iter::once(root_branch)
        .chain(beam.states.iter().map(|s| s.branch_id.clone()))
        .collect();
    for state in &beam.states {
        Planner::new(&store).generate_initial_subgoals(&spec, &root_claim.id, &state.branch_id)?;
    }
    let mut termination = TerminationCondition::Incomplete {
        reason: format!("Reached max iterations ({})", cli.max_iter),
    };
    let mut seen = std::collections::HashSet::new();
    let mut iteration = 0;
    'outer: for current in 1..=cli.max_iter {
        iteration = current;
        beam.sync_from_store(&store)?;
        let active: Vec<String> = beam
            .top_states(4)
            .iter()
            .map(|s| s.branch_id.clone())
            .collect();
        if active.is_empty() {
            termination = TerminationCondition::Incomplete {
                reason: "All beam branches exhausted".into(),
            };
            break;
        }
        for branch in active {
            let planner = Planner::new(&store);
            let Some(subgoal) = planner.next_subgoal(&branch)? else {
                continue;
            };
            let candidates = if let Some(proofs) = &submitted {
                proofs
                    .iter()
                    .map(|proof| {
                        StepCandidate::new(
                            &subgoal.id,
                            ActionType::IntroduceLemma,
                            vec![NewClaimSpec {
                                statement: proof.statement.clone(),
                                claim_type: "theorem".into(),
                            }],
                            vec![],
                            VerificationPlan {
                                stages: proof.stages.clone(),
                                success_criteria: HashMap::new(),
                                enumeration_bound: None,
                            },
                            vec![],
                            &proof.proof,
                            StrategyFamily::AlgebraicNormalization,
                            &branch,
                        )
                    })
                    .collect()
            } else {
                match request_candidates(
                    &worker,
                    &store,
                    &subgoal.id,
                    &branch,
                    &spec,
                    cli.formal_target.is_some(),
                ) {
                    Ok(candidates) => candidates,
                    Err(error) => {
                        termination = TerminationCondition::Incomplete {
                            reason: format!("Proposer worker error: {error}"),
                        };
                        break 'outer;
                    }
                }
            };
            let cascade = VerificationCascade::new(&store, |req| worker.call(req));
            let mut progress = false;
            for candidate in candidates {
                anyhow::ensure!(
                    candidate.subgoal_id == subgoal.id,
                    "Proposer returned a candidate for a different subgoal"
                );
                if !seen.insert(candidate.verification_hash()) {
                    continue;
                }
                match cascade.run(&candidate, &branch)? {
                    VerificationResult::Verified { claim, .. } => {
                        info!(claim_id = %claim.id, "Lean-verified formal claim");
                        // A useful lemma is progress, but cannot resolve an unrelated target.
                        let solves_target = cli.formal_target.is_some()
                            && claim.statement.trim() == spec.target.trim();
                        if solves_target {
                            planner.resolve(&subgoal.id)?;
                        }
                        beam.record_progress(&branch, 1, usize::from(solves_target));
                        progress = true;
                        if solves_target {
                            termination = TerminationCondition::TheoremVerified;
                            break 'outer;
                        }
                    }
                    VerificationResult::Rejected { stage, reason } => {
                        warn!(?stage, %reason, "Rejected candidate")
                    }
                    VerificationResult::Unverified { stage, reason } => {
                        warn!(?stage, %reason, "Candidate remains unverified")
                    }
                    VerificationResult::Error { message } => {
                        termination = TerminationCondition::Incomplete {
                            reason: format!("Verification infrastructure error: {message}"),
                        };
                        break 'outer;
                    }
                }
            }
            if !progress {
                beam.record_stale(&branch, 10);
            }
        }
        if submitted.is_some() {
            termination = TerminationCondition::Incomplete {
                reason: "Submitted candidates did not establish the explicit formal target".into(),
            };
            break;
        }
    }
    beam.sync_from_store(&store)?;
    report::write(
        &store,
        &artifacts,
        &spec,
        &branches,
        &beam,
        report::RunInfo {
            run_id,
            started_at,
            seed: cli.seed,
            iterations: iteration,
            formal_target: cli.formal_target,
            versions,
            termination,
        },
    )?;
    worker.shutdown()?;
    info!("Run complete: {}", artifacts.run_manifest_json().display());
    Ok(())
}

fn rpc(
    worker: &PythonWorker,
    stage: &str,
    context: serde_json::Value,
) -> Result<serde_json::Value> {
    let response = worker.call(PythonVerifyRequest {
        request_id: Uuid::new_v4().to_string(),
        stage: stage.into(),
        candidate_json: serde_json::json!({}),
        context,
    })?;
    anyhow::ensure!(response.passed, "{stage} failed: {}", response.details);
    Ok(response.details)
}

fn request_candidates(
    worker: &PythonWorker,
    store: &ProofStore,
    subgoal_id: &str,
    branch_id: &str,
    spec: &FormalSpec,
    formal_target: bool,
) -> Result<Vec<StepCandidate>> {
    let response = rpc(
        worker,
        "PROPOSE",
        serde_json::json!({
            "subgoal_id": subgoal_id, "branch_id": branch_id, "spec": spec, "formal_target": formal_target,
            "verified_claims": store.get_verified_claims(branch_id)?, "attempts": store.get_attempts_for_branch(branch_id)?,
        }),
    )?;
    serde_json::from_value(response["candidates"].clone()).context("Invalid candidate response")
}
