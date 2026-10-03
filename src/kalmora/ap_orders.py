"""Conservative PO recovery from explicit scope, position and receipt evidence.

Exact reference, material or concept matches can confirm a position. Scope alone
only retrieves candidates. Insufficient receipts do not erase the correct PO;
#44/#49 decide quantity readiness after this module resolves references.
"""
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .ap_allocation import ConsumptionState, OrderKey, OrderLine, Receipt
from .facts import Evidence
from .money import decimal, integer


@dataclass(frozen=True)
class POQuery:
    line_id: str
    company: str
    vendor: str
    currency: str
    quantity_milli: int
    uom: str
    evidence: tuple[Evidence, ...]
    portion_id: str = "1"
    po_reference: str | None = None
    po_item: int | None = None
    receipt_references: tuple[str, ...] = ()
    project: str | None = None
    material: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class POCandidate:
    order: OrderKey
    uom: str
    unit_price_cents: Decimal
    available_milli: int
    receipts: tuple[Receipt, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class POResolution:
    query: POQuery
    status: str  # RESOLVED, AMBIGUOUS, UNCONFIRMED, NOT_FOUND, CONFLICT, UNKNOWN
    selected: POCandidate | None
    candidates: tuple[POCandidate, ...]
    reference_recovered: bool
    diagnostics: tuple[str, ...] = ()


def _concept(value: str) -> str:
    return " ".join(value.casefold().split())


class POCatalog:
    def __init__(self, *, orders: Iterable[Mapping[str, Any]],
                 receipts: Iterable[Mapping[str, Any]]) -> None:
        self._items = {}
        for row in deepcopy(tuple(orders)):
            created = row["created_on"]
            if date.fromisoformat(created).isoformat() != created:
                raise ValueError("PO creation date must be ISO")
            for item in row["items"]:
                key = OrderKey(row["company"], row["vendor"], row["currency"], row["id"], item["item"])
                if key in self._items or integer(key.item, "PO item") <= 0:
                    raise ValueError("unique positive PO positions required")
                for value in (key.company, key.vendor, key.currency, key.po, item["uom"]):
                    if not isinstance(value, str) or not value:
                        raise ValueError("nonempty PO scope/unit required")
                price = decimal(item["unit_price"])
                if price < 0:
                    raise ValueError("PO price must be nonnegative")
                self._items[key] = (created, row.get("project"), item, price)
        self._receipts, self._references = {}, {}
        for row in deepcopy(tuple(receipts)):
            keys = [k for k in self._items if (k.company, k.po, k.item) == (row["company"], row["po"], row["po_item"])]
            if len(keys) != 1 or keys[0].vendor != row["vendor"]:
                raise ValueError("receipt must belong to exactly one supplied PO position/vendor")
            key = keys[0]
            receipt = Receipt(row["id"], key, row["quantity_milli"], self._items[key][2]["uom"], row["posting_date"], row["type"])
            if integer(receipt.quantity_milli, "receipt quantity") <= 0:
                raise ValueError("receipt quantity must be positive")
            if receipt.key in self._receipts or receipt.kind not in {"GR", "SES"}:
                raise ValueError("unique GR/SES receipt required")
            if date.fromisoformat(receipt.posting_date).isoformat() != receipt.posting_date:
                raise ValueError("receipt date must be ISO")
            self._receipts[receipt.key] = receipt
            for reference in {row["id"], row.get("reference")} - {None, ""}:
                self._references.setdefault((key.company, reference), []).append(receipt)

    def resolve(self, query: POQuery, *, invoice_date: str, receipt_as_of: str | None = None,
                state: ConsumptionState = ConsumptionState()) -> POResolution:
        """Resolve references with distinct invoice and receipt-visibility dates.

        The invoice date still constrains PO creation. An explicit observed
        processing/arrival date can expose later receipts without changing the
        invoice date used by fiscal and FX engines. The caller owns phase bounds.
        """
        if date.fromisoformat(invoice_date).isoformat() != invoice_date:
            raise ValueError("invoice date must be ISO")
        receipt_cutoff = invoice_date if receipt_as_of is None else receipt_as_of
        if date.fromisoformat(receipt_cutoff).isoformat() != receipt_cutoff:
            raise ValueError("receipt cutoff must be ISO")
        if integer(query.quantity_milli, "invoice quantity") <= 0:
            raise ValueError("invoice quantity must be positive")
        if not query.evidence or any(not isinstance(e, Evidence) for e in query.evidence):
            raise ValueError("PO query must carry source evidence")
        for value in (query.line_id, query.portion_id, query.company, query.vendor, query.currency, query.uom):
            if not isinstance(value, str) or not value:
                raise ValueError("query scope/position/unit required")
        if query.po_item is not None and integer(query.po_item, "PO item") <= 0:
            raise ValueError("positive PO item required")
        used = {}
        for usage in state.usages:
            receipt = self._receipts.get(usage.key)
            if (usage.key in used or receipt is None or receipt.order != usage.order
                    or integer(usage.quantity_milli) <= 0 or usage.quantity_milli > receipt.quantity_milli):
                raise ValueError("invalid prior receipt consumption")
            used[usage.key] = usage.quantity_milli
        scope = [k for k, (created, project, item, _) in self._items.items()
                  if (k.company, k.vendor, k.currency) == (query.company, query.vendor, query.currency)
                  and created <= invoice_date]
        scoped = [k for k in scope if self._items[k][2]["uom"] == query.uom
                  and (query.project is None or self._items[k][1] == query.project)
                  and (query.po_item is None or k.item == query.po_item)]
        explicit_order = [k for k in scope if k.po == query.po_reference]
        reference_orders = None
        diagnostics = []
        for reference in query.receipt_references:
            found = {r.order for r in self._references.get((query.company, reference), ())
                     if r.posting_date <= receipt_cutoff}
            if not found:
                diagnostics.append(f"UNRESOLVED_RECEIPT:{reference}")
            else:
                reference_orders = found if reference_orders is None else reference_orders & found
        def matches(key):
            item = self._items[key][2]
            return ((query.material is None or item.get("material") == query.material)
                    and (query.description is None or _concept(item.get("description", "")) == _concept(query.description)))
        if explicit_order:
            keys = [k for k in explicit_order if k in scoped and matches(k)]
            if reference_orders is not None:
                keys = [k for k in keys if k in reference_orders]
            conflict = not keys
            confirmed = True
        else:
            keys = [k for k in scoped if matches(k)]
            if reference_orders is not None:
                keys = [k for k in keys if k in reference_orders]
            confirmed = bool(query.material or query.description or reference_orders)
            conflict = reference_orders == set() and not diagnostics
        candidates = []
        for key in sorted(keys):
            referenced_ids = ({r.receipt_id for reference in query.receipt_references
                               for r in self._references.get((query.company, reference), ())}
                              if query.receipt_references else None)
            visible = tuple(sorted((r for r in self._receipts.values() if r.order == key and r.posting_date <= receipt_cutoff),
                                   key=lambda r: (r.posting_date, r.receipt_id)))
            if referenced_ids is not None:
                visible = tuple(r for r in visible if r.receipt_id in referenced_ids)
            if diagnostics:
                # A known subset must never replace all the references the
                # document asserts. Unknown references are not receipt supply.
                visible = ()
            evidence = (*query.evidence, Evidence("erp/purchase_orders.jsonl", f"id={key.po}.items[{key.item}]"),
                        *(Evidence("erp/goods_receipts.jsonl", f"id={r.receipt_id}") for r in visible))
            candidates.append(POCandidate(key, query.uom, self._items[key][3],
                sum(r.quantity_milli - used.get(r.key, 0) for r in visible), visible, evidence))
        selected = candidates[0] if confirmed and len(candidates) == 1 and not diagnostics and not conflict else None
        status = ("CONFLICT" if conflict else "UNKNOWN" if diagnostics else "NOT_FOUND" if not candidates else
                  "UNCONFIRMED" if not confirmed else "RESOLVED" if selected else "AMBIGUOUS")
        return POResolution(query, status, selected, tuple(candidates),
                            bool(selected and (selected.order.po != query.po_reference
                                               or selected.order.item != query.po_item)), tuple(diagnostics))

    def resolve_lines(self, queries: Sequence[POQuery], *, invoice_date: str, receipt_as_of: str | None = None,
                      state: ConsumptionState = ConsumptionState()) -> tuple[POResolution, ...]:
        identities = [(q.line_id, q.portion_id) for q in queries]
        if not queries or len(identities) != len(set(identities)):
            raise ValueError("unique invoice line/portion queries required")
        return tuple(self.resolve(q, invoice_date=invoice_date, receipt_as_of=receipt_as_of,
                                  state=state) for q in queries)

    @classmethod
    def from_phase(cls, data) -> "POCatalog":
        return cls(orders=data.table("purchase_orders"), receipts=data.table("goods_receipts"))
