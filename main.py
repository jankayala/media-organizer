#!/usr/bin/env python3
"""Media Organizer entry point.

    python main.py "./My Photos"
    python main.py "./My Photos" -o "./output"

After ``pip install .`` the same tool is available as ``media-organizer``.
"""

from __future__ import annotations

from media_organizer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())