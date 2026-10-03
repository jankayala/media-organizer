"""The plain-text run summary written into the output folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from media_organizer.config import Config
from media_organizer.executor import ExecutionResult
from media_organizer.models import MediaKind, Plan, PlannedCopy
from media_organizer.naming import sequence_key

_LINE = "=" * 60


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping_lines(rows: list[tuple[str, str]]) -> list[str]:
    """``source -> target`` with the source column padded to a common width."""
    if not rows:
        return ["none"]
    width = max(len(source) for source, _ in rows)
    return [f"{source.ljust(width)} ->  {target}" for source, target in rows]


def _target_lines(entries: list[PlannedCopy], plan: Plan) -> list[str]:
    """``source -> target`` rows for the given entries."""
    return _mapping_lines(
        [(item.source.display, _relative(item.target, plan.output_root)) for item in entries]
    )


def find_duplicate_groups(plan: Plan) -> list[tuple[str, str, list[PlannedCopy]]]:
    """Group the planned files that share a capture timestamp and extension.

    These are the files that compete for one filename, so all but the first of
    each group end up with a ``_NN`` suffix. The groups are returned sorted by
    timestamp.
    """
    groups: dict[tuple[str, str], list[PlannedCopy]] = {}
    for item in plan.items:
        key = sequence_key(item.metadata.taken_at, item.source.path.suffix)
        groups.setdefault(key, []).append(item)

    duplicates = [
        (stamp, extension, entries)
        for (stamp, extension), entries in groups.items()
        if len(entries) > 1
    ]
    duplicates.sort(key=lambda group: (group[0], group[1]))
    return duplicates


def _duplicate_lines(plan: Plan) -> list[str]:
    """The ``Duplicates`` section body."""
    groups = find_duplicate_groups(plan)
    if not groups:
        return ["none"]

    blocks: list[str] = []
    for stamp, extension, entries in groups:
        rows = [f"{stamp} ({extension}) - {len(entries)} files"]
        rows += [f"  {row}" for row in _target_lines(entries, plan)]
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks).splitlines()


def format_summary(plan: Plan, result: ExecutionResult) -> str:
    """Render the summary text for a completed run."""
    photos = plan.of_kind(MediaKind.PHOTO)
    videos = plan.of_kind(MediaKind.VIDEO)
    total = plan.total_count
    duplicates = find_duplicate_groups(plan)
    numbered = sum(len(entries) for _, _, entries in duplicates)

    earliest = min((item.metadata.taken_at for item in plan.items), default=None)
    latest = max((item.metadata.taken_at for item in plan.items), default=None)

    lines: list[str] = [
        "Media organizer summary",
        _LINE,
        f"input : {plan.input_dir.as_posix()}",
        f"output: {plan.output_dir.as_posix()}",
        f"run   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Found media",
        _LINE,
        f"photos           : {photos}",
        f"videos           : {videos}",
        f"total            : {total}",
        f"duplicates       : {len(duplicates)} group(s) sharing a timestamp and "
        f"extension, {numbered} file(s) involved",
    ]

    if earliest is not None and latest is not None:
        span = (
            f"{earliest:%Y-%m-%d %H:%M:%S}"
            if earliest == latest
            else f"{earliest:%Y-%m-%d %H:%M:%S} .. {latest:%Y-%m-%d %H:%M:%S}"
        )
        lines.append(f"date range       : {span}")

    lines += [
        "",
        "Result",
        _LINE,
        f"created          : {len(result.copied)}",
        f"already present  : {len(result.unchanged)}",
        f"renamed on clash : {len(result.renamed)}",
        f"duplicates       : {len(duplicates)}",
        f"skipped          : {len(plan.skipped)}",
        f"failed           : {len(result.failures)}",
    ]

    lines += ["", "Duplicates", _LINE]
    if duplicates:
        lines.append(
            "These files share a capture timestamp and extension, so only the first "
            "one of each group keeps the plain name."
        )
        lines.append("")
    lines += _duplicate_lines(plan)

    lines += ["", "Created files", _LINE]
    lines += _target_lines(result.copied or plan.items, plan)

    lines += ["", "Already present", _LINE]
    lines += _target_lines(result.unchanged, plan)

    lines += ["", "Skipped", _LINE]
    if plan.skipped:
        lines += [f"{item.source.display}: {item.reason}" for item in plan.skipped]
    else:
        lines.append("none")

    if plan.warnings:
        lines += ["", "Warnings", _LINE, *plan.warnings]

    if result.failures:
        lines += ["", "Failures", _LINE]
        lines += [
            f"{item.source.display}: {reason}" for item, reason in result.failures
        ]

    tagged = result.tagged
    if tagged:
        lines += ["", "Location tags written", _LINE]
        lines += [
            f"{_relative(item.target, plan.output_root)}: {', '.join(item.metadata.locations)}"
            for item in tagged
        ]

    return "\n".join(lines) + "\n"


def write_summary(
    plan: Plan,
    result: ExecutionResult,
    config: Config,
    *,
    path: Path | None = None,
) -> Path:
    """Write the run summary next to the created files and return its path."""
    if path is None:
        path = plan.output_root / config.summary_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_summary(plan, result), encoding="utf-8")
    return path