"""V4 placeholder: no sound natural-language-to-TPTP translation exists yet.

Do not invoke a prover on ``true`` and report it as evidence for another claim.
"""

from typing import Any

from ampp.schemas import StepCandidate
from ampp.verifiers.result import result


class ATPVerifier:
    """Report the translation limitation without fabricating ATP evidence."""

    def verify(
        self, candidate: StepCandidate, context: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        return result("inconclusive", reason="ATP translation is not implemented")
