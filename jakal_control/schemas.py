from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import detect_local_timezone
from .enums import JobRunStatus, ScheduleType, TriggerSource
from .schedules import normalize_weekdays


class RetryPolicyPayload(BaseModel):
    max_attempts: int = Field(default=1, ge=0, le=20)
    retry_delay_seconds: int = Field(default=300, ge=1, le=86400)
    retry_on_crash: bool = True
    retry_on_failure: bool = False
    retry_on_stale: bool = False


class SchedulePayload(BaseModel):
    kind: Literal["once", "daily", "every_hours", "weekdays"]
    timezone_name: str = Field(default_factory=detect_local_timezone)
    run_at_local: str | None = None
    start_at_local: str | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    interval_hours: int | None = Field(default=None, ge=1, le=168)
    weekdays: list[int] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        return list(normalize_weekdays(value))

    @model_validator(mode="after")
    def validate_shape(self) -> "SchedulePayload":
        kind = ScheduleType(self.kind)
        if kind is ScheduleType.ONCE and not self.run_at_local:
            raise ValueError("One-time schedules require run_at_local.")
        if kind is ScheduleType.DAILY and (self.hour is None or self.minute is None):
            raise ValueError("Daily schedules require hour and minute.")
        if kind is ScheduleType.EVERY_HOURS and self.interval_hours is None:
            raise ValueError("Every-hours schedules require interval_hours.")
        if kind is ScheduleType.WEEKDAYS:
            if self.hour is None or self.minute is None:
                raise ValueError("Weekday schedules require hour and minute.")
            if not self.weekdays:
                raise ValueError("Weekday schedules require at least one weekday.")
        return self


class JobPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repository_path: str
    repository_url_override: str | None = None
    prompt_text: str | None = None
    prompt_file_path: str | None = None
    model_provider: str | None = None
    local_model_provider: str | None = None
    model_name: str | None = None
    reasoning_effort: str | None = None
    working_branch: str = "main"
    workspace_name: str | None = None
    test_command: str | None = None
    approval_mode: str = "never"
    sandbox_mode: str = "workspace-write"
    max_blocks: int = Field(default=1, ge=1, le=100)
    enabled: bool = True
    max_concurrent_runs: int = Field(default=1, ge=1, le=16)
    stale_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    retry_policy: RetryPolicyPayload = Field(default_factory=RetryPolicyPayload)
    schedules: list[SchedulePayload] = Field(default_factory=list)


class AttemptView(BaseModel):
    id: str
    attempt_number: int
    status: JobRunStatus
    wrapper_pid: int | None = None
    child_pid: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    failure_category: str | None = None
    log_path: str | None = None
    last_heartbeat_at: datetime | None = None
    last_output_at: datetime | None = None
    summary: str | None = None


class ScheduleView(BaseModel):
    id: str
    kind: ScheduleType
    timezone_name: str
    enabled: bool
    anchor_local: str | None = None
    hour: int | None = None
    minute: int | None = None
    interval_hours: int | None = None
    weekdays: list[int] = Field(default_factory=list)
    next_run_at: datetime | None = None
    description: str


class JobView(BaseModel):
    id: str
    name: str
    repository_path: str
    repository_url_override: str | None = None
    prompt_text: str | None = None
    prompt_file_path: str | None = None
    model_provider: str | None = None
    local_model_provider: str | None = None
    model_name: str | None = None
    reasoning_effort: str | None = None
    working_branch: str
    workspace_name: str | None = None
    test_command: str | None = None
    approval_mode: str
    sandbox_mode: str
    max_blocks: int
    enabled: bool
    max_concurrent_runs: int
    stale_timeout_minutes: int
    retry_policy: RetryPolicyPayload
    schedules: list[ScheduleView]
    active_run_count: int
    next_run_at: datetime | None = None
    last_error: str | None = None


class RunView(BaseModel):
    id: str
    job_id: str
    job_name_snapshot: str
    trigger_source: TriggerSource
    status: JobRunStatus
    requested_at: datetime
    queued_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    next_retry_at: datetime | None = None
    retry_count: int
    last_error: str | None = None
    summary: str | None = None
    schedule_snapshot: str | None = None
    latest_attempt: AttemptView | None = None


class ScheduleOverviewItem(BaseModel):
    job_id: str
    job_name: str
    schedule_id: str
    description: str
    next_run_at: datetime | None = None


class DashboardView(BaseModel):
    timezone_name: str
    home_dir: str
    engine_command: str
    jobs: list[JobView]
    active_runs: list[RunView]
    recent_runs: list[RunView]
    schedule_overview: list[ScheduleOverviewItem]


class TogglePayload(BaseModel):
    enabled: bool


class LogTailView(BaseModel):
    run_id: str
    attempt_id: str | None = None
    log_path: str | None = None
    content: str
