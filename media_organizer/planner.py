"""Turn a folder of photos and videos into a plan.

:func:`build_plan` is deliberately free of side effects: it opens files for
reading only, and it never creates, moves, renames or deletes anything.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from media_organizer.config import Config, ConflictPolicy
from media_organizer.errors import OrganizerError
from media_organizer.geocode import LocationResolver, build_resolver
from media_organizer.metadata import read_metadata
from media_organizer.models import (
    MediaFile,
    MediaMetadata,
    Plan,
    PlannedCopy,
    SkippedFile,
)
from media_organizer.naming import (
    COLLISION_START,
    FIRST_SEQUENCE,
    normalise_extension,
    sequence_key,
    target_dir,
    target_filename,
)
from media_organizer.scanner import scan_media


def resolve_dir(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError as exc:  # pragma: no cover - platform dependent
        raise OrganizerError(f"cannot resolve path '{path}': {exc}") from exc


@dataclass(frozen=True)
class Slot:
    """The name chosen for one media file, and why it looks like that."""

    target: Path | None
    numbered: bool = False
    conflict_renamed: bool = False
    already_present: bool = False

    @property
    def skipped(self) -> bool:
        return self.target is None


class SlotAllocator:
    """Hands out filenames so that no target is ever reused.

    A slot is only numbered when it has to be: either another file already
    claimed the same timestamp and extension, or the plain name exists in the
    output folder with different content.
    """

    def __init__(self, output_dir: Path, policy: ConflictPolicy = ConflictPolicy.BUMP):
        self.output_dir = Path(output_dir)
        self.policy = policy
        self._used: dict[tuple[str, str], set[int]] = {}
        self._existing: dict[Path, set[str]] = {}

    def _existing_names(self, directory: Path) -> set[str]:
        names = self._existing.get(directory)
        if names is None:
            try:
                names = {entry.name for entry in directory.iterdir()}
            except OSError:
                names = set()
            self._existing[directory] = names
        return names

    def allocate(
        self,
        taken_at: datetime,
        extension: str,
        *,
        position: int = 1,
        identical_to: Callable[[Path], bool] | None = None,
    ) -> Slot:
        """Pick the filename for one file.

        ``position`` is the 1-based place of this file among the files sharing
        its timestamp and extension. Position 1 gets the plain name; every
        later position is numbered, and is bumped further if the name it wants
        is already taken in the output folder.
        """
        directory = target_dir(self.output_dir, taken_at)
        ext = normalise_extension(extension)
        used = self._used.setdefault(sequence_key(taken_at, ext), set())
        existing = self._existing_names(directory)

        def is_usable(candidate: Path) -> bool:
            return identical_to is not None and identical_to(candidate)

        fell_back = False
        if position <= FIRST_SEQUENCE:
            candidate = directory / target_filename(taken_at, None, ext)
            if candidate.name not in existing:
                return Slot(candidate)
            if is_usable(candidate):
                return Slot(candidate, already_present=True)
            if self.policy is ConflictPolicy.SKIP:
                return Slot(None)
            fell_back = True
            start = COLLISION_START
        else:
            start = position

        sequence = start
        collided = False
        while True:
            if sequence in used:
                sequence += 1
                continue
            candidate = directory / target_filename(taken_at, sequence, ext)
            if candidate.name in existing:
                if is_usable(candidate):
                    used.add(sequence)
                    return Slot(candidate, numbered=True, already_present=True)
                if self.policy is ConflictPolicy.SKIP:
                    return Slot(None, numbered=True)
                collided = True
                sequence += 1
                continue
            used.add(sequence)
            return Slot(
                candidate,
                numbered=True,
                conflict_renamed=fell_back or collided,
            )


def file_digest(path: Path) -> str | None:
    """SHA-256 of a file, or ``None`` when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def is_identical_copy(target: Path, source: Path) -> bool:
    """True when ``target`` already contains exactly the bytes of ``source``.

    An unreadable file is never treated as identical, so a copy that cannot be
    verified is written to a new name instead of silently reused.
    """
    try:
        if target.stat().st_size != source.stat().st_size:
            return False
    except OSError:
        return False
    target_digest = file_digest(target)
    return target_digest is not None and target_digest == file_digest(source)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_plan(config: Config) -> Plan:
    """Analyse ``config.input_dir`` and describe the files to create."""
    input_root = resolve_dir(config.input_dir)
    output_root = resolve_dir(config.output_dir)

    if not input_root.exists():
        raise OrganizerError(f"input folder does not exist: {config.input_dir}")
    if not input_root.is_dir():
        raise OrganizerError(f"input path is not a folder: {config.input_dir}")
    if output_root == input_root:
        raise OrganizerError("the output folder must not be the input folder")

    excluded: list[Path] = []
    if output_root.is_relative_to(input_root):
        excluded.append(output_root)

    media = scan_media(
        input_root,
        config.extensions,
        recursive=config.recursive,
        skip_hidden=config.skip_hidden,
        excluded_dirs=excluded,
        limit=config.limit,
    )

    resolver = build_resolver(config.geocoder, config.max_location_km)
    allocator = SlotAllocator(output_root, config.conflict_policy)

    plan = Plan(
        input_dir=Path(config.input_dir),
        input_root=input_root,
        output_dir=Path(config.output_dir),
        output_root=output_root,
        geocoder=resolver.name,
    )
    warnings: list[str] = []
    records: list[tuple[MediaFile, MediaMetadata]] = []

    for item in media:
        metadata = read_metadata(item.path, item.kind)
        if metadata.warning:
            warnings.append(f"{item.relative_path.as_posix()}: {metadata.warning}")
        records.append((item, metadata))

    # Files that share a timestamp and extension compete for the same name, so
    # each one is told its position within that group. Everything else keeps a
    # plain name.
    groups: dict[tuple[str, str], list[int]] = {}
    for index, (item, metadata) in enumerate(records):
        groups.setdefault(sequence_key(metadata.taken_at, item.path.suffix), []).append(index)

    for indices in groups.values():
        for position, index in enumerate(indices, start=FIRST_SEQUENCE):
            item, metadata = records[index]

            locations: tuple[str, ...] = ()
            if metadata.has_gps:
                locations = tuple(resolver.resolve(metadata.latitude, metadata.longitude))
            metadata = replace(metadata, locations=locations)

            slot = allocator.allocate(
                metadata.taken_at,
                item.path.suffix,
                position=position,
                identical_to=lambda candidate: is_identical_copy(candidate, item.path),
            )
            if slot.skipped:
                plan.skipped.append(
                    SkippedFile(
                        item, "a file with that name already exists in the output folder"
                    )
                )
                continue

            if resolve_dir(slot.target) == resolve_dir(item.path):
                plan.skipped.append(SkippedFile(item, "would overwrite the input file"))
                continue

            plan.items.append(
                PlannedCopy(
                    source=item,
                    metadata=metadata,
                    target=slot.target,
                    conflict_renamed=slot.conflict_renamed,
                    already_present=slot.already_present,
                )
            )

    plan.warnings = _dedupe(warnings)
    plan.warnings.extend(_dedupe(resolver.warnings))
    return plan