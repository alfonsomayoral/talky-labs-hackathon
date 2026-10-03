"""Exact AP order matching before bounded semantic interpretation (#43/#140).

Semantic selection proves a reference association only. Receipt certainty and
the quantity allocator retain control over availability and posting eligibility.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
from collections.abc import Sequence

from .ap_allocation import (ConsumptionState, InvoiceQuantityLine, OrderKey, OrderLine,
                            OrderPortion, Receipt, allocate_receipts)
from .ap_erp import APERPBaseline, ERPSource
from .ap_history import HistoricalReceiptSnapshot
from .ap_orders import POCatalog, POQuery, POQueryLine, POResolution, validate_query_lines
from .ap_order_sources import order_queries_from_facts
from .data import PhaseData
from .documents.contracts import (
    Candidate, ParsedDocument, ResolutionRequest, ResolutionResult, SemanticResolver, fingerprint,
)
from .documents.replay import validate_resolution
from .facts import DocumentFacts, Evidence
from .money import integer

BRIDGE_VERSION = "ap-order-bridge-v2"


@dataclass(frozen=True)
class APOrderMatch:
    reference: POResolution
    quantity_status: str  # AVAILABLE, INSUFFICIENT, UNKNOWN
    quantity_line: InvoiceQuantityLine | None
    semantic_called: bool = False
    semantic_result: ResolutionResult | None = None
    request_sha256: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class APOrderBatchMatch:
    reference_status: str  # RESOLVED or UNKNOWN
    quantity_status: str  # AVAILABLE, INSUFFICIENT, UNKNOWN
    matches: tuple[APOrderMatch, ...]
    quantity_lines: tuple[InvoiceQuantityLine, ...]
    diagnostics: tuple[str, ...] = ()


def _text(value):
    return " ".join(value.split())


def _residual_proofs(query: POQuery, document: ParsedDocument) -> tuple[tuple[str, Evidence], ...]:
    """Use only residual values actually carried by this source's evidence."""
    result = []
    for value in (query.description, query.po_reference):
        if not isinstance(value, str) or not value.strip():
            continue
        for proof in query.evidence:
            if (proof.document != document.path or not proof.quote
                    or _text(value) not in _text(proof.quote)):
                continue
            blocks = [b for b in document.blocks if proof.page is None or b.page == proof.page]
            literal = any(_text(proof.quote) in _text(b.text) for b in blocks)
            image = any(i.page == proof.page for i in document.images) and bool(blocks)
            if literal or image:
                result.append((value, proof))
    return tuple(result)


class APOrderBridge:
    def __init__(self, *, orders, receipts, history: HistoricalReceiptSnapshot,
                 sources: tuple[ERPSource, ...] = ()):
        if not isinstance(history, HistoricalReceiptSnapshot):
            raise TypeError("active-phase historical receipt certainty required")
        self._orders, self._receipts = deepcopy(tuple(orders)), deepcopy(tuple(receipts))
        self.catalog = POCatalog(orders=self._orders, receipts=self._receipts)
        self.history = history
        self._items = {}
        for row in self._orders:
            for item in row["items"]:
                key = OrderKey(row["company"], row["vendor"], row["currency"], row["id"], item["item"])
                self._items[key] = dict(company=key.company, vendor=key.vendor, currency=key.currency,
                    po=key.po, po_item=key.item, uom=item["uom"], project=row.get("project"),
                    material=item.get("material"), description=item.get("description"),
                    unit_price_cents=item["unit_price"])
        self._certainty = {c.receipt.key: c for c in history.certainties}
        expected = {}
        for row in self._receipts:
            keys = [key for key in self._items
                    if (key.company, key.po, key.item) == (row["company"], row["po"], row["po_item"])]
            key, = keys  # catalogue already validated uniqueness and supplier
            receipt = Receipt(row["id"], key, row["quantity_milli"], self._items[key]["uom"],
                              row["posting_date"], row["type"])
            expected[receipt.key] = receipt
        if (len(self._certainty) != len(history.certainties) or set(expected) != set(self._certainty)
                or any(self._certainty[key].receipt != receipt for key, receipt in expected.items())):
            raise ValueError("historical certainty belongs to a different receipt catalogue")
        self.snapshot_sha256 = fingerprint(dict(version=BRIDGE_VERSION, orders=self._orders,
            receipts=self._receipts, history=asdict(history), sources=[asdict(s) for s in sources]))

    @classmethod
    def from_phase(cls, phase_path: str | Path, baseline: APERPBaseline):
        """Load original PO/receipt text only when it matches the ERP baseline."""
        if not isinstance(baseline, APERPBaseline):
            raise TypeError("active-phase ERP baseline required")
        data = PhaseData(Path(phase_path))
        paths = []
        for source in baseline.sources:
            path = data.phase_dir / source.path
            if not path.resolve().is_relative_to(data.phase_dir) or "golden" in path.resolve().parts:
                raise ValueError("baseline source escapes the active phase")
            if sha256(path.read_bytes()).hexdigest() != source.sha256:
                raise ValueError("baseline source differs from the active phase")
            paths.append((path, source))
        if data.month != baseline.month:
            raise ValueError("baseline month differs from the active phase")
        bridge = cls(orders=data.table("purchase_orders"), receipts=data.table("goods_receipts"),
                     history=baseline.history, sources=baseline.sources)
        if any(sha256(path.read_bytes()).hexdigest() != source.sha256 for path, source in paths):
            raise ValueError("baseline source changed while loading order text")
        return bridge

    def _state(self, state):
        baseline = self.history.consumption
        state = baseline if state is None else state
        if not isinstance(state, ConsumptionState):
            raise TypeError("immutable receipt consumption snapshot required")
        used = {u.key: u.quantity_milli for u in state.usages}
        if any(used.get(u.key, 0) < u.quantity_milli for u in baseline.usages):
            raise ValueError("current state cannot discard historical receipt consumption")
        if not set(baseline.invoices) <= set(state.invoices):
            raise ValueError("current state cannot discard historical posted identities")
        if any(key not in self._certainty or self._certainty[key].consumed_milli is None for key in used):
            raise ValueError("current state cannot invent consumption for unknown historical receipts")
        return state

    def _finish(self, resolution, state, *, called=False, result=None, request_hash=None, diagnostics=()):
        diagnostics = (*resolution.diagnostics, *diagnostics)
        selected = resolution.selected
        if resolution.status != "RESOLVED" or selected is None:
            return APOrderMatch(resolution, "UNKNOWN", None, called, result, request_hash, diagnostics)
        known = tuple(r for r in selected.receipts if self._certainty[r.key].consumed_milli is not None)
        unknown = tuple(r for r in selected.receipts if self._certainty[r.key].consumed_milli is None)
        used = {u.key: u.quantity_milli for u in state.usages}
        available = sum(r.quantity_milli - used.get(r.key, 0) for r in known)
        selected = replace(selected, receipts=known, available_milli=available)
        selected = replace(selected, evidence=tuple(dict.fromkeys((*selected.evidence,
            *(proof for r in (*known, *unknown) for proof in self._certainty[r.key].evidence)))))
        resolution = replace(resolution, selected=selected)
        query = resolution.query
        if available < query.quantity_milli and unknown:
            return APOrderMatch(resolution, "UNKNOWN", None, called, result, request_hash,
                (*diagnostics, "HISTORICAL_RECEIPT_CAPACITY_UNKNOWN"))
        line = InvoiceQuantityLine(query.line_id, query.quantity_milli, query.uom,
            (OrderPortion(selected.order, query.quantity_milli, tuple(r.receipt_id for r in known)),))
        return APOrderMatch(resolution, "AVAILABLE" if available >= query.quantity_milli else "INSUFFICIENT",
                            line, called, result, request_hash, diagnostics)

    async def resolve_lines(self, lines: Sequence[POQueryLine], *, invoice_id: str,
                            invoice_date: str, receipt_as_of: str | None = None,
                            state: ConsumptionState | None = None, document: ParsedDocument | None = None,
                            resolver: SemanticResolver | None = None, max_candidates: int = 20) -> APOrderBatchMatch:
        """Resolve observed portions, then preview their *joint* receipt capacity.

        No consumption state is returned or committed. The real allocator must
        run again against the current snapshot before valuation/posting.
        """
        lines = validate_query_lines(lines)
        state = self._state(state)
        matches = tuple([await self.resolve(query, invoice_date=invoice_date,
            receipt_as_of=receipt_as_of, state=state, document=document, resolver=resolver,
            max_candidates=max_candidates) for line in lines for query in line.portions])
        diagnostics = tuple(dict.fromkeys(d for match in matches for d in match.diagnostics))
        if any(match.reference.status != "RESOLVED" or match.quantity_line is None for match in matches):
            return APOrderBatchMatch("UNKNOWN" if any(m.reference.status != "RESOLVED" for m in matches)
                else "RESOLVED", "UNKNOWN", matches, (), diagnostics)
        quantity_lines, offset = [], 0
        for line in lines:
            row_matches = matches[offset:offset + len(line.portions)]
            offset += len(line.portions)
            portions = tuple(p for match in row_matches for p in match.quantity_line.portions)
            quantity_lines.append(InvoiceQuantityLine(line.line_id, line.quantity_milli, line.uom, portions))
        query = lines[0].portions[0]
        preview = allocate_receipts(company=query.company, vendor=query.vendor, currency=query.currency,
            invoice_id=invoice_id, lines=tuple(quantity_lines), state=state,
            orders=tuple(OrderLine(key, row["uom"]) for key, row in self._items.items()),
            receipts=tuple(c.receipt for c in self.history.certainties))
        if preview.status == "ALLOCATED":
            return APOrderBatchMatch("RESOLVED", "AVAILABLE", matches, tuple(quantity_lines), diagnostics)
        codes = tuple(dict.fromkeys(d.code for d in preview.diagnostics))
        unresolved_capacity = any(self._certainty[r.key].consumed_milli is None
            for match in matches for candidate in match.reference.candidates
            if candidate.order == match.reference.selected.order for r in candidate.receipts)
        if any(code != "INSUFFICIENT_RECEIPTS" for code in codes) or unresolved_capacity:
            return APOrderBatchMatch("RESOLVED", "UNKNOWN", matches, (),
                (*diagnostics, *("BATCH:" + c for c in codes),
                 *(("HISTORICAL_RECEIPT_CAPACITY_UNKNOWN",) if unresolved_capacity else ())))
        return APOrderBatchMatch("RESOLVED", "INSUFFICIENT", matches, tuple(quantity_lines),
                                (*diagnostics, *("BATCH:" + c for c in codes)))

    async def resolve_facts(self, facts: DocumentFacts, *, company: str, vendor: str,
                            currency: str, invoice_id: str, receipt_as_of: str | None = None,
                            state: ConsumptionState | None = None, document: ParsedDocument | None = None,
                            resolver: SemanticResolver | None = None, max_candidates: int = 20) -> APOrderBatchMatch:
        """Connect existing extraction/normalization to this deterministic core."""
        if document is not None and facts.source_sha256 != document.source_sha256:
            raise ValueError("order facts and parsed source fingerprints disagree")
        if document is not None and any(f.evidence.document != document.path
                for candidates in facts.fields.values() for f in candidates):
            raise ValueError("order facts belong to another parsed source")
        observed = order_queries_from_facts(facts, company=company, vendor=vendor, currency=currency)
        if observed.status != "READY":
            return APOrderBatchMatch("UNKNOWN", "UNKNOWN", (), (), observed.diagnostics)
        return await self.resolve_lines(observed.lines, invoice_id=invoice_id,
            invoice_date=observed.invoice_date, receipt_as_of=receipt_as_of, state=state,
            document=document, resolver=resolver, max_candidates=max_candidates)

    async def resolve(self, query: POQuery, *, invoice_date: str, receipt_as_of: str | None = None,
                      state: ConsumptionState | None = None, document: ParsedDocument | None = None,
                      resolver: SemanticResolver | None = None, max_candidates: int = 20) -> APOrderMatch:
        if integer(max_candidates, "candidate limit") < 1:
            raise ValueError("positive bounded candidate limit required")
        state = self._state(state)
        exact = self.catalog.resolve(query, invoice_date=invoice_date, receipt_as_of=receipt_as_of, state=state)
        if exact.status in {"RESOLVED", "UNKNOWN"}:
            return self._finish(exact, state)
        # Drop only the description comparison. Structural constraints and every
        # observed receipt reference remain mandatory, even for semantic ranking.
        structural_query = replace(query, description=None)
        pool = self.catalog.resolve(structural_query, invoice_date=invoice_date,
                                    receipt_as_of=receipt_as_of, state=state)
        if pool.status in {"CONFLICT", "UNKNOWN"} or not pool.candidates:
            return self._finish(exact, state)
        residual = _residual_proofs(query, document) if isinstance(document, ParsedDocument) else ()
        if query.po_reference in {c.order.po for c in pool.candidates}:
            # An already exact PO number does not distinguish its positions.
            residual = tuple((value, proof) for value, proof in residual if value != query.po_reference)
        if not residual:
            return self._finish(exact, state, diagnostics=("SEMANTIC_SOURCE_EVIDENCE_UNKNOWN",))
        if len(pool.candidates) > max_candidates:
            return self._finish(exact, state, diagnostics=("SEMANTIC_CANDIDATE_LIMIT_EXCEEDED",))
        if resolver is None:
            return self._finish(exact, state, diagnostics=("SEMANTIC_RESOLVER_UNAVAILABLE",))
        mapping = {json.dumps([c.order.company, c.order.vendor, c.order.currency, c.order.po, c.order.item],
                              separators=(",", ":")): c for c in pool.candidates}
        hard = dict(company=query.company, vendor=query.vendor, currency=query.currency, uom=query.uom)
        for key in ("project", "material", "po_item"):
            if getattr(query, key) is not None:
                hard[key] = getattr(query, key)
        request = ResolutionRequest(document, tuple(Candidate(identifier, deepcopy(self._items[c.order]))
            for identifier, c in mapping.items()), context=dict(
                bridge_version=BRIDGE_VERSION, snapshot_sha256=self.snapshot_sha256,
                state_sha256=fingerprint(asdict(state)), query=asdict(query), invoice_date=invoice_date,
                receipt_as_of=receipt_as_of, hard_constraints=hard, max_selections=1))
        request_hash = request.sha256
        result = await resolver.resolve(request)
        if request.sha256 != request_hash:
            raise ValueError("semantic resolver changed its bounded source request")
        validate_resolution(request, result)
        if result.status != "SELECTED":
            reference = replace(exact, status="AMBIGUOUS" if result.status == "AMBIGUOUS" else "NOT_FOUND",
                                selected=None, candidates=pool.candidates)
            return self._finish(reference, state, called=True, result=result, request_hash=request.sha256)
        if len(result.selected_ids) != 1:
            raise ValueError("semantic order selection cannot invent a multi-position split")
        if not any(e.get("candidate_attribute") in {"description", "material", "po"}
                   and isinstance(e.get("candidate_value"), str) and e["candidate_value"].strip()
                   and isinstance(e.get("source_value"), str)
                   and any(_text(e["source_value"]) == _text(value) for value, _ in residual)
                   for e in result.evidence):
            raise ValueError("semantic association requires proof of the residual description/reference")
        selected = mapping[result.selected_ids[0]]
        checked = self.catalog.resolve(replace(structural_query, po_reference=selected.order.po,
            po_item=selected.order.item), invoice_date=invoice_date, receipt_as_of=receipt_as_of, state=state)
        if checked.status != "RESOLVED" or checked.selected.order != selected.order:
            raise ValueError("semantic order selection failed structural revalidation")
        proof = tuple(Evidence(document.path, str(e["block_id"]), e.get("image_page") or next(
            b.page for b in document.blocks if b.id == e["block_id"]), str(e["quote"]))
                      for e in result.evidence)
        selected = replace(checked.selected, evidence=(*checked.selected.evidence, *proof))
        reference = POResolution(query, "RESOLVED", selected, pool.candidates,
            selected.order.po != query.po_reference or selected.order.item != query.po_item,
            discarded=pool.discarded)
        return self._finish(reference, state, called=True, result=result, request_hash=request.sha256)
