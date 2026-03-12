# Contributing to AMPP

Thank you for your interest in contributing! This document explains the process for contributing code, tests, documentation, and bug reports.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ampp && cd ampp
   ```
3. **Set up the development environment:**
   ```bash
   # Rust
   cargo build --release

   # Python
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```
4. **Verify everything works:**
   ```bash
   pytest tests/python/ -q
   cargo test --all -q
   ```

---

## Before You Open a PR

For non-trivial changes, **open an issue first** to discuss the proposed change. This avoids wasted effort if the change is out of scope or conflicts with planned work.

For typo fixes, documentation improvements, or obvious bug fixes, feel free to open a PR directly.

---

## Code Standards

### Python

- **Python 3.11+** required.
- Use `ruff` for formatting and linting:
  ```bash
  pip install ruff
  ruff check ampp/ tests/
  ruff format ampp/ tests/
  ```
- All Pydantic models must use v2 syntax (`model_validator`, `field_validator`, etc.).
- All new public functions/classes must have type annotations.
- New code must come with tests. Run `pytest tests/python/ --cov=ampp` to check coverage.

### Rust

- Use `rustfmt` for formatting:
  ```bash
  cargo fmt --all
  ```
- Zero `cargo clippy` warnings:
  ```bash
  cargo clippy --all-targets --all-features -- -D warnings
  ```
- All new public functions must have documentation comments.
- New crate functionality must have integration tests in `crates/*/tests/`.

---

## The Verification Invariant

> **No mathematical claim may enter the proof state unless a deterministic verifier confirms it.**

Any change to the verification cascade (V0–V5) or the two-phase commit logic in `ampp-core` must preserve this invariant. PRs that bypass or weaken verification will not be merged.

---

## Testing

| Command | What it runs |
|---------|-------------|
| `pytest tests/python/ -v` | All Python tests |
| `pytest tests/python/ --cov=ampp` | Python tests + coverage |
| `cargo test --all` | All Rust tests |
| `cargo clippy --all-targets --all-features -- -D warnings` | Rust linting |
| `cargo fmt --all -- --check` | Rust formatting check |

All of the above must pass before a PR is reviewed.

---

## Adding a New Proposer

1. Add a new class to `ampp/proposers/specializations.py` inheriting from `BaseProposer`.
2. Implement `propose(subgoal, proof_state) -> list[StepCandidate]`.
3. Register the new proposer in `ampp/proposers/ensemble.py`.
4. Add at least 3 tests covering: empty input, valid candidates, and a rejected candidate.
5. Document the strategy family in the README proposer table.

Proposers must generate `StepCandidate` objects with all mandatory fields populated. Any candidate with a missing field will be silently discarded by the Rubric Agent.

---

## Adding a New Verifier Layer

New verifier layers should:
- Be added as `ampp/verifiers/vN_name.py` following the existing pattern.
- Accept a `Claim` and return a `VerificationResult`.
- Be registered in `ampp/worker.py` under a new RPC method.
- Be documented in the README verification cascade table.
- Have tests covering: positive verification, negative (counterexample), and timeout/skip behavior.

---

## Pull Request Process

1. Create a branch from `main` with a descriptive name: `feat/lean-minimizer-v2`, `fix/z3-timeout-handling`, `docs/openclaw-setup`.
2. Make your changes with clear, atomic commits.
3. Push your branch and open a PR against `main`.
4. Fill in the PR template fully — especially the test plan section.
5. Ensure all CI checks pass.
6. Address review feedback; the PR is merged by a maintainer once approved.

---

## Commit Message Format

We use a simplified Conventional Commits format:

```
type(scope): short description

Optional longer description explaining the why, not the what.
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

Examples:

```
feat(proposers): add PolynomialRootProposer for algebraic number claims
fix(v3_z3): handle quantified formulas by falling through to V4
docs(readme): add Docker Compose deployment example
test(rubric_agent): cover step-size tightening after V5 failures
```

---

## Reporting Security Issues

Please do **not** open a public issue for security vulnerabilities. Email the maintainer directly at the address listed in `pyproject.toml`. We will acknowledge within 48 hours and coordinate a fix before any public disclosure.

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
