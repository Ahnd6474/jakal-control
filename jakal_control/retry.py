from __future__ import annotations

from datetime import timedelta

from .enums import FailureCategory
from .models import Job, Run


def should_retry(job: Job, run: Run, category: FailureCategory) -> bool:
    if run.retry_count >= job.retry_max_attempts:
        return False
    if category in {FailureCategory.SUCCESS, FailureCategory.CANCELLED}:
        return False
    if category is FailureCategory.CRASH:
        return bool(job.retry_on_crash)
    if category is FailureCategory.TASK_FAILURE:
        return bool(job.retry_on_failure)
    if category is FailureCategory.STALE:
        return bool(job.retry_on_stale)
    return False


def retry_delay(job: Job) -> timedelta:
    return timedelta(seconds=max(1, job.retry_delay_seconds))

