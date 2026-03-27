from __future__ import annotations

import pytest

from jakal_control.enums import JobRunStatus
from jakal_control.state_machine import require_transition


def test_valid_transition_from_running_to_retry_waiting() -> None:
    require_transition(JobRunStatus.RUNNING, JobRunStatus.RETRY_WAITING)


def test_stale_can_recover_to_running() -> None:
    require_transition(JobRunStatus.STALE, JobRunStatus.RUNNING)


def test_invalid_transition_raises() -> None:
    with pytest.raises(ValueError):
        require_transition(JobRunStatus.SUCCEEDED, JobRunStatus.RUNNING)
