"""EXIF and container access.

Every function here opens files for reading only, except the explicitly named
writers that are only used on *output* copies.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from media_organizer.models import DateSource, MediaKind, MediaMetadata

TAG_DATETIME = 0x0132
TAG_IMAGE_DESCRIPTION = 0x010E
TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
TAG_USER_COMMENT = 0x9286

_GPS_LAT_REF = 1
_GPS_LAT = 2
_GPS_LON_REF = 3
_GPS_LON = 4

_LOCATION_TAG = "Location"
_HEIF_REGISTERED = False

_EXIF_DATE_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M")


def _register_heif_support() -> bool:
    """Enable HEIC/HEIF/AVIF support when ``pillow-heif`` is installed."""
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return True
    try:
        import pillow_heif
    except ImportError:
        _HEIF_REGISTERED = False
        return False
    try:
        pillow_heif.register_heif_opener()
    except Exception:  # pragma: no cover - depends on optional dependency
        _HEIF_REGISTERED = False
        return False
    _HEIF_REGISTERED = True
    return True


def _decode(value: Any) -> str | None:
    """Coerce an EXIF value into a string, or ``None`` if impossible."""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return value.decode(encoding).strip("\x00").strip()
            except UnicodeDecodeError:
                continue
        return None
    if isinstance(value, str):
        return value.strip("\x00").strip() or None
    return None


def _parse_exif_date(raw: Any) -> datetime | None:
    text = _decode(raw)
    if not text:
        return None
    for fmt in _EXIF_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    """Convert an EXIF numeric or rational value to a float."""
    if value is None or isinstance(value, (bytes, str, bool)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dms_to_degrees(value: Any) -> float | None:
    """Convert EXIF GPS coordinates to signed decimal degrees.

    A three element value is the classic ``(degrees, minutes, seconds)`` tuple
    of rationals; a zero seconds component is perfectly normal.
    """
    if isinstance(value, (tuple, list)):
        parts = [_to_float(part) for part in value]
        if any(part is None for part in parts):
            return None
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 3:
            return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
        return None
    return _to_float(value)


def read_gps(exif: Image.Exif) -> tuple[float | None, float | None]:
    """Return ``(latitude, longitude)`` in signed decimal degrees."""
    gps = _sub_ifd(exif, TAG_GPS_IFD)
    if not gps:
        return None, None

    latitude = _dms_to_degrees(gps.get(_GPS_LAT))
    longitude = _dms_to_degrees(gps.get(_GPS_LON))
    if latitude is None or longitude is None:
        return None, None

    if _decode(gps.get(_GPS_LAT_REF)) == "S":
        latitude = -abs(latitude)
    elif _decode(gps.get(_GPS_LAT_REF)) == "N":
        latitude = abs(latitude)
    if _decode(gps.get(_GPS_LON_REF)) == "W":
        longitude = -abs(longitude)
    elif _decode(gps.get(_GPS_LON_REF)) == "E":
        longitude = abs(longitude)

    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None, None
    return latitude, longitude


def _sub_ifd(exif: Image.Exif, ifd_tag: int) -> dict[int, Any]:
    """Return a nested EXIF IFD (Exif, GPS) as a plain dict."""
    try:
        return exif.get_ifd(ifd_tag)
    except Exception:
        return {}


def read_capture_date(exif: Image.Exif) -> datetime | None:
    """Prefer ``DateTimeOriginal``, then ``DateTimeDigitized``, then ``DateTime``.

    ``DateTimeOriginal`` and ``DateTimeDigitized`` live in the Exif sub-IFD,
    while ``DateTime`` is a plain IFD0 tag.
    """
    exif_ifd = _sub_ifd(exif, TAG_EXIF_IFD)
    candidates = [
        exif_ifd.get(TAG_DATETIME_ORIGINAL),
        exif_ifd.get(TAG_DATETIME_DIGITIZED),
        _safe_get(exif, TAG_DATETIME),
    ]
    for candidate in candidates:
        parsed = _parse_exif_date(candidate)
        if parsed is not None:
            return parsed
    return None


def _safe_get(exif: Image.Exif, tag: int) -> Any:
    try:
        return exif.get(tag)
    except Exception:
        return None


def read_photo_metadata(path: Path) -> MediaMetadata:
    """Read capture date and GPS from a photo.

    Falls back to the file system timestamp when no EXIF date is present.
    The file is only ever opened for reading.
    """
    fallback = datetime.fromtimestamp(Path(path).stat().st_mtime)
    _register_heif_support()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(path) as image:
                exif = image.getexif()
                taken_at = read_capture_date(exif)
                latitude, longitude = read_gps(exif)
    except Exception as exc:
        return MediaMetadata(
            taken_at=fallback,
            date_source=DateSource.FILESYSTEM,
            warning=f"metadata unreadable ({type(exc).__name__}); using file timestamp",
        )

    if taken_at is None:
        return MediaMetadata(
            taken_at=fallback,
            date_source=DateSource.FILESYSTEM,
            latitude=latitude,
            longitude=longitude,
        )

    return MediaMetadata(
        taken_at=taken_at,
        date_source=DateSource.EXIF,
        latitude=latitude,
        longitude=longitude,
    )


# --- videos -----------------------------------------------------------------
#
# MP4/MOV/M4V and friends store the recording time in the ``mvhd`` box of the
# ISO base media container, so no external tool is needed. Other containers
# (MKV, AVI, WebM, ...) fall back to the file timestamp.

#: Seconds between the ISOBMFF epoch (1904-01-01) and the Unix epoch.
_ISOBMFF_EPOCH_OFFSET = 2_082_844_800
_BOX_HEADER = 8


def _iter_boxes(handle, start: int, end: int):
    """Yield ``(type, payload_start, payload_end)`` for boxes in a range."""
    offset = start
    while offset + _BOX_HEADER <= end:
        handle.seek(offset)
        header = handle.read(_BOX_HEADER)
        if len(header) < _BOX_HEADER:
            return
        size = int.from_bytes(header[:4], "big")
        box_type = header[4:8]
        header_size = _BOX_HEADER

        if size == 1:
            extended = handle.read(8)
            if len(extended) < 8:
                return
            size = int.from_bytes(extended, "big")
            header_size = 16
        elif size == 0:
            size = end - offset

        if size < header_size or offset + size > end:
            return
        yield box_type, offset + header_size, offset + size
        offset += size


def _read_mvhd_date(handle, payload_start: int) -> datetime | None:
    """Decode the creation time stored in an ``mvhd`` box.

    Version 0 stores a 32 bit unsigned value, version 1 a 64 bit signed one.
    """
    handle.seek(payload_start)
    header = handle.read(4)
    if len(header) < 4:
        return None
    version = header[0]

    if version == 1:
        raw = handle.read(8)
        if len(raw) < 8:
            return None
        seconds = int.from_bytes(raw, "big", signed=True)
    else:
        raw = handle.read(4)
        if len(raw) < 4:
            return None
        # Unsigned: the ISOBMFF epoch pushes these values past 2**31.
        seconds = int.from_bytes(raw, "big")

    if seconds <= 0:
        return None
    try:
        # The stored value is UTC; local time lines up with EXIF wall-clock times.
        return datetime.fromtimestamp(seconds - _ISOBMFF_EPOCH_OFFSET)
    except (OverflowError, OSError, ValueError):
        return None


def read_video_creation_time(path: Path) -> datetime | None:
    """Return the recording time of an ISOBMFF video, or ``None``."""
    try:
        with open(path, "rb") as handle:
            size = Path(path).stat().st_size
            for box_type, start, end in _iter_boxes(handle, 0, size):
                if box_type != b"moov":
                    continue
                for child_type, child_start, _child_end in _iter_boxes(handle, start, end):
                    if child_type == b"mvhd":
                        return _read_mvhd_date(handle, child_start)
    except OSError:
        return None
    return None


def read_video_metadata(path: Path) -> MediaMetadata:
    """Read the recording time of a video.

    Videos carry no location tags, because the GPS data of common video
    containers is not stored in a location this tool can read without an
    external probe.
    """
    fallback = datetime.fromtimestamp(Path(path).stat().st_mtime)
    taken_at = read_video_creation_time(path)
    if taken_at is None:
        return MediaMetadata(taken_at=fallback, date_source=DateSource.FILESYSTEM)
    return MediaMetadata(taken_at=taken_at, date_source=DateSource.CONTAINER)


def read_metadata(path: Path, kind: MediaKind) -> MediaMetadata:
    """Read capture date and GPS for a photo or video."""
    if kind is MediaKind.VIDEO:
        return read_video_metadata(path)
    return read_photo_metadata(path)


def write_location_tags(path: Path, locations: tuple[str, ...]) -> None:
    """Store location tags on an already-created *output* file.

    The image data and the existing EXIF block (including GPS) are preserved.
    """
    if not locations:
        return
    _register_heif_support()
    summary = f"{_LOCATION_TAG}: {', '.join(locations)}"

    with Image.open(path) as image:
        exif = image.getexif()
        exif_ifd = _sub_ifd(exif, TAG_EXIF_IFD)

        existing_comment = _decode(exif_ifd.get(TAG_USER_COMMENT)) or ""
        if summary not in existing_comment:
            exif_ifd[TAG_USER_COMMENT] = (
                f"{existing_comment} | {summary}" if existing_comment else summary
            )

        if not _decode(_safe_get(exif, TAG_IMAGE_DESCRIPTION)):
            exif[TAG_IMAGE_DESCRIPTION] = summary

        image.save(path, exif=exif, format=image.format)