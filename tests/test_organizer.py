"""End-to-end tests: a run must organise the collection and never touch input."""

from __future__ import annotations

import io
import contextlib
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

from media_organizer.cli import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from media_organizer.config import Config
from media_organizer.executor import execute_plan
from media_organizer.planner import build_plan
from tests.support import MEDIA_SNAPSHOT_IGNORE, make_photo, make_video, snapshot, tree

BERLIN = (52.5200, 13.4050)


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _section(summary: str, heading: str) -> str:
    """The body of one ``heading`` section of the summary."""
    marker = f"\n{heading}\n{'=' * 60}\n"
    start = summary.index(marker) + len(marker)
    end = summary.find("\n\n", start)
    return summary[start:] if end == -1 else summary[start:end]


class OrganizerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.input = self.base / "My Photos"
        self.output = self.base / "output"

    def make_collection(self) -> None:
        make_photo(
            self.input / "IMG_4821.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18), gps=BERLIN
        )
        make_photo(
            self.input / "IMG_4822.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 19), gps=BERLIN
        )
        make_photo(
            self.input / "vacation" / "DSC_1093.jpg", taken_at=datetime(2023, 8, 21, 10, 45, 32)
        )

    def config(self, **overrides) -> Config:
        defaults = dict(input_dir=self.input, output_dir=self.output)
        defaults.update(overrides)
        return Config(**defaults)

    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
            code = main(list(argv))
        return code, buffer.getvalue()

    def summary_text(self) -> str:
        return (self.output / "summary.txt").read_text(encoding="utf-8")


class RunTests(OrganizerTestCase):
    def test_run_copies_and_leaves_input_untouched(self) -> None:
        self.make_collection()
        input_before = snapshot(self.input)

        code, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(snapshot(self.input), input_before)
        self.assertEqual(
            tree(self.output),
            [
                "2023",
                "2023/2023_08",
                "2023/2023_08/20230821_104532.jpg",
                "2024",
                "2024/2024_07",
                "2024/2024_07/20240714_163218.jpg",
                "2024/2024_07/20240714_163219.jpg",
                "summary.txt",
            ],
        )
        self.assertIn("The input folder was not modified.", output)

    def test_report_matches_the_documented_layout(self) -> None:
        self.make_collection()

        _, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertIn("Found 3 photos.", output)
        self.assertIn("IMG_4821.jpg", output)
        self.assertIn("2024/2024_07/20240714_163218.jpg", output)
        self.assertIn("vacation/DSC_1093.jpg", output)
        self.assertIn("2023/2023_08/20230821_104532.jpg", output)
        self.assertIn("Location tags:", output)
        self.assertIn("+ Berlin", output)
        self.assertIn("+ Germany", output)

    def test_copied_bytes_are_identical_to_the_source(self) -> None:
        self.make_collection()
        self.run_cli(str(self.input), "-o", str(self.output))

        original = (self.input / "IMG_4821.jpg").read_bytes()
        copy = (self.output / "2024" / "2024_07" / "20240714_163218.jpg").read_bytes()

        self.assertEqual(copy, original)

    def test_existing_output_file_is_never_overwritten(self) -> None:
        self.make_collection()
        target = self.output / "2024" / "2024_07" / "20240714_163218.jpg"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"precious")

        code, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(target.read_bytes(), b"precious")
        self.assertTrue((target.parent / "20240714_163218_02.jpg").exists())
        self.assertIn("already existed", output)

    def test_rerunning_is_idempotent(self) -> None:
        self.make_collection()
        self.run_cli(str(self.input), "-o", str(self.output))
        first = snapshot(self.output, MEDIA_SNAPSHOT_IGNORE)

        code, output = self.run_cli(str(self.input), "-o", str(self.output))
        second = snapshot(self.output, MEDIA_SNAPSHOT_IGNORE)

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(first, second)
        self.assertIn("3 file(s) were already up to date", output)

    def test_write_tags_only_touches_output_copies(self) -> None:
        self.make_collection()
        input_before = snapshot(self.input)

        self.run_cli(str(self.input), "-o", str(self.output), "--write-tags")

        self.assertEqual(snapshot(self.input), input_before)
        target = self.output / "2024" / "2024_07" / "20240714_163218.jpg"
        with Image.open(target) as image:
            self.assertEqual(image.getexif().get(0x010E), "Location: Berlin, Germany")

    def test_no_partial_files_are_left_behind(self) -> None:
        self.make_collection()

        self.run_cli(str(self.input), "-o", str(self.output))

        self.assertFalse(list(self.output.rglob("*.part")))

    def test_file_appearing_after_planning_is_not_overwritten(self) -> None:
        self.make_collection()
        plan = build_plan(self.config())
        target = self.output / "2024" / "2024_07" / "20240714_163218.jpg"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"raced")

        result = execute_plan(plan)

        self.assertTrue(result.ok)
        self.assertEqual(target.read_bytes(), b"raced")
        self.assertTrue((target.parent / "20240714_163218_02.jpg").exists())

    def test_duplicate_timestamps_number_only_the_extra_files(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_photo(self.input / "b.jpg", taken_at=taken)
        make_photo(self.input / "c.jpg", taken_at=taken)

        code, _ = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(
            sorted(path.name for path in (self.output / "2024" / "2024_07").iterdir()),
            ["20240714_163218.jpg", "20240714_163218_02.jpg", "20240714_163218_03.jpg"],
        )

    def test_output_folder_inside_input_is_never_rescanned(self) -> None:
        self.make_collection()
        nested = self.input / "output"

        code, _ = self.run_cli(str(self.input), "-o", str(nested))
        self.assertEqual(code, EXIT_OK)
        first = snapshot(nested, MEDIA_SNAPSHOT_IGNORE)

        code, _ = self.run_cli(str(self.input), "-o", str(nested))

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(snapshot(nested, MEDIA_SNAPSHOT_IGNORE), first)


class VideoRunTests(OrganizerTestCase):
    def test_videos_are_copied_with_their_recording_date(self) -> None:
        make_photo(self.input / "IMG_1.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_video(self.input / "clip.mp4", taken_at=datetime(2024, 7, 14, 17, 0, 0))
        make_video(self.input / "clip2.mov", taken_at=datetime(2023, 8, 21, 10, 45, 32))

        code, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(
            tree(self.output),
            [
                "2023",
                "2023/2023_08",
                "2023/2023_08/20230821_104532.mov",
                "2024",
                "2024/2024_07",
                "2024/2024_07/20240714_163218.jpg",
                "2024/2024_07/20240714_170000.mp4",
                "summary.txt",
            ],
        )
        self.assertIn("1 photo and 2 videos", output)

    def test_video_bytes_survive_the_copy(self) -> None:
        source = make_video(self.input / "clip.mp4", taken_at=datetime(2024, 7, 14, 17, 0, 0))

        self.run_cli(str(self.input), "-o", str(self.output))

        target = self.output / "2024" / "2024_07" / "20240714_170000.mp4"
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_write_tags_does_not_break_on_videos(self) -> None:
        make_photo(self.input / "IMG_1.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18), gps=BERLIN)
        make_video(self.input / "clip.mp4", taken_at=datetime(2024, 7, 14, 17, 0, 0))

        code, output = self.run_cli(
            str(self.input), "-o", str(self.output), "--write-tags"
        )

        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("Failed:", output)


class SummaryTests(OrganizerTestCase):
    def assertMapping(self, summary: str, source: str, target: str) -> None:
        pattern = rf"{re.escape(source)}\s+->\s+{re.escape(target)}"
        self.assertRegex(summary, pattern)

    def test_summary_is_written_into_the_output_folder(self) -> None:
        self.make_collection()

        code, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        summary = self.summary_text()
        self.assertIn("Found media", summary)
        self.assertIn("photos           : 3", summary)
        self.assertIn("videos           : 0", summary)
        self.assertIn("created          : 3", summary)
        self.assertMapping(summary, "IMG_4821.jpg", "2024/2024_07/20240714_163218.jpg")
        self.assertMapping(
            summary, "vacation/DSC_1093.jpg", "2023/2023_08/20230821_104532.jpg"
        )
        self.assertIn("Summary written to", output)

    def test_summary_shows_the_folders_that_were_used(self) -> None:
        self.make_collection()

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn(f"input : {self.input.as_posix()}", summary)
        self.assertIn(f"output: {self.output.as_posix()}", summary)

    def test_summary_counts_videos_separately(self) -> None:
        make_photo(self.input / "a.jpg", taken_at=datetime(2024, 7, 14, 16, 32, 18))
        make_video(self.input / "b.mp4", taken_at=datetime(2024, 7, 14, 16, 32, 19))
        make_video(self.input / "c.mov", taken_at=datetime(2024, 7, 14, 16, 32, 20))

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn("photos           : 1", summary)
        self.assertIn("videos           : 2", summary)
        self.assertIn("total            : 3", summary)

    def test_summary_marks_unchanged_files_on_a_second_run(self) -> None:
        self.make_collection()
        self.run_cli(str(self.input), "-o", str(self.output))

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn("created          : 0", summary)
        self.assertIn("already present  : 3", summary)

    def test_summary_lists_duplicate_groups_with_their_numbers(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_photo(self.input / "b.jpg", taken_at=taken)
        make_photo(self.input / "c.jpg", taken_at=taken)
        make_photo(self.input / "solo.jpg", taken_at=datetime(2023, 8, 21, 10, 45, 32))

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn(
            "duplicates       : 1 group(s) sharing a timestamp and extension, 3 file(s) involved",
            summary,
        )
        self.assertRegex(summary, r"(?m)^20240714_163218 \(\.jpg\) - 3 files$")
        self.assertRegex(summary, r"(?m)^\s+a\.jpg\s+->\s+2024/2024_07/20240714_163218\.jpg$")
        self.assertRegex(summary, r"(?m)^\s+b\.jpg\s+->\s+2024/2024_07/20240714_163218_02\.jpg$")
        self.assertRegex(summary, r"(?m)^\s+c\.jpg\s+->\s+2024/2024_07/20240714_163218_03\.jpg$")
        self.assertNotIn("solo.jpg", _section(summary, "Duplicates"))

    def test_summary_separates_same_timestamp_different_extensions(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_video(self.input / "b.mp4", taken_at=taken)

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn("duplicates       : 0 group(s) sharing a timestamp and extension, 0 file(s)", summary)
        self.assertIn("none", _section(summary, "Duplicates"))

    def test_summary_reports_duplicates_on_a_second_run_too(self) -> None:
        taken = datetime(2024, 7, 14, 16, 32, 18)
        make_photo(self.input / "a.jpg", taken_at=taken)
        make_photo(self.input / "b.jpg", taken_at=taken)
        self.run_cli(str(self.input), "-o", str(self.output))

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn("duplicates       : 1", summary)
        self.assertRegex(summary, r"(?m)^\s+b\.jpg\s+->\s+2024/2024_07/20240714_163218_02\.jpg$")

    def test_summary_lists_two_duplicate_groups_separately(self) -> None:
        first = datetime(2024, 7, 14, 16, 32, 18)
        second = datetime(2024, 7, 14, 17, 0, 0)
        make_photo(self.input / "a.jpg", taken_at=first)
        make_photo(self.input / "b.jpg", taken_at=first)
        make_video(self.input / "c.mp4", taken_at=second)
        make_video(self.input / "d.mp4", taken_at=second)

        self.run_cli(str(self.input), "-o", str(self.output))

        summary = self.summary_text()
        self.assertIn("duplicates       : 2 group(s) sharing a timestamp and extension, 4 file(s)", summary)
        self.assertRegex(summary, r"(?m)^20240714_163218 \(\.jpg\) - 2 files$")
        self.assertRegex(summary, r"(?m)^20240714_170000 \(\.mp4\) - 2 files$")

    def test_summary_name_can_be_changed(self) -> None:
        self.make_collection()

        self.run_cli(str(self.input), "-o", str(self.output), "--summary-name", "report.txt")

        self.assertTrue((self.output / "report.txt").exists())
        self.assertFalse((self.output / "summary.txt").exists())

    def test_summary_includes_the_date_range(self) -> None:
        self.make_collection()

        self.run_cli(str(self.input), "-o", str(self.output))

        self.assertIn(
            "date range       : 2023-08-21 10:45:32 .. 2024-07-14 16:32:19",
            self.summary_text(),
        )

    def test_empty_folder_summary_says_nothing_was_found(self) -> None:
        self.input.mkdir(parents=True)

        code, _ = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        summary = self.summary_text()
        self.assertIn("photos           : 0", summary)
        self.assertIn("videos           : 0", summary)
        self.assertIn("none", summary)


class CliTests(OrganizerTestCase):
    def test_relative_output_paths_are_reported_relatively(self) -> None:
        self.make_collection()

        with _working_directory(self.base):
            _, output = self.run_cli("My Photos")

        self.assertIn("output/2024/2024_07/20240714_163218.jpg", output)
        self.assertIn("Scanning: My Photos", output)

    def test_missing_input_folder_exits_with_an_error(self) -> None:
        code, _ = self.run_cli(str(self.base / "nope"))

        self.assertEqual(code, EXIT_ERROR)

    def test_mode_flags_are_gone(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli(str(self.input), "--dry")

        self.assertEqual(raised.exception.code, 2)

    def test_save_flag_is_gone(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli(str(self.input), "--save")

        self.assertEqual(raised.exception.code, 2)

    def test_invalid_limit_is_a_usage_error(self) -> None:
        self.make_collection()

        code, _ = self.run_cli(str(self.input), "-o", str(self.output), "--limit", "0")

        self.assertEqual(code, EXIT_USAGE)

    def test_empty_folder_reports_nothing_to_organize(self) -> None:
        self.input.mkdir(parents=True)

        code, output = self.run_cli(str(self.input), "-o", str(self.output))

        self.assertEqual(code, EXIT_OK)
        self.assertIn("No media to organize.", output)

    def test_quiet_prints_a_single_line(self) -> None:
        self.make_collection()

        code, output = self.run_cli(str(self.input), "-o", str(self.output), "--quiet")

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(output.strip().splitlines()), 1)
        self.assertIn("3 photo(s)", output)

    def test_json_output_is_machine_readable(self) -> None:
        self.make_collection()

        _, output = self.run_cli(str(self.input), "-o", str(self.output), "--json")

        payload = json.loads(output)
        self.assertEqual(payload["found"], {"photos": 3, "videos": 0, "total": 3})
        self.assertEqual(payload["created"], 3)
        self.assertEqual(payload["items"][0]["locations"], ["Berlin", "Germany"])
        self.assertEqual(payload["items"][0]["kind"], "photo")


if __name__ == "__main__":
    unittest.main()