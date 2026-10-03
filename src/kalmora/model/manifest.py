from typing import TypedDict

from .manifest_file import ManifestFile
from .manifest_phase import ManifestPhase


class Manifest(TypedDict):
    """Inventory of the original organizer package (``manifest.json``).

    Packages are preserved byte for byte — including the reference ``golden`` data and the
    ``score.py`` evaluator — so results can be reproduced and the originals proven
    unmodified. The manifest only *inventories* them: solver code still cannot read
    ``golden``; it is evaluation evidence only.
    """

    schema_version: int
    archive_sha256: str
    """SHA-256 of the original ZIP, computed over the same snapshot that is extracted, so the
    hash and the extracted bytes cannot disagree."""

    files: list[ManifestFile]
    """Sorted by path."""

    phases: list[ManifestPhase]
