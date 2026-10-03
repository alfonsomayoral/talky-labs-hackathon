"""Immutable simulated state; replay never writes ERP or source documents."""
from dataclasses import dataclass
from .ap_event import ApEvent


@dataclass(frozen=True)
class ApTimelineState:
    events: tuple[ApEvent, ...] = ()
