"""Runtime configuration. Secrets are read from the environment, never persisted."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    timeout_seconds: int = 90
    max_retries: int = 2
    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    mailto: str | None = None
    grobid_url: str | None = None
    grobid_timeout_seconds: int = 180
    agent_harness: str = "native"
    pipeline_harness: str = "native"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.getenv("ARGUMENTUM_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=os.getenv("ARGUMENTUM_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            model=os.getenv("ARGUMENTUM_LLM_MODEL", "gpt-4.1-mini"),
            timeout_seconds=int(os.getenv("ARGUMENTUM_TIMEOUT_SECONDS", "90")),
            max_retries=int(os.getenv("ARGUMENTUM_MAX_RETRIES", "2")),
            openalex_api_key=os.getenv("OPENALEX_API_KEY"),
            semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
            mailto=os.getenv("ARGUMENTUM_MAILTO"),
            grobid_url=(os.getenv("ARGUMENTUM_GROBID_URL") or "").rstrip("/") or None,
            grobid_timeout_seconds=int(os.getenv("ARGUMENTUM_GROBID_TIMEOUT_SECONDS", "180")),
            agent_harness=os.getenv("ARGUMENTUM_AGENT_HARNESS", "native").strip().lower(),
            pipeline_harness=os.getenv("ARGUMENTUM_PIPELINE_HARNESS", "native").strip().lower(),
        )
