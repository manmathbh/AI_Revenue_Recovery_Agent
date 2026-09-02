"""Application configuration (env-driven, pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/recoup"

    razorpay_key_id: str = "rzp_test_dummy"
    razorpay_key_secret: str = "dummy"
    razorpay_webhook_secret: str = "dev_webhook_secret_for_local_testing"
    razorpay_base_url: str = "https://api.razorpay.com/v1"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    admin_api_key: str = "change-me"

    # Agent bounds (AGENT_DESIGN.md).
    agent_max_iterations: int = 6
    agent_llm_timeout_s: float = 20.0
    agent_max_invalid_tool_calls: int = 2

    # Policy defaults (mirrors merchants.policy_config seed).
    policy_max_retries: int = 3
    policy_approval_limit_minor: int = 25_000_00
    policy_cooldown_base_min: int = 30
    policy_confidence_floor: float = 0.60
    policy_contact_cap_7d: int = 3
    policy_ttl_hours: int = 72
    policy_simulation_budget: int = 200

    # Razorpay client (RAZORPAY_INTEGRATION.md).
    rzp_timeout_s: float = 10.0
    rzp_max_retries: int = 2
    rzp_circuit_failure_threshold: int = 5

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
