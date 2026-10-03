"""Tests for EXIF reading and for writing tags onto output copies."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

from media_organizer.metadata import (
    read_metadata,
    read_video_creation_time,
    read_video_metadata,
    write_location_tags,
)
from media_organizer.models import DateSource, MediaKind
from tests.support import make_photo, make_video


class ReadMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_exif_capture_date(self) -> None:
        path = make_photo(
            self.root / "photo.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18)
        )

        metadata = read_metadata(path, MediaKind.PHOTO)

        self.assertEqual(metadata.taken_at, datetime(2024, 7, 14, 16, 32, 18))
        self.assertIs(metadata.date_source, DateSource.EXIF)

    def test_falls_back_to_file_timestamp_without_exif(self) -> None:
        path = make_photo(self.root / "photo.jpg")

        metadata = read_metadata(path, MediaKind.PHOTO)

        self.assertIs(metadata.date_source, DateSource.FILESYSTEM)
        self.assertIsNone(metadata.warning)

    def test_reports_unreadable_metadata(self) -> None:
        path = self.root / "broken.jpg"
        path.write_bytes(b"this is not an image")

        metadata = read_metadata(path, MediaKind.PHOTO)

        self.assertIs(metadata.date_source, DateSource.FILESYSTEM)
        self.assertIn("unreadable", metadata.warning)
        self.assertFalse(metadata.has_gps)

    def test_reads_signed_gps(self) -> None:
        path = make_photo(self.root / "photo.jpg", gps=(52.5200, 13.4050))
        metadata = read_metadata(path, MediaKind.PHOTO)
        self.assertAlmostEqual(metadata.latitude, 52.5200, places=3)
        self.assertAlmostEqual(metadata.longitude, 13.4050, places=3)

        south_west = make_photo(self.root / "sw.jpg", gps=(-33.8688, -70.6693))
        metadata = read_metadata(south_west, MediaKind.PHOTO)
        self.assertAlmostEqual(metadata.latitude, -33.8688, places=3)
        self.assertAlmostEqual(metadata.longitude, -70.6693, places=3)

    def test_ignores_zero_exif_dates(self) -> None:
        path = make_photo(self.root / "photo.jpg")

        with Image.open(path) as image:
            exif = image.getexif()
            exif.get_ifd(0x8769)[0x9003] = "0000:00:00 00:00:00"
            image.save(path, exif=exif, format=image.format)

        metadata = read_metadata(path, MediaKind.PHOTO)

        self.assertIs(metadata.date_source, DateSource.FILESYSTEM)


class ReadVideoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_the_recording_time_from_the_container(self) -> None:
        path = make_video(self.root / "clip.mp4", taken_at=datetime(2024, 7, 14, 16, 32, 18))

        metadata = read_metadata(path, MediaKind.VIDEO)

        self.assertEqual(metadata.taken_at, datetime(2024, 7, 14, 16, 32, 18))
        self.assertIs(metadata.date_source, DateSource.CONTAINER)
        self.assertFalse(metadata.has_gps)

    def test_works_for_mov_and_m4v_too(self) -> None:
        for index, extension in enumerate((".mov", ".m4v", ".3gp")):
            path = make_video(
                self.root / f"clip{index}{extension}",
                taken_at=datetime(2024, 1, 2, 3, 4, 5),
            )
            self.assertEqual(read_video_creation_time(path), datetime(2024, 1, 2, 3, 4, 5))

    def test_falls_back_to_the_file_timestamp(self) -> None:
        path = make_video(self.root / "clip.mp4")
        metadata = read_video_metadata(path)

        self.assertIs(metadata.date_source, DateSource.FILESYSTEM)
        self.assertEqual(
            metadata.taken_at, datetime.fromtimestamp(path.stat().st_mtime)
        )

    def test_truncated_container_does_not_raise(self) -> None:
        path = self.root / "broken.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x08free")

        self.assertIsNone(read_video_creation_time(path))

    def test_zero_creation_time_is_ignored(self) -> None:
        path = make_video(self.root / "clip.mp4", taken_at=None)
        metadata = read_video_metadata(path)

        self.assertIs(metadata.date_source, DateSource.FILESYSTEM)

    def test_reads_the_64_bit_mvhd_variant(self) -> None:
        path = make_video(
            self.root / "clip.mp4",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            mvhd_version=1,
        )

        self.assertEqual(
            read_video_creation_time(path), datetime(2024, 7, 14, 16, 32, 18)
        )

    def test_a_box_before_moov_does_not_hide_the_date(self) -> None:
        # Real cameras put the movie data in an mdat box before moov, so the
        # parser has to keep walking instead of giving up.
        path = make_video(
            self.root / "clip.mp4",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            leading_mdat=b"x" * 5000,
        )

        self.assertEqual(
            read_video_creation_time(path), datetime(2024, 7, 14, 16, 32, 18)
        )

    def test_a_file_without_a_moov_box_returns_none(self) -> None:
        path = self.root / "clip.mp4"
        path.write_bytes(b"\x00\x00\x00\x10ftypisom" + b"\x00" * 8)

        self.assertIsNone(read_video_creation_time(path))


class WriteLocationTagsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_tags_and_keeps_date_and_gps(self) -> None:
        path = make_photo(
            self.root / "photo.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            gps=(52.5200, 13.4050),
        )

        write_location_tags(path, ("Berlin", "Germany"))
        metadata = read_metadata(path, MediaKind.PHOTO)

        self.assertEqual(metadata.taken_at, datetime(2024, 7, 14, 16, 32, 18))
        self.assertAlmostEqual(metadata.latitude, 52.5200, places=3)

        with Image.open(path) as image:
            self.assertEqual(image.getexif().get(0x010E), "Location: Berlin, Germany")

    def test_without_locations_nothing_is_written(self) -> None:
        path = make_photo(self.root / "photo.jpg", gps=(52.5200, 13.4050))
        before = path.read_bytes()

        write_location_tags(path, ())

        self.assertEqual(path.read_bytes(), before)

    def test_image_data_survives(self) -> None:
        path = make_photo(self.root / "photo.jpg", colour="tomato")
        with Image.open(path) as image:
            before = image.tobytes()

        write_location_tags(path, ("Berlin", "Germany"))

        with Image.open(path) as image:
            self.assertEqual(image.tobytes(), before)


if __name__ == "__main__":
    unittest.main()