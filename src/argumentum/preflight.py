#!/usr/bin/env python3
"""Probe a running Argumentum deployment without disclosing credentials."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from collections.abc import Callable
from typing import Any


def _http(url: str, *, token: str | None = None, timeout: int = 10) -> tuple[int, bytes]:
    headers = {"Accept": "application/json, text/plain;q=0.9"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(1_048_577)
        if len(body) > 1_048_576:
            raise RuntimeError("response exceeded 1 MiB")
        return response.status, body


def _run_check(report: list[dict[str, str]], name: str, action: Callable[[], str], *, required: bool = True) -> None:
    try:
        detail = action()
        report.append({"name": name, "status": "passed", "detail": detail})
    except Exception as exc:
        report.append(
            {
                "name": name,
                "status": "failed" if required else "warning",
                "detail": type(exc).__name__,
            }
        )


def _api_check(base_url: str) -> str:
    status, _ = _http(f"{base_url.rstrip('/')}/health/live")
    if status != 200:
        raise RuntimeError("liveness endpoint failed")
    status, payload = _http(f"{base_url.rstrip('/')}/health/ready")
    if status != 200:
        raise RuntimeError("readiness endpoint failed")
    data = json.loads(payload.decode("utf-8"))
    if data.get("status") != "ready":
        raise RuntimeError("readiness endpoint did not report ready")
    return "liveness and readiness endpoints returned healthy"


def _identity_check(base_url: str, token: str) -> str:
    status, payload = _http(f"{base_url.rstrip('/')}/api/v1/tenant", token=token)
    if status != 200:
        raise RuntimeError("workspace authentication failed")
    data = json.loads(payload.decode("utf-8"))
    return f"authenticated workspace role={data.get('role', 'unknown')}"


def _docker_check() -> str:
    completed = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return f"Docker Compose returned {len(lines)} service record(s)"


def _postgres_check() -> str:
    from sqlalchemy import text

    from argumentum.server.db import get_engine

    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    return "PostgreSQL connection and SELECT 1 succeeded"


def _redis_check() -> str:
    from redis import Redis

    client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), socket_connect_timeout=5, socket_timeout=5
    )
    try:
        if client.ping() is not True:
            raise RuntimeError("Redis PING did not return PONG")
    finally:
        client.close()
    return "Redis connection and PING succeeded"


def _model_check() -> str:
    from argumentum.config import Settings
    from argumentum.providers import OpenAICompatibleProvider

    settings = Settings.from_env()
    result = OpenAICompatibleProvider(settings).complete_json(
        agent="selfhost_preflight",
        system_prompt='Return exactly one JSON object with a boolean field named "ok" set to true.',
        user_prompt='Reply with {"ok": true}.',
    )
    if result.get("ok") is not True:
        raise RuntimeError("model did not satisfy the JSON smoke-test contract")
    return f"JSON response succeeded for model={settings.model}"


def _grobid_check(url: str) -> str:
    status, payload = _http(f"{url.rstrip('/')}/api/isalive", timeout=15)
    if status != 200:
        raise RuntimeError("GROBID liveness endpoint failed")
    return (
        f"GROBID liveness endpoint returned HTTP {status} ({payload[:80].decode('utf-8', errors='replace').strip()!r})"
    )


def _scholarly_check(query: str) -> str:
    from argumentum.config import Settings
    from argumentum.sources import (
        ArxivSource,
        CrossrefSource,
        EuropePmcSource,
        OpenAlexSource,
        SemanticScholarSource,
    )

    settings = Settings.from_env()
    clients = [
        OpenAlexSource(settings),
        CrossrefSource(settings),
        SemanticScholarSource(settings),
        EuropePmcSource(settings),
        ArxivSource(settings),
    ]
    outcomes: list[str] = []
    failures: list[str] = []
    for client in clients:
        try:
            papers = client.search(query, 2)
            outcomes.append(f"{client.name}={len(papers)}")
        except Exception as exc:
            failures.append(f"{client.name}:{type(exc).__name__}")
    if failures:
        raise RuntimeError("provider checks failed: " + ", ".join(failures))
    return "; ".join(outcomes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("ARGUMENTUM_SELFHOST_API_URL", "http://127.0.0.1:8080"))
    parser.add_argument(
        "--infrastructure",
        action="store_true",
        help="Run live PostgreSQL and Redis connection checks (requires server extra)",
    )
    parser.add_argument(
        "--model", action="store_true", help="Send a small JSON-mode prompt to the configured model endpoint"
    )
    parser.add_argument("--grobid", action="store_true", help="Probe ARGUMENTUM_GROBID_URL/api/isalive")
    parser.add_argument(
        "--scholarly", action="store_true", help="Send one bounded search to each scholarly metadata provider"
    )
    parser.add_argument("--query", default="reproducible scientific research workflows")
    parser.add_argument("--docker", action="store_true", help="Run docker compose ps")
    args = parser.parse_args(argv)

    checks: list[dict[str, str]] = []
    _run_check(checks, "api", lambda: _api_check(args.api_url))
    api_token = os.getenv("ARGUMENTUM_API_TOKEN", "")
    if api_token:
        _run_check(checks, "workspace_authentication", lambda: _identity_check(args.api_url, api_token))
    else:
        checks.append(
            {"name": "workspace_authentication", "status": "skipped", "detail": "ARGUMENTUM_API_TOKEN not set"}
        )

    if args.infrastructure:
        _run_check(checks, "postgresql", _postgres_check)
        _run_check(checks, "redis", _redis_check)
    else:
        checks.append(
            {
                "name": "postgresql",
                "status": "skipped",
                "detail": "pass --infrastructure for a live database connection check",
            }
        )
        checks.append(
            {"name": "redis", "status": "skipped", "detail": "pass --infrastructure for a live broker connection check"}
        )

    if args.model:
        _run_check(checks, "model_inference", _model_check)
    else:
        checks.append(
            {"name": "model_inference", "status": "skipped", "detail": "pass --model to make a live model request"}
        )

    grobid_url = os.getenv("ARGUMENTUM_GROBID_URL", "")
    if args.grobid and grobid_url:
        _run_check(checks, "grobid", lambda: _grobid_check(grobid_url))
    elif args.grobid:
        checks.append({"name": "grobid", "status": "failed", "detail": "ARGUMENTUM_GROBID_URL is not set"})
    else:
        checks.append(
            {"name": "grobid", "status": "skipped", "detail": "pass --grobid with ARGUMENTUM_GROBID_URL configured"}
        )

    if args.scholarly:
        _run_check(checks, "scholarly_catalogues", lambda: _scholarly_check(args.query))
    else:
        checks.append(
            {
                "name": "scholarly_catalogues",
                "status": "skipped",
                "detail": "pass --scholarly to make live provider requests",
            }
        )

    if args.docker:
        _run_check(checks, "docker_compose", _docker_check)
    else:
        checks.append(
            {
                "name": "docker_compose",
                "status": "skipped",
                "detail": "pass --docker to inspect the current Compose project",
            }
        )

    failed = any(item["status"] == "failed" for item in checks)
    warnings = any(item["status"] == "warning" for item in checks)
    result: dict[str, Any] = {
        "status": "failed"
        if failed
        else "passed_with_skips_or_warnings"
        if warnings or any(item["status"] == "skipped" for item in checks)
        else "passed",
        "checks": checks,
    }
    print(json.dumps(result, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
