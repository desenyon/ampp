"""AMPP Python package — Autonomous Mathematical Proof Pipeline."""

from ampp.config import cfg
from ampp.llm import (
    AnthropicProvider,
    LLMProvider,
    NullProvider,
    OpenAIProvider,
    get_provider,
    llm_generate_claims,
    set_provider,
)
from ampp.schemas import (
    ActionType,
    ClaimStatus,
    ClaimType,
    FormalSpec,
    NewClaimSpec,
    SmallCaseTest,
    StepCandidate,
    StrategyFamily,
    VerificationPlan,
    VerificationRequest,
    VerificationResponse,
)

__version__ = "0.1.1"

__all__ = [
    # Schemas
    "ActionType",
    "ClaimStatus",
    "ClaimType",
    "FormalSpec",
    "NewClaimSpec",
    "SmallCaseTest",
    "StepCandidate",
    "StrategyFamily",
    "VerificationPlan",
    "VerificationRequest",
    "VerificationResponse",
    # Config
    "cfg",
    # LLM
    "AnthropicProvider",
    "LLMProvider",
    "NullProvider",
    "OpenAIProvider",
    "get_provider",
    "llm_generate_claims",
    "set_provider",
]
