# AMPP — Autonomous Mathematical Proof Pipeline

[![CI](https://github.com/naitikgupta/ampp/actions/workflows/ci.yml/badge.svg)](https://github.com/naitikgupta/ampp/actions/workflows/ci.yml)
[![Rust](https://img.shields.io/badge/rust-stable-orange)](https://www.rust-lang.org/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AMPP is a production-grade autonomous system for solving advanced mathematical problems — combinatorics, number theory, Erdős-style extremal problems — with **formal, machine-verifiable proofs**. It combines a deterministic Rust core with a Python AI/solver ecosystem connected via a high-performance JSON-RPC bridge.

**The central invariant:** no mathematical statement is ever accepted as true unless a deterministic verifier (up to and including Lean 4) independently confirms it.

---

## Table of Contents

1. [Quick Start (30 seconds)](#quick-start-30-seconds)
2. [Architecture Overview](#architecture-overview)
3. [Installation](#installation)
4. [LLM Provider Setup](#llm-provider-setup)
5. [Configuration Reference](#configuration-reference)
6. [CLI Reference](#cli-reference)
7. [Verification Cascade](#verification-cascade)
8. [Proof Loop Architecture](#proof-loop-architecture)
9. [Strategy Families](#strategy-families)
10. [Python Module Reference](#python-module-reference)
11. [Output Artefacts](#output-artefacts)
12. [Testing](#testing)
13. [Deployment](#deployment)
14. [Project Structure](#project-structure)
15. [Contributing](#contributing)

---

## Quick Start (30 seconds)

```bash
# 1 — Clone and build
git clone https://github.com/naitikgupta/ampp && cd ampp
cargo build --release

# 2 — Install Python stack
pip install -e ".[dev]"

# 3 — Set your API key  (or see OpenClaw section for local models)
export OPENAI_API_KEY=sk-...

# 4 — Solve a problem
./target/release/ampp prove "For all n >= 2, there are infinitely many primes p ≡ 1 (mod n)"
```

Output lands in `output/` — `solution.lean`, `solution.md`, `proof_graph.json`, and a full `verification_log.json`.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Problem Input (CLI)                      │
└───────────────────────────────┬─────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                RUST CORE  (ampp-cli / ampp-core)                │
│  [ProofStore SQLite]  [BeamSearch 3-6 branches]  [V0 Checker]  │
│  [Planner (subgoal DAG)]  [Normalizer]  [Artifacts]            │
│               JSON-RPC over subprocess stdin/stdout             │
└───────────────────────────────┬─────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                  PYTHON SOLVER STACK  (ampp/)                   │
│  [Normalizer]  [Proposer Ensemble — 10 strategies]  [Rubric]   │
│  [V1: Counterex|V2: SymPy|V3: Z3|V4: ATP|V5: Lean 4]          │
│  [Conjecture Miner]  [Strategy Controller]  [LLM Provider]     │
└─────────────────────────────────────────────────────────────────┘
```

The pipeline separates **creativity** (LLM proposers) from **correctness** (deterministic verifiers). The Rust core enforces the two-phase commit: a claim moves from `proposed` to `verified` only after the full cascade succeeds.

---

## Installation

### Prerequisites

| Tool | Min version | Install |
|------|-------------|---------|
| Rust | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Python | 3.11 | [python.org](https://python.org) |
| Lean 4 | 4.x | [leanprover.github.io](https://leanprover.github.io/lean4/doc/setup.html) |
| Z3 | 4.12+ | bundled via `pip install z3-solver` |
| Vampire / E | any | optional — ATP stage skipped if absent |

### macOS / Linux

```bash
git clone https://github.com/naitikgupta/ampp && cd ampp

# Build Rust binaries
cargo build --release

# Install Python package
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment
cp .env.example .env && $EDITOR .env

# Verify
pytest tests/python/ -q && cargo test --all -q
```

Optionally symlink the binary:

```bash
ln -s "$(pwd)/target/release/ampp" /usr/local/bin/ampp
```

### Docker

```bash
docker build -t ampp:latest .
docker run --rm \
  -e OPENAI_API_KEY=sk-... \
  -v "$(pwd)/output:/app/output" \
  ampp:latest prove "Prove Ramsey R(3,3)=6"
```

---

## LLM Provider Setup

AMPP supports three provider backends with **zero code changes** required.

### OpenAI

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o          # optional — this is the default
```

### Anthropic (Claude)

```bash
ANTHROPIC_API_KEY=sk-ant-...
AMPP_LLM_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-opus-4-5   # optional — this is the default
```

### OpenClaw (Self-hosted / Local Models)

OpenClaw exposes an OpenAI-compatible REST API, making it a drop-in replacement for self-hosted or private models (Ollama, LM Studio, vLLM, text-generation-webui, etc.).

```bash
# Point AMPP at your OpenClaw endpoint
OPENAI_BASE_URL=https://your-openclaw.example.com/v1
OPENAI_API_KEY=your-openclaw-key   # or "none" if auth is disabled
OPENAI_MODEL=mistral-7b            # whichever model is loaded
```

AMPP auto-detects OpenClaw when `OPENAI_BASE_URL` is set to a non-OpenAI URL.

#### Local Ollama quickstart

```bash
# Pull a model
ollama pull llama3.1:70b

# Configure AMPP
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
export OPENAI_MODEL=llama3.1:70b

./target/release/ampp prove "Prove that sqrt(2) is irrational"
```

#### Recommended local models

| Model | Size | Notes |
|-------|------|-------|
| Llama 3.1 | 70B | Best open-source option |
| Qwen2.5 | 72B | Excellent math reasoning |
| DeepSeek-R1 | 32B+ | Strong formal reasoning |
| Mistral | 7B | Minimum viable; very fast |

Models must support instruction following. JSON mode is optional but improves output reliability.

#### Test without any API key

```bash
AMPP_LLM_PROVIDER=null
```

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI or OpenClaw API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for OpenClaw / compatible server |
| `OPENAI_MODEL` | `gpt-4o` | Model for OpenAI / OpenClaw |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-opus-4-5` | Model for Anthropic |
| `AMPP_LLM_PROVIDER` | `openai` | Backend: `openai`, `anthropic`, `null` |
| `AMPP_LLM_MAX_TOKENS` | `4096` | Max tokens per LLM call |
| `AMPP_LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `AMPP_LLM_RETRIES` | `3` | Retry attempts on transient failures |
| `AMPP_BEAM_WIDTH` | `4` | Concurrent proof branches |
| `AMPP_MAX_ITERATIONS` | `50` | Hard cap on loop iterations |
| `AMPP_OUTPUT_DIR` | `output/` | Directory for proof artefacts |
| `AMPP_LOG_LEVEL` | `info` | `trace` / `debug` / `info` / `warn` / `error` |
| `LEAN_PATH` | auto | Path to `lean` binary |
| `VAMPIRE_PATH` | auto | Path to `vampire` binary |
| `E_PROVER_PATH` | auto | Path to `eprover` binary |

---

## CLI Reference

```
ampp <COMMAND> [OPTIONS]

COMMANDS:
  prove      Submit a problem for autonomous proof
  status     Show status of a running or completed session
  resume     Resume from a saved state file
  verify     Verify a Lean file against the current toolchain
  clean      Remove runtime artefacts (state.db, output/)

OPTIONS:
  -o, --output <DIR>    Output directory (default: output/)
  -b, --beam-width <N>  Beam search width (default: 4)
  -i, --max-iter <N>    Maximum iterations (default: 50)
  -p, --provider <NAME> LLM provider: openai, anthropic, null
  -v, --verbose         Increase verbosity (can repeat)
  -h, --help            Print help
      --version         Print version
```

**Examples:**

```bash
ampp prove "Show that every planar graph is 4-colorable"
ampp prove -i 100 -b 6 "Prove Turán's theorem for triangle-free graphs"
ampp prove -p anthropic "Prove the Cauchy-Davenport theorem"
ampp resume output/ampp_state.db
ampp verify output/solution.lean
```

---

## Verification Cascade

| Layer | Tool | What it checks | On failure |
|-------|------|---------------|------------|
| **V0** | Rust | Symbol validity, domain consistency, quantifier scope, dependency purity | Immediate reject |
| **V1** | Python | Exhaustive + random counterexample search | Witness stored, rejected |
| **V2** | SymPy | Symbolic simplification, identity + inequality verification | Mismatch → reject |
| **V3** | Z3 | SMT negation unsatisfiability | Countermodel found → reject |
| **V4** | Vampire / E | FOL ATP over translated representation | Counter-satisfiable → reject |
| **V5** | Lean 4 | Full formal proof compilation | Compile failure → minimize + retry |

---

## Proof Loop Architecture

Each iteration:

1. Select highest-priority subgoal (by `impact / difficulty`)
2. Invoke Proposer Ensemble — all 10 specialists fire in parallel
3. Rubric Agent triage: hard-reject missing fields / unverified deps; score the rest
4. Verification Cascade V0 → V5
5. Two-Phase Commit: `proposed → verified` (all pass) or `proposed → rejected` (any fail)
6. Counterexample-guided refinement: extract failure pattern, add exclusion constraints
7. Conjecture Miner: enumerate small instances, mine invariants and bounds
8. Strategy Controller: check entropy threshold; switch strategy family if stale
9. Rubric Agent postmortem: update per-strategy weights for next iteration

**Termination conditions:**
- Target theorem verified (Lean compiles), OR
- All subgoals reduced to exhaustive finite verification, OR
- Explicit incompleteness declaration with full artefact log

---

## Strategy Families

| Proposer | Technique | Best for |
|----------|-----------|----------|
| `InductionProposer` | Standard induction | Statements with a natural base case |
| `StrongInductionProposer` | Strong / complete induction | P(k) uses all P(j < k) |
| `MinimalCounterexampleProposer` | Minimal counterexample | Existence-of-minimum + contradiction |
| `ExtremalProposer` | Extremal principle | Max/min arguments |
| `InvariantMonovariantProposer` | Invariants and monovariants | Process termination, preservation |
| `AlgebraicNormalizationProposer` | Algebraic manipulation | Identity proofs, ring arguments |
| `DoubleCountingProposer` | Double counting | Combinatorial identities, bijections |
| `ConstructiveProposer` | Explicit construction | Existence proofs via algorithm |
| `GraphTranslationProposer` | Graph reinterpretation | Problems reducible to graph theory |
| `ContradictionProposer` | Proof by contradiction | Irrationality, non-existence, lower bounds |

---

## Python Module Reference

| Module | Purpose |
|--------|---------|
| `ampp.normalizer` | Problem statement → `FormalSpec` |
| `ampp.schemas` | Pydantic v2 schemas (`Claim`, `StepCandidate`, `VerificationResult`, …) |
| `ampp.worker` | JSON-RPC event loop bridging Rust IPC to Python |
| `ampp.config` | `AMPPConfig` dataclass + `cfg` module-level singleton |
| `ampp.llm` | Provider abstraction (`OpenAIProvider`, `AnthropicProvider`, `NullProvider`) |
| `ampp.proposers.base` | `BaseProposer` ABC |
| `ampp.proposers.ensemble` | Parallel proposer orchestrator |
| `ampp.proposers.specializations` | All 10 concrete strategy proposers |
| `ampp.verifiers.v1_counterexample` | Exhaustive + random counterexample engine |
| `ampp.verifiers.v2_sympy` | SymPy symbolic verification |
| `ampp.verifiers.v3_z3` | Z3 SMT verification |
| `ampp.verifiers.v4_atp` | Vampire / E Prover (ATP) |
| `ampp.verifiers.v5_lean` | Lean 4 compilation gate |
| `ampp.agents.rubric_agent` | Quality gate, triage, postmortem, strategy weight updates |
| `ampp.agents.conjecture_miner` | Small-case enumeration + LLM conjecture generation |
| `ampp.agents.strategy_controller` | Entropy-based switching + beam diversity governance |

---

## Output Artefacts

| File | Description |
|------|-------------|
| `solution.lean` | Lean 4 source — compile with `lean solution.lean` |
| `solution.md` | Human-readable proof with LaTeX equations |
| `proof_graph.json` | DAG of all verified claims and their dependencies |
| `verification_log.json` | Per-claim trace through V0–V5 with solver outputs |
| `rejected_claims.json` | All rejected candidates with failure reasons + witnesses |
| `run_manifest.json` | Seeds, tool versions, prompt hashes — full reproducibility record |

All runs are fully reproducible by replaying with the seeds in `run_manifest.json`.

---

## Testing

```bash
# Python tests
pytest tests/python/ -v

# Rust tests
cargo test --all

# Coverage
pytest tests/python/ --cov=ampp --cov-report=html && open htmlcov/index.html
```

| Layer | Tests | File |
|-------|-------|------|
| Schemas | 14 | `test_schemas.py` |
| Normalizer | 12 | `test_normalizer.py` |
| Proposers + Strategy | 23 | `test_proposer_and_strategy.py` |
| Rubric Agent | 14 | `test_rubric_agent.py` |
| V1 Counterexample | 10 | `test_v1_counterexample.py` |
| V2 SymPy | 8 | `test_v2_sympy.py` |
| V3 Z3 | 10 | `test_v3_z3.py` |
| Conjecture Miner | 12 | `test_conjecture_miner.py` |
| Worker / IPC | 6 | `test_worker.py` |
| LLM + Config | 23 | `test_llm_and_config.py` |
| **Python total** | **132** | |
| Rust integration | 26 | `crates/*/tests/` |
| **Grand total** | **158** | |

---

## Deployment

### systemd Service

```ini
# /etc/systemd/system/ampp.service
[Unit]
Description=AMPP Autonomous Mathematical Proof Pipeline
After=network.target

[Service]
Type=simple
User=ampp
WorkingDirectory=/opt/ampp
EnvironmentFile=/opt/ampp/.env
ExecStart=/opt/ampp/target/release/ampp prove "%i"
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ampp
sudo journalctl -u ampp -f
```

### Docker Compose

```yaml
version: "3.9"
services:
  ampp:
    build: .
    restart: unless-stopped
    volumes:
      - ./output:/app/output
      - ./ampp_state.db:/app/ampp_state.db
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - AMPP_LLM_PROVIDER=${AMPP_LLM_PROVIDER:-openai}
      - AMPP_BEAM_WIDTH=${AMPP_BEAM_WIDTH:-4}
      # OpenClaw / self-hosted model:
      # - OPENAI_BASE_URL=http://ollama:11434/v1
      # - OPENAI_MODEL=llama3.1:70b
```

```bash
docker compose up -d && docker compose logs -f ampp
```

### Production Checklist

- [ ] API keys in secrets manager — not plain `.env`
- [ ] `output/` on persistent storage
- [ ] SQLite WAL mode active (AMPP default — do not disable)
- [ ] Lean 4 toolchain version pinned and logged
- [ ] Z3 version pinned and logged
- [ ] `AMPP_LLM_RETRIES` ≥ 3
- [ ] CI green on `ubuntu-latest` and `macos-latest`
- [ ] Read/write access to `output/` and `ampp_state.db`
- [ ] Outbound HTTPS to LLM provider (or inbound to OpenClaw endpoint)

---

## Project Structure

```
ampp/
├── Cargo.toml              Rust workspace
├── pyproject.toml          Python package (v0.2.0)
├── .env.example            Environment variable template
├── crates/
│   ├── ampp-core/          State, SQLite store, V0, beam search, planner
│   ├── ampp-ipc/           PythonWorker subprocess + JSON-RPC
│   └── ampp-cli/           CLI entry point
├── ampp/
│   ├── config.py           AMPPConfig + cfg singleton
│   ├── llm.py              LLM provider abstraction
│   ├── normalizer.py       Problem → FormalSpec
│   ├── schemas.py          Pydantic v2 data schemas
│   ├── worker.py           JSON-RPC event loop
│   ├── agents/             rubric_agent, conjecture_miner, strategy_controller
│   ├── proposers/          base, ensemble, 10 specializations
│   └── verifiers/          v1 through v5
└── tests/python/           132 pytest tests
```

---

## Design Philosophy

1. **Two-phase commit** — no claim enters proof state without deterministic verification.
2. **Strict dependency purity** — verified claims depend only on other verified claims.
3. **Deterministic verification supremacy** — LLMs propose; solvers and Lean decide.
4. **Reproducible execution** — every run is replayable from `run_manifest.json`.
5. **Progress-monotonic iteration** — each loop iteration must reduce proof complexity or trigger a strategy switch.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines. Quick summary:

- Open an issue first for anything non-trivial
- New Python code requires pytest coverage
- New Rust code must pass `cargo test` and `cargo clippy`
- PRs must pass CI on `ubuntu-latest` and `macos-latest`

---

*Built by [Naitik Gupta](https://github.com/naitikgupta). Released under the [MIT License](LICENSE).*
