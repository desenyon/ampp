## Summary

<!-- A one-line description of what this PR does. -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Refactor (no functional change)
- [ ] Documentation update
- [ ] CI / tooling change

## Related issue

Fixes # <!-- issue number -->

## Changes

<!-- A bullet list of the key changes. Be specific. -->

-
-

## Verification invariant

> No mathematical claim may enter the proof state unless a deterministic verifier confirms it.

- [ ] This PR does not weaken or bypass the verification cascade.
- [ ] If this PR changes V0–V5 logic, I have verified the invariant is preserved.

## Test plan

<!-- Describe how you tested this change. Include new tests added and any manual testing performed. -->

- [ ] New unit/integration tests added
- [ ] Existing tests still pass: `pytest tests/python/ -q && cargo test --all -q`
- [ ] CI passes on this branch

## Checklist

- [ ] `cargo fmt --all -- --check` passes
- [ ] `cargo clippy --all-targets --all-features -- -D warnings` passes
- [ ] `ruff check ampp/ tests/` passes
- [ ] `ruff format --check ampp/ tests/` passes
- [ ] PR title follows Conventional Commits: `type(scope): description`
- [ ] Documentation updated (README, docstrings) where needed
