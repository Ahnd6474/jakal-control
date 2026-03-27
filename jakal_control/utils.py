from __future__ import annotations

import json
import os
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    value = value.strip("-")
    return value or "job"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    Path(temp_name).replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def tail_text_file(path: str | Path, lines: int = 200) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    data = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not data:
        return ""
    return "\n".join(data[-lines:])


def shorten(text: str | None, limit: int = 240) -> str | None:
    if text is None:
        return None
    stripped = " ".join(text.split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + "..."


def parse_json_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        return []
    return [int(item) for item in value]


def dump_json_list(values: list[int]) -> str:
    return json.dumps(sorted(set(int(value) for value in values)))


def split_command(command: str) -> list[str]:
    if os.name == "nt":
        return shlex.split(command, posix=False)
    return shlex.split(command)

