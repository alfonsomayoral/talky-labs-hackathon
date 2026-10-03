"""Receipt quantity allocation from explicitly resolved AP references (#44).

No ERP reads, reference recovery, eligibility decision or posting. Quantities are
integer thousandths. A successful invoice returns a new immutable consumption
snapshot; a blocked invoice leaves the supplied snapshot unchanged.
"""
from collections import deque
from dataclasses import dataclass
from datetime import date

from .money import integer


@dataclass(frozen=True, order=True)
class OrderKey:
    company: str
    vendor: str
    currency: str
    po: str
    item: int


@dataclass(frozen=True)
class OrderLine:
    key: OrderKey
    uom: str


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    order: OrderKey
    quantity_milli: int
    uom: str
    posting_date: str
    kind: str = "GR"  # GR goods receipt or SES service acceptance

    @property
    def key(self):
        return (self.order.company, self.receipt_id)


@dataclass(frozen=True)
class OrderPortion:
    order: OrderKey
    quantity_milli: int
    receipt_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class InvoiceQuantityLine:
    line_id: str
    quantity_milli: int
    uom: str
    portions: tuple[OrderPortion, ...] = ()
    references_resolved: bool = True


@dataclass(frozen=True)
class ReceiptUsage:
    order: OrderKey
    receipt_id: str
    quantity_milli: int

    @property
    def key(self):
        return (self.order.company, self.receipt_id)


@dataclass(frozen=True)
class ConsumptionState:
    usages: tuple[ReceiptUsage, ...] = ()
    invoices: tuple[tuple[str, str, str, str], ...] = ()


@dataclass(frozen=True)
class QuantityAllocation:
    line_id: str
    order: OrderKey
    receipt_id: str
    quantity_milli: int


@dataclass(frozen=True)
class AllocationDiagnostic:
    line_id: str | None
    code: str
    required_milli: int = 0
    available_milli: int = 0


@dataclass(frozen=True)
class AllocationResult:
    status: str
    company: str
    vendor: str
    currency: str
    invoice_id: str
    allocations: tuple[QuantityAllocation, ...]
    state: ConsumptionState
    diagnostics: tuple[AllocationDiagnostic, ...] = ()


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("nonempty reference required")


def _positive(value):
    if integer(value, "quantity_milli") <= 0:
        raise ValueError("quantity_milli must be positive")


def _order(key):
    for value in (key.company, key.vendor, key.currency, key.po):
        _text(value)
    if integer(key.item, "po item") <= 0:
        raise ValueError("po item must be positive")


def _assign_quantities(demands, used):
    """Integral max flow over resolved portion/receipt edges only.

    Residual edges allow reassignment when an earlier flexible portion consumed
    supply needed by a later restricted one. Stable insertion/BFS order keeps
    results reproducible without claiming a policy preference between solutions.
    """
    source, sink = ("source",), ("sink",)
    graph, receipt_nodes = {}, set()

    def edge(left, right, capacity):
        graph.setdefault(left, {})[right] = capacity
        graph.setdefault(right, {})[left] = 0

    for index, (_, portion, candidates) in enumerate(demands):
        node = ("portion", index)
        edge(source, node, portion.quantity_milli)
        for receipt in candidates:
            receipt_node = ("receipt", *receipt.key)
            edge(node, receipt_node, portion.quantity_milli)
            if receipt_node not in receipt_nodes:
                edge(receipt_node, sink, receipt.quantity_milli - used.get(receipt.key, 0))
                receipt_nodes.add(receipt_node)
    while source in graph:
        parents, queue = {source: None}, deque([source])
        while queue and sink not in parents:
            node = queue.popleft()
            for neighbor, capacity in graph[node].items():
                if capacity > 0 and neighbor not in parents:
                    parents[neighbor] = node
                    queue.append(neighbor)
        if sink not in parents:
            break
        node, path = sink, []
        while node != source:
            parent = parents[node]
            path.append((parent, node))
            node = parent
        take = min(graph[left][right] for left, right in path)
        for left, right in path:
            graph[left][right] -= take
            graph[right][left] += take
    allocations, diagnostics, new_used = [], [], dict(used)
    for index, (line_id, portion, candidates) in enumerate(demands):
        node = ("portion", index)
        available = portion.quantity_milli - graph[source][node]
        if available < portion.quantity_milli:
            diagnostics.append(AllocationDiagnostic(line_id, "INSUFFICIENT_RECEIPTS",
                                                    portion.quantity_milli, available))
        for receipt in candidates:
            take = graph[("receipt", *receipt.key)][node]
            if take:
                allocations.append(QuantityAllocation(line_id, portion.order, receipt.receipt_id, take))
                new_used[receipt.key] = new_used.get(receipt.key, 0) + take
    return allocations, diagnostics, new_used


def allocate_receipts(*, company, vendor, currency, invoice_id, lines,
                      orders, receipts, state=ConsumptionState()):
    """Allocate an entire invoice atomically, returning ALLOCATED or BLOCKED.

    Portions are quantities already resolved to specific PO positions by #43.
    Without explicit receipt_ids, prefer eligible receipts in date/id order,
    reassigning tentative quantities if needed to honor other explicit references.
    The caller supplies eligible receipt candidates and the complete catalog
    needed to validate prior consumption. Commit state only after downstream
    eligibility, valuation and posting succeed; this function performs no I/O.
    """
    for value in (company, vendor, currency, invoice_id):
        _text(value)
    lines, orders, receipts = tuple(lines), tuple(orders), tuple(receipts)
    order_map = {}
    for order in orders:
        _order(order.key)
        _text(order.uom)
        if order.key in order_map:
            raise ValueError("duplicate PO position")
        order_map[order.key] = order
    receipt_map = {}
    for receipt in receipts:
        _order(receipt.order)
        _text(receipt.receipt_id)
        _text(receipt.uom)
        _positive(receipt.quantity_milli)
        if date.fromisoformat(receipt.posting_date).isoformat() != receipt.posting_date:
            raise ValueError("invalid receipt date")
        if receipt.kind not in ("GR", "SES"):
            raise ValueError("receipt kind must be GR or SES")
        if receipt.key in receipt_map:
            raise ValueError("duplicate receipt within company")
        if receipt.order not in order_map or order_map[receipt.order].uom != receipt.uom:
            raise ValueError("receipt does not match PO position/unit")
        receipt_map[receipt.key] = receipt
    used = {}
    for usage in state.usages:
        _positive(usage.quantity_milli)
        if usage.key in used:
            raise ValueError("duplicate consumption record")
        receipt = receipt_map.get(usage.key)
        if (receipt is None or receipt.order != usage.order
                or usage.quantity_milli > receipt.quantity_milli):
            raise ValueError("invalid prior receipt consumption")
        used[usage.key] = usage.quantity_milli
    if len(set(state.invoices)) != len(state.invoices):
        raise ValueError("duplicate invoice in consumption state")
    for invoice in state.invoices:
        if len(invoice) != 4:
            raise ValueError("invalid invoice consumption key")
        for value in invoice:
            _text(value)
    if not lines:
        raise ValueError("invoice requires quantity lines")
    seen = set()
    for line in lines:
        _text(line.line_id)
        _text(line.uom)
        _positive(line.quantity_milli)
        if type(line.references_resolved) is not bool:
            raise TypeError("references_resolved must be boolean")
        if line.line_id in seen:
            raise ValueError("duplicate invoice line")
        seen.add(line.line_id)
        for portion in line.portions:
            _order(portion.order)
            _positive(portion.quantity_milli)
            if portion.receipt_ids is not None:
                if len(set(portion.receipt_ids)) != len(portion.receipt_ids):
                    raise ValueError("duplicate explicit receipt reference")
                for value in portion.receipt_ids:
                    _text(value)
    invoice_key = (company, vendor, currency, invoice_id)
    diagnostics, demands = [], []
    if invoice_key in state.invoices:
        diagnostics.append(AllocationDiagnostic(None, "ALREADY_ALLOCATED"))
    else:
        for line in lines:
            def block(code, required=0, available=0):
                diagnostics.append(AllocationDiagnostic(line.line_id, code, required, available))

            if not line.references_resolved:
                block("AMBIGUOUS_REFERENCE")
                continue
            if not line.portions:
                block("MISSING_REFERENCE")
                continue
            if sum(p.quantity_milli for p in line.portions) != line.quantity_milli:
                block("PORTION_QUANTITY_MISMATCH")
                continue
            for portion in line.portions:
                key = portion.order
                if (key.company, key.vendor, key.currency) != (company, vendor, currency):
                    block("SCOPE_MISMATCH")
                    continue
                order = order_map.get(key)
                if order is None:
                    block("UNKNOWN_PO_POSITION")
                    continue
                if order.uom != line.uom:
                    block("UNIT_MISMATCH")
                    continue
                if portion.receipt_ids is None:
                    candidates = [r for r in receipts if r.order == key]
                else:
                    candidates = [receipt_map.get((company, rid)) for rid in portion.receipt_ids]
                    if any(r is None or r.order != key for r in candidates):
                        block("UNKNOWN_RECEIPT_REFERENCE")
                        continue
                candidates.sort(key=lambda r: (r.posting_date, r.receipt_id))
                demands.append((line.line_id, portion, candidates))
    if not diagnostics:
        allocations, diagnostics, used = _assign_quantities(demands, used)
    if diagnostics:
        return AllocationResult("BLOCKED", company, vendor, currency, invoice_id,
                                (), state, tuple(diagnostics))
    new_state = ConsumptionState(
        tuple(ReceiptUsage(receipt_map[k].order, k[1], qty) for k, qty in sorted(used.items())),
        tuple(sorted((*state.invoices, invoice_key))),
    )
    return AllocationResult("ALLOCATED", company, vendor, currency, invoice_id,
                            tuple(allocations), new_state)
