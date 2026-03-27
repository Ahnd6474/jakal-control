from __future__ import annotations

from datetime import UTC, datetime

from jakal_control.enums import ScheduleType
from jakal_control.schedules import ScheduleDefinition, compute_next_run


def test_compute_next_run_for_daily_schedule() -> None:
    definition = ScheduleDefinition(
        kind=ScheduleType.DAILY,
        timezone_name="Asia/Seoul",
        hour=9,
        minute=30,
    )
    after = datetime(2026, 3, 27, 0, 0, tzinfo=UTC)
    next_run = compute_next_run(definition, after)
    assert next_run == datetime(2026, 3, 27, 0, 30, tzinfo=UTC)


def test_compute_next_run_for_every_hours_schedule() -> None:
    definition = ScheduleDefinition(
        kind=ScheduleType.EVERY_HOURS,
        timezone_name="Asia/Seoul",
        anchor_local="2026-03-27T09:00",
        interval_hours=6,
    )
    after = datetime(2026, 3, 27, 5, 30, tzinfo=UTC)
    next_run = compute_next_run(definition, after)
    assert next_run == datetime(2026, 3, 27, 6, 0, tzinfo=UTC)


def test_compute_next_run_for_weekday_schedule() -> None:
    definition = ScheduleDefinition(
        kind=ScheduleType.WEEKDAYS,
        timezone_name="Asia/Seoul",
        hour=10,
        minute=0,
        weekdays=(0, 2, 4),
    )
    after = datetime(2026, 3, 27, 2, 0, tzinfo=UTC)
    next_run = compute_next_run(definition, after)
    assert next_run == datetime(2026, 3, 30, 1, 0, tzinfo=UTC)


def test_compute_next_run_for_one_time_schedule_expires() -> None:
    definition = ScheduleDefinition(
        kind=ScheduleType.ONCE,
        timezone_name="Asia/Seoul",
        anchor_local="2026-03-27T08:00",
    )
    after = datetime(2026, 3, 27, 0, 0, tzinfo=UTC)
    assert compute_next_run(definition, after) is None
