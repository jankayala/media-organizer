"""Tests for recursive photo and video discovery."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from media_organizer.config import DEFAULT_EXTENSIONS
from media_organizer.models import MediaKind
from media_organizer.scanner import scan_media
from tests.support import make_photo, make_video


class ScanMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_finds_media_recursively_in_sorted_order(self) -> None:
        make_photo(self.root / "IMG_4822.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 19))
        make_photo(self.root / "IMG_4821.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_photo(
            self.root / "vacation" / "DSC_1093.jpg", taken_at=datetime(2023, 8, 21, 10, 45, 32)
        )

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual(
            [item.relative_path.as_posix() for item in found],
            ["IMG_4821.jpg", "IMG_4822.jpg", "vacation/DSC_1093.jpg"],
        )
        self.assertTrue(all(item.size > 0 for item in found))

    def test_finds_videos_and_labels_the_kind(self) -> None:
        make_video(self.root / "clip.mp4")
        make_photo(self.root / "photo.jpg")
        (self.root / "notes.txt").write_text("x", encoding="utf-8")

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual(
            [(item.relative_path.as_posix(), item.kind) for item in found],
            [("clip.mp4", MediaKind.VIDEO), ("photo.jpg", MediaKind.PHOTO)],
        )

    def test_recognises_raw_photo_extensions(self) -> None:
        make_photo(self.root / "IMG_0001.CR3")
        make_photo(self.root / "IMG_0002.NEF")
        make_photo(self.root / "scan.tiff")

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual(
            [item.relative_path.as_posix() for item in found],
            ["IMG_0001.CR3", "IMG_0002.NEF", "scan.tiff"],
        )
        self.assertTrue(all(item.kind is MediaKind.PHOTO for item in found))

    def test_extension_filter_can_limit_the_run(self) -> None:
        make_video(self.root / "clip.mp4")
        make_photo(self.root / "photo.jpg")

        found = scan_media(self.root, (".mp4",))

        self.assertEqual([item.relative_path.as_posix() for item in found], ["clip.mp4"])

    def test_ignores_unsupported_files(self) -> None:
        make_photo(self.root / "photo.jpg")
        for name in ("notes.txt", "raw.xmp", "archive.zip", "song.mp3"):
            (self.root / name).write_text("not media", encoding="utf-8")

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual([item.relative_path.as_posix() for item in found], ["photo.jpg"])

    def test_matches_extension_case_insensitively(self) -> None:
        make_photo(self.root / "SHOUT.JPG")
        make_video(self.root / "MOVIE.MP4")

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual(
            [item.relative_path.as_posix() for item in found],
            ["MOVIE.MP4", "SHOUT.JPG"],
        )

    def test_non_recursive_stays_in_top_folder(self) -> None:
        make_photo(self.root / "top.jpg")
        make_photo(self.root / "sub" / "deep.jpg")

        found = scan_media(self.root, DEFAULT_EXTENSIONS, recursive=False)

        self.assertEqual([item.relative_path.as_posix() for item in found], ["top.jpg"])

    def test_skips_hidden_folders(self) -> None:
        make_photo(self.root / "visible.jpg")
        make_photo(self.root / ".thumbnails" / "cache.jpg")

        found = scan_media(self.root, DEFAULT_EXTENSIONS)

        self.assertEqual([item.relative_path.as_posix() for item in found], ["visible.jpg"])

    def test_skips_the_output_folder_when_nested_in_input(self) -> None:
        output = self.root / "output"
        make_photo(self.root / "photo.jpg")
        make_photo(output / "2024" / "2024_07" / "already.jpg")

        found = scan_media(self.root, DEFAULT_EXTENSIONS, excluded_dirs=[output])

        self.assertEqual([item.relative_path.as_posix() for item in found], ["photo.jpg"])

    def test_limit_stops_the_scan(self) -> None:
        for index in range(5):
            make_photo(self.root / f"photo_{index}.jpg")

        found = scan_media(self.root, DEFAULT_EXTENSIONS, limit=2)

        self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()