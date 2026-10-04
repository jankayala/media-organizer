"""Human readable and machine readable output for a run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from media_organizer.executor import ExecutionResult
from media_organizer.models import MediaKind, Plan, PlannedCopy
from media_organizer.summary import find_duplicate_groups

INDENT = "  "


def _posix(path: Path | str) -> str:
    return Path(path).as_posix()


def _truncate(items: Sequence[Any], max_display: int | None) -> tuple[list[Any], int]:
    if max_display is None or len(items) <= max_display:
        return list(items), 0
    return list(items[:max_display]), len(items) - max_display


def _more_line(count: int, noun: str = "more file") -> str:
    return f"  ... and {count:,} {noun}{'s' if count != 1 else ''}"


def target_display(plan: Plan, target: Path) -> str:
    """Show targets the way the user asked for them: ``output/2024/2024_07/x.jpg``."""
    try:
        relative = Path(target).relative_to(plan.output_root)
    except ValueError:
        return _posix(target)
    return _posix(Path(plan.output_dir) / relative)


def _target_line(plan: Plan, item: PlannedCopy) -> str:
    line = f"{INDENT}-> {target_display(plan, item.target)}"
    if item.already_present:
        line += "  (already present, left unchanged)"
    elif item.conflict_renamed:
        line += "  (renamed: a file with that name already existed)"
    return line


def _render_entries(
    lines: list[str],
    heading: str,
    entries: Iterable[tuple[str, list[str]]],
) -> None:
    entries = list(entries)
    if not entries:
        return
    lines.append(heading)
    lines.append("")
    for name, details in entries:
        lines.append(name)
        lines.extend(f"{INDENT}{detail}" for detail in details)
        lines.append("")


def found_line(plan: Plan) -> str:
    """``Found 12 photos and 3 videos.``"""
    photos = plan.of_kind(MediaKind.PHOTO)
    videos = plan.of_kind(MediaKind.VIDEO)
    parts: list[str] = []
    if photos:
        parts.append(f"{photos:,} photo{'s' if photos != 1 else ''}")
    if videos:
        parts.append(f"{videos:,} video{'s' if videos != 1 else ''}")
    if not parts:
        return "Found no media."
    if len(parts) == 1:
        return f"Found {parts[0]}."
    if len(parts) == 2:
        return f"Found {parts[0]} and {parts[1]}."
    return f"Found {', '.join(parts[:-1])} and {parts[-1]}."


def render_plan(plan: Plan, *, max_display: int | None = None) -> list[str]:
    """Everything the user learns about the run, before and after copying."""
    lines: list[str] = [f"Scanning: {_posix(plan.input_dir)}", ""]
    lines.append(found_line(plan))
    lines.append("")

    shown, hidden = _truncate(plan.items, max_display)
    if shown:
        lines.append("Created files:")
        lines.append("")
        for item in shown:
            lines.append(item.source.display)
            lines.append(_target_line(plan, item))
            lines.append("")
        if hidden:
            lines.append(_more_line(hidden))
            lines.append("")
    else:
        lines.append("No media to organize.")
        lines.append("")

    _render_entries(
        lines,
        "Location tags:",
        [
            (item.source.display, [f"+ {tag}" for tag in item.metadata.locations])
            for item in _truncate(plan.tagged_items(), max_display)[0]
        ],
    )

    if plan.skipped:
        skipped, hidden_skipped = _truncate(plan.skipped, max_display)
        _render_entries(
            lines,
            "Skipped:",
            [(item.source.display, [f"- {item.reason}"]) for item in skipped],
        )
        if hidden_skipped:
            lines.append(_more_line(hidden_skipped))
            lines.append("")

    if plan.warnings:
        _render_entries(lines, "Warnings:", [("-", [w]) for w in plan.warnings])

    return lines


def render_report(
    plan: Plan,
    result: ExecutionResult,
    *,
    summary_path: Path | None = None,
    max_display: int | None = None,
) -> str:
    """The single report printed after the organizer has run."""
    lines = render_plan(plan, max_display=max_display)
    lines.append(
        f"Wrote {len(result.copied):,} of {len(plan.items):,} file(s) to {_posix(plan.output_dir)}."
    )
    if result.unchanged:
        lines.append(
            f"{len(result.unchanged):,} file(s) were already up to date and left untouched."
        )
    if result.renamed:
        lines.append(
            f"{len(result.renamed):,} file(s) got a _NN suffix because the name was taken."
        )
    duplicates = find_duplicate_groups(plan)
    if duplicates:
        numbered = sum(len(entries) for _, _, entries in duplicates)
        lines.append(
            f"{len(duplicates):,} duplicate group(s) found: {numbered:,} file(s) share "
            f"a capture timestamp and extension, so they got a number."
        )
    if result.tagged:
        lines.append(f"Location tags written to {len(result.tagged):,} new file(s).")
    lines.append("No original file was moved, renamed or deleted.")
    if summary_path is not None:
        lines.append(f"Summary written to {_posix(summary_path)}.")
    if result.failures:
        _render_entries(
            lines,
            "Failed:",
            [(item.source.display, [f"- {reason}"]) for item, reason in result.failures],
        )
    return "\n".join(lines)


def render_summary(plan: Plan, result: ExecutionResult) -> str:
    """One-line summary, used by ``--quiet``."""
    years = sorted({item.metadata.taken_at.year for item in plan.items})
    span = f"{years[0]}-{years[-1]}" if years else "-"
    photos = plan.of_kind(MediaKind.PHOTO)
    videos = plan.of_kind(MediaKind.VIDEO)
    return (
        f"{len(result.copied):,} file(s) created from {photos:,} photo(s) and "
        f"{videos:,} video(s), {len(plan.skipped):,} skipped, "
        f"{len(plan.tagged_items()):,} with location tags, years {span}"
    )


def run_as_dict(plan: Plan, result: ExecutionResult) -> dict[str, Any]:
    """The run as plain data, for :func:`render_json`."""
    return {
        "input": _posix(plan.input_dir),
        "output": _posix(plan.output_dir),
        "geocoder": plan.geocoder,
        "found": {
            "photos": plan.of_kind(MediaKind.PHOTO),
            "videos": plan.of_kind(MediaKind.VIDEO),
            "total": plan.total_count,
        },
        "created": len(result.copied),
        "already_present": len(result.unchanged),
        "renamed": len(result.renamed),
        "items": [
            {
                "source": item.source.display,
                "kind": item.kind.value,
                "target": target_display(plan, item.target),
                "taken_at": item.metadata.taken_at.isoformat(),
                "date_source": item.metadata.date_source.value,
                "gps": (
                    None
                    if not item.metadata.has_gps
                    else [item.metadata.latitude, item.metadata.longitude]
                ),
                "locations": list(item.metadata.locations),
                "conflict_renamed": item.conflict_renamed,
                "already_present": item.already_present,
                "created": not item.already_present,
            }
            for item in plan.items
        ],
        "skipped": [
            {"source": item.source.display, "reason": item.reason} for item in plan.skipped
        ],
        "warnings": list(plan.warnings),
        "failures": [
            {"source": item.source.display, "reason": reason} for item, reason in result.failures
        ],
    }


def render_json(plan: Plan, result: ExecutionResult) -> str:
    """The run as indented JSON."""
    return json.dumps(run_as_dict(plan, result), indent=2, ensure_ascii=False)