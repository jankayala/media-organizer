"""Media Organizer - organize a photo and video collection by capture date.

The package is split so that the analysis phase is provably free of side
effects: :mod:`media_organizer.planner` only reads metadata and builds a plan,
and only :mod:`media_organizer.executor` is allowed to touch the filesystem.
"""

__version__ = "1.2.0"

from media_organizer.config import (
    DEFAULT_EXTENSIONS,
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    ConflictPolicy,
    GeocoderMode,
)
from media_organizer.models import (
    DateSource,
    MediaFile,
    MediaKind,
    MediaMetadata,
    Plan,
    PlannedCopy,
    SkippedFile,
)

__all__ = [
    "DEFAULT_EXTENSIONS",
    "PHOTO_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "ConflictPolicy",
    "DateSource",
    "GeocoderMode",
    "MediaFile",
    "MediaKind",
    "MediaMetadata",
    "Plan",
    "PlannedCopy",
    "SkippedFile",
    "__version__",
]