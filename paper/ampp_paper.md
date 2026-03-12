# AMPP: An Autonomous Mathematical Proof Pipeline Combining Large Language Model Creativity with Deterministic Formal Verification

**Naitik Gupta**

---

## Abstract

We present AMPP (Autonomous Mathematical Proof Pipeline), a production-grade system that autonomously constructs and formally verifies proofs for advanced mathematical problems in combinatorics, number theory, and extremal graph theory. AMPP enforces a single global invariant throughout its execution: *no mathematical claim ever enters the proof state unless a deterministic verifier independently confirms it.* The system achieves this by maintaining a strict separation between creative hypothesis generation — handled by an ensemble of ten specialized Large Language Model (LLM) proposers — and correctness determination, which is handled exclusively by a five-layer deterministic verification cascade culminating in Lean 4 formal proof compilation. A Rubric Agent continuously scores and constrains the workflow quality, preventing hallucinated leaps, vague lemmas, and repeated dead ends. The Rust core enforces a two-phase commit protocol over an append-only SQLite proof store, while a Python solver stack provides LLM orchestration, symbolic computation, and formal verification. We describe the architecture, the verification cascade (V0 structural checking through V5 Lean 4 compilation), the ten strategy proposer families, and the beam search over proof states. All proofs produced by AMPP are reproducible artefacts: the system emits a Lean 4 source file, a human-readable proof narrative, a proof dependency DAG, and a full run manifest with pinned tool versions and random seeds. AMPP supports multiple LLM backends including OpenAI, Anthropic, and OpenAI-compatible self-hosted servers, with zero code changes required.

---

## 1. Introduction

Automated theorem proving has a long history, from early resolution-based provers such as MESON and Otter to modern interactive proof assistants including Coq, Isabelle, and Lean 4. The advent of large language models has reopened the question of whether informal mathematical intuition — the kind that guides human mathematicians — can be operationalized in an automated system without sacrificing formal rigor.

The key tension is this: LLMs are excellent generators of plausible-sounding mathematical reasoning but are not reliable verifiers of truth. Systems that rely on LLM outputs without an independent verification step will accumulate unverified claims and eventually produce unsound proofs. Several recent approaches have grappled with this problem, including AlphaProof (DeepMind, 2024), which trains a model to generate Lean 4 proofs for IMO problems, and Hypertree Proof Search (Lample et al., 2022), which uses Monte Carlo tree search over a formal tactic language. These systems demonstrate that LLM-guided formal proof search is feasible but require substantial reinforcement learning infrastructure.

AMPP takes a different approach. Rather than training a specialized prover model, AMPP orchestrates general-purpose LLMs as *proposers* that generate structured `StepCandidate` objects — small, checkable proof steps — while routing each candidate through an escalating verification cascade before accepting it. This separation means that the system can use any capable instruction-following LLM, including locally hosted open-source models, as the creative engine, reserving formal trust for deterministic tools.

### 1.1 Contributions

1. **Architecture**: A complete, production-grade autonomous proof pipeline that enforces two-phase commit semantics for all mathematical claims.
2. **Verification Cascade**: A five-layer cascade (V1: exhaustive counterexample, V2: SymPy, V3: Z3 SMT, V4: Vampire/E first-order ATP, V5: Lean 4) with well-defined failure modes and structured witnesses.
3. **Proposer Ensemble**: Ten parallel specialized LLM proposers covering the major proof strategies used in competition mathematics.
4. **Rubric Agent**: A meta-verifier that enforces process quality — preventing common failure modes before they consume solver time — and dynamically reweights strategy families based on observed outcomes.
5. **Reproducibility Guarantees**: All runs emit a `run_manifest.json` with fixed seeds, tool versions, and prompt hashes, enabling exact replay.
6. **Provider Flexibility**: Unified provider abstraction supporting OpenAI, Anthropic, and any OpenAI-compatible server (OpenClaw, Ollama, vLLM) with zero code changes.

---

## 2. System Architecture

### 2.1 High-Level Design

AMPP is structured as two cooperating subsystems:

**Rust Core** (`ampp-core`, `ampp-ipc`, `ampp-cli`): handles the orchestration loop, state management, beam search over proof branches, and V0 structural verification. The core is written in Rust for determinism, performance, and memory safety. Proof state is stored in an append-only SQLite database using WAL mode, ensuring that no claim is ever silently overwritten.

**Python Solver Stack** (`ampp/`): handles LLM interaction, symbolic computation, and formal verification (V1–V5). The Python worker is spawned as a subprocess and communicates with the Rust core via JSON-RPC over stdin/stdout. This architecture allows the Python stack to use any available solver tool without constraining the Rust core.

The two subsystems interact through a `PythonWorker` IPC bridge that marshals structured requests and responses. The Rust core is the authority on proof state; the Python stack is a stateless request handler.

### 2.2 State Model

All state objects are Pydantic v2 models serialized to SQLite. The core objects are:

- **`Claim`**: a mathematical statement with a status (`proposed`, `verified`, `rejected`), a list of dependency claim IDs, verification artefacts, and a proof hash.
- **`Subgoal`**: a prioritized proof obligation, ranked by `impact_score / difficulty_estimate`.
- **`Counterexample`**: a falsifying witness including the construction method and random seed.
- **`Attempt`**: a record of a failed verification attempt including the stage of failure and the failure reason.

The state model is append-only. Verified claims are immutable. Rejected claims are permanently marked and their failure reasons are indexed for pattern extraction by the Rubric Agent.

### 2.3 Formal Normalization

Before any reasoning occurs, the input problem is converted by the `Normalizer` into a structured `FormalSpec` with explicit fields for variable declarations, domains, quantifiers, constraints, the target statement, and known edge cases. All notation is canonicalized at this stage. No informal ambiguity is permitted to propagate into the reasoning pipeline.

---

## 3. Verification Cascade

Each candidate proof step must survive five escalating verification layers. The cascade is designed so that cheap, fast checks occur first and expensive formal checks occur last.

### 3.1 V0 — Structural Verification (Rust)

The Rust core performs structural checks before any Python invocation:

- All symbols in the step are declared in scope.
- All claimed domains are consistent with variable declarations.
- All quantifiers have a valid scope.
- All dependency claim IDs refer to existing **verified** claims (dependency purity).

V0 failures are synchronous and immediate, adding no solver latency.

### 3.2 V1 — Counterexample Search

The Python counterexample engine searches for a falsifying witness using two strategies:

1. **Exhaustive enumeration** over small parameter ranges (configurable, default to n ≤ 30 for discrete problems).
2. **Random property testing** with a fixed seed, using a uniform distribution over the problem domain.

If a counterexample is found, the witness is stored in the `Counterexample` table with its construction method and seed. The claim is marked rejected, and the structural features of the witness are extracted and returned to the Rubric Agent for pattern generalization.

V1 is the most computationally cheap layer that can detect false claims and is therefore given high priority. A claim that passes V1 is not assumed correct; it simply has no small counterexample.

### 3.3 V2 — SymPy Symbolic Verification

For algebraic and analytic claims, the SymPy computer algebra system verifies:

- Identity simplification (both sides reduce to the same canonical form)
- Inequality normalization
- Polynomial and rational function equivalence
- Logical composition of verified sub-identities

V2 applies primarily to claims of the form `expr_A = expr_B` or `expr_A ≥ expr_B` where both sides can be expressed in SymPy's symbolic language.

### 3.4 V3 — Z3 SMT Verification

The claim is translated into Z3 constraint form. The negation of the claim is asserted and the solver is queried for satisfiability:

- If UNSAT: no counterexample exists within the constraint theory — claim is verified at this layer.
- If SAT: the satisfying assignment is a counterexample — stored and claim rejected.

Z3 handles quantifier-free linear arithmetic, integer arithmetic, and bitvector theories effectively. For quantified claims, the translation may fall back to V4.

### 3.5 V4 — First-Order ATP (Vampire / E Prover)

The claim is translated into first-order predicate logic. The Vampire or E Prover attempts to find a proof (for the positive claim) or a countermodel (which would indicate falsity):

- **Theorem**: the claim follows from the axioms — verified at this layer.
- **CounterSatisfiable**: a model falsifies the claim — rejected.
- **Timeout / Unknown**: claim proceeds to V5 without a V4 decision.

V4 is optional; if neither Vampire nor E is installed, this layer is skipped and the claim proceeds directly to V5.

### 3.6 V5 — Lean 4 Formal Verification

Each candidate step includes a `lean_stub` field — a partial Lean 4 proof that the proposer generates. The verifier completes this stub into a minimal lemma and attempts local compilation using the Lean 4 toolchain.

- **Compilation succeeds**: the claim is considered formally verified. This is the highest trust level.
- **Compilation fails**: the Lemma Minimizer is invoked to split the claim into smaller sub-lemmas, and compilation is retried on each sub-lemma individually.

The Lean 4 toolchain version is pinned in the run manifest. Only after successful Lean compilation does a claim transition from `proposed` to `verified`.

---

## 4. Proposer Ensemble

The Proposer Ensemble contains ten independent proposers, each specialized in a different proof strategy family. They execute in parallel for each subgoal, and the resulting `StepCandidate` objects are collected and passed to the Rubric Agent for triage.

Each proposer generates structured `StepCandidate` objects with mandatory fields:

- `subgoal_id`: the target subgoal
- `action_type`: the strategy classification
- `new_claims`: a list of new claim statements proposed
- `dependencies`: IDs of verified claims this step depends on
- `verification_plan`: which layers should apply and success criteria
- `small_case_tests`: explicit test cases for V1
- `lean_stub`: a partial Lean 4 proof attempt

Any candidate missing a mandatory field is immediately discarded.

### 4.1 The Ten Strategy Families

| Proposer | Technique | Trigger conditions |
|----------|-----------|-------------------|
| `InductionProposer` | Standard induction | Statement quantified over a well-ordered set |
| `StrongInductionProposer` | Complete induction | Inductive step requires all smaller values |
| `MinimalCounterexampleProposer` | Minimal counterexample | Existence claims admitting a minimum element |
| `ExtremalProposer` | Extremal principle | Optimization problems over finite structures |
| `InvariantMonovariantProposer` | Invariants / monovariants | Processes with preserved or monotone quantities |
| `AlgebraicNormalizationProposer` | Algebraic manipulation | Claims expressible as polynomial identities |
| `DoubleCountingProposer` | Double counting | Combinatorial identities via two counting methods |
| `ConstructiveProposer` | Explicit construction | Existence proofs requiring an explicit witness |
| `GraphTranslationProposer` | Graph reinterpretation | Problems amenable to graph-theoretic encoding |
| `ContradictionProposer` | Proof by contradiction | Irrationality, impossibility, lower bounds |

---

## 5. Rubric Agent

The Rubric Agent implements a process-quality meta-verifier. It does not verify mathematical truth — that is the cascade's responsibility — but it enforces that candidates are worth spending solver time on.

### 5.1 Triage (Before Verification)

Each `StepCandidate` is scored on seven dimensions:

1. **Checkability** (mandatory): does the candidate include a complete, executable verification plan?
2. **Locality** (mandatory): does the step propose exactly one small, independent claim?
3. **Dependency hygiene** (mandatory): does the step depend only on verified claims?
4. **Counterexample risk** (mandatory): does the candidate specify small-case test bounds?
5. **Complexity reduction** (scored): does the step measurably reduce proof depth or goal size?
6. **Novelty** (scored): is the step semantically distinct from previously rejected candidates?
7. **Lean-friendliness** (scored): is the statement expressible in Lean's type theory?

Candidates failing any mandatory dimension are hard-rejected before any solver is invoked. Scored dimensions produce a priority ordering for the candidates that pass triage.

### 5.2 Postmortem (After Verification)

After each verification outcome, the Rubric Agent:

- Classifies the failure stage (V1, V2, V3, V4, V5) and the failure reason
- Updates a failure pattern index (prevents regenerating the same flawed structure)
- Adjusts the per-strategy weight vector: successful strategies gain weight; repeated failures lose weight
- Adjusts step-size control: if V5 failures dominate, the Rubric Agent requires smaller steps in subsequent iterations

### 5.3 Termination Governance

The Rubric Agent also controls termination. It blocks the system from declaring completion unless:

- The top-level theorem is verified by Lean 4 compilation, OR
- The state explicitly marks incompleteness with all supporting artefacts logged

This prevents the system from silently accepting an incomplete proof.

---

## 6. Beam Search and Strategy Control

### 6.1 Beam Search

AMPP maintains 3–6 concurrent proof branches (configurable via `AMPP_BEAM_WIDTH`). Each branch represents an independent proof state — a different sequence of verified claims leading toward the target theorem. Branches are ranked by:

- Number of verified claims
- Subgoal reduction rate
- Structural diversity from other active branches

The Strategy Controller enforces beam diversity: at least 60% of active beam states must use different strategy families. This prevents the beam from collapsing into near-identical proof paths.

### 6.2 Strategy Switching

The Strategy Controller triggers a strategy family switch when:

- No new verified claims have been added in M consecutive iterations (stale threshold)
- The last K failure reasons are identical (repeated failure pattern)
- The Shannon entropy over recent failure distribution falls below a threshold (entropy-based switch)

When a switch is triggered, the lowest-ranked beam branch is replaced with a new branch using the highest-weighted strategy family that is not currently active in the beam.

---

## 7. Conjecture Mining

The Conjecture Mining Engine operates as a background process that continuously enumerates small problem instances and extracts invariants, candidate bounds, and structural conjectures. Mining operates in two phases:

**Deterministic phase**: computes difference sequences, ratio sequences, parity patterns, divisibility structure, and fits O(·) asymptotic bounds to the observed data. Conjectures are generated from detected patterns without any LLM involvement.

**LLM phase**: the deterministic observations are passed to the LLM with a structured prompt requesting additional conjectures. The LLM output is parsed and deduplicated against the `_seen` set, which persists across calls to prevent re-mining the same conjectures.

All conjectures produced by the miner must still pass the full verification cascade before entering the proof state.

---

## 8. Reproducibility

Every AMPP run produces a `run_manifest.json` containing:

- Random seeds for all stochastic components (LLM temperature, V1 random testing)
- Tool versions: Lean 4 toolchain, Z3, Vampire, SymPy, Python, Rust
- SHA-256 hashes of all prompts sent to the LLM
- SHA-256 hashes of all solver inputs
- Timestamp and problem statement (normalized form)

Given the manifest, any run can be exactly replayed. This is essential for peer review and for detecting regressions when tool versions change.

---

## 9. LLM Provider Abstraction

AMPP's LLM layer is built around a `LLMProvider` abstract base class with a single required method `complete(messages) → str` and an optional `complete_json(messages, schema) → dict`. Three concrete implementations are provided:

- **`OpenAIProvider`**: wraps the OpenAI Python SDK. Respects `OPENAI_BASE_URL` for transparent OpenClaw / OpenAI-compatible server support.
- **`AnthropicProvider`**: wraps the Anthropic Python SDK.
- **`NullProvider`**: returns empty responses for testing without an API key.

The active provider is selected by the `AMPP_LLM_PROVIDER` environment variable and can be switched at runtime via `set_provider()`. All proposers and agents call `get_provider()` to obtain the current provider, so switching backends requires no code changes anywhere in the system.

This design means AMPP can be used with local LLMs (Llama, Mistral, Qwen, DeepSeek) served through any OpenAI-compatible inference server such as Ollama, LM Studio, vLLM, or a commercial OpenClaw deployment.

---

## 10. Related Work

**AlphaProof** (DeepMind, 2024) trains a reinforcement-learning model to generate Lean 4 proofs for IMO-level problems, achieving silver-medal performance. Unlike AMPP, AlphaProof requires specialized training and is not a general-purpose proof search framework.

**Hypertree Proof Search** (Lample et al., 2022) uses Monte Carlo tree search over formal proof states with LLM-generated tactic suggestions. AMPP differs by operating at the level of mathematical claims rather than formal tactics, which allows it to exploit the full diversity of proof strategy families.

**Draft, Sketch, and Prove** (Jiang et al., 2023) uses LLMs to generate proof sketches that are then elaborated into Lean 4 proofs. AMPP extends this idea with a more structured verification cascade and an explicit quality gate (the Rubric Agent) that prevents low-quality sketches from consuming solver resources.

**Lean Copilot** (Han et al., 2024) provides interactive LLM assistance within the Lean 4 IDE. AMPP is fully autonomous and does not require a human in the loop.

**Minerva** (Lewkowycz et al., 2022) demonstrates LLM mathematical reasoning at scale but without formal verification. AMPP uses LLM generation as a component within a formally verified pipeline rather than as a standalone reasoner.

---

## 11. Current Limitations

1. **Lean 4 stub quality**: the quality of V5 verification depends heavily on the LLM's ability to generate syntactically valid Lean 4 stubs. Weaker local models may produce stubs that require extensive minimization.

2. **Quantified formulas in Z3**: Z3's handling of universally quantified formulas is incomplete. Claims requiring quantifier instantiation strategies may time out at V3 and proceed to V4/V5 unnecessarily.

3. **ATP coverage**: V4 uses untyped first-order logic, which can express a wide class of mathematical statements but not those requiring higher-order reasoning (e.g., statements quantifying over functions or sets).

4. **Problem scope**: the system is designed for competition-style discrete mathematics. Continuous analysis problems (epsilon-delta arguments, measure theory) require extensions to the verifier stack not currently implemented.

---

## 12. Conclusion

AMPP demonstrates that a clean architectural separation between creative hypothesis generation and deterministic formal verification produces a system that is both mathematically safe and practically flexible. The two-phase commit protocol, enforced by the Rust core, ensures that no unverified reasoning ever contaminates the proof state. The ten-proposer ensemble, weighted by the Rubric Agent, provides broad strategic coverage. The five-layer verification cascade provides a graceful escalation from fast heuristic checks to Lean 4 formal proof.

The system's provider abstraction makes it accessible to researchers without commercial API access: local models served through any OpenAI-compatible inference server can be substituted with a single environment variable change. All proofs are reproducible artefacts, enabling peer review and regression testing.

Future work includes extending the verifier stack to handle continuous analysis, training a Lean 4 stub completion model fine-tuned on AMPP's rejected/accepted candidate pairs, and integrating with the Mathlib4 library for a richer vocabulary of verified mathematical results.

---

## References

- Avigad, J., de Moura, L., and Ullrich, S. (2023). *Theorem Proving in Lean 4*. Microsoft Research.
- de Moura, L. and Bjørner, N. (2008). Z3: An efficient SMT solver. *TACAS 2008*.
- Han, J. M., Rabe, F., and Szegedy, C. (2024). *Lean Copilot: LLMs as Copilots for Theorem Proving in Lean*. arXiv:2404.09235.
- Jiang, A. Q., Welleck, S., Zhou, J. P., Li, W., Liu, J., Jamnik, M., Lacroix, T., Wu, Y., and Lample, G. (2023). Draft, Sketch, and Prove: Guiding Formal Theorem Provers with Informal Proofs. *ICLR 2023*.
- Kovács, L. and Voronkov, A. (2013). First-Order Theorem Proving and Vampire. *CAV 2013*.
- Lample, G., Lacroix, T., Lachaux, M.-A., Rodriguez, A., Hayat, A., Lavril, T., Ebner, G., and Martinet, J. (2022). Hypertree Proof Search for Neural Theorem Proving. *NeurIPS 2022*.
- Lewkowycz, A., Andreassen, A., Dohan, D., Dyer, E., Michalewski, H., Ramasesh, V., Slone, A., Anil, C., Schlag, I., Gutman-Solo, T., and Evans, N. (2022). Solving Quantitative Reasoning Problems with Language Models. *NeurIPS 2022*.
- Matichuk, D., Murray, T., and Andronick, J. (2016). *Eisbach: A Proof Method Language for Isabelle*. Journal of Automated Reasoning.
- Schulz, S. (2013). System Description: E 1.8. *LPAR-19*.
- Trinh, T. H., Wu, Y., Le, Q. V., He, H., and Luong, T. (2024). Solving Olympiad Geometry without Human Demonstrations. *Nature 2024*.
