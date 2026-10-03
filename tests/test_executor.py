"""Unit tests for the executor internals."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_organizer.executor import _free_target


class FreeTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, name: str) -> Path:
        path = self.root / name
        path.write_bytes(b"x")
        return path

    def test_missing_target_is_returned_unchanged(self) -> None:
        self.assertEqual(
            _free_target(self.root / "20240714_163218_02.jpg"),
            self.root / "20240714_163218_02.jpg",
        )

    def test_bumps_the_sequence_number(self) -> None:
        self.touch("20240714_163218_02.jpg")

        self.assertEqual(
            _free_target(self.root / "20240714_163218_02.jpg").name,
            "20240714_163218_03.jpg",
        )

    def test_skips_over_every_taken_name(self) -> None:
        for name in ("20240714_163218_02.jpg", "20240714_163218_03.jpg"):
            self.touch(name)

        self.assertEqual(
            _free_target(self.root / "20240714_163218_02.jpg").name,
            "20240714_163218_04.jpg",
        )

    def test_name_without_a_sequence_gets_one(self) -> None:
        self.touch("holiday.jpg")

        self.assertEqual(
            _free_target(self.root / "holiday.jpg").name, "holiday_02.jpg"
        )

    def test_bare_timestamp_gains_a_counter(self) -> None:
        # The 6 digit time must not be treated as an existing counter.
        self.touch("20240714_163218.jpg")

        self.assertEqual(
            _free_target(self.root / "20240714_163218.jpg").name,
            "20240714_163218_02.jpg",
        )

    def test_bare_timestamp_and_counter_coexist(self) -> None:
        self.touch("20240714_163218.jpg")
        self.touch("20240714_163218_02.jpg")

        self.assertEqual(
            _free_target(self.root / "20240714_163218.jpg").name,
            "20240714_163218_03.jpg",
        )

    def test_extension_is_preserved(self) -> None:
        self.touch("20240714_163218_01.png")

        self.assertEqual(
            _free_target(self.root / "20240714_163218_01.png").name,
            "20240714_163218_02.png",
        )


if __name__ == "__main__":
    unittest.main()