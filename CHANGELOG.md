# Changelog

All notable changes to AMPP are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.1.0] — 2026-03-12

### Added
- Rust workspace (`ampp-core`, `ampp-ipc`, `ampp-cli`) with full pipeline state model, beam search manager, two-phase commit, and SQLite-backed store.
- Python components: `Normalizer`, `ProposerEnsemble`, `RubricAgent`, `StrategyController`, `ConjectureMiner`, and verifiers V1–V5 (counterexample, SymPy, Z3, ATP, Lean).
- IPC bridge between Rust and Python worker via stdin/stdout JSON-lines protocol.
- GitHub Actions CI for Rust (fmt, clippy, tests) and Python (ruff, pyright, pytest + coverage) on macOS, Python 3.11 and 3.12.
- Integration smoke test with artifact verification.
- MIT licence, `CONTRIBUTING.md`, issue templates, and PR template.

[Unreleased]: https://github.com/desenyon/ampp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/desenyon/ampp/releases/tag/v0.1.0
