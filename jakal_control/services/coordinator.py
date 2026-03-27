from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..adapters.jakal_flow import JakalFlowAdapter
from ..config import AppConfig
from ..database import Database
from ..enums import FailureCategory, JobRunStatus, TriggerSource
from ..models import Job, Run, RunAttempt, Schedule
from ..retry import retry_delay, should_retry
from ..schedules import ScheduleDefinition, compute_next_run, describe_schedule
from ..utils import atomic_write_json, parse_json_list, read_json, shorten, tail_text_file, utc_now


def terminate_process_tree(pid: int | None) -> None:
    if not pid:
        return
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return
    children = process.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        process.terminate()
    except psutil.Error:
        pass
    psutil.wait_procs(children + [process], timeout=3)
    for proc in children + [process]:
        if proc.is_running():
            try:
                proc.kill()
            except psutil.Error:
                pass


class SupervisorCoordinator:
    def __init__(self, db: Database, config: AppConfig) -> None:
        self.db = db
        self.config = config
        self.adapter = JakalFlowAdapter(config)
        self._thread = threading.Thread(target=self._loop, name="jakal-control-supervisor", daemon=True)
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def tick(self) -> None:
        now = utc_now()
        with self.db.session() as session:
            self._sync_active_runs(session, now)
            self._claim_due_schedules(session, now)
            self._launch_ready_runs(session, now)

    def _loop(self) -> None:
        while not self._stop_event.wait(self.config.scheduler_poll_seconds):
            self.tick()

    def _claim_due_schedules(self, session, now) -> None:
        schedules = session.scalars(
            select(Schedule)
            .join(Schedule.job)
            .where(
                Schedule.enabled.is_(True),
                Schedule.next_run_at.is_not(None),
                Schedule.next_run_at <= now,
                Job.enabled.is_(True),
                Job.deleted_at.is_(None),
            )
            .options(selectinload(Schedule.job))
            .order_by(Schedule.next_run_at.asc())
        ).all()
        for schedule in schedules:
            job = schedule.job
            if self._blocking_run_count(session, job.id) >= job.max_concurrent_runs:
                continue
            run = Run(
                job_id=job.id,
                schedule_id=schedule.id,
                schedule_snapshot=self._schedule_description(schedule),
                job_name_snapshot=job.name,
                trigger_source=TriggerSource.SCHEDULE,
                status=JobRunStatus.QUEUED,
                summary="Queued from schedule.",
            )
            session.add(run)
            schedule.last_fired_at = now
            next_run_at = compute_next_run(self._schedule_definition(schedule), now + timedelta(seconds=1))
            schedule.next_run_at = next_run_at
            if next_run_at is None:
                schedule.enabled = False

    def _launch_ready_runs(self, session, now) -> None:
        runs = session.scalars(
            select(Run)
            .join(Run.job)
            .where(
                Run.ended_at.is_(None),
                Run.status.in_((JobRunStatus.QUEUED, JobRunStatus.RETRY_WAITING)),
                Job.deleted_at.is_(None),
            )
            .options(selectinload(Run.attempts), selectinload(Run.job))
            .order_by(Run.requested_at.asc())
        ).all()
        for run in runs:
            job = run.job
            if run.status == JobRunStatus.RETRY_WAITING and run.next_retry_at and run.next_retry_at > now:
                continue
            if self._active_execution_count(session, job.id) >= job.max_concurrent_runs:
                continue

            plan = self.adapter.build_execution_plan(job)
            attempt_number = len(run.attempts) + 1
            attempt_dir = self.config.runs_dir / run.id / f"attempt-{attempt_number}"
            command_file = attempt_dir / "command.json"
            status_file = attempt_dir / "status.json"
            log_file = attempt_dir / "output.log"
            atomic_write_json(command_file, plan.to_json())

            runner_cmd = [
                sys.executable,
                "-m",
                "jakal_control.job_runner",
                "--command-file",
                str(command_file),
                "--status-file",
                str(status_file),
                "--log-file",
                str(log_file),
                "--heartbeat-seconds",
                str(self.config.runner_heartbeat_seconds),
            ]
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(runner_cmd, cwd=plan.cwd, creationflags=creationflags)
            attempt = RunAttempt(
                run_id=run.id,
                attempt_number=attempt_number,
                status=JobRunStatus.STARTING,
                wrapper_pid=process.pid,
                started_at=now,
                log_path=str(log_file),
                status_file_path=str(status_file),
                command_file_path=str(command_file),
            )
            session.add(attempt)
            run.status = JobRunStatus.STARTING
            run.started_at = run.started_at or now
            run.next_retry_at = None
            run.summary = "Launching Jakal Flow."

    def _sync_active_runs(self, session, now) -> None:
        runs = session.scalars(
            select(Run)
            .join(Run.job)
            .where(
                Run.ended_at.is_(None),
                Run.status.in_((JobRunStatus.STARTING, JobRunStatus.RUNNING, JobRunStatus.STALE)),
            )
            .options(selectinload(Run.attempts), selectinload(Run.job))
        ).all()
        for run in runs:
            attempt = run.attempts[-1] if run.attempts else None
            if not attempt:
                run.status = JobRunStatus.FAILED
                run.ended_at = now
                run.summary = "Run lost its attempt record."
                run.last_error = run.summary
                continue

            snapshot = read_json(Path(attempt.status_file_path)) if attempt.status_file_path else None
            if snapshot:
                self._apply_snapshot(attempt, snapshot)

            if snapshot and snapshot.get("result"):
                self._finalize_from_snapshot(run.job, run, attempt, snapshot, now)
                continue

            if not self._pid_exists(attempt.wrapper_pid):
                if run.cancellation_requested_at:
                    self._finalize(
                        run.job,
                        run,
                        attempt,
                        final_status=JobRunStatus.CANCELLED,
                        category=FailureCategory.CANCELLED,
                        summary="Cancelled by user.",
                        now=now,
                    )
                else:
                    self._finalize(
                        run.job,
                        run,
                        attempt,
                        final_status=JobRunStatus.FAILED,
                        category=FailureCategory.CRASH,
                        summary=self._summary_from_logs(attempt, "Supervisor lost the runner process."),
                        now=now,
                    )
                continue

            if attempt.child_pid and run.status != JobRunStatus.RUNNING:
                run.status = JobRunStatus.RUNNING
                attempt.status = JobRunStatus.RUNNING

            last_progress = attempt.last_output_at or attempt.started_at or run.started_at or now
            if last_progress and (now - last_progress) >= timedelta(minutes=max(1, run.job.stale_timeout_minutes)):
                summary = f"No output observed for {run.job.stale_timeout_minutes} minute(s)."
                if run.job.retry_on_stale and should_retry(run.job, run, FailureCategory.STALE):
                    terminate_process_tree(attempt.wrapper_pid)
                    self._finalize(
                        run.job,
                        run,
                        attempt,
                        final_status=JobRunStatus.STALE,
                        category=FailureCategory.STALE,
                        summary=summary,
                        now=now,
                    )
                else:
                    run.status = JobRunStatus.STALE
                    run.summary = summary
                    run.last_error = summary
                    attempt.status = JobRunStatus.STALE
                    attempt.summary = summary
            elif run.status == JobRunStatus.STALE:
                run.status = JobRunStatus.RUNNING
                attempt.status = JobRunStatus.RUNNING

    def _apply_snapshot(self, attempt: RunAttempt, snapshot: dict) -> None:
        if snapshot.get("runner_pid") and not attempt.wrapper_pid:
            attempt.wrapper_pid = int(snapshot["runner_pid"])
        if snapshot.get("child_pid"):
            attempt.child_pid = int(snapshot["child_pid"])
        if snapshot.get("last_heartbeat_at"):
            attempt.last_heartbeat_at = self._parse_dt(snapshot["last_heartbeat_at"])
        if snapshot.get("last_output_at"):
            attempt.last_output_at = self._parse_dt(snapshot["last_output_at"])
        if snapshot.get("exit_code") is not None:
            attempt.exit_code = int(snapshot["exit_code"])

    def _finalize_from_snapshot(self, job: Job, run: Run, attempt: RunAttempt, snapshot: dict, now) -> None:
        result = str(snapshot.get("result", "")).strip()
        if result == "success":
            self._finalize(
                job,
                run,
                attempt,
                final_status=JobRunStatus.SUCCEEDED,
                category=FailureCategory.SUCCESS,
                summary=self._summary_from_logs(attempt, "Jakal Flow completed successfully."),
                now=now,
            )
            return
        if run.cancellation_requested_at:
            self._finalize(
                job,
                run,
                attempt,
                final_status=JobRunStatus.CANCELLED,
                category=FailureCategory.CANCELLED,
                summary="Cancelled by user.",
                now=now,
            )
            return
        category = FailureCategory.CRASH if result == "launch_error" else FailureCategory.TASK_FAILURE
        self._finalize(
            job,
            run,
            attempt,
            final_status=JobRunStatus.FAILED,
            category=category,
            summary=self._summary_from_logs(attempt, snapshot.get("error") or "Jakal Flow exited with an error."),
            now=now,
        )

    def _finalize(
        self,
        job: Job,
        run: Run,
        attempt: RunAttempt,
        final_status: JobRunStatus,
        category: FailureCategory,
        summary: str,
        now,
    ) -> None:
        summary = shorten(summary, limit=320) or "Run finished."
        attempt.status = final_status
        attempt.ended_at = now
        attempt.failure_category = category.value
        attempt.summary = summary
        run.summary = summary

        if category is FailureCategory.SUCCESS:
            run.status = JobRunStatus.SUCCEEDED
            run.ended_at = now
            run.last_error = None
            return
        if category is FailureCategory.CANCELLED:
            run.status = JobRunStatus.CANCELLED
            run.ended_at = now
            run.last_error = summary
            return
        if should_retry(job, run, category):
            run.retry_count += 1
            run.status = JobRunStatus.RETRY_WAITING
            run.next_retry_at = now + retry_delay(job)
            run.last_error = summary
            run.ended_at = None
            run.summary = f"{summary} Retrying at {run.next_retry_at.isoformat()}."
            return
        run.status = JobRunStatus.STALE if category is FailureCategory.STALE else JobRunStatus.FAILED
        run.ended_at = now
        run.last_error = summary
        job.last_error = summary

    def _summary_from_logs(self, attempt: RunAttempt, fallback: str) -> str:
        if attempt.log_path:
            tail = tail_text_file(attempt.log_path, lines=12)
            lines = [line.strip() for line in tail.splitlines() if line.strip()]
            for line in reversed(lines):
                if line.startswith("argv:") or line.startswith("====="):
                    continue
                return line
        return fallback

    def _schedule_definition(self, schedule: Schedule) -> ScheduleDefinition:
        return ScheduleDefinition(
            kind=schedule.kind,
            timezone_name=schedule.timezone_name,
            anchor_local=schedule.anchor_local,
            hour=schedule.hour,
            minute=schedule.minute,
            interval_hours=schedule.interval_hours,
            weekdays=tuple(parse_json_list(schedule.weekdays_json)),
        )

    def _schedule_description(self, schedule: Schedule) -> str:
        return describe_schedule(self._schedule_definition(schedule))

    def _blocking_run_count(self, session, job_id: str) -> int:
        return len(
            session.scalars(
                select(Run).where(
                    Run.job_id == job_id,
                    Run.ended_at.is_(None),
                    Run.status.in_(
                        (
                            JobRunStatus.QUEUED,
                            JobRunStatus.STARTING,
                            JobRunStatus.RUNNING,
                            JobRunStatus.RETRY_WAITING,
                            JobRunStatus.STALE,
                        )
                    ),
                )
            ).all()
        )

    def _active_execution_count(self, session, job_id: str) -> int:
        return len(
            session.scalars(
                select(Run).where(
                    Run.job_id == job_id,
                    Run.ended_at.is_(None),
                    Run.status.in_((JobRunStatus.STARTING, JobRunStatus.RUNNING, JobRunStatus.STALE)),
                )
            ).all()
        )

    def _pid_exists(self, pid: int | None) -> bool:
        if not pid:
            return False
        try:
            return psutil.pid_exists(pid)
        except psutil.Error:
            return False

    def _parse_dt(self, value: str) -> datetime:
        return datetime.fromisoformat(value)
