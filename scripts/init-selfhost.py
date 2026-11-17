#!/usr/bin/env python3
"""Create a local .env with strong secrets without overwriting existing config."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def main() -> int:
    content = SOURCE.read_text(encoding="utf-8")
    replacements = {
        "REPLACE_WITH_POSTGRES_SECRET": secrets.token_hex(32),
        "REPLACE_WITH_REDIS_SECRET": secrets.token_hex(32),
        "REPLACE_WITH_A_LONG_RANDOM_BEARER_TOKEN": secrets.token_urlsafe(48),
        "REPLACE_WITH_A_DIFFERENT_PLATFORM_ADMIN_TOKEN": secrets.token_urlsafe(56),
        "REPLACE_WITH_VLLM_SECRET": secrets.token_urlsafe(48),
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value, 1)

    try:
        descriptor = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(".env already exists; leaving it unchanged.")
        return 0
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(content)

    print("Created .env with unique random database, Redis, workspace, platform-admin, and vLLM secrets.")
    print("Review ARGUMENTUM_LLM_MODEL and the inference profile before starting services.")
    print("Keep .env private. It is excluded from Git and Docker build context.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
