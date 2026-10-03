"""Materialise a plan inside the output folder.

Guarantees enforced here:

* sources are opened read-only, never moved, renamed or deleted;
* targets are created below the output folder only;
* an existing target file is never overwritten;
* partial copies are removed so no half-written file survives.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from media_organizer.metadata import write_location_tags
from media_organizer.models import MediaKind, Plan, PlannedCopy
from media_organizer.naming import COLLISION_START, SEQUENCE_WIDTH, split_sequence
from media_organizer.planner import resolve_dir


@dataclass
class ExecutionResult:
    """Outcome of running a plan."""

    copied: list[PlannedCopy] = field(default_factory=list)
    unchanged: list[PlannedCopy] = field(default_factory=list)
    renamed: list[PlannedCopy] = field(default_factory=list)
    tagged: list[PlannedCopy] = field(default_factory=list)
    failures: list[tuple[PlannedCopy, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _free_target(target: Path) -> Path:
    """Return ``target`` or the next free ``_02``-style variant of it."""
    if not target.exists():
        return target

    # split_sequence keeps the timestamp intact: ``20240714_163218`` has no
    # counter, while ``20240714_163218_02`` has sequence 2.
    prefix, sequence = split_sequence(target.stem)
    start = sequence + 1 if sequence is not None else COLLISION_START

    for number in range(start, 10_000):
        candidate = target.with_name(f"{prefix}_{number:0{SEQUENCE_WIDTH}d}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"no free filename available next to {target}")


def _copy(source: Path, target: Path) -> None:
    """Copy ``source`` to ``target`` atomically, preserving its timestamps."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f"{target.name}.{os.getpid()}.part")
    try:
        shutil.copy2(source, staging)
        if target.exists():
            raise FileExistsError(f"{target} appeared while copying")
        os.replace(staging, target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def execute_plan(plan: Plan, *, write_tags: bool = False) -> ExecutionResult:
    """Copy every planned photo and video into the output folder."""
    result = ExecutionResult()
    output_root = plan.output_root

    for item in plan.items:
        source = resolve_dir(item.source.path)
        if not source.is_relative_to(plan.input_root):
            result.failures.append((item, "source is outside the input folder"))
            continue

        target = resolve_dir(item.target)
        if not target.is_relative_to(output_root):
            result.failures.append((item, "target is outside the output folder"))
            continue
        if target == source:
            result.failures.append((item, "refusing to overwrite the input file"))
            continue

        if item.already_present and target.exists():
            result.unchanged.append(item)
            continue

        try:
            final = _free_target(target)
        except FileExistsError as exc:
            result.failures.append((item, str(exc)))
            continue

        try:
            _copy(source, final)
        except Exception as exc:
            result.failures.append((item, f"{type(exc).__name__}: {exc}"))
            continue

        saved = PlannedCopy(
            source=item.source,
            metadata=item.metadata,
            target=final,
            # The planner already renamed around an existing file; the extra
            # comparison covers a file that appeared while copying.
            conflict_renamed=item.conflict_renamed or final != item.target,
            already_present=False,
        )
        result.copied.append(saved)
        if saved.conflict_renamed:
            result.renamed.append(saved)

        if write_tags and saved.metadata.locations and saved.kind is MediaKind.PHOTO:
            try:
                write_location_tags(final, saved.metadata.locations)
            except Exception as exc:
                result.failures.append((saved, f"could not write location tags: {exc}"))
                continue
            result.tagged.append(saved)

    return result