# Contributing to AMPP

Start with the [README](README.md), particularly the verification contract and limitations. For substantial feature proposals, discuss scope with the maintainers. Soundness fixes should include a reproducer and regression coverage.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cargo build --workspace --locked -j 2
```

Use stable Rust and Python 3.11+. Install elan and the checked-in Lean toolchain for integration tests. Core examples do not need Mathlib. Avoid adding credentials, private mathematical material, paid API calls, or unbounded workloads to fixtures.

## Required checks

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -j 2 -- -D warnings
cargo test --workspace --locked -j 2
cargo build --workspace --release --locked -j 2
ruff check ampp tests
ruff format --check ampp tests
pyright ampp
python -m pytest tests/python -q
python -m build
export AMPP_LEAN_BINARY="$(elan which lean)"
AMPP_BIN=target/release/ampp python -m pytest tests/integration -q
```

Python unit tests isolate provider credentials. A skipped real-Lean test does not establish proof-checker correctness; CI installs the pinned checker and runs those cases. Rust unit tests use synthetic evidence explicitly and are complemented by the real integration suite.

## Verification invariant

Only a statement-bound, compiled Lean proof with an approved axiom audit can make a claim verified. V0 and V5 are mandatory. A prover proposal cannot select a weaker policy. The store must enforce evidence and dependency validity independently of candidate generation.

When changing a verifier:

- Return explicit `outcome` metadata and keep `passed` consistent with it.
- Distinguish unsupported input, missing tools, timeout, infrastructure errors, and rejection.
- Never turn absence of a counterexample into a universal proof.
- Test the exact statement/proof association, not merely a successful compiler exit.
- Preserve diagnostic traces and witnesses, and avoid blacklisting infrastructure failures.
- Never evaluate candidate arithmetic text as Python code.

Proof checking is not a sandbox. Treat workers, toolchains, imports, and code execution as trusted inputs; do not advertise isolation beyond what is implemented.

## Adding proposers and stages

Informal proposers implement `BaseProposer` and register with `ProposerEnsemble`. The explicit-target path uses `FormalProofProposer` and cannot change the target. Test empty/malformed model output and valid structured output with a fake provider. A whole-module `True` stub is not evidence for a natural-language statement.

New diagnostic stages need Python tests, worker registration, and an explicit Rust policy decision. Do not silently grant a new stage authority to commit claims. Update the schema, README, migration notes, and artifact consumers together when changing the wire contract.

## Pull requests

Create a descriptive branch, use a Conventional Commit title, and describe the concrete before/after behavior. Include validation results, any intentionally unsupported behavior, and migration requirements. Keep generated artifacts, virtual environments, build output, and private data out of commits. `Cargo.lock` is tracked because this workspace ships a CLI.

Use a draft PR when a change needs further review. Do not merge, publish releases, or change repository settings as part of routine development.

For sensitive security reports, use the repository's private reporting channel if available, rather than publishing exploit details in a public issue. No response-time guarantee is implied by this document.

Contributions are licensed under the repository's [MIT License](LICENSE).
