"""Runtime configuration for a single organizer run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ConflictPolicy(str, Enum):
    """What to do when a planned target already exists in the output folder."""

    BUMP = "bump"
    SKIP = "skip"


class GeocoderMode(str, Enum):
    """Which reverse geocoder turns GPS coordinates into location tags."""

    AUTO = "auto"
    OFFLINE = "offline"
    NOMINATIM = "nominatim"
    NONE = "none"


PHOTO_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".psd",
    ".dng",
    ".raw",
    ".cr2",
    ".cr3",
    ".crw",
    ".nef",
    ".nrw",
    ".arw",
    ".srf",
    ".sr2",
    ".orf",
    ".rw2",
    ".raf",
    ".pef",
    ".srw",
    ".3fr",
    ".fff",
    ".iiq",
    ".rwl",
)

#: Containers whose creation time can be read directly from the file header.
ISOBMFF_VIDEO_EXTENSIONS: tuple[str, ...] = (
    ".mp4",
    ".m4v",
    ".mov",
    ".3gp",
    ".3g2",
    ".3gpp",
    ".mp4v",
    ".mts",
    ".m2ts",
    ".m2t",
    ".ts",
)

#: Containers that need an external probe, so they fall back to the file time.
OTHER_VIDEO_EXTENSIONS: tuple[str, ...] = (
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".asf",
    ".flv",
    ".f4v",
    ".mpg",
    ".mpeg",
    ".mpe",
    ".m2v",
    ".ogv",
    ".vob",
    ".rm",
    ".rmvb",
    ".mxf",
    ".insv",
    ".dv",
)

VIDEO_EXTENSIONS: tuple[str, ...] = ISOBMFF_VIDEO_EXTENSIONS + OTHER_VIDEO_EXTENSIONS

DEFAULT_EXTENSIONS: tuple[str, ...] = PHOTO_EXTENSIONS + VIDEO_EXTENSIONS

DEFAULT_OUTPUT_DIR = "output"
DEFAULT_SUMMARY_NAME = "summary.txt"
DEFAULT_MAX_LOCATION_KM = 50.0
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"


@dataclass(frozen=True)
class Config:
    """Everything a run needs. ``input_dir`` is kept unresolved for display."""

    input_dir: Path
    output_dir: Path
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    recursive: bool = True
    skip_hidden: bool = True
    conflict_policy: ConflictPolicy = ConflictPolicy.BUMP
    geocoder: GeocoderMode = GeocoderMode.AUTO
    max_location_km: float = DEFAULT_MAX_LOCATION_KM
    write_tags: bool = False
    limit: int | None = None
    summary_name: str = DEFAULT_SUMMARY_NAME