from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import AppConfig
from ..database import Database
from ..enums import JobRunStatus, ScheduleType, TriggerSource
from ..exceptions import ControlError
from ..models import Job, Run, RunAttempt, Schedule
from ..schemas import (
    AttemptView,
    DashboardView,
    JobPayload,
    JobView,
    LogTailView,
    RetryPolicyPayload,
    RunView,
    ScheduleOverviewItem,
    ScheduleView,
)
from ..schedules import ScheduleDefinition, compute_next_run, describe_schedule, now_local_iso
from ..utils import dump_json_list, parse_json_list, tail_text_file, utc_now


BLOCKING_STATUSES = (
    JobRunStatus.QUEUED,
    JobRunStatus.STARTING,
    JobRunStatus.RUNNING,
    JobRunStatus.RETRY_WAITING,
    JobRunStatus.STALE,
)


class ControlService:
    def __init__(self, db: Database, config: AppConfig) -> None:
        self.db = db
        self.config = config

    def upsert_job(self, payload: JobPayload, job_id: str | None = None) -> JobView:
        repository_path = self._normalize_existing_path(payload.repository_path, "Repository path")
        prompt_file_path = None
        if payload.prompt_file_path:
            prompt_file_path = self._normalize_prompt_path(payload.prompt_file_path, repository_path)

        with self.db.session() as session:
            if job_id:
                job = session.get(Job, job_id)
                if not job or job.deleted_at is not None:
                    raise ControlError("Job not found.", status_code=404)
            else:
                job = Job()
                session.add(job)

            job.name = payload.name.strip()
            job.repository_path = str(repository_path)
            job.repository_url_override = payload.repository_url_override.strip() if payload.repository_url_override else None
            job.prompt_text = payload.prompt_text.strip() if payload.prompt_text else None
            job.prompt_file_path = str(prompt_file_path) if prompt_file_path else None
            job.model_provider = payload.model_provider.strip() if payload.model_provider else None
            job.local_model_provider = payload.local_model_provider.strip() if payload.local_model_provider else None
            job.model_name = payload.model_name.strip() if payload.model_name else None
            job.reasoning_effort = payload.reasoning_effort.strip() if payload.reasoning_effort else None
            job.working_branch = payload.working_branch.strip() or "main"
            job.workspace_name = payload.workspace_name.strip() if payload.workspace_name else None
            job.test_command = payload.test_command.strip() if payload.test_command else None
            job.approval_mode = payload.approval_mode.strip() or "never"
            job.sandbox_mode = payload.sandbox_mode.strip() or "workspace-write"
            job.max_blocks = payload.max_blocks
            job.enabled = payload.enabled
            job.max_concurrent_runs = payload.max_concurrent_runs
            job.stale_timeout_minutes = payload.stale_timeout_minutes
            job.retry_max_attempts = payload.retry_policy.max_attempts
            job.retry_delay_seconds = payload.retry_policy.retry_delay_seconds
            job.retry_on_crash = payload.retry_policy.retry_on_crash
            job.retry_on_failure = payload.retry_policy.retry_on_failure
            job.retry_on_stale = payload.retry_policy.retry_on_stale

            job.schedules.clear()
            now = utc_now()
            for schedule_payload in payload.schedules:
                definition = self._definition_from_payload(schedule_payload, now)
                next_run_at = compute_next_run(definition, now)
                schedule = Schedule(
                    kind=definition.kind,
                    timezone_name=definition.timezone_name,
                    anchor_local=definition.anchor_local,
                    hour=definition.hour,
                    minute=definition.minute,
                    interval_hours=definition.interval_hours,
                    weekdays_json=dump_json_list(list(definition.weekdays)) if definition.weekdays else None,
                    enabled=schedule_payload.enabled,
                    next_run_at=next_run_at,
                )
                job.schedules.append(schedule)

            session.flush()
            return self._serialize_job(job, self._active_counts(session))

    def delete_job(self, job_id: str) -> None:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if not job or job.deleted_at is not None:
                raise ControlError("Job not found.", status_code=404)
            if self._blocking_run_count(session, job.id) > 0:
                raise ControlError("Cancel or finish active runs before deleting this job.", status_code=409)
            job.enabled = False
            job.deleted_at = utc_now()

    def set_job_enabled(self, job_id: str, enabled: bool) -> JobView:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if not job or job.deleted_at is not None:
                raise ControlError("Job not found.", status_code=404)
            job.enabled = enabled
            session.flush()
            return self._serialize_job(job, self._active_counts(session))

    def queue_run(self, job_id: str, trigger_source: TriggerSource = TriggerSource.MANUAL, parent_run_id: str | None = None) -> RunView:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if not job or job.deleted_at is not None:
                raise ControlError("Job not found.", status_code=404)
            if self._blocking_run_count(session, job.id) >= job.max_concurrent_runs:
                raise ControlError("Job concurrency limit reached.", status_code=409)
            run = Run(
                job_id=job.id,
                parent_run_id=parent_run_id,
                job_name_snapshot=job.name,
                trigger_source=trigger_source,
                status=JobRunStatus.QUEUED,
                summary="Queued for execution.",
            )
            session.add(run)
            session.flush()
            return self._serialize_run(run)

    def retry_run(self, run_id: str) -> RunView:
        with self.db.session() as session:
            run = session.get(Run, run_id)
            if not run:
                raise ControlError("Run not found.", status_code=404)
            if run.status == JobRunStatus.SUCCEEDED:
                raise ControlError("Successful runs cannot be retried.", status_code=409)
            if run.ended_at is None:
                raise ControlError("Run is still active.", status_code=409)
            job = session.get(Job, run.job_id)
            if not job or job.deleted_at is not None:
                raise ControlError("Associated job is no longer available.", status_code=404)
            if self._blocking_run_count(session, job.id) >= job.max_concurrent_runs:
                raise ControlError("Job concurrency limit reached.", status_code=409)
            new_run = Run(
                job_id=job.id,
                parent_run_id=run.id,
                job_name_snapshot=job.name,
                trigger_source=TriggerSource.MANUAL_RETRY,
                status=JobRunStatus.QUEUED,
                summary=f"Manual retry queued for run {run.id[:8]}.",
            )
            session.add(new_run)
            session.flush()
            return self._serialize_run(new_run)

    def cancel_run(self, run_id: str) -> RunView:
        from .coordinator import terminate_process_tree

        with self.db.session() as session:
            run = session.get(Run, run_id, options=[selectinload(Run.attempts)])
            if not run:
                raise ControlError("Run not found.", status_code=404)
            if run.status in {JobRunStatus.SUCCEEDED, JobRunStatus.FAILED, JobRunStatus.CANCELLED}:
                return self._serialize_run(run)

            now = utc_now()
            summary = "Cancelled by user."
            run.cancellation_requested_at = now
            run.ended_at = now
            run.status = JobRunStatus.CANCELLED
            run.last_error = summary
            run.summary = summary
            latest_attempt = run.attempts[-1] if run.attempts else None
            if latest_attempt:
                if latest_attempt.wrapper_pid:
                    terminate_process_tree(latest_attempt.wrapper_pid)
                latest_attempt.status = JobRunStatus.CANCELLED
                latest_attempt.ended_at = now
                latest_attempt.failure_category = "cancelled"
                latest_attempt.summary = summary
            session.flush()
            return self._serialize_run(run)

    def get_dashboard(self) -> DashboardView:
        with self.db.session() as session:
            active_counts = self._active_counts(session)
            jobs = session.scalars(
                select(Job)
                .where(Job.deleted_at.is_(None))
                .options(selectinload(Job.schedules))
                .order_by(Job.name.asc())
            ).all()
            active_runs = session.scalars(
                select(Run)
                .where(Run.ended_at.is_(None), Run.status.in_(BLOCKING_STATUSES))
                .options(selectinload(Run.attempts))
                .order_by(Run.requested_at.desc())
            ).all()
            recent_runs = session.scalars(
                select(Run)
                .options(selectinload(Run.attempts))
                .order_by(Run.requested_at.desc())
                .limit(self.config.recent_history_limit)
            ).all()

            schedule_overview: list[ScheduleOverviewItem] = []
            for job in jobs:
                for schedule in job.schedules:
                    schedule_overview.append(
                        ScheduleOverviewItem(
                            job_id=job.id,
                            job_name=job.name,
                            schedule_id=schedule.id,
                            description=self._schedule_description(schedule),
                            next_run_at=schedule.next_run_at,
                        )
                    )

            schedule_overview.sort(key=lambda item: (item.next_run_at is None, item.next_run_at))
            return DashboardView(
                timezone_name=self.config.default_timezone,
                home_dir=str(self.config.home),
                engine_command=self.config.engine_command,
                jobs=[self._serialize_job(job, active_counts) for job in jobs],
                active_runs=[self._serialize_run(run) for run in active_runs],
                recent_runs=[self._serialize_run(run) for run in recent_runs],
                schedule_overview=schedule_overview[:20],
            )

    def get_run_log(self, run_id: str) -> LogTailView:
        with self.db.session() as session:
            run = session.get(Run, run_id, options=[selectinload(Run.attempts)])
            if not run:
                raise ControlError("Run not found.", status_code=404)
            latest_attempt = run.attempts[-1] if run.attempts else None
            if not latest_attempt or not latest_attempt.log_path:
                return LogTailView(run_id=run.id, attempt_id=None, log_path=None, content="")
            return LogTailView(
                run_id=run.id,
                attempt_id=latest_attempt.id,
                log_path=latest_attempt.log_path,
                content=tail_text_file(latest_attempt.log_path, lines=self.config.log_tail_lines),
            )

    def _normalize_existing_path(self, raw_path: str, label: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise ControlError(f"{label} does not exist: {path}")
        return path

    def _normalize_prompt_path(self, raw_path: str, repository_path: Path) -> Path:
        prompt_path = Path(raw_path).expanduser()
        if not prompt_path.is_absolute():
            prompt_path = (repository_path / prompt_path).resolve()
        if not prompt_path.exists():
            raise ControlError(f"Prompt file does not exist: {prompt_path}")
        return prompt_path

    def _definition_from_payload(self, payload, now) -> ScheduleDefinition:
        if payload.kind == "once":
            anchor_local = payload.run_at_local
        elif payload.kind == "every_hours":
            anchor_local = payload.start_at_local or now_local_iso(payload.timezone_name, now)
        else:
            anchor_local = None
        return ScheduleDefinition(
            kind=ScheduleType(payload.kind),
            timezone_name=payload.timezone_name,
            anchor_local=anchor_local,
            hour=payload.hour,
            minute=payload.minute,
            interval_hours=payload.interval_hours,
            weekdays=tuple(payload.weekdays),
        )

    def _schedule_description(self, schedule: Schedule) -> str:
        definition = ScheduleDefinition(
            kind=schedule.kind,
            timezone_name=schedule.timezone_name,
            anchor_local=schedule.anchor_local,
            hour=schedule.hour,
            minute=schedule.minute,
            interval_hours=schedule.interval_hours,
            weekdays=tuple(parse_json_list(schedule.weekdays_json)),
        )
        return describe_schedule(definition)

    def _serialize_schedule(self, schedule: Schedule) -> ScheduleView:
        return ScheduleView(
            id=schedule.id,
            kind=schedule.kind,
            timezone_name=schedule.timezone_name,
            enabled=schedule.enabled,
            anchor_local=schedule.anchor_local,
            hour=schedule.hour,
            minute=schedule.minute,
            interval_hours=schedule.interval_hours,
            weekdays=parse_json_list(schedule.weekdays_json),
            next_run_at=schedule.next_run_at,
            description=self._schedule_description(schedule),
        )

    def _serialize_attempt(self, attempt: RunAttempt) -> AttemptView:
        return AttemptView(
            id=attempt.id,
            attempt_number=attempt.attempt_number,
            status=attempt.status,
            wrapper_pid=attempt.wrapper_pid,
            child_pid=attempt.child_pid,
            started_at=attempt.started_at,
            ended_at=attempt.ended_at,
            exit_code=attempt.exit_code,
            failure_category=attempt.failure_category,
            log_path=attempt.log_path,
            last_heartbeat_at=attempt.last_heartbeat_at,
            last_output_at=attempt.last_output_at,
            summary=attempt.summary,
        )

    def _serialize_job(self, job: Job, active_counts: dict[str, int]) -> JobView:
        next_run_at = min((schedule.next_run_at for schedule in job.schedules if schedule.next_run_at), default=None)
        return JobView(
            id=job.id,
            name=job.name,
            repository_path=job.repository_path,
            repository_url_override=job.repository_url_override,
            prompt_text=job.prompt_text,
            prompt_file_path=job.prompt_file_path,
            model_provider=job.model_provider,
            local_model_provider=job.local_model_provider,
            model_name=job.model_name,
            reasoning_effort=job.reasoning_effort,
            working_branch=job.working_branch,
            workspace_name=job.workspace_name,
            test_command=job.test_command,
            approval_mode=job.approval_mode,
            sandbox_mode=job.sandbox_mode,
            max_blocks=job.max_blocks,
            enabled=job.enabled,
            max_concurrent_runs=job.max_concurrent_runs,
            stale_timeout_minutes=job.stale_timeout_minutes,
            retry_policy=RetryPolicyPayload(
                max_attempts=job.retry_max_attempts,
                retry_delay_seconds=job.retry_delay_seconds,
                retry_on_crash=job.retry_on_crash,
                retry_on_failure=job.retry_on_failure,
                retry_on_stale=job.retry_on_stale,
            ),
            schedules=[self._serialize_schedule(schedule) for schedule in job.schedules],
            active_run_count=active_counts.get(job.id, 0),
            next_run_at=next_run_at,
            last_error=job.last_error,
        )

    def _serialize_run(self, run: Run) -> RunView:
        latest_attempt = run.attempts[-1] if run.attempts else None
        return RunView(
            id=run.id,
            job_id=run.job_id,
            job_name_snapshot=run.job_name_snapshot,
            trigger_source=run.trigger_source,
            status=run.status,
            requested_at=run.requested_at,
            queued_at=run.queued_at,
            started_at=run.started_at,
            ended_at=run.ended_at,
            next_retry_at=run.next_retry_at,
            retry_count=run.retry_count,
            last_error=run.last_error,
            summary=run.summary,
            schedule_snapshot=run.schedule_snapshot,
            latest_attempt=self._serialize_attempt(latest_attempt) if latest_attempt else None,
        )

    def _active_counts(self, session) -> dict[str, int]:
        runs = session.scalars(
            select(Run).where(Run.ended_at.is_(None), Run.status.in_(BLOCKING_STATUSES))
        ).all()
        counts: dict[str, int] = {}
        for run in runs:
            counts[run.job_id] = counts.get(run.job_id, 0) + 1
        return counts

    def _blocking_run_count(self, session, job_id: str) -> int:
        return len(
            session.scalars(
                select(Run)
                .where(
                    Run.job_id == job_id,
                    Run.ended_at.is_(None),
                    Run.status.in_(BLOCKING_STATUSES),
                )
            ).all()
        )
