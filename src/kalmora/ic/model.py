"""M5 input/output objects. Missing upstream data is not an empty success."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Mapping, Sequence
import hashlib
import json

from kalmora.facts import Evidence
from kalmora.ledger import Ledger
from kalmora.money import integer


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    default=str, allow_nan=False).encode()).hexdigest()


def event_key(cause: str, *identity: object) -> str:
    """Economic identity, independent of traversal order or run UUID."""
    return "ic:" + cause.lower() + ":" + digest(identity)[:24]


@dataclass(frozen=True)
class Receipt:
    company: str
    issuer: str
    reference: str
    received_on: str
    evidence: Evidence

    def __post_init__(self):
        date.fromisoformat(self.received_on)
        if not self.company or not self.issuer or not self.reference:
            raise ValueError("receipt requires company, issuer and reference")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("receipt requires Evidence")


@dataclass(frozen=True)
class ReceiptCoverage:
    """AP certifies the inventory, not IC. complete=False never implies absence."""
    month: str
    complete: bool
    receipts: tuple[Receipt, ...]
    producer: str
    evidence: Evidence
    unresolved_documents: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.complete) is not bool or not self.producer:
            raise ValueError("receipt coverage requires completeness and producer")
        if self.complete and self.unresolved_documents:
            raise ValueError("unresolved AP documents cannot certify full coverage")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("receipt coverage requires Evidence")


@dataclass(frozen=True)
class OwnedEntry:
    """A producer-owned entry. M5 consumes it; it does not synthesize bank/AP work."""
    event_id: str
    stage: str
    entry: dict
    evidence: Evidence

    def __post_init__(self):
        if not self.event_id or not self.stage or not isinstance(self.evidence, Evidence):
            raise ValueError("entry needs producer event, stage and evidence")


@dataclass(frozen=True)
class BankDelivery:
    producer: str
    complete: bool
    entries: tuple[OwnedEntry, ...]
    # Original statement identity -> entry's (event_id, stage).
    pooling_links: Mapping[str, tuple[str, str]]
    evidence: Evidence

    def __post_init__(self):
        if type(self.complete) is not bool or not self.producer:
            raise ValueError("bank delivery requires completeness and producer")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("bank delivery requires Evidence")
        owners = {(e.event_id, e.stage) for e in self.entries}
        if len(owners) != len(self.entries):
            raise ValueError("duplicate producer entry ownership")
        for owner in self.pooling_links.values():
            if tuple(owner) not in owners:
                raise ValueError("pooling link must identify a supplied bank entry")


@dataclass(frozen=True)
class Allocation:
    """An explicitly supplied or independently evidenced net-expense allocation."""
    account: str
    cost_center: str | None
    wbs: str | None
    evidence: Evidence

    def __post_init__(self):
        if bool(self.cost_center) == bool(self.wbs):
            raise ValueError("an expense allocation needs exactly one cost object")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("allocation requires Evidence")


@dataclass(frozen=True)
class Upstream:
    """All missing interfaces stay None and appear in the audit report.

    prior_projection is a *full* append-only projection containing the recorded
    book. AP/bank entries may already be present; ownership makes replay safe.
    """
    prior_projection: Ledger | None
    ap_entries: tuple[OwnedEntry, ...] | None
    ap_coverage: ReceiptCoverage | None
    banks: BankDelivery | None
    invoice_allocations: Mapping[tuple[str, str, str], Allocation] = field(default_factory=dict)
    interest_allocations: Mapping[str, Allocation] = field(default_factory=dict)
    valuation_entry_ids: frozenset[str] = frozenset()

    @classmethod
    def missing(cls) -> Upstream:
        return cls(None, None, None, None)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    issues: tuple[int, ...] = ()
    event_id: str | None = None
    evidence: tuple[Evidence, ...] = ()
    blocking: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass
class Finding:
    event_id: str
    pair: tuple[str, str]
    cause: str
    amount: int
    responsible: str
    amount_currency: str
    proposed: dict | None
    evidence: tuple[Evidence, ...]
    details: dict = field(default_factory=dict)
    status: str = "detected"
    emitted_adjustment: list[dict] = field(default_factory=list)

    def __post_init__(self):
        integer(self.amount)
        if self.amount < 0 or len(set(self.pair)) != 2 or self.responsible not in self.pair:
            raise ValueError("invalid IC finding identity, amount or responsible")
        if self.cause not in {"INVOICE_IN_TRANSIT", "INTEREST_DAY_COUNT", "WRONG_TRADING_PARTNER",
                              "DUPLICATE_POSTING", "POOLING_NOT_BOOKED"}:
            raise ValueError("unknown IC cause")

    def record(self) -> dict:
        # FORMATO_ENTREGA.md: no internal IDs/currency/status added to the contract.
        return {"pair": list(self.pair), "cause": self.cause, "amount": self.amount,
                "responsible": self.responsible, "adjustment": self.emitted_adjustment}

    def audit(self) -> dict:
        return {"event_id": self.event_id, **self.record(), "amount_currency": self.amount_currency,
                "status": self.status, "evidence": [asdict(e) for e in self.evidence],
                "details": self.details}


@dataclass
class Result:
    findings: list[Finding]
    diagnostics: list[Diagnostic]
    original: dict
    before: dict
    corrected: dict
    projection: Ledger
    metadata: dict

    @property
    def records(self) -> list[dict]:
        return [f.record() for f in self.findings]

    @property
    def complete(self) -> bool:
        return not any(d.blocking for d in self.diagnostics)

    def audit(self) -> dict:
        return {"schema_version": 1, "complete": self.complete, "metadata": self.metadata,
                "findings": [f.audit() for f in self.findings],
                "diagnostics": [d.to_dict() for d in self.diagnostics],
                "positions": {"recorded": self.original, "before_ic": self.before,
                              "corrected": self.corrected}}
