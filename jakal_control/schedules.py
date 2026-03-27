from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .enums import ScheduleType


@dataclass(frozen=True)
class ScheduleDefinition:
    kind: ScheduleType
    timezone_name: str
    anchor_local: str | None = None
    hour: int | None = None
    minute: int | None = None
    interval_hours: int | None = None
    weekdays: tuple[int, ...] = ()


def parse_local_datetime(raw: str, timezone_name: str) -> datetime:
    local = datetime.fromisoformat(raw)
    tz = ZoneInfo(timezone_name)
    if local.tzinfo is not None:
        return local.astimezone(tz)
    return local.replace(tzinfo=tz)


def compute_next_run(definition: ScheduleDefinition, after_utc: datetime) -> datetime | None:
    tz = ZoneInfo(definition.timezone_name)
    local_after = after_utc.astimezone(tz).replace(second=0, microsecond=0)

    if definition.kind is ScheduleType.ONCE:
        if not definition.anchor_local:
            return None
        candidate = parse_local_datetime(definition.anchor_local, definition.timezone_name)
        if candidate <= local_after:
            return None
        return candidate.astimezone(UTC)

    if definition.kind is ScheduleType.DAILY:
        if definition.hour is None or definition.minute is None:
            return None
        candidate = datetime.combine(local_after.date(), time(definition.hour, definition.minute), tzinfo=tz)
        if candidate <= local_after:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(UTC)

    if definition.kind is ScheduleType.EVERY_HOURS:
        if not definition.anchor_local or not definition.interval_hours:
            return None
        anchor = parse_local_datetime(definition.anchor_local, definition.timezone_name)
        if anchor > local_after:
            return anchor.astimezone(UTC)
        interval_seconds = definition.interval_hours * 3600
        elapsed_seconds = max(0.0, (local_after - anchor).total_seconds())
        steps = math.floor(elapsed_seconds / interval_seconds) + 1
        candidate = anchor + timedelta(hours=definition.interval_hours * steps)
        return candidate.astimezone(UTC)

    if definition.kind is ScheduleType.WEEKDAYS:
        if definition.hour is None or definition.minute is None or not definition.weekdays:
            return None
        weekdays = set(definition.weekdays)
        for offset in range(8):
            candidate_date = local_after.date() + timedelta(days=offset)
            if candidate_date.weekday() not in weekdays:
                continue
            candidate = datetime.combine(candidate_date, time(definition.hour, definition.minute), tzinfo=tz)
            if candidate > local_after:
                return candidate.astimezone(UTC)
        return None

    return None


def describe_schedule(definition: ScheduleDefinition) -> str:
    if definition.kind is ScheduleType.ONCE and definition.anchor_local:
        return f"Once at {definition.anchor_local} ({definition.timezone_name})"
    if definition.kind is ScheduleType.DAILY and definition.hour is not None and definition.minute is not None:
        return f"Daily at {definition.hour:02d}:{definition.minute:02d} ({definition.timezone_name})"
    if definition.kind is ScheduleType.EVERY_HOURS:
        return f"Every {definition.interval_hours} hour(s) from {definition.anchor_local} ({definition.timezone_name})"
    if definition.kind is ScheduleType.WEEKDAYS and definition.hour is not None and definition.minute is not None:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        selected = ", ".join(day_names[index] for index in definition.weekdays)
        return f"{selected} at {definition.hour:02d}:{definition.minute:02d} ({definition.timezone_name})"
    return definition.kind.value


def normalize_weekdays(values: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if 0 <= int(value) <= 6}))


def now_local_iso(timezone_name: str, now: datetime) -> str:
    return now.astimezone(ZoneInfo(timezone_name)).replace(second=0, microsecond=0).isoformat(timespec="minutes")


def date_to_local_iso(run_date: date, hour: int, minute: int, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    return datetime.combine(run_date, time(hour, minute), tzinfo=tz).isoformat(timespec="minutes")
