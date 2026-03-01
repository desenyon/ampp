
# Autonomous Mathematical Proof Pipeline

this will be AMPP as an algirthm

## Definitive Architecture Guide

This document defines a complete, production‑grade autonomous proof system designed to solve advanced combinatorics and Erdős‑style problems with strict verification guarantees.

The system enforces a single invariant:

> No mathematical statement becomes part of the proof state unless it is deterministically verified.

All reasoning components are separated from truth validation. LLMs generate hypotheses. Deterministic systems establish truth.

---

# 1. System Philosophy

The pipeline is built around five non‑negotiable principles:

1. Two‑phase commit for all claims.
2. Strict dependency purity.
3. Deterministic verification supremacy.
4. Reproducible execution.
5. Progress‑monotonic iteration.

The system never advances proof state based on confidence, plausibility, or heuristic reasoning alone.

---

# 2. High-Level Architecture

```
Problem Input
      ↓
Normalizer
      ↓
Formal Specification Builder
      ↓
Planner
      ↓
Proposer Ensemble
      ↓
Verification Cascade
      ↓
Lean Gate
      ↓
Two‑Phase Commit
      ↓
State Update
      ↓
Loop
```

Parallel subsystems:

• Counterexample Engine
• Conjecture Mining Engine
• Strategy Switching Controller
• Beam State Manager
• Lemma Minimizer

---

# 3. Core State Model

The state model is append‑only and versioned.

## 3.1 Objects

### Definition

* id
* statement
* canonical_form
* lean_name
* hash

### Claim

* id
* statement
* type (lemma | theorem | auxiliary)
* status (proposed | verified | rejected)
* dependencies
* verification_artifacts
* proof_hash

### Subgoal

* id
* target_claim
* priority_score
* difficulty_estimate
* blockers

### Counterexample

* claim_id
* witness_structure
* generation_method
* seed

### Attempt

* branch_id
* failed_claim
* failure_reason
* verifier_stage

---

# 4. Formal Normalization Layer

The problem is converted into a structured specification:

• Variable declarations
• Domains
• Quantifiers
• Constraints
• Target statement
• Edge cases

All notation is canonicalized before any reasoning occurs.

No informal ambiguity is allowed beyond this stage.

---

# 5. Planner

The planner generates a dependency DAG of subgoals.

Each proposed subgoal must include:

* Statement
* Required dependencies
* Expected proof strategy
* Verification plan

Subgoals are ranked using:

impact_score / estimated_complexity

Impact score measures downstream unlock potential.

---

# 6. Proposer Ensemble

Multiple specialized proposers operate in parallel.

### Specializations

* Induction reasoning
* Strong induction
* Minimal counterexample method
* Extremal principle
* Invariant / monovariant
* Algebraic normalization
* Double counting
* Constructive method
* Graph translation
* Counterexample search reasoning

Each proposer outputs structured StepCandidate objects only.

No prose is accepted.

---

# 7. StepCandidate Schema

Each candidate must include:

* subgoal_id
* action_type
* new_claims
* dependencies
* verification_plan
* small_case_tests
* lean_stub

If any field is missing, the candidate is discarded.

---

# 8. Verification Cascade

Verification occurs in escalating layers.

## V0 — Structural Checks

* Symbol validation
* Domain consistency
* Quantifier scope
* Dependency purity

Failure → reject.

---

## V1 — Counterexample Search

Methods:

* Exhaustive enumeration for small parameters
* Random property testing
* Boundary testing

If counterexample found:

* Claim marked rejected
* Witness stored
* Pattern extracted for refinement

---

## V2 — Symbolic Verification

Using SymPy:

* Identity simplification
* Canonicalization
* Inequality normalization
* Logical equivalence

Mismatch → reject.

---

## V3 — SMT Verification (Z3)

Translate to constraint form.

* If negation unsatisfiable → verified fragment
* If model found → counterexample

---

## V4 — First‑Order ATP (Vampire/E)

Translate to FOL where possible.

Theorem → verified fragment.
CounterSatisfiable → reject.

---

## V5 — Lean Proof Checker

Generate Lean lemma.

Attempt local compilation.

If compilation succeeds → verified.

If fails:

* Invoke Lemma Minimizer
* Retry

Optional formal proof repair may be used, but Lean compilation is mandatory for verification.

---

# 9. Two‑Phase Commit

Only after passing all required verification layers:

proposed → verified

Commit includes:

* Lean artifact
* Build log
* Solver logs
* Hash record

Rejected claims are immutable.

---

# 10. Lemma Minimization Engine

When Lean fails:

1. Remove redundant quantifiers
2. Introduce intermediate lemmas
3. Split casework
4. Separate implications
5. Reduce scope

Smaller lemmas are easier to verify.

---

# 11. Beam Search Manager

Maintain 3–6 active proof states.

Ranking factors:

* Verified claim count
* Subgoal reduction rate
* Structural diversity
* Branching control

Beam prevents premature strategic commitment.

---

# 12. Counterexample‑Guided Refinement

When a claim fails:

* Extract structural features of witness
* Generalize failure condition
* Add exclusion constraints
* Regenerate refined lemma

Prevents repeated failure patterns.

---

# 13. Conjecture Mining Engine

Continuously:

* Enumerate small instances
* Detect invariants
* Infer candidate bounds
* Suggest structural conjectures

All conjectures must still pass full verification cascade.

---

# 14. Strategy Switching Controller

Triggered when:

* No verified claims for M iterations
* Repeated identical failure reasons
* Frontier entropy exceeds threshold

Switch among:

* Direct proof
* Contradiction
* Strong induction
* Minimal counterexample
* Invariant
* Double counting
* Algebraic transform
* Graph reinterpretation

---

# 15. Progress Metric Enforcement

Each iteration must achieve one of:

* Add verified claim
* Reduce subgoal count
* Shrink difficulty estimate
* Eliminate branch via counterexample
* Produce tighter canonical form

Otherwise strategy switch is forced.

---

# 15A. Rubric Agent (Quality Gate and Workflow Controller)

## Purpose

The Rubric Agent enforces process quality and prevents common failure modes (hallucinated leaps, vague lemmas, unverifiable steps, repeated dead ends). It does not prove math. It **scores and constrains** the workflow so that the system remains check-driven.

The Rubric Agent runs continuously in the loop and acts as a **meta-verifier** over  *method* , not  *truth* . Truth remains determined only by the deterministic verification stack.

## Placement in the Architecture

The Rubric Agent is inserted at two points:

1. **Before verification (candidate triage):** rejects low-quality StepCandidates before wasting solver/Lean time.
2. **After verification (postmortem + policy update):** updates strategy weights and proposes workflow corrections.

## Inputs

* Current proof state (verified claims, subgoals, rejected claims)
* Recent attempts and failure logs
* StepCandidates for the active subgoal
* Resource budgets (iteration count, beam width, time)

## Outputs

* Candidate ranking and rejection decisions with reasons
* Required edits to StepCandidates (e.g., must split lemma, must add verification plan)
* Updated strategy weights for proposers and strategy switch controller
* Updated constraints for future candidates (avoid patterns, enforce smaller steps)

## Rubric Structure

The rubric is a scored checklist. Each StepCandidate receives a score and a pass/fail gate.

### Candidate Rubric Dimensions

1. **Checkability (mandatory)**
   * Includes a concrete verification plan that is executable by the verifier stack.
   * Specifies which verifiers apply (brute force, SymPy, Z3, ATP, Lean).
   * Specifies success criteria (e.g., “Lean compiles,” “Z3 shows UNSAT for negation,” “no counterexample up to N”).
2. **Locality of Step (mandatory)**
   * Step is a micro-lemma or micro-transform.
   * Does not bundle multiple independent claims.
   * Does not introduce new major constructs without defining them.
3. **Dependency Hygiene (mandatory)**
   * Depends only on verified claims.
   * No implicit dependencies.
4. **Counterexample Risk Control (mandatory)**
   * Includes a smallest-case test plan.
   * If the domain admits quick falsification, it must specify the bounds to test.
5. **Complexity Reduction (scored)**
   * Step measurably reduces the search space, proof depth, or goal complexity.
   * Examples: fewer quantifiers, smaller parameter range, normalized form.
6. **Novelty / Non-repetition (scored)**
   * Not equivalent (by hash or semantic match) to previously rejected attempts.
   * Does not repeat the same failure mode unless new evidence is provided.
7. **Lean-Friendliness (scored)**
   * Statement is likely expressible in Lean/mathlib.
   * Avoids ambiguous English.
   * Prefers standard library constructs.

### Hard Gates

A StepCandidate is immediately rejected if any of these fail:

* Missing `verification_plan`
* Uses undefined symbols
* Uses unverified dependencies
* Has no `small_case_tests` when the domain admits falsification
* Attempts to advance the main theorem with a non-local leap

## Continuous Monitoring Policies

The Rubric Agent maintains and updates workflow policies across iterations.

### A. Failure Pattern Tracking

From the `Attempt` logs, the Rubric Agent extracts failure modes:

* Counterexample found at V1
* Mismatch at V2 (symbolic)
* Z3 model found at V3
* ATP counter-satisfiable at V4
* Lean proof failure at V5

It then adapts behavior:

* If many V1 failures: tighten falsification bounds and require stronger test plans.
* If many V3 failures: enforce SMT-friendly restatements.
* If many V5 failures: enforce lemma minimization and Lean-friendly phrasing.

### B. Strategy Weighting

The Rubric Agent maintains a weight vector over strategy families:

* induction
* extremal
* invariant
* counting
* construction
* contradiction
* translation (graph/number theory)

Weights update via outcomes:

* Verified steps increase weights for the strategies involved.
* Repeated failures decrease weights.

This controls which proposers are prioritized in the next iteration.

### C. Step Size Control

The Rubric Agent computes a “step size” estimate from candidate structure.

If step size is too large:

* Require splitting into smaller lemmas.
* Require explicit intermediate objects and named subclaims.

### D. Beam State Governance

The Rubric Agent prevents beam collapse into near-duplicate states.

It enforces diversity constraints:

* Different strategy families across beam states
* Different representation choices (graph vs algebra)
* Different lemma paths (dependency differences)

## Integration with Two-Phase Commit

Even if a candidate passes the rubric, it is still only `proposed` until deterministic verification succeeds.

Rubric pass means only:

* “This is worth spending solver/Lean time on.”

## Rubric Agent Termination Role

The Rubric Agent also validates termination.

It blocks termination unless:

* The top-level theorem is verified (Lean compiles), or
* The state explicitly marks incompleteness and includes all artifacts and blockers.

---

# 16. Reproducibility Guarantees

* Fixed random seeds
* Tool version logs
* Hash of all prompts
* Hash of all solver inputs
* Lean toolchain version pinned

Full runs are replayable.

---

# 17. Output Artifacts

Final proof requires:

* solution.lean (compiles locally)
* solution.md
* proof_graph.json
* verification_log.json
* rejected_claims.json
* run_manifest.json

No solution is accepted without reproducible artifacts.

---

# 18. Safety and Isolation

* Solvers run in sandboxed environment
* File writes logged
* Deterministic execution only
* No external state mutation

---

# 19. Termination Conditions

Allowed only when:

1. Target theorem verified (Lean success), OR
2. Proof reduced to finite exhaustive verification, OR
3. Explicit declaration of incompleteness with full artifact log.

---

# 20. Rigor Statement

This pipeline guarantees:

* No unverified reasoning contaminates state.
* Every accepted claim has deterministic evidence.
* Formal proof checker is final authority.
* All failures are recorded and non‑repeatable.
* Execution is fully reproducible.

The system separates creativity from correctness.

Creativity proposes.
Verification decides.

---

End of Document.
