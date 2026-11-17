#!/usr/bin/env python3
"""Exercise a Compose deployment with a non-scholarly offline run."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8080"


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def request(path: str, token: str | None = None, body: dict[str, object] | None = None) -> object:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise RuntimeError(f"Response from {path} exceeded the smoke-test limit")
            content_type = response.headers.get("Content-Type", "")
            return json.loads(payload.decode("utf-8")) if "json" in content_type else payload.decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Avoid printing response headers (which may contain operational data).
        body_text = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {body_text}") from exc


def main() -> int:
    env = load_env(ROOT / ".env")
    token = env.get("ARGUMENTUM_API_TOKEN", "")
    if not token or token.startswith("REPLACE_"):
        raise SystemExit("ARGUMENTUM_API_TOKEN missing from generated .env")

    deadline = time.monotonic() + 150
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request("/health/ready")
            last_error = None
            break
        except Exception as exc:  # service may still be starting
            last_error = exc
            time.sleep(3)
    if last_error is not None:
        raise SystemExit(f"API did not become ready: {type(last_error).__name__}")

    ui = request("/ui")
    if not isinstance(ui, str) or "ARGUMENTUM" not in ui:
        raise SystemExit("Researcher UI did not return the expected page")

    accepted = request("/api/v1/runs", token, {
        "topic": "Docker Compose integration smoke test",
        "question": "Can the containerized database, queue, API and worker complete an offline research workflow?",
        "source_limit": 2,
        "demo_mode": True,
    })
    if not isinstance(accepted, dict) or not accepted.get("run_id"):
        raise SystemExit("Run submission did not return a run_id")
    run_id = str(accepted["run_id"])

    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        status = request(f"/api/v1/runs/{run_id}", token)
        if isinstance(status, dict) and status.get("status") in {"completed", "completed_with_warnings", "failed"}:
            break
        time.sleep(2)
    else:
        raise SystemExit(f"Run {run_id} did not reach a terminal status")

    if status.get("status") == "failed":
        raise SystemExit(f"Demo run failed: {status.get('error', 'no safe error detail')}")
    artifacts = request(f"/api/v1/runs/{run_id}/artifacts", token)
    names = {str(item.get("name")) for item in artifacts} if isinstance(artifacts, list) else set()
    required = {"RUN_SUMMARY.md", "manuscript.md", "run_manifest.json"}
    missing = required - names
    if missing:
        raise SystemExit(f"Run completed but artifacts are missing: {sorted(missing)}")
    print(f"Compose smoke test passed: run_id={run_id}, status={status['status']}, artifacts={len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
