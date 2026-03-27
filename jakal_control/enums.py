from __future__ import annotations

from enum import Enum


class JobRunStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_WAITING = "retry_waiting"
    STALE = "stale"


class ScheduleType(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    EVERY_HOURS = "every_hours"
    WEEKDAYS = "weekdays"


class TriggerSource(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    AUTO_RETRY = "auto_retry"
    MANUAL_RETRY = "manual_retry"


class FailureCategory(str, Enum):
    SUCCESS = "success"
    TASK_FAILURE = "task_failure"
    CRASH = "crash"
    STALE = "stale"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = {
    JobRunStatus.SUCCEEDED,
    JobRunStatus.FAILED,
    JobRunStatus.CANCELLED,
    JobRunStatus.STALE,
}

ACTIVE_RUN_STATUSES = {
    JobRunStatus.QUEUED,
    JobRunStatus.STARTING,
    JobRunStatus.RUNNING,
    JobRunStatus.RETRY_WAITING,
    JobRunStatus.STALE,
}

IN_PROGRESS_RUN_STATUSES = {
    JobRunStatus.STARTING,
    JobRunStatus.RUNNING,
    JobRunStatus.STALE,
}

