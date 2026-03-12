"""AMPP Python package — Autonomous Mathematical Proof Pipeline."""
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

__version__ = "0.2.0"

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
