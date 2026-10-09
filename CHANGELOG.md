# Changelog

All notable changes to AMPP are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Fixed
- Enforce V0 and statement-bound Lean verification independently of candidate-selected stages. V0-only plans, skipped tools, legacy stubs, and unrelated `True` theorems cannot commit verified claims.
- Audit Lean axioms; reject admitted proofs, custom axioms, and native-decision certificates outside the supported policy.
- Replace permissive solver fallthrough with explicit failed, inconclusive, unavailable, and error outcomes. Disable the placeholder ATP translation.
- Parse diagnostic arithmetic without evaluating Python code; correct Z3 numeric literals and assumption polarity, reject inconsistent assumptions, and ignore candidate-selected success criteria as assumptions.
- Preserve case in mathematical identity and include proof/context in rejection-cache identity. Unavailable tools and worker failures remain retryable.
- Require evidence and verified dependencies at storage boundaries; exclude legacy verified rows from dependency sets without deleting them.
- Correlate and serialize worker requests; bound I/O, timeouts, and shutdown; stop solver process groups on Unix after transport failure.
- Export all current run branches, real tool versions, witnesses, accurate counts, and exact checked Lean source. Preserve previous output files and isolate reports when reusing a database.
- Honor the null provider even when credentials exist; avoid repeatedly counting the same rubric failure.

### Added
- `--formal-target`, `--candidate-file`, `--offline`, `--doctor`, and `--worker-timeout` CLI options, plus installed-module worker startup.
- A formal proof proposer that keeps the supplied target fixed and asks the selected model for a proof term.
- Pinned Lean 4.19.0 core examples, trust-boundary regressions, real CLI/worker/SQLite/Lean integration tests, enforced Python type checks, package builds, and Linux/macOS Rust CI.
- README covering actual architecture, setup, configuration, usage, evidence formats, migration, and limitations.

### Changed
- Verified claims require the `lean-kernel-v1` certificate. Legacy worker responses and whole-declaration `lean_stub` values require migration.
- Manifest schema is 2. Incomplete runs omit `solution.lean`; `verification_log.json` contains verified claims and attempts. See the README migration guide.

---

## [0.1.1] — 2026-03-12

### Fixed
- Release packaging: copy binary to a temp dir before archiving to avoid clash with the `ampp/` Python package directory ([`rm ampp: is a directory`](https://github.com/desenyon/ampp/actions)).
- Quantifier key `for_all` → `forall` to match Rust serde `rename_all = "lowercase"`.
- Windows packager updated to use temp dir consistently.

---

## [0.1.0] — 2026-03-12

### Added
- Rust workspace (`ampp-core`, `ampp-ipc`, `ampp-cli`) with full pipeline state model, beam search manager, two-phase commit, and SQLite-backed store.
- Python components: `Normalizer`, `ProposerEnsemble`, `RubricAgent`, `StrategyController`, `ConjectureMiner`, and verifiers V1–V5 (counterexample, SymPy, Z3, ATP, Lean).
- IPC bridge between Rust and Python worker via stdin/stdout JSON-lines protocol.
- GitHub Actions CI for Rust (fmt, clippy, tests) and Python (ruff, pyright, pytest + coverage) on macOS, Python 3.11 and 3.12.
- Integration smoke test with artifact verification.
- MIT licence, `CONTRIBUTING.md`, issue templates, and PR template.

[Unreleased]: https://github.com/desenyon/ampp/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/desenyon/ampp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/desenyon/ampp/releases/tag/v0.1.0
