from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .utils import ensure_directory, split_command


def detect_local_timezone() -> str:
    tzinfo = datetime.now().astimezone().tzinfo
    key = getattr(tzinfo, "key", None)
    if key:
        return str(key)
    if isinstance(tzinfo, ZoneInfo):
        return tzinfo.key
    return os.getenv("TZ", "UTC")


@dataclass(frozen=True)
class AppConfig:
    home: Path
    db_path: Path
    logs_dir: Path
    runs_dir: Path
    workspaces_dir: Path
    host: str
    port: int
    engine_command: str
    scheduler_poll_seconds: int
    runner_heartbeat_seconds: int
    recent_history_limit: int
    default_timezone: str
    log_tail_lines: int

    @property
    def engine_command_parts(self) -> list[str]:
        return split_command(self.engine_command)

    def ensure_directories(self) -> None:
        ensure_directory(self.home)
        ensure_directory(self.logs_dir)
        ensure_directory(self.runs_dir)
        ensure_directory(self.workspaces_dir)


def load_config() -> AppConfig:
    home = Path(os.getenv("JAKAL_CONTROL_HOME", ".jakal-control")).expanduser().resolve()
    config = AppConfig(
        home=home,
        db_path=home / "jakal_control.db",
        logs_dir=home / "logs",
        runs_dir=home / "runs",
        workspaces_dir=home / "workspaces",
        host=os.getenv("JAKAL_CONTROL_HOST", "127.0.0.1"),
        port=int(os.getenv("JAKAL_CONTROL_PORT", "8787")),
        engine_command=os.getenv("JAKAL_CONTROL_ENGINE_COMMAND", "python -m jakal_flow"),
        scheduler_poll_seconds=int(os.getenv("JAKAL_CONTROL_POLL_SECONDS", "5")),
        runner_heartbeat_seconds=int(os.getenv("JAKAL_CONTROL_RUNNER_HEARTBEAT_SECONDS", "5")),
        recent_history_limit=int(os.getenv("JAKAL_CONTROL_RECENT_HISTORY_LIMIT", "20")),
        default_timezone=os.getenv("JAKAL_CONTROL_TIMEZONE", detect_local_timezone()),
        log_tail_lines=int(os.getenv("JAKAL_CONTROL_LOG_TAIL_LINES", "200")),
    )
    config.ensure_directories()
    return config
