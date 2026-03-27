from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, ensure_directory


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


class StatusWriter:
    def __init__(self, path: Path, base_payload: dict[str, Any]) -> None:
        self.path = path
        self.payload = base_payload
        self.lock = threading.Lock()

    def update(self, **changes: Any) -> None:
        with self.lock:
            self.payload.update(changes)
            self.payload["last_heartbeat_at"] = _iso_now()
            atomic_write_json(self.path, self.payload)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.payload)


def _reader(stream, label: str, log_handle, writer: StatusWriter) -> None:
    for line in iter(stream.readline, ""):
        timestamp = _iso_now()
        log_handle.write(f"[{timestamp}] [{label}] {line}")
        log_handle.flush()
        writer.update(last_output_at=timestamp, phase="running")
    stream.close()


def run_plan(command_file: Path, status_file: Path, log_file: Path, heartbeat_seconds: int) -> int:
    plan = json.loads(command_file.read_text(encoding="utf-8"))
    ensure_directory(log_file.parent)
    ensure_directory(status_file.parent)
    base_status = {
        "phase": "starting",
        "runner_pid": os.getpid(),
        "child_pid": None,
        "started_at": _iso_now(),
        "last_heartbeat_at": _iso_now(),
        "last_output_at": None,
        "exit_code": None,
        "result": None,
        "completed_at": None,
        "error": None,
        "current_command": None,
    }
    writer = StatusWriter(status_file, base_status)
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(max(1, heartbeat_seconds)):
            writer.update(phase=writer.snapshot().get("phase", "running"))

    with log_file.open("a", encoding="utf-8", buffering=1) as log_handle:
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        env = os.environ.copy()
        extra_env = plan.get("env") or {}
        if isinstance(extra_env, dict):
            env.update({str(key): str(value) for key, value in extra_env.items()})

        try:
            for command in plan["commands"]:
                label = str(command.get("label", "command"))
                argv = [str(part) for part in command["argv"]]
                writer.update(current_command=label, phase="starting_command")
                log_handle.write(f"\n===== {label} =====\n")
                log_handle.write(f"argv: {argv}\n")
                log_handle.flush()

                process = subprocess.Popen(
                    argv,
                    cwd=plan["cwd"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                writer.update(child_pid=process.pid, phase="running")

                stdout_thread = threading.Thread(
                    target=_reader,
                    args=(process.stdout, "stdout", log_handle, writer),
                    daemon=True,
                )
                stderr_thread = threading.Thread(
                    target=_reader,
                    args=(process.stderr, "stderr", log_handle, writer),
                    daemon=True,
                )
                stdout_thread.start()
                stderr_thread.start()
                return_code = process.wait()
                stdout_thread.join()
                stderr_thread.join()
                writer.update(exit_code=return_code)

                if return_code != 0:
                    writer.update(
                        phase="completed",
                        result="exit_nonzero",
                        completed_at=_iso_now(),
                    )
                    stop_event.set()
                    heartbeat_thread.join(timeout=2)
                    return return_code

            writer.update(
                phase="completed",
                result="success",
                completed_at=_iso_now(),
                exit_code=0,
            )
            return 0
        except OSError as exc:
            writer.update(
                phase="completed",
                result="launch_error",
                error=str(exc),
                completed_at=_iso_now(),
                exit_code=127,
            )
            return 127
        finally:
            stop_event.set()
            heartbeat_thread.join(timeout=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a persisted Jakal Control execution plan.")
    parser.add_argument("--command-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--heartbeat-seconds", type=int, default=5)
    args = parser.parse_args(argv)
    return run_plan(
        command_file=Path(args.command_file),
        status_file=Path(args.status_file),
        log_file=Path(args.log_file),
        heartbeat_seconds=args.heartbeat_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
