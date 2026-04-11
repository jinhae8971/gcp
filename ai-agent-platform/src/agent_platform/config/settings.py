"""Centralized configuration via pydantic-settings.

Environment variables or .env file are loaded automatically.
All secrets stay out of code; validation happens at startup.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderKeys(BaseSettings):
    """API keys for each LLM provider. Only the ones you use need to be set."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""


class ModelGatewaySettings(BaseSettings):
    """LiteLLM-based model gateway configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    default_model: str = "claude-sonnet-4-20250514"
    litellm_master_key: str = ""
    max_retries: int = 3
    request_timeout: int = 120
    fallback_models: list[str] = Field(
        default_factory=lambda: ["gpt-4o", "gemini-2.5-pro"]
    )


class SandboxSettings(BaseSettings):
    """Execution sandbox configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    sandbox_mode: str = "container"  # "container" | "local" | "gvisor"
    workspace_root: str = "/workspace"
    max_execution_time_seconds: int = 300
    max_output_size_bytes: int = 1_048_576  # 1 MB


class ServerSettings(BaseSettings):
    """API server configuration."""

    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me-in-production"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class ObservabilitySettings(BaseSettings):
    """Logging and tracing configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    enable_tracing: bool = True


class Settings(BaseSettings):
    """Root settings aggregator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"

    provider_keys: ProviderKeys = Field(default_factory=ProviderKeys)
    gateway: ModelGatewaySettings = Field(default_factory=ModelGatewaySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


def get_settings() -> Settings:
    """Singleton-style settings loader."""
    return Settings()
