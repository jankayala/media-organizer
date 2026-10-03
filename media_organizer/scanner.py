"""Read-only discovery of photos and videos below an input folder."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator

from media_organizer.config import VIDEO_EXTENSIONS
from media_organizer.models import MediaFile, MediaKind


def _normalise(extensions: Iterable[str]) -> frozenset[str]:
    """Lower-case the extension set and make sure every entry has a dot."""
    result = set()
    for raw in extensions:
        ext = raw.strip().lower()
        if not ext:
            continue
        result.add(ext if ext.startswith(".") else f".{ext}")
    return frozenset(result)


def classify(extension: str, video_extensions: frozenset[str]) -> MediaKind:
    """Decide whether an extension belongs to a photo or to a video."""
    return MediaKind.VIDEO if extension.lower() in video_extensions else MediaKind.PHOTO


def _is_excluded(path: Path, excluded: tuple[Path, ...]) -> bool:
    resolved = _safe_resolve(path)
    for candidate in excluded:
        if resolved == candidate or resolved.is_relative_to(candidate):
            return True
    return False


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def iter_media_files(
    root: Path,
    extensions: Iterable[str],
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
    excluded_dirs: Iterable[Path] = (),
) -> Iterator[MediaFile]:
    """Yield every photo and video below ``root`` in a stable, sorted order."""
    exts = _normalise(extensions)
    videos = frozenset(VIDEO_EXTENSIONS)
    excluded = tuple(_safe_resolve(Path(item)) for item in excluded_dirs)
    root = Path(root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)

        kept = []
        for name in sorted(dirnames):
            child = current / name
            if skip_hidden and name.startswith("."):
                continue
            if _is_excluded(child, excluded):
                continue
            if not recursive:
                break
            kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            if skip_hidden and name.startswith("."):
                continue
            path = current / name
            extension = path.suffix.lower()
            if extension not in exts:
                continue
            try:
                if not path.is_file():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            yield MediaFile(
                path=path,
                relative_path=path.relative_to(root),
                size=size,
                kind=classify(extension, videos),
            )


def scan_media(
    root: Path,
    extensions: Iterable[str],
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
    excluded_dirs: Iterable[Path] = (),
    limit: int | None = None,
) -> list[MediaFile]:
    """Collect photos and videos below ``root``, optionally capped at ``limit``."""
    found: list[MediaFile] = []
    for media in iter_media_files(
        root,
        extensions,
        recursive=recursive,
        skip_hidden=skip_hidden,
        excluded_dirs=excluded_dirs,
    ):
        found.append(media)
        if limit is not None and len(found) >= limit:
            break
    return found