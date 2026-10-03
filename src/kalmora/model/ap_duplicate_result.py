"""Duplicate policy result, independent from the AP output contract."""
from dataclasses import dataclass
from kalmora.facts import Evidence


@dataclass(frozen=True)
class DuplicateResult:
    status: str
    duplicate_of: str | None = None
    reissue_of: str | None = None
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[str, ...] = ()
