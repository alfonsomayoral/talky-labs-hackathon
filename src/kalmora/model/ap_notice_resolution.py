"""A notice action and its immutable simulated state transition."""
from dataclasses import dataclass
from kalmora.facts import Evidence
from .ap_timeline_state import ApTimelineState


@dataclass(frozen=True)
class NoticeResolution:
    decision: str
    action: str | None
    state: ApTimelineState
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[str, ...] = ()
