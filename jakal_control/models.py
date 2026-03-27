from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import JobRunStatus, ScheduleType, TriggerSource
from .utils import utc_now


def new_id() -> str:
    return uuid.uuid4().hex


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    repository_path: Mapped[str] = mapped_column(Text, nullable=False)
    repository_url_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    local_model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    working_branch: Mapped[str] = mapped_column(String(120), default="main")
    workspace_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    test_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_mode: Mapped[str] = mapped_column(String(40), default="never")
    sandbox_mode: Mapped[str] = mapped_column(String(40), default="workspace-write")
    max_blocks: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=1)
    stale_timeout_minutes: Mapped[int] = mapped_column(Integer, default=30)
    retry_max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=300)
    retry_on_crash: Mapped[bool] = mapped_column(Boolean, default=True)
    retry_on_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_on_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Schedule.next_run_at",
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="job")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[ScheduleType] = mapped_column(Enum(ScheduleType), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), nullable=False)
    anchor_local: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekdays_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    job: Mapped[Job] = relationship(back_populates="schedules")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    schedule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schedule_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_source: Mapped[TriggerSource] = mapped_column(Enum(TriggerSource), nullable=False)
    status: Mapped[JobRunStatus] = mapped_column(Enum(JobRunStatus), default=JobRunStatus.QUEUED)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    job: Mapped[Job] = relationship(back_populates="runs", foreign_keys=[job_id])
    attempts: Mapped[list["RunAttempt"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunAttempt.attempt_number",
    )


class RunAttempt(Base):
    __tablename__ = "run_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[JobRunStatus] = mapped_column(Enum(JobRunStatus), default=JobRunStatus.STARTING)
    wrapper_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_output_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    run: Mapped[Run] = relationship(back_populates="attempts")
