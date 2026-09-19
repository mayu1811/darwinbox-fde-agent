"""Application configuration.

Everything is environment driven. The application is designed to run with an
empty environment (DEMO MODE) so a reviewer can clone and run without any keys.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Darwinbox FDE — AI Data Migration Agent"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = f"sqlite:///{BACKEND_DIR / 'migration.db'}"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- LLM configuration -------------------------------------------------
    # LLM_PROVIDER: "none" (deterministic demo mode) | "ollama" | "openai"
    llm_provider: str = "none"
    llm_model: str = "llama3.1:8b"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 20.0
    # If the LLM is unreachable we silently fall back to deterministic mapping.
    llm_fallback_to_deterministic: bool = True

    # ---- Autonomy policy ---------------------------------------------------
    high_confidence_threshold: float = 0.90
    medium_confidence_threshold: float = 0.70
    # Minimum gap between the best and the runner-up candidate for a mapping to
    # be applied without a human. This is what turns "confident" into "certain".
    min_confidence_margin: float = 0.15
    max_auto_repair_attempts: int = 2

    # ---- Target API simulation --------------------------------------------
    # "<employee_id>:<number of attempts that fail before it succeeds>"
    #   EMP1009 recovers inside the first push (attempt 3 succeeds)
    #   EMP1022 exhausts the first push and only recovers on an explicit retry
    target_transient_profile: str = "EMP1009:2,EMP1022:3"
    max_push_attempts: int = 3
    retry_base_delay_seconds: float = 0.4
    auto_push_after_resolution: bool = True

    # Pacing of the agent so a human can actually watch it work.
    agent_step_delay_seconds: float = 0.35

    upload_max_bytes: int = 10 * 1024 * 1024
    allowed_upload_extensions: str = ".csv,.xlsx,.xls"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_upload_extensions.split(",") if e.strip()}

    @property
    def transient_failure_profile(self) -> dict[str, int]:
        profile: dict[str, int] = {}
        for entry in self.target_transient_profile.split(","):
            entry = entry.strip()
            if not entry:
                continue
            emp_id, _, attempts = entry.partition(":")
            try:
                profile[emp_id.strip().upper()] = int(attempts or 1)
            except ValueError:
                continue
        return profile

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider.lower() not in ("", "none", "off", "disabled")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_target_schema() -> dict:
    with open(DATA_DIR / "target_schema.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


settings = get_settings()
