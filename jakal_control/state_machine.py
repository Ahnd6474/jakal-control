from __future__ import annotations

from .enums import JobRunStatus


ALLOWED_RUN_TRANSITIONS: dict[JobRunStatus, set[JobRunStatus]] = {
    JobRunStatus.QUEUED: {
        JobRunStatus.STARTING,
        JobRunStatus.CANCELLED,
    },
    JobRunStatus.STARTING: {
        JobRunStatus.RUNNING,
        JobRunStatus.FAILED,
        JobRunStatus.CANCELLED,
        JobRunStatus.RETRY_WAITING,
        JobRunStatus.STALE,
    },
    JobRunStatus.RUNNING: {
        JobRunStatus.SUCCEEDED,
        JobRunStatus.FAILED,
        JobRunStatus.CANCELLED,
        JobRunStatus.RETRY_WAITING,
        JobRunStatus.STALE,
    },
    JobRunStatus.RETRY_WAITING: {
        JobRunStatus.QUEUED,
        JobRunStatus.STARTING,
        JobRunStatus.CANCELLED,
    },
    JobRunStatus.STALE: {
        JobRunStatus.RUNNING,
        JobRunStatus.CANCELLED,
        JobRunStatus.RETRY_WAITING,
        JobRunStatus.FAILED,
    },
    JobRunStatus.SUCCEEDED: set(),
    JobRunStatus.FAILED: set(),
    JobRunStatus.CANCELLED: set(),
}


def require_transition(current: JobRunStatus, new: JobRunStatus) -> None:
    if current == new:
        return
    allowed = ALLOWED_RUN_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise ValueError(f"Invalid run transition: {current.value} -> {new.value}")

