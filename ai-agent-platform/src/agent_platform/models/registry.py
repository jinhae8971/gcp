"""Model registry - manages model metadata and selection criteria.

Provides a queryable catalog of available models with their capabilities,
pricing tiers, and recommended use cases. Used by the gateway for intelligent
routing and by the eval framework for model comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelTier(str, Enum):
    FRONTIER = "frontier"  # Most capable, highest cost
    STANDARD = "standard"  # Good balance of capability and cost
    FAST = "fast"  # Fastest response, lowest cost


class Capability(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"
    LONG_CONTEXT = "long_context"
    VISION = "vision"


@dataclass
class ModelInfo:
    model_id: str
    provider: str
    tier: ModelTier
    max_context: int
    max_output: int
    capabilities: list[Capability] = field(default_factory=list)
    input_cost_per_m: float = 0.0  # USD per 1M input tokens
    output_cost_per_m: float = 0.0  # USD per 1M output tokens
    description: str = ""


# Pre-configured model catalog
MODEL_CATALOG: dict[str, ModelInfo] = {
    "claude-opus-4-20250514": ModelInfo(
        model_id="claude-opus-4-20250514",
        provider="anthropic",
        tier=ModelTier.FRONTIER,
        max_context=200_000,
        max_output=32_000,
        capabilities=[
            Capability.CODE_GENERATION, Capability.REASONING,
            Capability.TOOL_USE, Capability.LONG_CONTEXT, Capability.VISION,
        ],
        input_cost_per_m=15.0,
        output_cost_per_m=75.0,
        description="Anthropic flagship - best for complex multi-step reasoning and coding",
    ),
    "claude-sonnet-4-20250514": ModelInfo(
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        tier=ModelTier.STANDARD,
        max_context=200_000,
        max_output=16_000,
        capabilities=[
            Capability.CODE_GENERATION, Capability.REASONING,
            Capability.TOOL_USE, Capability.LONG_CONTEXT, Capability.VISION,
        ],
        input_cost_per_m=3.0,
        output_cost_per_m=15.0,
        description="Best price-performance ratio for coding agents",
    ),
    "gpt-4o": ModelInfo(
        model_id="gpt-4o",
        provider="openai",
        tier=ModelTier.STANDARD,
        max_context=128_000,
        max_output=16_384,
        capabilities=[
            Capability.CODE_GENERATION, Capability.TOOL_USE,
            Capability.VISION, Capability.REASONING,
        ],
        input_cost_per_m=2.50,
        output_cost_per_m=10.0,
        description="OpenAI flagship multimodal model",
    ),
    "gemini-2.5-pro": ModelInfo(
        model_id="gemini-2.5-pro",
        provider="google",
        tier=ModelTier.STANDARD,
        max_context=1_000_000,
        max_output=65_536,
        capabilities=[
            Capability.CODE_GENERATION, Capability.REASONING,
            Capability.LONG_CONTEXT, Capability.VISION,
        ],
        input_cost_per_m=1.25,
        output_cost_per_m=10.0,
        description="Google flagship with 1M context window",
    ),
}


def get_models_by_tier(tier: ModelTier) -> list[ModelInfo]:
    return [m for m in MODEL_CATALOG.values() if m.tier == tier]


def get_models_by_capability(cap: Capability) -> list[ModelInfo]:
    return [m for m in MODEL_CATALOG.values() if cap in m.capabilities]


def get_cheapest_model(capability: Capability | None = None) -> ModelInfo:
    candidates = (
        get_models_by_capability(capability) if capability else list(MODEL_CATALOG.values())
    )
    return min(candidates, key=lambda m: m.input_cost_per_m + m.output_cost_per_m)
