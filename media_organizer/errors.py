"""Exceptions shared across the package."""

from __future__ import annotations


class OrganizerError(Exception):
    """A problem the user can act on; reported without a traceback."""