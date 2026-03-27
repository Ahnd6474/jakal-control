from __future__ import annotations

from pathlib import Path

import pytest

from jakal_control.config import AppConfig
from jakal_control.database import Database
from jakal_control.services.control import ControlService
from jakal_control.services.coordinator import SupervisorCoordinator


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig(
        home=tmp_path,
        db_path=tmp_path / "test.db",
        logs_dir=tmp_path / "logs",
        runs_dir=tmp_path / "runs",
        workspaces_dir=tmp_path / "workspaces",
        host="127.0.0.1",
        port=8787,
        engine_command="python -m jakal_flow",
        scheduler_poll_seconds=5,
        runner_heartbeat_seconds=2,
        recent_history_limit=20,
        default_timezone="Asia/Seoul",
        log_tail_lines=100,
    )
    cfg.ensure_directories()
    return cfg


@pytest.fixture
def db(config: AppConfig) -> Database:
    database = Database(config.db_path)
    database.initialize()
    return database


@pytest.fixture
def service(db: Database, config: AppConfig) -> ControlService:
    return ControlService(db, config)


@pytest.fixture
def coordinator(db: Database, config: AppConfig) -> SupervisorCoordinator:
    return SupervisorCoordinator(db, config)
