<p align="center">
  <strong>AMPP</strong><br>
  <em>Autonomous Mathematical Proof Pipeline</em>
</p>

<p align="center">
  <a href="#architecture">Architecture</a> |
  <a href="#how-it-works">How It Works</a> |
  <a href="#installation">Installation</a> |
  <a href="#usage">Usage</a> |
  <a href="#verification-stack">Verification Stack</a> |
  <a href="#project-structure">Project Structure</a>
</p>

---

AMPP is an autonomous system that proves mathematical theorems with machine-checked guarantees. It targets advanced combinatorics, number theory, and Erdos-style problems — the kind of mathematics where a single clever construction or counterexample can change everything.

The system separates creativity from correctness. Language models generate hypotheses. Deterministic verifiers — SymPy, Z3, Vampire, and Lean 4 — establish truth. Nothing enters the proof state unless a formal checker confirms it.

**The invariant is absolute: no unverified claim contaminates the proof.**

---

## Architecture

AMPP operates as a closed loop. Each iteration takes the current proof state, identifies the most promising subgoal, generates proof candidates through an ensemble of ten specialized proposers, subjects them to a six-layer verification cascade, and commits verified results through an atomic two-phase protocol.

```
                            +-------------------+
                            |   Problem Input   |
                            +--------+----------+
                                     |
                            +--------v----------+
                            |    Normalizer     |  raw text --> FormalSpec
                            +--------+----------+
                                     |
                            +--------v----------+
                            |     Planner       |  FormalSpec --> subgoal DAG
                            +--------+----------+
                                     |
                  +------------------v------------------+
                  |        Proposer Ensemble            |
                  |  10 strategies running in parallel  |
                  +------------------+------------------+
                                     |
                            +--------v----------+
                            |   Rubric Agent    |  quality gate / filter
                            +--------+----------+
                                     |
              +----------------------v----------------------+
              |         Verification Cascade                |
              |  V0: Structural   V1: Counterexample        |
              |  V2: Symbolic     V3: SMT (Z3)              |
              |  V4: ATP          V5: Lean 4                 |
              +----------------------+----------------------+
                                     |
                            +--------v----------+
                            |  Two-Phase Commit |  atomic state update
                            +--------+----------+
                                     |
                            +--------v----------+
                            |    State Update   |
                            +--------+----------+
                                     |
                                     +-------> loop
```

Six parallel subsystems run alongside the main loop:

- **Beam Search Manager** maintains 3-6 concurrent proof states to prevent premature strategic commitment.
- **Strategy Controller** dynamically switches among proof strategies when progress stalls.
- **Rubric Agent** enforces process quality, prevents hallucinated leaps, and gates verification spending.
- **Counterexample Refiner** learns structural patterns from failed claims and prevents repeated failures.
- **Conjecture Miner** enumerates small instances and discovers invariants, bounds, and structural conjectures.
- **Lemma Minimizer** decomposes failing Lean proofs into smaller, independently verifiable pieces.

---

## How It Works

### The Proof State

All state is append-only and versioned. Every mutation increments a version counter and logs the change. The state contains:

- **Claims** — mathematical assertions with status `proposed`, `verified`, or `rejected`. Rejected claims are immutable.
- **Subgoals** — nodes in a dependency DAG, ranked by `impact_score / estimated_complexity`.
- **Counterexamples** — concrete witnesses that disprove proposed claims.
- **Attempts** — full records of every failed proof attempt, including failure stage and strategy used.

### The Proposer Ensemble

Ten specialized proposers generate structured `StepCandidate` objects in parallel:

| Proposer | Method |
|---|---|
| Induction | Standard and strong induction on natural numbers |
| Extremal Principle | Select minimal/maximal element and derive contradiction |
| Invariant | Identify quantities preserved or monotone under operations |
| Double Counting | Count the same set two ways to establish equality |
| Constructive | Explicitly build the required object |
| Contradiction | Assume negation and derive inconsistency |
| Algebraic Normalization | Rewrite expressions into canonical algebraic forms |
| Graph Translation | Reinterpret the problem in graph-theoretic language |
| Minimal Counterexample | Assume a smallest counterexample exists and show it cannot |
| Counterexample Search | Systematically search for disproving witnesses |

Every proposer emits structured `StepCandidate` objects. No prose is accepted. Candidates with missing fields are silently discarded.

### The Rubric Agent

Before any candidate reaches the verification cascade, the Rubric Agent applies four mandatory gates:

1. **Checkability** — the candidate must include a concrete, executable verification plan.
2. **Locality** — the step must be a micro-lemma, not a multi-claim leap.
3. **Dependency Hygiene** — all dependencies must point to already-verified claims.
4. **Counterexample Risk Control** — falsifiable claims must include small-case test plans.

Failure on any gate means immediate rejection. Candidates that pass are additionally scored on complexity reduction, novelty, and Lean-friendliness.

After verification (pass or fail), the Rubric Agent runs a postmortem that adjusts strategy weights, tracks failure patterns by verifier stage, and tightens constraints for future iterations.

---

## Verification Stack

Every claim passes through an escalating cascade. Failure at any layer halts progression and rejects the claim.

### V0 --- Structural Checks

Symbol validation, domain consistency, quantifier scope analysis, and dependency purity verification. This layer runs on every candidate unconditionally.

### V1 --- Counterexample Search

Exhaustive enumeration for small parameter values, random property testing with configurable seeds, and boundary case analysis. If a counterexample is found, the witness is stored and the claim is rejected.

### V2 --- Symbolic Verification (SymPy)

Identity simplification, expression canonicalization, inequality normalization, and logical equivalence checking through symbolic computation.

### V3 --- SMT Verification (Z3)

Translates claims into constraint form and checks satisfiability of the negation. If the negation is unsatisfiable, the claim fragment is verified. If Z3 finds a satisfying model, it constitutes a counterexample.

### V4 --- First-Order ATP (Vampire / E)

Translates to TPTP format for first-order automated theorem proving. Proof found means verified fragment. Counter-satisfiable means rejection.

### V5 --- Lean 4 Proof Checker

The final authority. Generates a Lean 4 lemma and compiles it. If compilation succeeds, the claim is verified. If it fails, the Lemma Minimizer attempts decomposition and retry. Lean compilation is mandatory for full verification.

### Two-Phase Commit

After the cascade, the commit engine executes atomically:

- **Phase 1 (Prepare):** Validate all artifacts, compute a deterministic commit hash over the claim and its verification evidence.
- **Phase 2 (Commit):** Update the proof state. Verified claims get artifacts attached. Rejected claims get attempt records and counterexamples logged.

No partial commits. Rejected claims are permanent.

---

## Installation

```bash
git clone https://github.com/yourusername/ampp.git
cd ampp
pip install -e .
```

**Python 3.11+** is required.

### External Tools

The core pipeline runs with Python dependencies alone (SymPy, Z3). For the full verification stack:

| Tool | Layer | Installation |
|---|---|---|
| Lean 4 | V5 | [elan toolchain manager](https://leanprover.github.io/lean4/doc/setup.html) |
| Vampire | V4 | [vprover.github.io](https://vprover.github.io/) |
| E Prover | V4 | [dhbw-stuttgart.de/~sschulz/E](https://wwwlehre.dhbw-stuttgart.de/~sschulz/E/E.html) |

V4 and V5 are optional. The pipeline degrades gracefully — it will skip layers whose tools are unavailable and verify with whatever is present.

---

## Usage

### Command Line

```bash
# Prove a statement directly
ampp "For all n >= 1, the sum 1+2+...+n = n(n+1)/2" --problem-id gauss_sum

# Read from a file
ampp problem.txt --output-dir results --max-iterations 100

# Full options
ampp "..." \
  --problem-id my_theorem \
  --output-dir output \
  --max-iterations 200 \
  --max-time 3600 \
  --seed 42 \
  --lean-project ./my-lean-project \
  --verbose
```

### Python API

```python
from ampp.config import PipelineConfig
from ampp.main import Pipeline

config = PipelineConfig(
    max_iterations=100,
    max_wall_time_seconds=1800,
)

pipeline = Pipeline(config)
artifacts = pipeline.run(
    problem_id="gauss_sum",
    raw_statement="Prove that for all n >= 1, 1+2+...+n = n(n+1)/2",
)

for name, path in artifacts.items():
    print(f"  {name}: {path}")
```

### Output Artifacts

Every run produces a complete, self-contained artifact set:

| File | Contents |
|---|---|
| `solution.lean` | Verified Lean 4 proof that compiles standalone |
| `solution.md` | Human-readable proof narrative with claim graph |
| `proof_graph.json` | Full dependency graph of all claims and their relationships |
| `verification_log.json` | Every verification check across all cascade layers |
| `rejected_claims.json` | All rejected claims, failure reasons, and counterexample witnesses |
| `run_manifest.json` | Reproducibility manifest: config, seeds, tool versions, hashes |

No solution is accepted without its artifact set. The manifest contains everything needed to reproduce the run deterministically.

---

## Design Principles

AMPP is built on five non-negotiable principles:

**1. Two-Phase Commit.** Every claim transition (proposed to verified, proposed to rejected) is an atomic operation with full artifact logging. There are no partial updates.

**2. Dependency Purity.** A claim can only depend on claims that are already verified. No circular dependencies. No forward references. The proof state forms a clean DAG at all times.

**3. Deterministic Verification Supremacy.** The formal proof checker is the final authority. No amount of LLM confidence, plausibility, or heuristic reasoning overrides a failed Lean compilation. Truth is binary.

**4. Reproducible Execution.** Fixed random seeds, pinned tool versions, hashed inputs and outputs, deterministic solver invocations. Every run can be replayed exactly.

**5. Progress-Monotonic Iteration.** Every iteration must achieve at least one of: add a verified claim, reduce the subgoal count, shrink difficulty estimates, eliminate a branch via counterexample, or produce a tighter canonical form. If none of these occur, a strategy switch is forced.

---

## Project Structure

```
ampp/
|-- main.py                          Pipeline orchestrator and CLI entry point
|-- config.py                        All configuration, enumerations, and defaults
|
|-- models/
|   |-- state.py                     Frozen dataclasses: Claim, Subgoal, Counterexample, Attempt
|   |-- step_candidate.py            StepCandidate schema with validation
|   +-- proof_state.py               Append-only versioned proof state container
|
|-- normalizer/
|   +-- normalizer.py                Raw problem text to FormalSpec conversion
|
|-- planner/
|   +-- planner.py                   Subgoal DAG generation and frontier computation
|
|-- proposers/
|   |-- base.py                      Abstract base for all proposers
|   |-- induction.py                 Standard and strong induction
|   |-- extremal.py                  Extremal principle
|   |-- invariant.py                 Invariant and monovariant detection
|   |-- counting.py                  Double counting arguments
|   |-- constructive.py              Direct construction
|   |-- contradiction.py             Proof by contradiction
|   |-- algebraic.py                 Algebraic normalization and rewriting
|   |-- graph_translation.py         Graph-theoretic reinterpretation
|   |-- counterexample_search.py     Minimal counterexample method
|   +-- ensemble.py                  Parallel proposer coordination with strategy weights
|
|-- verification/
|   |-- v0_structural.py             Symbol, scope, and dependency checks
|   |-- v1_counterexample.py         Exhaustive and random counterexample search
|   |-- v2_symbolic.py               SymPy-based symbolic verification
|   |-- v3_smt.py                    Z3 SMT solver integration
|   |-- v4_atp.py                    Vampire/E automated theorem proving
|   |-- v5_lean.py                   Lean 4 compilation and proof checking
|   +-- cascade.py                   Orchestrates V0 through V5 in sequence
|
|-- commit/
|   +-- two_phase.py                 Atomic two-phase commit with hash logging
|
|-- engines/
|   |-- lemma_minimizer.py           Lean failure decomposition and retry
|   |-- counterexample_refiner.py    Learns from counterexamples to refine claims
|   +-- conjecture_miner.py          Small-instance enumeration and pattern discovery
|
|-- controllers/
|   |-- beam_manager.py              Parallel proof state management (3-6 beams)
|   |-- strategy_controller.py       Dynamic strategy switching on stall detection
|   |-- progress_monitor.py          Progress-monotonic invariant enforcement
|   +-- rubric_agent.py              Quality gating, scoring, and policy updates
|
|-- utils/
|   |-- hashing.py                   Deterministic SHA-256 hashing utilities
|   |-- pipeline_logging.py          Structured JSONL event logging
|   +-- sandbox.py                   Sandboxed subprocess execution
|
+-- artifacts/
    +-- generator.py                 Output artifact generation (all six files)
```

---

## Configuration

All behavior is controlled through frozen dataclasses in `config.py`:

```python
from ampp.config import PipelineConfig, VerifierConfig, BeamConfig

config = PipelineConfig(
    max_iterations=200,           # hard iteration cap
    max_wall_time_seconds=3600,   # hard wall-clock cap
    global_seed=42,               # deterministic reproducibility
    verifier=VerifierConfig(
        max_exhaustive_n=12,      # V1: enumerate up to n=12
        z3_timeout_ms=30_000,     # V3: 30s Z3 timeout
        lean_timeout_seconds=120, # V5: 2min Lean compilation
    ),
    beam=BeamConfig(
        min_beams=3,              # minimum concurrent proof states
        max_beams=6,              # maximum concurrent proof states
    ),
)
```

---

## Termination

The pipeline terminates under exactly three conditions:

1. **Theorem verified.** The top-level theorem has been verified through the full cascade including Lean compilation.
2. **Resource exhaustion.** The iteration or wall-time limit has been reached. All progress is preserved in artifacts.
3. **Explicit incompleteness.** The system declares incompleteness and produces a full artifact log documenting exactly what was proved, what failed, and what remains open.

In all cases, the complete artifact set is generated before exit.

---

## License

MIT
