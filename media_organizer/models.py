"""Value objects shared by the scanner, planner and executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class DateSource(str, Enum):
    """Where the capture timestamp came from."""

    EXIF = "exif"
    CONTAINER = "container"
    FILESYSTEM = "filesystem"


class MediaKind(str, Enum):
    """What sort of media file this is."""

    PHOTO = "photo"
    VIDEO = "video"


@dataclass(frozen=True)
class MediaFile:
    """A photo or video found on disk. ``path`` is only ever opened for reading."""

    path: Path
    relative_path: Path
    size: int
    kind: MediaKind

    @property
    def display(self) -> str:
        """The path as the user typed it, with forward slashes."""
        return self.relative_path.as_posix()


@dataclass(frozen=True)
class MediaMetadata:
    """Everything the planner needs to know about one file."""

    taken_at: datetime
    date_source: DateSource
    latitude: float | None = None
    longitude: float | None = None
    locations: tuple[str, ...] = ()
    warning: str | None = None

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class PlannedCopy:
    """One entry of the plan: copy ``source`` to ``target``."""

    source: MediaFile
    metadata: MediaMetadata
    target: Path
    conflict_renamed: bool = False
    already_present: bool = False

    @property
    def kind(self) -> MediaKind:
        return self.source.kind


@dataclass
class SkippedFile:
    """A file that is deliberately left out of the output."""

    source: MediaFile
    reason: str

    @property
    def kind(self) -> MediaKind:
        return self.source.kind


@dataclass
class Plan:
    """The complete, side-effect free description of a run."""

    input_dir: Path
    input_root: Path
    output_dir: Path
    output_root: Path
    geocoder: str = ""
    items: list[PlannedCopy] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.items) + len(self.skipped)

    def of_kind(self, kind: MediaKind) -> int:
        """Number of discovered files of ``kind``, planned or skipped."""
        return sum(1 for item in self.all_files() if item.kind is kind)

    def all_files(self) -> list[MediaFile]:
        """Every file the run looked at, planned and skipped alike."""
        return [item.source for item in self.items] + [item.source for item in self.skipped]

    def tagged_items(self) -> list[PlannedCopy]:
        """The planned files that got at least one location tag."""
        return [item for item in self.items if item.metadata.locations]