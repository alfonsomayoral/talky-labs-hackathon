"""Conservative receipt consumption inferred from evidenced historical GR/IR.

No invoice/receipt link is invented. Monetary conservation gives quantity
bounds; a grounded processing clock can add temporal constraints. Ambiguous
receipts stay UNKNOWN and must not become quantity HOLD reasons.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .ap_allocation import ConsumptionState, OrderKey, Receipt, ReceiptUsage
from .facts import Evidence, Fact
from .money import decimal, integer, line_amount


@dataclass(frozen=True)
class HistoricalReceipt:
    receipt: Receipt
    amount_doc: int
    unit_price_cents: Decimal | int | str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class HistoricalDemand:
    order: OrderKey
    amount_doc: int
    evidence: tuple[Evidence, ...]
    # A processing date, not an invoice/GL date used as a substitute for it.
    processed_on: Fact | None = None


@dataclass(frozen=True)
class ReceiptCertainty:
    receipt: Receipt
    status: str  # AVAILABLE, CONSUMED, PARTIAL, UNKNOWN
    consumed_milli: int | None
    minimum_consumed_milli: int
    maximum_consumed_milli: int
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def known_available_milli(self) -> int | None:
        return (None if self.consumed_milli is None else
                self.receipt.quantity_milli - self.consumed_milli)


@dataclass(frozen=True)
class HistoricalReceiptSnapshot:
    certainties: tuple[ReceiptCertainty, ...]
    consumption: ConsumptionState

    def known_receipt_ids(self, order: OrderKey) -> tuple[str, ...]:
        """Only IDs whose remaining capacity is established, including zero."""
        return tuple(c.receipt.receipt_id for c in self.certainties
                     if c.receipt.order == order and c.consumed_milli is not None)


def _proof(value: tuple[Evidence, ...]) -> None:
    if not isinstance(value, tuple) or not value or any(not isinstance(e, Evidence) for e in value):
        raise ValueError("historical observations require source Evidence")


def quantity_interval(amount_doc: int, unit_price_cents: Decimal | int | str) -> tuple[int, int]:
    """All nonnegative milli quantities yielding this half-up rounded amount.

    Integer cents do not imply an exact quantity. For positive price P, rounded
    A bounds q by (A-.5)*1000/P <= q < (A+.5)*1000/P.
    """
    if integer(amount_doc, "historical document cents") < 0:
        raise ValueError("historical reversal needs explicit receipt restoration evidence")
    price = decimal(unit_price_cents)
    if price <= 0:
        raise ValueError("positive price required to infer quantity")
    numerator, denominator = price.as_integer_ratio()
    lower_numerator = 500 * (2 * amount_doc - 1) * denominator
    upper_numerator = 500 * (2 * amount_doc + 1) * denominator
    lower = max(0, -(-lower_numerator // numerator))
    upper = -(-upper_numerator // numerator) - 1
    if lower > upper:
        raise ValueError("historical amount is incompatible with integer milli quantity")
    return lower, upper


def reconcile_receipt_history(
    receipts: tuple[HistoricalReceipt, ...], demands: tuple[HistoricalDemand, ...], *,
    inventory_complete: Fact,
) -> HistoricalReceiptSnapshot:
    """Return only uniquely established usage, retaining the uncertain bounds.

    inventory_complete is an evidenced assertion that the supplied demands cover
    all registered AP GR/IR consumption for these scopes. Unrelated accrual
    reversals are not AP receipt consumption. The source adapter owns that join.

    A processing cutoff is used only if every demand of the position supplies
    it with proof. Otherwise conservation is checked without an inferred clock.
    No FIFO allocation or preferred historical matching is selected.
    """
    if not isinstance(inventory_complete, Fact) or inventory_complete.value is not True:
        raise ValueError("complete historical AP inventory requires evidenced True")
    by_order, demand_map, keys = defaultdict(list), defaultdict(list), set()
    for observation in receipts:
        _proof(observation.evidence)
        r = observation.receipt
        if not isinstance(r, Receipt) or not isinstance(r.order, OrderKey):
            raise TypeError("historical receipt requires an explicit order scope")
        if any(not isinstance(value, str) or not value for value in (
                r.receipt_id, r.uom, r.order.company, r.order.vendor, r.order.currency, r.order.po)):
            raise ValueError("nonempty historical receipt scope and unit required")
        if integer(r.order.item, "PO position") <= 0 or r.kind not in {"GR", "SES"}:
            raise ValueError("positive PO position and GR/SES receipt required")
        if r.key in keys or integer(r.quantity_milli, "receipt quantity") <= 0:
            raise ValueError("unique positive historical receipts required")
        if date.fromisoformat(r.posting_date).isoformat() != r.posting_date:
            raise ValueError("receipt posting date must be ISO")
        if integer(observation.amount_doc, "receipt document cents") < 0:
            raise ValueError("receipt amount must be nonnegative")
        keys.add(r.key)
        by_order[r.order].append(observation)
    for demand in demands:
        _proof(demand.evidence)
        integer(demand.amount_doc, "historical document cents")
        if demand.processed_on is not None:
            if (not isinstance(demand.processed_on, Fact) or
                    not isinstance(demand.processed_on.value, str) or
                    date.fromisoformat(demand.processed_on.value).isoformat() != demand.processed_on.value):
                raise ValueError("historical processing date requires an evidenced ISO date")
        if demand.order not in by_order:
            raise ValueError("historical demand has no supplied receipt position")
        demand_map[demand.order].append(demand)
    certainties, usages = [], []
    for order in sorted(by_order):
        observations = sorted(by_order[order], key=lambda o: o.receipt.key)
        history = demand_map[order]
        proof = tuple(dict.fromkeys((inventory_complete.evidence,
                *(e for o in observations for e in o.evidence),
                *(e for d in history for e in d.evidence),
                *(d.processed_on.evidence for d in history if d.processed_on is not None))))
        capacity = sum(o.receipt.quantity_milli for o in observations)
        diagnostics = []
        intervals = []
        try:
            prices = {decimal(o.unit_price_cents) for o in observations}
            if len(prices) != 1:
                raise ValueError("contradictory historical PO prices")
            if len({o.receipt.uom for o in observations}) != 1:
                raise ValueError("contradictory historical receipt units")
            price, = prices
            if any(line_amount(o.receipt.quantity_milli, price) != o.amount_doc for o in observations):
                raise ValueError("receipt amount is incompatible with PO price/quantity")
            intervals = [quantity_interval(d.amount_doc, price) for d in history]
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"HISTORY_VALUATION_UNRESOLVED:{exc}")
        lower, upper = (sum(i[0] for i in intervals), sum(i[1] for i in intervals))
        if not diagnostics and lower > capacity:
            diagnostics.append("HISTORY_CAPACITY_EVIDENCE_INSUFFICIENT")
        temporal = bool(history) and all(d.processed_on is not None for d in history)
        latest = None
        if not diagnostics and temporal:
            latest = max(d.processed_on.value for d in history)
            days = sorted({d.processed_on.value for d in history})
            for day in days:
                required = sum(intervals[i][0] for i, d in enumerate(history) if d.processed_on.value <= day)
                available = sum(o.receipt.quantity_milli for o in observations if o.receipt.posting_date <= day)
                if required > available:
                    diagnostics.append("HISTORY_TEMPORAL_EVIDENCE_INSUFFICIENT")
                    break
        eligible_capacity = (sum(o.receipt.quantity_milli for o in observations
                                 if o.receipt.posting_date <= latest) if latest is not None else capacity)
        upper = min(upper, eligible_capacity)
        for observation in observations:
            r = observation.receipt
            if diagnostics:
                minimum, maximum = 0, r.quantity_milli
                consumed, status = None, "UNKNOWN"
            else:
                eligible = latest is None or r.posting_date <= latest
                maximum = min(r.quantity_milli, upper) if eligible else 0
                minimum = max(0, lower - (eligible_capacity - r.quantity_milli)) if eligible else 0
                consumed = minimum if minimum == maximum else None
                status = ("UNKNOWN" if consumed is None else "AVAILABLE" if consumed == 0 else
                          "CONSUMED" if consumed == r.quantity_milli else "PARTIAL")
            notes = tuple(diagnostics) if diagnostics else (() if consumed is not None else ("HISTORY_RECEIPT_SPLIT_UNKNOWN",))
            certainties.append(ReceiptCertainty(r, status, consumed, minimum, maximum, proof, notes))
            if consumed:
                usages.append(ReceiptUsage(order, r.receipt_id, consumed))
    return HistoricalReceiptSnapshot(tuple(certainties), ConsumptionState(tuple(usages)))
