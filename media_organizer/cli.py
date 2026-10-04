"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence, TextIO

from media_organizer import __version__
from media_organizer.config import (
    DEFAULT_EXTENSIONS,
    DEFAULT_MAX_LOCATION_KM,
    DEFAULT_OUTPUT_DIR_SUFFIX,
    DEFAULT_SUMMARY_NAME,
    Config,
    ConflictPolicy,
    GeocoderMode,
    resolve_output_dir,
)
from media_organizer.errors import OrganizerError
from media_organizer.executor import execute_plan
from media_organizer.planner import build_plan
from media_organizer.reporting import render_json, render_report, render_summary
from media_organizer.summary import write_summary

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3


def configure_streams() -> None:
    """Make stdout/stderr able to carry non-ASCII file names.

    Windows consoles frequently default to a legacy code page (cp1252).
    Switching to UTF-8 keeps the report readable; ``errors`` is relaxed so
    that exotic file names can never abort a run.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):  # pragma: no cover
            pass


def emit(text: str, stream: TextIO | None = None) -> None:
    """Print ``text``, degrading unprintable characters instead of crashing."""
    stream = sys.stdout if stream is None else stream
    try:
        print(text, file=stream)
    except UnicodeEncodeError:  # pragma: no cover - depends on the console code page
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-organizer",
        description=(
            "Organize photos and videos into {input}"
            f"{DEFAULT_OUTPUT_DIR_SUFFIX}/{{year}}/{{year}}_{{month}}/, "
            "a folder next to the input folder, without ever modifying it."
        ),
    )
    parser.add_argument("input", help="input folder (opened read-only)")
    parser.add_argument(
        "--version", action="version", version=f"media-organizer {__version__}"
    )

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="DIR",
        help=(
            "output folder; a relative path is resolved next to the input folder "
            f"(default: <input>{DEFAULT_OUTPUT_DIR_SUFFIX})"
        ),
    )
    parser.add_argument(
        "--summary-name",
        default=DEFAULT_SUMMARY_NAME,
        help=f"name of the summary file in the output folder (default: {DEFAULT_SUMMARY_NAME})",
    )
    parser.add_argument(
        "--write-tags",
        action="store_true",
        help="also write location tags into the new output photos",
    )
    parser.add_argument(
        "--on-conflict",
        choices=[policy.value for policy in ConflictPolicy],
        default=ConflictPolicy.BUMP.value,
        help="what to do when a target file already exists (default: bump)",
    )
    parser.add_argument(
        "--geocoder",
        choices=[mode.value for mode in GeocoderMode],
        default=GeocoderMode.AUTO.value,
        help="reverse geocoding backend (default: auto, offline city table)",
    )
    parser.add_argument(
        "--max-location-km",
        type=float,
        default=DEFAULT_MAX_LOCATION_KM,
        help=f"offline lookup radius in km (default: {DEFAULT_MAX_LOCATION_KM})",
    )
    parser.add_argument(
        "--ext",
        action="append",
        metavar="EXT",
        help="only consider this extension; repeatable",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="do not descend into subfolders",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N", help="only analyse the first N files"
    )
    parser.add_argument(
        "--max-display",
        type=int,
        metavar="N",
        help="show at most N entries per section (default: show everything)",
    )
    parser.add_argument("--json", action="store_true", help="print the run as JSON")
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="print only a one line summary"
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    extensions = tuple(args.ext) if args.ext else DEFAULT_EXTENSIONS
    if args.limit is not None and args.limit < 1:
        raise OrganizerError("--limit must be at least 1")
    if args.max_display is not None and args.max_display < 1:
        raise OrganizerError("--max-display must be at least 1")
    if not args.summary_name.strip():
        raise OrganizerError("--summary-name must not be empty")
    return Config(
        input_dir=Path(args.input),
        output_dir=resolve_output_dir(Path(args.input), args.output),
        extensions=extensions,
        recursive=args.recursive,
        conflict_policy=ConflictPolicy(args.on_conflict),
        geocoder=GeocoderMode(args.geocoder),
        max_location_km=args.max_location_km,
        write_tags=args.write_tags,
        limit=args.limit,
        summary_name=args.summary_name,
    )


def main(argv: Sequence[str] | None = None) -> int:
    configure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = _config_from_args(args)
    except OrganizerError as exc:
        emit(f"error: {exc}", stream=sys.stderr)
        return EXIT_USAGE

    try:
        plan = build_plan(config)
        result = execute_plan(plan, write_tags=config.write_tags)
        summary_path = write_summary(plan, result, config)
    except OrganizerError as exc:
        emit(f"error: {exc}", stream=sys.stderr)
        return EXIT_ERROR

    if args.json:
        emit(render_json(plan, result))
        return EXIT_OK if result.ok else EXIT_PARTIAL

    if args.quiet:
        emit(render_summary(plan, result))
    else:
        emit(render_report(plan, result, summary_path=summary_path, max_display=args.max_display))
    return EXIT_OK if result.ok else EXIT_PARTIAL