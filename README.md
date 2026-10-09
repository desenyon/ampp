# AMPP — Autonomous Mathematical Proof Pipeline

[![CI](https://github.com/desenyon/ampp/actions/workflows/ci.yml/badge.svg)](https://github.com/desenyon/ampp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AMPP is an experimental Rust/Python workbench for mathematical proof exploration. Rust owns the proof state, branch search, verification policy, and evidence export. Python provides LLM proposers, arithmetic diagnostics, and a Lean 4 checker.

**A claim is verified only when Lean checks a proof of that exact formal proposition and its axiom audit passes.** Missing tools, finite testing, unsupported syntax, and model confidence never count as a proof. Natural-language interpretation remains a research aid; AMPP does not certify that a formal proposition faithfully translates a natural-language problem.

The repository supports two workflows:

- **Proof checking:** supply an explicit Lean proposition and proof candidates, or ask a configured model for a proof term of that proposition. This path can finish with `theorem_verified`.
- **Research exploration:** supply a natural-language problem. Ten strategy families suggest lemmas and the pipeline records diagnostics. Current research proposers still produce legacy scaffold stubs; those cannot become verified claims. These runs finish incomplete.

This is not a general autonomous solver for open mathematical problems. See [limitations](#limitations) before interpreting any result.

## Contents

- [Install and run offline](#install-and-run-offline)
- [Verify a formal proposition](#verify-a-formal-proposition)
- [Model-assisted work](#model-assisted-work)
- [Architecture](#architecture)
- [Verification contract](#verification-contract)
- [CLI reference](#cli-reference)
- [Configuration](#configuration)
- [Evidence and storage](#evidence-and-storage)
- [Python and IPC interfaces](#python-and-ipc-interfaces)
- [Testing and development](#testing-and-development)
- [Migration from 0.1.1](#migration-from-011)
- [Limitations](#limitations)

## Install and run offline

Requirements: stable Rust/Cargo, Python 3.11+, and macOS or Linux. The Rust binary and Python package are both required. SQLite is bundled with the Rust dependency. SymPy and Z3 install with the Python package. Lean is optional for exploration, but mandatory for verified results.

```bash
git clone https://github.com/desenyon/ampp.git
cd ampp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# Limit parallel builds when sharing a machine.
cargo build --workspace --locked -j 2

./target/debug/ampp --doctor --offline --python "$VIRTUAL_ENV/bin/python"
./target/debug/ampp \
  --problem 'For all n in N, n*(n+1) is even' \
  --offline --max-iter 1 \
  --python "$VIRTUAL_ENV/bin/python" \
  --db /tmp/ampp-exploration.db --output /tmp/ampp-exploration
```

Use a fresh output directory each time. The example makes no LLM calls, even if credentials are already in your environment. An incomplete result is expected. Read `run_manifest.json` for the mathematical result; exit code 0 means the run completed and its report was written, not that a theorem was proved.

The worker defaults to `python -m ampp.worker`, so an installed package works outside the repository. Select the interpreter where you installed it with `--python`.

## Verify a formal proposition

Install Lean using the official [elan instructions](https://github.com/leanprover/elan#installation). The checked-in [`lean-toolchain`](lean-toolchain) pins Lean 4.19.0 for the core-only examples and CI. No Mathlib download is needed for these examples.

From the repository root, after installing elan:

```bash
lean --version
# Resolve the actual binary so subprocesses use this toolchain from any directory.
export AMPP_LEAN_BINARY="$(elan which lean)"

./target/debug/ampp \
  --problem 'Check two plus two' \
  --formal-target '2 + 2 = 4' \
  --candidate-file examples/two_plus_two.json \
  --offline --max-iter 1 \
  --python "$VIRTUAL_ENV/bin/python" \
  --db /tmp/ampp-two-plus-two.db --output /tmp/ampp-two-plus-two

"$AMPP_LEAN_BINARY" /tmp/ampp-two-plus-two/solution.lean
```

A successful run reports `"termination_condition": "theorem_verified"`. `solution.lean` is the exact source checked by V5, including the axiom audit. It is not a placeholder.

The candidate file is a JSON array:

```json
[
  {
    "statement": "2 + 2 = 4",
    "proof": "by decide",
    "stages": ["V0", "V5"]
  }
]
```

`statement` is a Lean proposition, not an informal description. `proof` is a proof term beginning with `by`, not an entire `theorem` declaration. `stages` is optional and defaults to V0/V5. Rust supplies branch and subgoal IDs. Unknown file fields are errors. Each candidate contains exactly one claim; dependencies are not imported from these files.

For example, AMPP generates:

```lean
theorem ampp_claim : (
2 + 2 = 4
) :=
by decide

#print axioms ampp_claim
```

Try [`examples/false_claim.json`](examples/false_claim.json) with `--formal-target '2 + 2 = 5'` to exercise rejection. If Lean is absent, a well-formed candidate remains unverified and no `solution.lean` is emitted. Proving an unrelated proposition, such as `True`, does not resolve the target.

### Mathlib and project-specific imports

The default import list is empty. To use Mathlib, prepare a trusted Lake project with a matching Lean toolchain and built dependencies. Run the binary inside that project's `lake env` so Lean can locate those dependencies:

```bash
cd /absolute/path/to/mathlib-project
AMPP_LEAN_PROJECT="$PWD" AMPP_LEAN_IMPORTS=Mathlib \
  lake env /absolute/path/to/ampp/target/debug/ampp \
  --problem 'Your problem' --formal-target 'Your Lean proposition' \
  --candidate-file /absolute/path/to/candidates.json \
  --python /absolute/path/to/ampp/.venv/bin/python \
  --offline --db /tmp/ampp-mathlib.db --output /tmp/ampp-mathlib
```

Supply a real proposition and candidate file in place of the placeholders. This command does not install or build Mathlib for you. `AMPP_LEAN_PROJECT` controls the checker working directory; it does not independently configure Lake's dependency paths. The checker otherwise retains its startup working directory, rather than selecting a toolchain from a temporary directory. The manifest records the observed Lean version.

## Model-assisted work

Omit `--offline` and configure a provider to request a proof term for `--formal-target`. The formal proposer keeps the user-supplied proposition fixed; the model supplies only the proof. Failed attempts are fed into later proposals. Every proposal still goes through the mandatory Lean gate.

```bash
export AMPP_LLM_PROVIDER=openai
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='your-available-model'

./target/debug/ampp \
  --problem 'An arithmetic identity' --formal-target '2 + 2 = 4' \
  --max-iter 3 --python "$VIRTUAL_ENV/bin/python" \
  --db /tmp/ampp-model.db --output /tmp/ampp-model
```

Anthropic uses `AMPP_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_MODEL`. OpenAI-compatible servers can use `OPENAI_BASE_URL` and `OPENAI_MODEL`; endpoint/model compatibility must be tested with that server. Azure-specific authentication is not implemented.

`AMPP_LLM_PROVIDER=null` and `--offline` always disable model calls. Without an explicit null selection, provider resolution prefers a configured Anthropic provider when selected, then an OpenAI key, then an Anthropic key, and finally null. Missing credentials may therefore fall back to another configured provider. Library callers can override selection with `set_provider()`.

The ten informal strategies are induction, strong induction, minimal counterexample, extremal principle, invariant/monovariant, algebraic normalization, double counting, construction, graph translation, and contradiction. They run sequentially. Their suggestions and stub proofs are exploration material, not established mathematics.

## Architecture

```text
CLI: problem + optional formal target / submitted proof candidates
  |
  +-- Rust planner and four beam branches
  |     +-- SQLite ProofStore: claims, subgoals, attempts, definitions
  |     +-- V0: schema, branch ownership, dependency checks
  |     +-- Mandatory verification policy: V5 cannot be omitted
  |
  +-- JSON lines over a managed Python subprocess
  |     +-- Normalizer and LLM proposers
  |     +-- V1/V2/V3 diagnostic arithmetic checks
  |     +-- V4: explicit unsupported translation result
  |     +-- V5: exact proposition + proof -> Lean -> axiom audit
  |
  +-- Statement-bound certificate -> verified claim commit
  +-- Run-scoped reports, actual versions, artifact hashes
```

| Component | Responsibility |
| --- | --- |
| `crates/ampp-core` | State types, SQLite store, planner, beam ranking, V0, acceptance policy, artifact paths |
| `crates/ampp-ipc` | Serialized request/response exchange, correlation checks, deadlines, process cleanup |
| `crates/ampp-cli` | Inputs, iteration loop, formal target completion, reports |
| `ampp/schemas.py` | Python candidate and protocol schemas |
| `ampp/proposers/formal.py` | Proof-term generation for an explicit Lean target |
| `ampp/proposers/specializations.py` | Ten informal research strategies |
| `ampp/verifiers` | Bounded arithmetic diagnostics and mandatory Lean checking |
| `ampp/agents` | Rubric, conjecture mining, and strategy-controller APIs |

A verified auxiliary lemma is progress, but does not resolve the target subgoal. Only an exact, case-sensitive match to the explicit `--formal-target`, with valid Lean evidence, can terminate successfully. The CLI runs four branches; the beam manager supports expansion/diversity APIs, but automatic expansion and strategy switching are not wired into the CLI loop. Conjecture mining is available through Python/IPC, not automatically run each CLI iteration.

## Verification contract

V0 always runs first. Candidate-selected V1–V4 run in order as diagnostics. V5 always runs, even if the plan contains only V0. Diagnostic failures reject that attempt; inconclusive/unavailable diagnostics may continue to V5. No diagnostic success can replace Lean.

| Stage | Implemented scope | Meaning and limits |
| --- | --- | --- |
| V0 | Single-claim schema, known stage names, branch identity, verified dependencies, enumeration/test consistency | Structural validation, not a proof of truth or full Lean symbol/type checking |
| V1 | Small cases, bounded enumeration of `n`, seeded integer sampling | Can find witnesses; absence of a witness is always inconclusive |
| V2 | SymPy integer polynomial equalities and simple inequalities | Explicit supported result or inconclusive; safe AST construction, no evaluation of Python text |
| V3 | Z3 integer arithmetic and negated-claim satisfiability | Numeric literals remain constants; candidate success criteria are never assumptions |
| V4 | No sound general TPTP translation yet | Always inconclusive; does not ask an ATP to prove a fabricated `true` conjecture |
| V5 | Generated theorem of the exact claim, Lean compilation, axiom audit | Required for acceptance; compilation exit code alone is insufficient |

The shared arithmetic parser accepts integer literals, identifiers, unary `+/-`, addition, subtraction, multiplication, powers from 0 through 8, and one comparison. It bounds input length, AST size, and literal magnitude. Calls, attributes, indexing, division, arbitrary Python expressions, and natural-language quantifiers are unsupported. Diagnostics interpret free symbols as integers. Do not assume they implement every domain or hypothesis in an informal problem.

The Z3 Python API accepts explicit caller-owned `context["assumptions"]`. It checks that every assumption parses and the assumption set is satisfiable before checking a claim. The CLI does not turn model-generated success criteria or heuristic normalizer constraints into assumptions.

Verifier details carry an explicit `outcome`:

| Outcome | Meaning |
| --- | --- |
| `passed` | The stage completed its implemented check successfully |
| `failed` | That check rejected the submitted attempt; not necessarily a disproof of the theorem |
| `inconclusive` | Unsupported syntax, bounded testing, timeout, or insufficient evidence |
| `unavailable` | Required executable or package cannot be invoked |
| `error` | Invalid protocol or infrastructure failure |

The legacy `passed` boolean is true only for the `passed` outcome. The Rust gate validates the pair, stage, and request ID. Missing outcome metadata fails closed.

V5 accepts only an axiom audit for `ampp_claim`; allowed axioms are `propext`, `Classical.choice`, and `Quot.sound`. `sorryAx`, custom axioms, and `Lean.ofReduceBool` are not accepted. Inputs containing proof holes, declarations, comments, strings, command escapes, or `native_decide` are outside the supported proof-term interface. The certificate records the proposition, exact checked source, source SHA-256, axiom list, and policy `lean-kernel-v1`.

**Trust boundary:** Rust, the selected Python worker, the Lean executable, configured imports, and their runtime dependencies are trusted. Certificate JSON is evidence, not a cryptographic signature. Input filters and timeouts do not make Lean a security sandbox. Run unfamiliar proof code in an isolated environment without credentials or private files.

## CLI reference

```text
ampp --problem <TEXT> [OPTIONS]
ampp --doctor [--offline] [--python <INTERPRETER>]
```

| Option | Default | Purpose |
| --- | --- | --- |
| `-p, --problem` | Required except for doctor | Original problem/context text |
| `--formal-target` | None | User-owned Lean proposition required for verified termination |
| `--candidate-file` | None | JSON candidate array; replaces model proposal generation |
| `--offline` | Off | Force the null provider |
| `-d, --db` | `ampp_state.db` | Persistent SQLite database |
| `-o, --output` | `output` | Fresh directory for this run's artifacts |
| `--python` | `python3` | Interpreter with AMPP installed |
| `--worker` | `ampp.worker` | Installed module or custom trusted script path |
| `--seed` | `42` | V1 search seed, also recorded in the manifest |
| `--max-iter` | `200` | Iteration cap; zero writes a baseline incomplete report |
| `--worker-timeout` | `300` seconds | Positive deadline covering request write and response read |
| `--doctor` | Off | Print actual Python/package/Lean versions and worker health |
| `-h, --help`; `--version` | — | Usage/package version |

There are no `prove`, `resume`, `status`, `verify`, or `clean` subcommands. Earlier documentation listed commands that did not exist. For independent verification, run the selected Lean binary on the exported file.

A completed incomplete run returns 0. Invalid inputs/startup failures return nonzero. Verification transport failures after setup produce an incomplete report with the error recorded; read the termination condition. Submitted candidate files are evaluated once across the active branches. Identical candidates are not retried within a run.

## Configuration

Use shell environment variables. `.env` is **not loaded automatically**. Copy [`.env.example`](.env.example), edit it, and load it with `set -a; source .env; set +a` in a compatible shell.

| Variable | Default | Effect |
| --- | --- | --- |
| `AMPP_LLM_PROVIDER` | Provider/key resolution above | `openai`, `anthropic`, or `null` |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Unset | Provider credentials |
| `OPENAI_BASE_URL` | SDK default | OpenAI-compatible endpoint |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model ID; choose one available to your account |
| `ANTHROPIC_MODEL` | `claude-opus-4-5` | Anthropic model ID; choose one available to your account |
| `AMPP_LLM_RETRIES` | `3` | Provider wrapper attempts |
| `AMPP_LLM_MAX_TOKENS` | `2048` | Explicit formal proof proposer token limit |
| `AMPP_LLM_TEMPERATURE` | `0.2` | Explicit formal proof proposer sampling setting |
| `AMPP_LEAN_BINARY` | `lean` | Executable name or absolute path; not Lean's `LEAN_PATH` |
| `AMPP_LEAN_PROJECT` | Worker startup directory | Lean working directory |
| `AMPP_LEAN_IMPORTS` | Empty | Space-separated trusted import module names |
| `AMPP_LEAN_TIMEOUT_SEC` | `120` | Per-compilation deadline |
| `AMPP_Z3_TIMEOUT_MS` | `30000` | Per-solver check deadline |
| `AMPP_V1_RANDOM_TRIALS` | `500` | Random integer samples per V1 call |
| `AMPP_V1_MAX_ENUM_BOUND` | `10000` | Maximum V1 enumeration bound |
| `AMPP_RANDOM_SEED` | `42` in library use | CLI sets this from `--seed` |
| `RUST_LOG` | `ampp=info` | Rust tracing filter |

Timeouts, retry counts, and token limits must be positive; V1 budgets must be nonnegative. Pipeline flags are the CLI source of truth. Legacy `AMPPConfig` fields for beam width, iteration limits, artifact paths, ATP budget, candidate caps, and rubric threshold remain for Python API compatibility but do not configure the CLI loop. Use the documented flags rather than the old `AMPP_BEAM_WIDTH`, `AMPP_OUTPUT_DIR`, or `AMPP_MAX_ITERATIONS` examples.

## Evidence and storage

| Artifact | Contents |
| --- | --- |
| `run_manifest.json` | Schema version 2, result, explicit formal target, iterations, actual tool versions, counts, seed, policy, SHA-256 of produced artifacts |
| `proof_graph.json` | This run's root and branch claims, dependencies, and attached verification evidence |
| `verification_log.json` | Verified claim certificates and all rejected/unverified/error attempts with stage traces and witnesses |
| `rejected_claims.json` | Attempts whose outcome is rejected; unverified results are not mislabeled as disproofs |
| `solution.md` | Problem, result, counts, and verified formal propositions |
| `solution.lean` | Exact target source checked by Lean; **only present after successful formal target verification** |

The manifest does not hash itself. Legacy `rust_version` is `"not recorded"` rather than a fabricated compiler version; `ampp_version` is the package version. Random seeds make V1 sampling repeatable, but model calls, tool versions, UUIDs, and timestamps prevent whole-run deterministic replay. There is no replay command or benchmark claim.

SQLite uses WAL and preserves prior runs. Each run has unique root/branch identities, so new reports do not include another run's records. The store requires statement-bound evidence before inserting or updating a verified claim. Claim identity/dependencies and terminal records are immutable through its update API. Legacy verified rows without the current certificate remain readable but cannot supply verified dependencies.

Rejected-attempt identities include proof text, exact case-sensitive claims, branch/subgoal context, dependencies, test cases, and the plan. They are computed by Rust, not trusted from proposer hashes. Changing the proof permits a new attempt. Missing tools and infrastructure errors do not permanently blacklist a claim.

## Python and IPC interfaces

The worker consumes one JSON object per line and produces one response per line; logs go to stderr. Supported stages are `PING`, `NORMALISE`, `PROPOSE`, `MINE_CONJECTURE`, `RUBRIC_POSTMORTEM`, and V1–V5. `{"type":"shutdown"}` exits gracefully. Unknown stages and malformed messages return error results rather than successful checks.

Example request:

```json
{"request_id":"health-1","stage":"PING","candidate_json":{},"context":{}}
```

Rust serializes exchanges so concurrent callers cannot consume each other's responses. It validates request ID/stage, bounds request/response size at 8 MiB, and applies a configurable deadline to both writes and reads. A transport failure stops that worker; start a new one before retrying. Shutdown is bounded; on Unix, timeout cleanup also terminates the worker's solver process group.

Python verifier APIs retain `(passed, details)` return values, with `details["outcome"]` as the authoritative stage state. Consumers must distinguish a completed diagnostic from proof acceptance. `VerificationCascade` and the store enforce the final certificate requirement.

## Testing and development

```bash
source .venv/bin/activate
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -j 2 -- -D warnings
cargo test --workspace --locked -j 2
cargo build --workspace --release --locked -j 2
ruff check ampp tests
ruff format --check ampp tests
pyright ampp
python -m pytest tests/python -q
python -m build

# Actual Rust -> Python -> SQLite -> Lean tests, using the built binary.
export AMPP_LEAN_BINARY="$(elan which lean)"
AMPP_BIN=target/release/ampp python -m pytest tests/integration -q
```

Python unit tests clear provider credentials and use fakes for model APIs. No test requires a paid service. The real Lean tests skip locally if the checker is absent; CI installs the pinned checker and exercises them. Rust policy tests use explicitly synthetic certificates and separately test that missing/mismatched evidence cannot commit. They do not substitute for the real Lean integration tests.

Coverage includes mandatory V5 for V0-only plans, unavailable tools, axiom auditing, wrong propositions, unsafe arithmetic text, numeric SMT constants, inconsistent assumptions, legacy database records, retry identity, process deadlines, malformed IPC, run isolation, artifact preservation, and recompilation of the actual exported proof.

CI runs Rust formatting/lint/tests/release builds on Linux and macOS, Python lint/format/typecheck/tests/package builds on Python 3.11–3.13, and the real Lean integration suite on Linux. Type checking is enforced rather than advisory. Windows process-group cleanup is not covered by this CI matrix.

## Migration from 0.1.1

This unreleased improvement corrects unsound acceptance behavior. Expect fewer claims marked verified.

1. Install the Rust binary and Python package from the same revision. Legacy worker responses without an explicit outcome cannot satisfy the new policy.
2. Replace whole-file/theorem `lean_stub` values with a `by` proof term, and put the exact Lean proposition in the claim's `statement`. Existing informal `True` scaffolds are unverified.
3. Supply `--formal-target` to request successful theorem termination. The natural-language description cannot serve as a certified translation.
4. Configure `AMPP_LEAN_BINARY` and optional project/imports. An unavailable Lean executable no longer counts as success. `LEAN_PATH` keeps its normal Lean library-search meaning.
5. Treat `inconclusive`, `unavailable`, and `error` separately from rejection. Check `details.outcome`, not just the old boolean or a skipped flag.
6. Update artifact consumers: the verification log contains `verified_claims` and `attempts`; rejected output contains rejected attempt records; incomplete runs omit `solution.lean`; manifest schema is 2.
7. Keep old databases for audit, but reverify old claims. No old evidence is silently upgraded. Mathematical hashes now preserve case; run fingerprints include the target and constraints.
8. Use a fresh output path for each run. Existing artifact files are preserved, not silently reused or overwritten.

## Limitations

- General natural-language formalization and autonomous proofs of advanced/open problems are not implemented guarantees. The normalizer is heuristic and may misinterpret input.
- Informal strategy stubs, V4 translation, automatic counterexample-driven repair, Lean proof minimization, and full automatic strategy switching remain incomplete.
- Proofs use the configured imported environment and must be self-contained. Stored dependency IDs enforce bookkeeping purity but do not automatically import prior generated lemmas into Lean.
- The restricted proof-term interface intentionally excludes many valid Lean programs, custom commands, comments, strings, and native decision procedures. Unsupported syntax may need manual adaptation.
- V1–V3 only cover the documented integer arithmetic fragment. Their rejection is a diagnostic for that interpretation, not a theorem about all possible mathematical domains.
- There is no crash-resume CLI, authenticated remote worker, proof sandbox, or complete reproducible replay system. Setup failures may occur before artifacts exist.
- A successful checker certifies the formal proposition under the recorded axiom policy and trusted toolchain. It does not establish the correctness of an English translation or protect against a malicious worker/toolchain.
- No Dockerfile, hosted service, benchmark suite, or deployment automation is included. Earlier README examples implying those features have been removed.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md). Licensed under [MIT](LICENSE).
