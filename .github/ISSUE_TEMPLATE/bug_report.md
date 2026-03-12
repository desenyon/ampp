---
name: Bug report
about: Report a reproducible problem with AMPP
title: "bug: "
labels: bug
assignees: ''
---

## Describe the bug

A clear and concise description of what the bug is.

## To reproduce

Steps to reproduce the behavior:

1. Set these environment variables: `...`
2. Run command: `ampp prove "..."`
3. See error

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include the full error message and stack trace if available.

## Artefacts

If the run produced any output (e.g., partial `verification_log.json`, `run_manifest.json`), paste or attach them here. The manifest is especially helpful — it includes tool versions and seeds.

```json
// paste run_manifest.json here if available
```

## Environment

- OS: [e.g., macOS 14.5, Ubuntu 22.04]
- Rust version (`rustc --version`):
- Python version (`python --version`):
- AMPP version (`ampp --version` or `git rev-parse --short HEAD`):
- LLM provider: [openai / anthropic / openclaw / null]
- Lean 4 version (`lean --version`), if relevant:
- Z3 version (`z3 --version`), if relevant:

## Additional context

Any other context about the problem.
