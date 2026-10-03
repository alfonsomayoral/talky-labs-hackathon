from typing import TypedDict

from .scalars import Month


class ManifestPhase(TypedDict):
    """A phase discovered in the package: a folder with its own ERP data, tasks and inbox."""

    phase: str
    """Folder name: ``phase_dev`` (development, July 2026) or ``phase_test`` (evaluation,
    September 2026)."""

    month: Month
    """Close month read from the phase's ``tasks/close.json``."""
