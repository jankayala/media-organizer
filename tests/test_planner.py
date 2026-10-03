"""Tests for plan construction: paths, sequence numbers and conflicts."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from media_organizer.config import Config, ConflictPolicy, GeocoderMode
from media_organizer.errors import OrganizerError
from media_organizer.models import DateSource, MediaKind
from media_organizer.planner import SlotAllocator, build_plan
from tests.support import make_photo, make_video


class SlotAllocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.taken = datetime(2024, 7, 14, 16, 32, 18)

    def test_photo_without_conflict_gets_a_plain_name(self) -> None:
        allocator = SlotAllocator(self.root / "output")

        slot = allocator.allocate(self.taken, ".jpg")

        self.assertEqual(
            slot.target, self.root / "output" / "2024" / "2024_07" / "20240714_163218.jpg"
        )
        self.assertFalse(slot.numbered)
        self.assertFalse(slot.conflict_renamed)
        self.assertFalse(slot.already_present)

    def test_duplicates_start_at_02(self) -> None:
        allocator = SlotAllocator(self.root / "output")

        targets = [
            allocator.allocate(self.taken, ".jpg", position=position).target.name
            for position in (1, 2, 3)
        ]

        self.assertEqual(
            targets,
            [
                "20240714_163218.jpg",
                "20240714_163218_02.jpg",
                "20240714_163218_03.jpg",
            ],
        )

    def test_only_the_duplicates_are_numbered(self) -> None:
        allocator = SlotAllocator(self.root / "output")

        first = allocator.allocate(self.taken, ".jpg", position=1)
        second = allocator.allocate(self.taken, ".jpg", position=2)

        self.assertEqual(first.target.name, "20240714_163218.jpg")
        self.assertEqual(second.target.name, "20240714_163218_02.jpg")
        self.assertTrue(second.numbered)
        self.assertFalse(second.conflict_renamed)

    def test_different_timestamps_both_stay_plain(self) -> None:
        allocator = SlotAllocator(self.root / "output")

        first = allocator.allocate(datetime(2024, 7, 14, 16, 32, 18), ".jpg")
        second = allocator.allocate(datetime(2024, 7, 14, 16, 32, 19), ".jpg")

        self.assertEqual(first.target.name, "20240714_163218.jpg")
        self.assertEqual(second.target.name, "20240714_163219.jpg")

    def test_same_timestamp_different_extension_stays_plain(self) -> None:
        allocator = SlotAllocator(self.root / "output")

        jpeg = allocator.allocate(self.taken, ".jpg")
        png = allocator.allocate(self.taken, ".png")

        self.assertEqual(jpeg.target.name, "20240714_163218.jpg")
        self.assertEqual(png.target.name, "20240714_163218.png")

    def test_existing_file_on_disk_forces_the_numbered_form(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218.jpg").write_bytes(b"existing")
        allocator = SlotAllocator(self.root / "output")

        slot = allocator.allocate(self.taken, ".jpg")

        self.assertEqual(slot.target.name, "20240714_163218_02.jpg")
        self.assertTrue(slot.numbered)
        self.assertTrue(slot.conflict_renamed)

    def test_existing_number_is_bumped(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218_02.jpg").write_bytes(b"existing")
        allocator = SlotAllocator(self.root / "output")

        slot = allocator.allocate(self.taken, ".jpg", position=2)

        self.assertEqual(slot.target.name, "20240714_163218_03.jpg")
        self.assertTrue(slot.conflict_renamed)

    def test_byte_identical_file_is_reused_instead_of_duplicated(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218.jpg").write_bytes(b"payload")
        allocator = SlotAllocator(self.root / "output")

        slot = allocator.allocate(
            self.taken, ".jpg", identical_to=lambda path: path.read_bytes() == b"payload"
        )

        self.assertEqual(slot.target.name, "20240714_163218.jpg")
        self.assertFalse(slot.numbered)
        self.assertTrue(slot.already_present)

    def test_identical_numbered_file_is_reused(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218_02.jpg").write_bytes(b"payload")
        allocator = SlotAllocator(self.root / "output")

        slot = allocator.allocate(
            self.taken,
            ".jpg",
            position=2,
            identical_to=lambda path: path.read_bytes() == b"payload",
        )

        self.assertEqual(slot.target.name, "20240714_163218_02.jpg")
        self.assertTrue(slot.already_present)

    def test_skip_policy_reports_no_free_target(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218.jpg").write_bytes(b"existing")
        allocator = SlotAllocator(self.root / "output", ConflictPolicy.SKIP)

        slot = allocator.allocate(self.taken, ".jpg")

        self.assertIsNone(slot.target)
        self.assertTrue(slot.skipped)

    def test_skip_policy_also_applies_to_the_numbered_form(self) -> None:
        target_dir = self.root / "output" / "2024" / "2024_07"
        target_dir.mkdir(parents=True)
        (target_dir / "20240714_163218_02.jpg").write_bytes(b"existing")
        allocator = SlotAllocator(self.root / "output", ConflictPolicy.SKIP)

        slot = allocator.allocate(self.taken, ".jpg", position=2)

        self.assertTrue(slot.skipped)


class BuildPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.input = self.base / "My Photos"
        self.output = self.base / "output"

    def config(self, **overrides) -> Config:
        defaults = dict(
            input_dir=self.input,
            output_dir=self.output,
            geocoder=GeocoderMode.OFFLINE,
        )
        defaults.update(overrides)
        return Config(**defaults)

    def test_builds_the_documented_output_structure(self) -> None:
        make_photo(
            self.input / "IMG_4821.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            gps=(52.5200, 13.4050),
        )
        make_photo(
            self.input / "IMG_4822.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 19),
            gps=(52.5200, 13.4050),
        )
        make_photo(
            self.input / "vacation" / "DSC_1093.jpg",
            taken_at=datetime(2023, 8, 21, 10, 45, 32),
        )

        plan = build_plan(self.config())

        self.assertEqual(
            [
                (item.source.display, item.target.relative_to(self.output).as_posix())
                for item in plan.items
            ],
            [
                ("IMG_4821.jpg", "2024/2024_07/20240714_163218.jpg"),
                ("IMG_4822.jpg", "2024/2024_07/20240714_163219.jpg"),
                ("vacation/DSC_1093.jpg", "2023/2023_08/20230821_104532.jpg"),
            ],
        )

    def test_the_first_of_a_timestamp_group_stays_plain(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_photo(self.input / "b.jpg", taken_at=taken)
        make_photo(self.input / "c.jpg", taken_at=taken)

        plan = build_plan(self.config())

        self.assertEqual(
            [item.target.name for item in plan.items],
            [
                "20240714_163218.jpg",
                "20240714_163218_02.jpg",
                "20240714_163218_03.jpg",
            ],
        )

    def test_same_timestamp_with_other_extensions_stays_plain(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        # Pillow cannot store EXIF in a PNG, so the file timestamp is used.
        png = make_photo(self.input / "b.png", image_format="PNG")
        stamp = taken.timestamp()
        os.utime(png, (stamp, stamp))

        plan = build_plan(self.config())

        self.assertEqual(
            [item.target.name for item in plan.items],
            ["20240714_163218.jpg", "20240714_163218.png"],
        )

    def test_keeps_original_extension_and_lowercases_it(self) -> None:
        make_photo(
            self.input / "SHOUT.JPG",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            image_format="JPEG",
        )

        plan = build_plan(self.config())

        self.assertEqual(plan.items[0].target.name, "20240714_163218.jpg")

    def test_attaches_location_tags_from_gps(self) -> None:
        make_photo(
            self.input / "berlin.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            gps=(52.5200, 13.4050),
        )
        make_photo(
            self.input / "nowhere.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 19),
            gps=(0.0, -30.0),
        )
        make_photo(self.input / "no_gps.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 20))

        plan = build_plan(self.config())

        tags = {item.source.display: item.metadata.locations for item in plan.items}
        self.assertEqual(tags["berlin.jpg"], ("Berlin", "Germany"))
        self.assertEqual(tags["nowhere.jpg"], ())
        self.assertEqual(tags["no_gps.jpg"], ())

    def test_geocoder_none_disables_location_tags(self) -> None:
        make_photo(
            self.input / "berlin.jpg",
            taken_at=datetime(2024, 7, 14, 16, 32, 18),
            gps=(52.5200, 13.4050),
        )

        plan = build_plan(self.config(geocoder=GeocoderMode.NONE))

        self.assertEqual(plan.items[0].metadata.locations, ())

    def test_extension_filtering(self) -> None:
        make_photo(self.input / "keep.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_photo(
            self.input / "skip.png",
            taken_at=datetime(2024, 7, 14, 16, 32, 19),
            image_format="PNG",
        )

        plan = build_plan(self.config(extensions=(".jpg",)))

        self.assertEqual([item.source.display for item in plan.items], ["keep.jpg"])

    def test_skip_policy_moves_media_to_skipped_list(self) -> None:
        make_photo(self.input / "photo.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        existing = self.output / "2024" / "2024_07"
        existing.mkdir(parents=True)
        (existing / "20240714_163218.jpg").write_bytes(b"existing")

        plan = build_plan(self.config(conflict_policy=ConflictPolicy.SKIP))

        self.assertEqual(plan.items, [])
        self.assertEqual(len(plan.skipped), 1)
        self.assertEqual((existing / "20240714_163218.jpg").read_bytes(), b"existing")

    def test_nested_output_folder_is_never_scanned(self) -> None:
        make_photo(self.input / "photo.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_photo(
            self.input / "output" / "2024" / "2024_07" / "old.jpg",
            taken_at=datetime(2020, 1, 1, 0, 0, 0),
        )

        plan = build_plan(self.config(output_dir=self.input / "output"))

        self.assertEqual([item.source.display for item in plan.items], ["photo.jpg"])

    def test_missing_input_folder_is_reported(self) -> None:
        with self.assertRaises(OrganizerError):
            build_plan(self.config(input_dir=self.base / "does-not-exist"))

    def test_output_equal_to_input_is_rejected(self) -> None:
        make_photo(self.input / "photo.jpg")

        with self.assertRaises(OrganizerError):
            build_plan(self.config(output_dir=self.input))

    def test_filesystem_dates_are_marked_as_such(self) -> None:
        make_photo(self.input / "photo.jpg")

        plan = build_plan(self.config())

        self.assertIs(plan.items[0].metadata.date_source, DateSource.FILESYSTEM)


class VideoPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.input = self.base / "input"
        self.output = self.base / "output"

    def config(self, **overrides) -> Config:
        defaults = dict(input_dir=self.input, output_dir=self.output)
        defaults.update(overrides)
        return Config(**defaults)

    def test_video_date_comes_from_the_container(self) -> None:
        make_video(self.input / "clip.mp4", taken_at=datetime(2024, 7, 14, 16, 32, 18))

        plan = build_plan(self.config())

        self.assertEqual(plan.items[0].target.name, "20240714_163218.mp4")
        self.assertIs(plan.items[0].metadata.date_source, DateSource.CONTAINER)
        self.assertIs(plan.items[0].kind, MediaKind.VIDEO)

    def test_video_without_creation_time_uses_the_file_timestamp(self) -> None:
        taken = datetime(2023, 3, 3, 9, 15, 0)
        clip = make_video(self.input / "clip.mov")
        stamp = taken.timestamp()
        os.utime(clip, (stamp, stamp))

        plan = build_plan(self.config())

        self.assertEqual(plan.items[0].target.name, "20230303_091500.mov")
        self.assertIs(plan.items[0].metadata.date_source, DateSource.FILESYSTEM)

    def test_photo_and_video_share_the_timestamp_namespace(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_video(self.input / "b.mp4", taken_at=taken)

        plan = build_plan(self.config())

        self.assertEqual(
            [item.target.name for item in plan.items],
            ["20240714_163218.jpg", "20240714_163218.mp4"],
        )

    def test_counts_photos_and_videos_separately(self) -> None:
        make_photo(self.input / "a.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_video(self.input / "b.mp4", taken_at=datetime(2024, 7, 14, 16, 32, 19))
        make_video(self.input / "c.mkv", taken_at=datetime(2024, 7, 14, 16, 32, 20))

        plan = build_plan(self.config())

        self.assertEqual(plan.of_kind(MediaKind.PHOTO), 1)
        self.assertEqual(plan.of_kind(MediaKind.VIDEO), 2)
        self.assertEqual(plan.total_count, 3)

    def test_two_videos_with_the_same_timestamp_are_numbered_from_02(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_video(self.input / "a.mp4", taken_at=taken)
        make_video(self.input / "b.mp4", taken_at=taken)

        plan = build_plan(self.config())

        self.assertEqual(
            [item.target.name for item in plan.items],
            ["20240714_163218.mp4", "20240714_163218_02.mp4"],
        )


if __name__ == "__main__":
    unittest.main()