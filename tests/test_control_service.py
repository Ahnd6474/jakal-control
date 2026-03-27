from __future__ import annotations

import pytest

from jakal_control.exceptions import ControlError
from jakal_control.schemas import JobPayload, RetryPolicyPayload, SchedulePayload


def build_payload(repo_path: str) -> JobPayload:
    return JobPayload(
        name="Nightly Sync",
        repository_path=repo_path,
        prompt_text="Keep the repo healthy.",
        working_branch="main",
        retry_policy=RetryPolicyPayload(max_attempts=2, retry_delay_seconds=120),
        schedules=[
            SchedulePayload(
                kind="daily",
                timezone_name="Asia/Seoul",
                hour=8,
                minute=15,
            )
        ],
    )


def test_job_create_persists_schedule(service, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    job = service.upsert_job(build_payload(str(repo)))
    assert job.name == "Nightly Sync"
    assert len(job.schedules) == 1
    assert job.schedules[0].next_run_at is not None


def test_queue_run_respects_concurrency(service, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    job = service.upsert_job(build_payload(str(repo)))
    first_run = service.queue_run(job.id)
    assert first_run.status.value == "queued"
    with pytest.raises(ControlError):
        service.queue_run(job.id)


def test_retry_run_requires_terminal_state(db, service, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    job = service.upsert_job(build_payload(str(repo)))
    service.queue_run(job.id)
    with pytest.raises(ControlError):
        service.retry_run(service.get_dashboard().recent_runs[0].id)
