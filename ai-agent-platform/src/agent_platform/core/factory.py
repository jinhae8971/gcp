"""Application factory - wires all components together.

Single place that reads config, creates provider adapters, registers tools,
instantiates harnesses, and returns a ready-to-use platform context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from agent_platform.config.settings import Settings, get_settings
from agent_platform.core.session_store import BaseSessionStore, InMemorySessionStore, RedisSessionStore
from agent_platform.harness.architect import ArchitectHarness
from agent_platform.harness.base import BaseHarness
from agent_platform.harness.code_review import CodeReviewHarness
from agent_platform.harness.debate import DebateHarness
from agent_platform.harness.human_in_loop import HumanInLoopHarness
from agent_platform.harness.multi_file import MultiFileHarness
from agent_platform.harness.plan_execute import PlanExecuteHarness
from agent_platform.harness.react import ReactHarness
from agent_platform.models.gateway import ModelGateway
from agent_platform.models.providers.base import BaseProvider
from agent_platform.observability.logger import setup_logging
from agent_platform.tools.builtin.file_ops import FILE_TOOLS
from agent_platform.tools.builtin.shell import SHELL_TOOLS
from agent_platform.tools.registry import ToolDefinition, ToolRegistry

logger = structlog.get_logger()


@dataclass
class PlatformContext:
    """Holds all initialized components for the platform."""

    settings: Settings
    gateway: ModelGateway
    tool_registry: ToolRegistry
    harnesses: dict[str, BaseHarness]
    session_store: BaseSessionStore


def _build_providers(settings: Settings) -> dict[str, BaseProvider]:
    """Create provider adapters for all configured API keys."""
    providers: dict[str, BaseProvider] = {}
    keys = settings.provider_keys

    if keys.anthropic_api_key:
        from agent_platform.models.providers.anthropic import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(api_key=keys.anthropic_api_key)
        logger.info("provider.registered", name="anthropic")

    if keys.openai_api_key:
        from agent_platform.models.providers.openai_provider import OpenAIProvider

        providers["openai"] = OpenAIProvider(api_key=keys.openai_api_key)
        logger.info("provider.registered", name="openai")

    if keys.google_api_key:
        from agent_platform.models.providers.google import GoogleProvider

        providers["google"] = GoogleProvider(api_key=keys.google_api_key)
        logger.info("provider.registered", name="google")

    if not providers:
        logger.warning("provider.none_configured", hint="Set at least one API key in .env")

    return providers


def _build_tool_registry(settings: Settings) -> ToolRegistry:
    """Register all built-in tools."""
    registry = ToolRegistry(max_output_size=settings.sandbox.max_output_size_bytes)

    for tool_spec in FILE_TOOLS + SHELL_TOOLS:
        spec = dict(tool_spec)
        handler = spec.pop("handler")
        tags = spec.pop("tags", [])
        registry.register(ToolDefinition(handler=handler, tags=tags, **spec))

    return registry


def _build_session_store(settings: Settings) -> BaseSessionStore:
    """Choose session store backend based on config."""
    redis_url = settings.redis_url
    if redis_url and redis_url != "redis://localhost:6379/0":
        try:
            return RedisSessionStore(redis_url=redis_url)
        except Exception as exc:
            logger.warning("session_store.redis_failed", error=str(exc), fallback="in_memory")
    return InMemorySessionStore()


def _build_harnesses(tool_registry: ToolRegistry) -> dict[str, BaseHarness]:
    """Create all available harness instances."""
    tool_defs = tool_registry.get_llm_definitions()
    return {
        "react": ReactHarness(tool_definitions=tool_defs),
        "plan_execute": PlanExecuteHarness(tool_definitions=tool_defs),
        "architect": ArchitectHarness(tool_definitions=tool_defs),
        "code_review": CodeReviewHarness(tool_definitions=tool_defs),
        "multi_file": MultiFileHarness(tool_definitions=tool_defs),
        "debate": DebateHarness(tool_definitions=tool_defs),
        "human_in_loop": HumanInLoopHarness(tool_definitions=tool_defs),
    }


def create_platform(settings: Settings | None = None) -> PlatformContext:
    """Build the complete platform from settings.

    This is the main entry point for both CLI and API server.
    """
    settings = settings or get_settings()
    setup_logging(level=settings.observability.log_level)

    providers = _build_providers(settings)
    gateway = ModelGateway(
        providers=providers,
        default_model=settings.gateway.default_model,
        fallback_models=settings.gateway.fallback_models,
        max_retries=settings.gateway.max_retries,
    )

    tool_registry = _build_tool_registry(settings)
    harnesses = _build_harnesses(tool_registry)
    session_store = _build_session_store(settings)

    logger.info(
        "platform.ready",
        providers=list(providers.keys()),
        tools=len(tool_registry.list_tools()),
        harnesses=list(harnesses.keys()),
    )

    return PlatformContext(
        settings=settings,
        gateway=gateway,
        tool_registry=tool_registry,
        harnesses=harnesses,
        session_store=session_store,
    )
