from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from jakal_control.enums import FailureCategory, JobRunStatus, TriggerSource
from jakal_control.models import Job, Run, RunAttempt, Schedule
from jakal_control.schemas import JobPayload, RetryPolicyPayload, SchedulePayload
from jakal_control.utils import utc_now


def test_due_schedule_creates_queued_run(service, coordinator, db, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    job = service.upsert_job(
        JobPayload(
            name="Scheduled Job",
            repository_path=str(repo),
            retry_policy=RetryPolicyPayload(max_attempts=1, retry_delay_seconds=60),
            schedules=[
                SchedulePayload(
                    kind="once",
                    timezone_name="Asia/Seoul",
                    run_at_local="2099-01-01T09:00",
                )
            ],
        )
    )

    with db.session() as session:
        schedule = session.scalars(select(Schedule)).one()
        schedule.next_run_at = utc_now() - timedelta(seconds=10)
        coordinator._claim_due_schedules(session, utc_now())
        runs = session.scalars(select(Run)).all()
        assert len(runs) == 1
        assert runs[0].trigger_source is TriggerSource.SCHEDULE
        assert runs[0].status is JobRunStatus.QUEUED


def test_finalize_failure_moves_run_to_retry_waiting(coordinator, db) -> None:
    with db.session() as session:
        job = Job(
            name="Retry Job",
            repository_path="C:/repo",
            retry_max_attempts=2,
            retry_delay_seconds=30,
            retry_on_crash=True,
        )
        session.add(job)
        session.flush()
        run = Run(
            job_id=job.id,
            job_name_snapshot=job.name,
            trigger_source=TriggerSource.MANUAL,
            status=JobRunStatus.RUNNING,
        )
        session.add(run)
        session.flush()
        attempt = RunAttempt(
            run_id=run.id,
            attempt_number=1,
            status=JobRunStatus.RUNNING,
            log_path=None,
        )
        session.add(attempt)
        session.flush()

        coordinator._finalize(
            job,
            run,
            attempt,
            final_status=JobRunStatus.FAILED,
            category=FailureCategory.CRASH,
            summary="Runner disappeared.",
            now=utc_now(),
        )
        assert run.status is JobRunStatus.RETRY_WAITING
        assert run.retry_count == 1
        assert run.next_retry_at is not None
