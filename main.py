#!/usr/bin/env python3
"""Media Organizer entry point.

    python main.py "./My Photos"
    python main.py "./My Photos" -o "sorted"

Both write next to the input folder: the first into ``My Photos_output``, the
second into ``sorted``, both beside ``My Photos``. Pass an absolute path to
``-o`` to place the output somewhere else entirely.

After ``pip install .`` the same tool is available as ``media-organizer``.
"""

from __future__ import annotations

from media_organizer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())