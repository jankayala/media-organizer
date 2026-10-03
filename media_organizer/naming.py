"""Naming rules for the organised output.

    output/
    └── {year}/
        └── {year}_{month}/
            └── {year}{month}{day}_{time}[_{##}].{extension}

The ``_{##}`` counter is optional: it is only added to a file whose capture
timestamp is already used by an earlier file, or whose plain name is already
taken in the output folder. The first file of a timestamp therefore keeps the
plain name and its duplicates are numbered from ``_02``.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

SEQUENCE_WIDTH = 2
FIRST_SEQUENCE = 1
#: The plain name counts as number 1, so the first duplicate becomes ``_02``.
COLLISION_START = 2
TIMESTAMP_SHAPE = r"\d{8}_\d{6}"
#: Counter is ``SEQUENCE_WIDTH`` digits wide and grows past that, so ``_100``
#: stays parseable; the timestamp shape keeps ``_163218`` from being one.
SEQUENCE_SUFFIX = re.compile(
    rf"^(?P<stem>{TIMESTAMP_SHAPE})_(?P<sequence>\d{{{SEQUENCE_WIDTH},}})$"
)


def normalise_extension(extension: str) -> str:
    """Return a lower-case extension including the leading dot."""
    ext = extension.strip().lower()
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return ext


def target_dir(output_dir: Path, taken_at: datetime) -> Path:
    """``output/2024/2024_07`` for a file captured in July 2024."""
    return Path(output_dir) / f"{taken_at:%Y}" / f"{taken_at:%Y}_{taken_at:%m}"


def timestamp_prefix(taken_at: datetime) -> str:
    """``20240714_163218`` - the part of the filename that identifies the moment."""
    return f"{taken_at:%Y%m%d}_{taken_at:%H%M%S}"


def target_filename(taken_at: datetime, sequence: int | None, extension: str) -> str:
    """``20240714_163218.jpg``, or ``20240714_163218_02.jpg`` for sequence 2.

    ``sequence=None`` omits the counter entirely.
    """
    ext = normalise_extension(extension)
    stamp = timestamp_prefix(taken_at)
    if sequence is None:
        return f"{stamp}{ext}"
    return f"{stamp}_{sequence:0{SEQUENCE_WIDTH}d}{ext}"


def sequence_key(taken_at: datetime, extension: str) -> tuple[str, str]:
    """Identity of a naming slot, ignoring the ``##`` counter.

    Two files only compete for the same name when both this timestamp and the
    extension match.
    """
    return (timestamp_prefix(taken_at), normalise_extension(extension))


def split_sequence(stem: str) -> tuple[str, int | None]:
    """Split ``20240714_163218_02`` into ``("20240714_163218", 2)``.

    Only planner-generated names are understood. A bare timestamp such as
    ``20240714_163218`` has no counter and is returned unchanged with ``None``,
    and so is anything that is not a timestamp followed by a counter.
    """
    match = SEQUENCE_SUFFIX.match(stem)
    if match is None:
        return stem, None
    return match.group("stem"), int(match.group("sequence"))