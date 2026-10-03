from typing import TypedDict


class ManifestFile(TypedDict):
    """A file of the imported package with its fingerprint, so any later change to the
    organizer's data is detectable."""

    path: str
    """Path relative to the destination, starting with ``participant/``."""

    size: int
    sha256: str
