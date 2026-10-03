"""Tests for the output naming rules."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from media_organizer.naming import (
    COLLISION_START,
    FIRST_SEQUENCE,
    SEQUENCE_WIDTH,
    normalise_extension,
    split_sequence,
    target_dir,
    target_filename,
    timestamp_prefix,
)

TAKEN = datetime(2024, 7, 14, 16, 32, 18)


class NamingTests(unittest.TestCase):
    def test_target_dir_matches_documented_structure(self) -> None:
        self.assertEqual(
            target_dir(Path("output"), TAKEN),
            Path("output") / "2024" / "2024_07",
        )

    def test_target_filename_without_sequence(self) -> None:
        self.assertEqual(target_filename(TAKEN, None, ".jpg"), "20240714_163218.jpg")
        self.assertEqual(target_filename(TAKEN, None, "JPG"), "20240714_163218.jpg")

    def test_target_filename_with_sequence(self) -> None:
        self.assertEqual(target_filename(TAKEN, 1, ".jpg"), "20240714_163218_01.jpg")
        self.assertEqual(target_filename(TAKEN, 42, ".JPEG"), "20240714_163218_42.jpeg")

    def test_the_first_file_is_number_one_and_a_collision_starts_at_two(self) -> None:
        self.assertEqual(FIRST_SEQUENCE, 1)
        self.assertEqual(COLLISION_START, 2)
        self.assertEqual(target_filename(TAKEN, FIRST_SEQUENCE, ".jpg"), "20240714_163218_01.jpg")
        self.assertEqual(target_filename(TAKEN, COLLISION_START, ".jpg"), "20240714_163218_02.jpg")

    def test_the_counter_uses_exactly_two_digits(self) -> None:
        self.assertEqual(SEQUENCE_WIDTH, 2)
        self.assertEqual(target_filename(TAKEN, 2, ".jpg"), "20240714_163218_02.jpg")
        self.assertEqual(target_filename(TAKEN, 9, ".jpg"), "20240714_163218_09.jpg")
        self.assertEqual(target_filename(TAKEN, 99, ".jpg"), "20240714_163218_99.jpg")

    def test_the_counter_keeps_growing_past_two_digits(self) -> None:
        # 100+ duplicates must not produce a name that collides with the
        # two-digit range again.
        self.assertEqual(target_filename(TAKEN, 100, ".jpg"), "20240714_163218_100.jpg")

    def test_month_is_zero_padded(self) -> None:
        taken = datetime(2023, 8, 21, 10, 45, 32)

        self.assertEqual(target_dir(Path("output"), taken), Path("output/2023/2023_08"))
        self.assertEqual(target_filename(taken, None, ".jpg"), "20230821_104532.jpg")
        self.assertEqual(target_filename(taken, 1, ".jpg"), "20230821_104532_01.jpg")

    def test_extension_normalisation(self) -> None:
        self.assertEqual(normalise_extension("JPG"), ".jpg")
        self.assertEqual(normalise_extension(".JPEG"), ".jpeg")
        self.assertEqual(normalise_extension(" png "), ".png")

    def test_timestamp_prefix(self) -> None:
        self.assertEqual(timestamp_prefix(TAKEN), "20240714_163218")


class SplitSequenceTests(unittest.TestCase):
    def test_numbered_name_is_split(self) -> None:
        self.assertEqual(split_sequence("20240714_163218_01"), ("20240714_163218", 1))
        self.assertEqual(split_sequence("20240714_163218_42"), ("20240714_163218", 42))

    def test_counter_grows_beyond_the_minimum_width(self) -> None:
        # The formatter pads to SEQUENCE_WIDTH digits but never truncates, so
        # names above _99 must still parse back.
        stem = target_filename(TAKEN, 100, ".jpg")
        self.assertEqual(stem, "20240714_163218_100.jpg")
        self.assertEqual(split_sequence(Path(stem).stem), ("20240714_163218", 100))

    def test_bare_timestamp_has_no_sequence(self) -> None:
        # The 6 digit time must not be mistaken for a counter.
        self.assertEqual(split_sequence("20240714_163218"), ("20240714_163218", None))

    def test_only_planner_names_are_parsed(self) -> None:
        self.assertEqual(split_sequence("holiday"), ("holiday", None))
        self.assertEqual(split_sequence("holiday_final"), ("holiday_final", None))
        self.assertEqual(split_sequence("holiday_02"), ("holiday_02", None))
        self.assertEqual(split_sequence("a_01_02"), ("a_01_02", None))


if __name__ == "__main__":
    unittest.main()