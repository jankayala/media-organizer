"""Helpers for building synthetic photo and video folders in tests."""

from __future__ import annotations

import hashlib
import struct
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825

#: Seconds between the ISOBMFF epoch (1904-01-01) and the Unix epoch.
_ISOBMFF_EPOCH_OFFSET = 2_082_844_800


def make_photo(
    path: Path,
    *,
    taken_at: datetime | None = None,
    gps: tuple[float, float] | None = None,
    image_format: str = "JPEG",
    size: tuple[int, int] = (16, 12),
    colour: str = "steelblue",
    create_parents: bool = True,
) -> Path:
    """Write a small image, optionally with EXIF date and GPS."""
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", size, colour)
    exif = image.getexif()

    if taken_at is not None:
        exif.get_ifd(_EXIF_IFD)[0x9003] = taken_at.strftime("%Y:%m:%d %H:%M:%S")

    if gps is not None:
        latitude, longitude = gps
        gps_ifd = exif.get_ifd(_GPS_IFD)
        gps_ifd[1] = "N" if latitude >= 0 else "S"
        gps_ifd[2] = _dms_rationals(latitude)
        gps_ifd[3] = "E" if longitude >= 0 else "W"
        gps_ifd[4] = _dms_rationals(longitude)

    image.save(path, exif=exif, format=image_format)
    image.close()
    return path


def make_video(
    path: Path,
    *,
    taken_at: datetime | None = None,
    create_parents: bool = True,
    payload: bytes = b"fake-video-data",
    mvhd_version: int = 0,
    leading_mdat: bytes = b"",
) -> Path:
    """Write a minimal ISOBMFF file with a recording time in ``mvhd``.

    Only the boxes the reader needs are emitted, which keeps the fixture small
    while still exercising the real container parsing code.
    """
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    seconds = int(taken_at.timestamp()) + _ISOBMFF_EPOCH_OFFSET if taken_at else 0

    if mvhd_version == 1:
        # version(1) + flags(3) + creation(8) + modification(8) + timescale(4)
        mvhd_body = struct.pack(">B3sQQI", 1, b"\x00\x00\x00", seconds, seconds, 1000)
    else:
        # version(1) + flags(3) + creation(4) + modification(4) + timescale(4)
        mvhd_body = struct.pack(">B3sIIII", 0, b"\x00\x00\x00", seconds, seconds, 1000, 0)
    mvhd_body += struct.pack(">i", 0x00010000)  # rate
    mvhd_body += struct.pack(">h", 0x0100)  # volume
    mvhd_body += b"\x00" * 10  # reserved
    mvhd_body += struct.pack(
        ">9i",
        0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000,
    )  # unity matrix
    mvhd_body += b"\x00" * 24  # pre_defined
    mvhd_body += struct.pack(">I", 2)  # next track id
    mvhd = _box(b"mvhd", mvhd_body)

    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2")
    free = _box(b"free", b"")
    parts = [ftyp, free]
    if leading_mdat:
        # Real cameras write the whole movie data before the moov box.
        parts.append(_box(b"mdat", leading_mdat))
    parts.append(_box(b"moov", mvhd))
    path.write_bytes(b"".join(parts) + payload)
    return path


def _box(box_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + box_type + body


def _dms_rationals(value: float, scale: int = 1000) -> tuple[IFDRational, ...]:
    """Encode decimal degrees as the EXIF ``(degrees, minutes, seconds)`` tuple."""
    value = abs(value)
    degrees = int(value)
    minutes_decimal = (value - degrees) * 60.0
    minutes = int(minutes_decimal)
    seconds = (minutes_decimal - minutes) * 60.0
    return (
        IFDRational(degrees, 1),
        IFDRational(minutes, 1),
        IFDRational(round(seconds * scale), scale),
    )


def snapshot(root: Path, ignore_names: frozenset[str] = frozenset()) -> dict[str, tuple[int, float, str]]:
    """Map every file below ``root`` to (size, mtime, sha256).

    ``ignore_names`` skips the run summary, whose text and timestamp change on
    every run by design.
    """
    result: dict[str, tuple[int, float, str]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.name in ignore_names:
            continue
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime, digest)
    return result


#: The summary is rewritten on every run, so snapshots ignore it.
MEDIA_SNAPSHOT_IGNORE = frozenset({"summary.txt", "report.txt"})


def tree(root: Path) -> list[str]:
    """Sorted list of relative paths below ``root``."""
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))