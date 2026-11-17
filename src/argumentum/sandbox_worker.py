"""Opt-in isolated experiment runner using bubblewrap namespaces.

The queue volume is read only by this trusted worker. Untrusted research code runs
inside a bubblewrap filesystem view that does not mount the queue, API data, secrets,
or host paths. If bubblewrap/user namespaces are unavailable, execution fails closed.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("ARGUMENTUM_DATA_DIR", "/data")).resolve()
QUEUE_ROOT = DATA_DIR / "sandbox"
MAX_CODE_BYTES = 32_768
MAX_STDOUT_BYTES = 16_384
MAX_STDERR_BYTES = 16_384
ISOLATION_LABEL = "bubblewrap user/mount/pid/network namespaces; no network; no host or queue mounts"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _limited_child() -> None:
    """Apply hard limits inherited by the untrusted Python interpreter."""
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_048_576, 1_048_576))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_AS, (268_435_456, 268_435_456))
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))


def build_bwrap_command(code_path: Path, work_dir: Path) -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("SandboxUnavailable: bubblewrap is not installed; refusing unsafe execution")
    if not code_path.is_file() or code_path.is_symlink():
        raise RuntimeError("SandboxInputInvalid: experiment code file is not a regular file")
    if not work_dir.is_dir() or work_dir.is_symlink():
        raise RuntimeError("SandboxInputInvalid: experiment workspace is not a regular directory")

    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/etc",
        "/etc",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(work_dir),
        "/work",
        "--chdir",
        "/work",
        sys.executable,
        "-I",
        "-S",
        "-B",
        "/work/main.py",
    ]
    # CPython in official images is under /usr/local; /usr contains the runtime and
    # site libraries. /lib* are needed for some dynamically linked builds.
    for library_dir in ("/lib", "/lib64"):
        if Path(library_dir).exists():
            command[7:7] = ["--ro-bind", library_dir, library_dir]
    return command


def _write_status(job: dict[str, Any], status: str, **extra: Any) -> None:
    public = {
        "experiment_id": job["experiment_id"],
        "tenant_id": job["tenant_id"],
        "status": status,
        "purpose": job["purpose"],
        "submitted_at": job["submitted_at"],
        "finished_at": _utc_now() if status in {"succeeded", "failed", "blocked"} else None,
        **extra,
    }
    _atomic_json(QUEUE_ROOT / "results" / f"{job['experiment_id']}.json", public)


def process_job(job_path: Path) -> dict[str, Any]:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    experiment_id = str(uuid.UUID(job["experiment_id"]))
    if len(job.get("code", "").encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("Experiment code exceeds the configured limit")
    if job.get("human_approved") is not True:
        raise ValueError("Experiment execution requires explicit human approval")
    timeout_seconds = max(1, min(int(job.get("timeout_seconds", 10)), 30))
    _write_status(job, "running", isolation=ISOLATION_LABEL)
    started = time.monotonic()

    try:
        with tempfile.TemporaryDirectory(prefix=f"argumentum-exp-{experiment_id}-") as temporary:
            work_dir = Path(temporary)
            code_path = work_dir / "main.py"
            code_path.write_text(job["code"], encoding="utf-8")
            os.chmod(code_path, 0o400)
            stdout_path = work_dir / "stdout.txt"
            stderr_path = work_dir / "stderr.txt"
            command = build_bwrap_command(code_path, work_dir)
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/nonexistent",
                "LANG": "C.UTF-8",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONHASHSEED": "0",
            }
            try:
                with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
                    completed = subprocess.run(
                        command,
                        cwd=work_dir,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        timeout=timeout_seconds + 2,
                        check=False,
                        close_fds=True,
                        preexec_fn=_limited_child,
                    )
                stdout = stdout_path.read_bytes()[:MAX_STDOUT_BYTES].decode("utf-8", errors="replace")
                stderr = stderr_path.read_bytes()[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
                status = "succeeded" if completed.returncode == 0 else "failed"
                result = {
                    "exit_code": int(completed.returncode),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "stdout": stdout,
                    "stderr": stderr,
                    "isolation": ISOLATION_LABEL,
                }
            except subprocess.TimeoutExpired:
                stdout = (
                    stdout_path.read_bytes()[:MAX_STDOUT_BYTES].decode("utf-8", errors="replace")
                    if stdout_path.exists()
                    else ""
                )
                stderr = (
                    stderr_path.read_bytes()[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
                    if stderr_path.exists()
                    else ""
                )
                status = "failed"
                result = {
                    "exit_code": None,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "stdout": stdout,
                    "stderr": (stderr + "\nExperiment exceeded its wall-clock limit.")[-MAX_STDERR_BYTES:],
                    "isolation": ISOLATION_LABEL,
                }
    except Exception as exc:
        status = "blocked" if type(exc).__name__ == "RuntimeError" else "failed"
        safe_message = (
            "Sandbox isolation is unavailable; no experiment code was executed."
            if status == "blocked"
            else "Sandbox runner failed before producing a result."
        )
        result = {
            "exit_code": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {safe_message}",
            "isolation": None,
        }

    _write_status(job, status, **result)
    return {"experiment_id": experiment_id, "status": status}


def run_forever(poll_interval: float = 1.0) -> None:
    if QUEUE_ROOT.is_symlink():
        raise RuntimeError("Sandbox queue root cannot be a symbolic link")
    QUEUE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = QUEUE_ROOT / "runner.lock"
    lock_handle = lock_path.open("a+b")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise RuntimeError("Another sandbox runner already holds the exclusive queue lock") from exc
    for folder in ("inbox", "processing", "results"):
        target = QUEUE_ROOT / folder
        if target.is_symlink():
            raise RuntimeError("Sandbox queue directories cannot be symbolic links")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Jobs left in processing after abrupt process death are safe to return to inbox:
    # the queue worker is a single service replica, and outputs are deterministic IDs.
    for stale in sorted((QUEUE_ROOT / "processing").glob("*.json")):
        if stale.is_file() and not stale.is_symlink():
            destination = QUEUE_ROOT / "inbox" / stale.name
            if not destination.exists():
                os.replace(stale, destination)
    while True:
        candidates = sorted((QUEUE_ROOT / "inbox").glob("*.json"))
        if not candidates:
            time.sleep(max(0.2, poll_interval))
            continue
        for queued in candidates:
            if queued.is_symlink() or not queued.is_file():
                continue
            result_path = QUEUE_ROOT / "results" / queued.name
            if result_path.is_file() and not result_path.is_symlink():
                try:
                    previous = json.loads(result_path.read_text(encoding="utf-8"))
                    if previous.get("status") in {"succeeded", "failed", "blocked"}:
                        queued.unlink(missing_ok=True)
                        continue
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            claimed = QUEUE_ROOT / "processing" / queued.name
            try:
                os.replace(queued, claimed)
            except FileNotFoundError:
                continue
            try:
                process_job(claimed)
            except Exception as exc:
                # Do not include raw payload or exception messages in shared logs.
                print(f"Sandbox job {claimed.stem} failed ({type(exc).__name__})", flush=True)
            finally:
                claimed.unlink(missing_ok=True)


if __name__ == "__main__":  # pragma: no cover - exercised by container deployment
    run_forever(float(os.getenv("ARGUMENTUM_SANDBOX_POLL_SECONDS", "1")))
