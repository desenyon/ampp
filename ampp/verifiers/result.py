"""Shared explicit verifier outcomes; non-results can never be proof evidence."""

from typing import Any

from ampp.schemas import VerificationOutcome


def result(outcome: str, **details: Any) -> tuple[bool, dict[str, Any]]:
    status = VerificationOutcome(outcome)
    return status == VerificationOutcome.PASSED, {"outcome": status.value, **details}
