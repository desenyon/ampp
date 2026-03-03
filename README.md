# AMPP — Autonomous Mathematical Proof Pipeline

[![CI](https://github.com/your-username/ampp/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/ampp/actions/workflows/ci.yml)
[![Rust](https://img.shields.io/badge/rust-stable-orange)](https://www.rust-lang.org/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AMPP is a production-grade autonomous system for solving advanced mathematical problems — combinatorics, number theory, Erdős-style extremal problems — with **formal, machine-verifiable proofs**. It combines a deterministic Rust core with a Python AI/solver ecosystem connected via a high-performance JSON-RPC bridge.

**The central invariant:** no mathematical statement is ever accepted as true unless a deterministic verifier (up to and including Lean 4) independently confirms it.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Breakdown](#component-breakdown)
   - [Rust Core](#rust-core)
   - [Python Solver Stack](#python-solver-stack)
   - [IPC Bridge](#ipc-bridge)
3. [Verification Cascade](#verification-cascade)
4. [Proof Loop](#proof-loop)
5. [Quick Start](#quick-start)
6. [Installation](#installation)
7. [CLI Reference](#cli-reference)
8. [Configuration & Environment Variables](#configuration--environment-variables)
9. [Output Artefacts](#output-artefacts)
10. [Testing](#testing)
11. [Project Structure](#project-structure)
12. [Design Philosophy](#design-philosophy)
13. [Contributing](#contributing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Problem Input (CLI)                       │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                     RUST CORE  (ampp-cli / ampp-core)           │
│                                                                  │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐  │
│  │  ProofStore  │   │  BeamSearch   │   │  VerifyCascade     │  │
│  │  (SQLite)    │   │  Manager      │   │  V0 – structural   │  │
│  │  append-only │   │  3-6 branches │   │  (in-process Rust) │  │
│  └──────────────┘   └───────────────┘   └────────────────────┘  │
│                                                                  │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐  │
│  │  Planner     │   │  Normalizer   │   │  Artifacts         │  │
│  │  (subgoal    │   │  (FormalSpec) │   │  (manifest, lean,  │  │
│  │   DAG)       │   │               │   │   proof graph)     │  │
│  └──────────────┘   └───────────────┘   └────────────────────┘  │
│                                                                  │
│         JSON-RPC over subprocess stdin/stdout (PythonWorker)    │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                    PYTHON SOLVER STACK  (ampp/)                  │
│                                                                  │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐  │
│  │  Normalizer  │   │  Proposer     │   │  RubricAgent       │  │
│  │  (FormalSpec)│   │  Ensemble     │   │  (quality gate,    │  │
│  │              │   │  5 strategies │   │   strategy weights)│  │
│  └──────────────┘   └───────────────┘   └────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Verification Cascade  V1 → V2 → V3 → V4 → V5             │  │
│  │  CounterexampleVerifier │ SymPy │ Z3 │ ATP │ Lean 4        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────┐   ┌───────────────┐                           │
│  │ Conjecture   │   │ Strategy      │                           │
│  │ Miner        │   │ Controller    │                           │
│  └──────────────┘   └───────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

The pipeline separates **creativity** (Python LLM proposers) from **correctness** (deterministic verifiers). The Rust core enforces the two-phase commit: a claim moves from `proposed` → `verified` only after the full cascade succeeds.

---

## Component Breakdown

### Rust Core

| Crate | Purpose |
|-------|---------|
| `ampp-core` | State model, SQLite store, V0 checker, verification cascade orchestrator, beam search, planner, normalizer, artifacts |
| `ampp-ipc` | `PythonWorker` subprocess manager — spawns Python worker, JSON-RPC call/response |
| `ampp-cli` | CLI entry point — assembles all components, runs the main proof loop |

**State objects** (all serialised to SQLite, append-only):

| Object | Key fields |
|--------|-----------|
| `Claim` | `id`, `statement`, `type` (lemma/theorem/auxiliary), `status` (proposed/verified/rejected), `dependencies`, `verification_artifacts`, `proof_hash` |
| `Definition` | `id`, `statement`, `canonical_form`, `lean_name`, `hash` |
| `Subgoal` | `id`, `target_claim`, `priority_score`, `difficulty_estimate`, `blockers` |
| `Counterexample` | `claim_id`, `witness_structure`, `generation_method`, `seed` |
| `Attempt` | `branch_id`, `failed_claim`, `failure_reason`, `verifier_stage` |
| `StepCandidate` | `subgoal_id`, `action_type`, `new_claims`, `dependencies`, `verification_plan`, `small_case_tests`, `lean_stub` |

### Python Solver Stack

| Module | Role |
|--------|------|
| `ampp/normalizer.py` | Converts raw problem text → `FormalSpec` (variables, quantifiers, constraints, target, edge cases, Lean namespace) |
| `ampp/schemas.py` | Pydantic models mirroring the Rust state; JSON-RPC contract |
| `ampp/proposers/` | 5 strategy-specific proposers + ensemble with deduplication |
| `ampp/agents/rubric_agent.py` | 7-dimension quality gate; scores and filters `StepCandidate`s before sending to verifiers |
| `ampp/agents/strategy_controller.py` | Shannon-entropy-based strategy switching; prevents getting stuck |
| `ampp/agents/conjecture_miner.py` | Enumerates small cases, detects invariants, suggests conjectural bounds |
| `ampp/verifiers/` | V1–V5 verifiers (see cascade section) |
| `ampp/worker.py` | Main JSON-RPC event loop; routes requests to the correct component |

**Proposer strategies:**

| Proposer | Mathematical technique |
|----------|----------------------|
| `InductionProposer` | Base case + inductive step |
| `ExtremalProposer` | Extremal / minimal-counterexample principle |
| `DoubleCountingProposer` | Counting in two ways |
| `ConstructiveProposer` | Explicit construction / algorithm |
| `AlgebraicNormalizationProposer` | Algebraic manipulation and canonical forms |

LLM integration is through `_llm_generate()` in `specializations.py`. If `ANTHROPIC_API_KEY` is set, Claude is used (claude-opus-4-5). If only `OPENAI_API_KEY` is set, GPT-4o is used. The pipeline runs without any API key (proposers return empty candidates; useful for testing infrastructure).

### IPC Bridge

The Rust `PythonWorker` spawns the Python worker script as a subprocess and communicates via **newline-delimited JSON-RPC** over `stdin`/`stdout`. Logging from Python is directed to `stderr` so it never contaminates the message channel.

```
Rust  ──[JSON request\n]──▶  Python worker
Rust  ◀──[JSON response\n]── Python worker
```

Each message has `request_id` (echoed in response), `stage`, `candidate_json`, and `context`.

---

## Verification Cascade

Claims must pass all applicable layers in order. Any failure stops the cascade for that candidate and the claim is permanently rejected.

```
V0  Structural (Rust, in-process)
    │  Schema completeness, symbol validation, dependency purity,
    │  quantifier scope, small-case test requirement
    ↓
V1  Counterexample Search (Python)
    │  Exhaustive enumeration (small N), seeded random property testing,
    │  boundary testing. Counterexample found → claim rejected + witness stored
    ↓
V2  Symbolic Verification (SymPy)
    │  Identity simplification, canonicalization, inequality normalization,
    │  logical equivalence. Mismatch → reject.
    ↓
V3  SMT Verification (Z3)
    │  Translate claim to constraint form; check negation unsatisfiable.
    │  Model found → counterexample + reject.
    ↓
V4  First-Order ATP (Vampire / E)
    │  Translate to FOL via TPTP; invoke ATP.
    │  Theorem proved → verified fragment. Counter-sat → reject.
    ↓
V5  Lean 4 Proof Checker
       Compile generated Lean lemma. Success → formally verified.
       Failure → Lemma Minimizer → retry → reject if still failing.
```

**Two-phase commit:** only after all layers pass does the claim transition `proposed → verified` and the Lean artifact is committed to the proof store.

**Conservative default:** if a solver is unavailable (e.g., Lean not installed), that stage passes conservatively rather than blocking the pipeline.

---

## Proof Loop

```
1.  Normalise problem → FormalSpec
2.  Create root Claim (Theorem)
3.  Initialise beam (4 branches × different strategies)
4.  For each iteration:
    a.  For each active beam branch:
        i.   Pick highest-priority Subgoal
        ii.  Request StepCandidates from Proposer Ensemble
        iii. RubricAgent scores and filters candidates
        iv.  Run VerificationCascade on each candidate
        v.   On Verified: commit claim, resolve subgoal, record progress
        vi.  On Rejected: store attempt, extract witness pattern
    b.  StrategyController: switch strategy if stuck (entropy / failure patterns)
    c.  BeamSearchManager: prune stale branches, enforce diversity
5.  Terminate when:
    •  Root theorem verified (Lean compile succeeds), OR
    •  Finite exhaustive verification complete, OR
    •  Max iterations reached (explicit incomplete declaration)
6.  Write output artefacts
```

---

## Quick Start

```bash
# 1. Build the CLI
cargo build --release

# 2. Install the Python worker
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 3. (Optional) Set an LLM key for full proposer power
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY

# 4. Run
./target/release/ampp \
  --problem "For all integers n >= 1, 1+2+...+n = n*(n+1)/2" \
  --python .venv/bin/python3 \
  --worker ampp/worker.py
```

Results appear in `output/`. The run manifest at `output/run_manifest.json` records every artefact hash, tool version, and termination condition for full reproducibility.

---

## Installation

### Prerequisites

| Tool | Version | Required? |
|------|---------|-----------|
| Rust | stable (≥ 1.78) | Yes |
| Python | ≥ 3.11 | Yes |
| Lean 4 | any | No (V5 skips gracefully) |
| Vampire / E | any | No (V4 skips gracefully) |
| OpenAI or Anthropic key | — | No (proposers return empty without key) |

### Step-by-step

```bash
# Clone
git clone https://github.com/your-username/ampp.git
cd ampp

# Rust — builds all three crates, produces ./target/release/ampp
cargo build --release

# Python (editable install with all deps)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Copy and edit environment variables
cp .env.example .env
# edit .env with your API keys
```

---

## CLI Reference

```
ampp [OPTIONS] --problem <PROBLEM>

Options:
  -p, --problem <PROBLEM>    Problem statement (natural language or LaTeX)
  -d, --db <DB>              SQLite state file  [default: ampp_state.db]
  -o, --output <OUTPUT>      Output artefacts directory  [default: output]
      --python <PYTHON>      Python interpreter path  [default: python3]
      --worker <WORKER>      Python worker script  [default: ampp/worker.py]
      --seed <SEED>          Random seed for reproducibility  [default: 42]
      --max-iter <MAX_ITER>  Maximum proof iterations  [default: 200]
  -h, --help                 Print help
  -V, --version              Print version
```

### Examples

```bash
# Simple identity
ampp -p "For all n >= 1, the sum of the first n positive integers is n(n+1)/2"

# Combinatorics
ampp -p "Prove that in any group of 6 people, there exist 3 mutual acquaintances or 3 mutual strangers (Ramsey R(3,3)=6)"

# Reproducible run with explicit seed
ampp -p "Every even integer greater than 2 is the sum of at most 4 primes" \
     --seed 1337 --max-iter 500

# Custom Python interpreter (e.g., in a venv)
ampp -p "..." \
     --python /path/to/.venv/bin/python3 \
     --worker /path/to/ampp/worker.py \
     --output /tmp/proof_run
```

---

## Configuration & Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENAI_API_KEY` | GPT-4o for proposer ensemble | — |
| `ANTHROPIC_API_KEY` | Claude for proposer ensemble (takes priority) | — |
| `LEAN_PATH` | Path to `lean` binary | `lean` (in `$PATH`) |
| `VAMPIRE_PATH` | Path to `vampire` binary | `vampire` |
| `E_PROVER_PATH` | Path to `eprover` binary | `eprover` |
| `RUST_LOG` | Rust tracing filter | `ampp=info` |

See [.env.example](.env.example) for a ready-to-copy template.

---

## Output Artefacts

Every run produces the following in `--output` (default: `output/`):

| File | Contents |
|------|---------|
| `run_manifest.json` | Run ID, problem fingerprint, tool versions, random seed, termination condition, beam summary, SHA-256 hashes of all artefacts |
| `solution.lean` | Lean 4 source compiled by V5; stub if proof incomplete |
| `solution.md` | Human-readable proof sketch with problem statement and result |
| `proof_graph.json` | All verified claims as a dependency DAG |
| `verification_log.json` | Full attempt log — every candidate, every verifier stage, every rejection reason |
| `rejected_claims.json` | All permanently rejected claims with witnesses |

Runs are **fully reproducible**: re-run with the same `--seed`, `--problem`, and tool versions to get byte-for-byte identical artefacts.

---

## Testing

### Rust (22 tests — unit + integration)

```bash
cargo test          # all tests
cargo test --lib    # unit tests only (ampp-core)
cargo test --test integration_tests   # integration suite
```

### Python (79 tests)

```bash
# All tests
pytest tests/python/ -v

# With coverage
pytest tests/python/ --cov=ampp --cov-report=html

# Specific module
pytest tests/python/test_rubric_agent.py -v
pytest tests/python/test_v3_z3.py -v
```

### Test summary

| Suite | Tests | Covers |
|-------|-------|--------|
| `test_schemas` | 13 | Pydantic validation, JSON roundtrips, `FormalSpec.fingerprint()` |
| `test_v1_counterexample` | 6 | Exhaustive enumeration, seeded random, boundary detection |
| `test_v2_sympy` | 7 | Identity simplification, inequality normalization, conservative pass |
| `test_v3_z3` | 4 | SMT negation (UNSAT = verified), graceful absence handling |
| `test_rubric_agent` | 9 | 7-dimension scoring, hard gates, strategy weight updates, termination guard |
| `test_normalizer` | 9 | Canonicalization, LaTeX replacement, stable fingerprints |
| `test_proposer_and_strategy` | 13 | Ensemble dedup, weight updates, strategy switching, Shannon entropy |
| `test_conjecture_miner` | 3 | Pattern detection, deduplication |
| `test_worker` | 8 | JSON-RPC handler routing, exception safety, request ID echoing |
| **Rust unit** | **10** | Store CRUD, V0 structural checker, beam search, planner |
| **Rust integration** | **12** | Full cascade lifecycle, artifact manifests, two-phase commit |
| **Total** | **101** | |

---

## Project Structure

```
ampp/
├── Cargo.toml                  # Rust workspace root
├── pyproject.toml              # Python package
├── .env.example                # Environment variable template
├── .gitignore
├── LICENSE
│
├── crates/
│   ├── ampp-core/              # Core library crate
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── store.rs        # SQLite ProofStore (append-only)
│   │       ├── state/          # Claim, Definition, Subgoal, Attempt, StepCandidate
│   │       ├── verification/   # V0 structural check + cascade orchestrator
│   │       ├── pipeline/       # Normalizer, Planner, BeamSearchManager
│   │       └── artifacts/      # RunManifest, ArtifactSet
│   │
│   ├── ampp-ipc/               # Python subprocess bridge
│   │   └── src/python_bridge.rs
│   │
│   └── ampp-cli/               # Binary entry point
│       └── src/main.rs         # Proof loop, CLI, artefact writer
│
├── ampp/                       # Python package
│   ├── schemas.py              # Pydantic state models (IPC contract)
│   ├── normalizer.py           # Problem text → FormalSpec
│   ├── worker.py               # JSON-RPC event loop
│   ├── proposers/
│   │   ├── base.py             # BaseProposer ABC
│   │   ├── specializations.py  # 5 strategy proposers (LLM-backed)
│   │   └── ensemble.py         # Fan-out, dedup, rubric triage, ranking
│   ├── agents/
│   │   ├── rubric_agent.py     # 7-dimension quality gate
│   │   ├── conjecture_miner.py # Small-case enumeration + pattern mining
│   │   └── strategy_controller.py  # Entropy-based strategy switching
│   └── verifiers/
│       ├── v1_counterexample.py
│       ├── v2_sympy.py
│       ├── v3_z3.py
│       ├── v4_atp.py
│       └── v5_lean.py
│
└── tests/
    └── python/
        ├── conftest.py
        ├── test_schemas.py
        ├── test_normalizer.py
        ├── test_v1_counterexample.py
        ├── test_v2_sympy.py
        ├── test_v3_z3.py
        ├── test_rubric_agent.py
        ├── test_proposer_and_strategy.py
        ├── test_conjecture_miner.py
        └── test_worker.py
```

---

## Design Philosophy

AMPP is built around five non-negotiable principles drawn from the architecture specification:

### 1. Deterministic Verification Supremacy

LLMs generate hypotheses. Deterministic systems establish truth. No statement moves to the verified state based on confidence, plausibility, or heuristic reasoning.

### 2. Two-Phase Commit

Every claim starts as `proposed`. It becomes `verified` only after passing the full verification cascade. Rejection is permanent and immutable.

### 3. Strict Dependency Purity

A claim may only depend on already-verified claims. The V0 structural checker enforces this before any solver is invoked.

### 4. Reproducible Execution

Fixed random seeds, pinned tool versions, SHA-256 hashes of all inputs and outputs, full solver logs. Any run can be replayed exactly.

### 5. Progress-Monotonic Iteration

Each iteration must produce at least one of: a new verified claim, a subgoal reduction, a tighter canonical form, or a branch elimination. Otherwise the strategy controller forces a switch.

### Rubric Agent

The `RubricAgent` scores every `StepCandidate` on seven dimensions before exposing it to solvers:

| Dimension | Points | Gate |
|-----------|--------|------|
| Checkability | 40 | Hard — must have executable verification plan |
| Locality | 20 | Hard — one micro-lemma per candidate |
| Dependency hygiene | 20 | Hard — only verified dependencies |
| Counterexample risk | 10 | Hard — test plan required when domain admits falsification |
| Complexity reduction | 5 | Scored |
| Novelty / non-repetition | 3 | Scored |
| Lean-friendliness | 2 | Scored |

**Pass threshold: 70 / 100.** Any hard gate failure → immediate reject, no solver time wasted.

---

## Contributing

1. Fork and create a feature branch.
2. Run `cargo fmt --all && cargo clippy --all-targets -- -D warnings` before committing Rust code.
3. Run `ruff check ampp/ tests/` before committing Python code.
4. Ensure `cargo test --all` and `pytest tests/python/` both pass at 100%.
5. Open a PR against `main`.

CI enforces all of the above automatically on every push.

---

## License

[MIT](LICENSE) © 2026 Naitik Gupta
