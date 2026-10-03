"""Bind posting line observations to independent normalized financial sources.

No source row is inferred from a header, no PDF/XML row amounts are added, and
no unit price is calculated from a net amount or quantity. Eligibility remains
with the ordered policy engines; this boundary checks their source linkage.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import DecimalException
import re

from .ap_allocation import InvoiceQuantityLine
from .ap_document_bridge import APFactSet, APField, APLineFacts
from .ap_holds import PriceLine
from .ap_valuation import ValuationLine
from .documents.contracts import fingerprint, source_path as validate_source_path
from .facts import DocumentFacts, Evidence, Fact
from .money import decimal

LINE_SOURCE_BRIDGE_VERSION = "ap-line-source-bridge-v1"
_ROW = re.compile(r"line\.([1-9]\d*)\.(.+)")


@dataclass(frozen=True)
class APLineSourceBinding:
    line_id: str
    source_path: str
    index: int

    def __post_init__(self):
        if not isinstance(self.line_id, str) or not self.line_id:
            raise ValueError("posting line identity is required")
        object.__setattr__(self, "source_path", validate_source_path(self.source_path))
        if type(self.index) is not int or self.index < 1:
            raise ValueError("source row index must be a positive integer")


@dataclass(frozen=True)
class APLineSourceResult:
    status: str  # CLEAR or UNKNOWN; never an accounting decision
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...]
    bindings: tuple[APLineSourceBinding, ...]
    views: tuple[APLineFacts, ...]
    source_hashes: tuple[tuple[str, str], ...]
    version: str = LINE_SOURCE_BRIDGE_VERSION


def _indexed(items: Iterable, cls, name: str):
    result = {}
    for item in items:
        if not isinstance(item, cls) or not isinstance(item.line_id, str) or not item.line_id:
            raise ValueError(f"{name} requires typed, identified posting lines")
        if item.line_id in result:
            raise ValueError(f"duplicate {name} line identity")
        result[item.line_id] = item
    return result


def _signature(fields) -> str:
    # Type-sensitive canonicalization prevents bool/int or Decimal/int equality
    # from passing off a fabricated view as the accepted source observations.
    return fingerprint({name: [dict(value=f.value, evidence=dict(
        document=f.evidence.document, field=f.evidence.field,
        page=f.evidence.page, quote=f.evidence.quote)) for f in values]
        for name, values in fields.items()})


def _consensus(name: str, fields: Iterable[APField], kind: str) -> APField:
    candidates = tuple(f for field in fields for f in field.candidates)
    return APFactSet({name: candidates}).field(name, kind=kind)


def _net_observation(view: APLineFacts) -> APField:
    net = view.net_cents
    if net.candidates:
        return net  # An explicit net remains distinct from a before-discount amount.
    amount = view.amount_cents
    discount = view.facts.integer("discount_cents")
    if discount.candidates and (not discount.known or discount.value != 0):
        return APField("amount_doc", "UNKNOWN", None, (),
            (*amount.evidence, *discount.evidence), ("SOURCE_NET_BASIS_UNKNOWN_WITH_DISCOUNT",))
    return amount


def validate_ap_line_sources(
    *, bindings: Iterable[APLineSourceBinding], amount_sources: Iterable[DocumentFacts],
    valuation_lines: Iterable[ValuationLine], quantity_lines: Iterable[InvoiceQuantityLine] = (),
    price_lines: Iterable[PriceLine] = (), views: Iterable[APLineFacts] | None = None,
    currency: str | None = None, amounts_required: bool = True,
) -> APLineSourceResult:
    """Check complete row coverage and agreement with exact source observations.

    Independent sources may bind different row indices to the same posting ID.
    Every source row is covered once; missing bindings/required observations and
    source contradictions return UNKNOWN. A resolved source observation that
    disagrees with a caller's posting input raises ValueError before any factory.

    ``amounts_required=False`` permits ordered quantity/price gates to run before
    line amounts are resolved. It still rejects a contradiction with known net.
    Optional ``views`` are checked against the full accepted source row fields
    and Evidence, never treated as another factual authority.
    """
    if type(amounts_required) is not bool:
        raise ValueError("line amount requirement must be an explicit boolean")
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
        raise ValueError("posting currency must be an explicit canonical code")
    bindings = tuple(bindings)
    if any(not isinstance(binding, APLineSourceBinding) for binding in bindings):
        raise ValueError("explicit APLineSourceBinding objects are required")
    valued = _indexed(valuation_lines, ValuationLine, "valuation")
    quantified = _indexed(quantity_lines, InvoiceQuantityLine, "quantity")
    priced = _indexed(price_lines, PriceLine, "price")
    if not set(quantified).issubset(valued) or not set(priced).issubset(valued):
        raise ValueError("quantity and price lines must identify a valued posting line")
    if any(type(line.amount_doc) is not int for line in valued.values()):
        raise ValueError("valued line amounts require exact integer cents")

    notes, proof, headers, hashes, actual = [], [], {}, {}, {}
    for source in amount_sources:
        if not isinstance(source, DocumentFacts):
            raise ValueError("financial sources require normalized DocumentFacts")
        paths = {f.evidence.document for values in source.fields.values() for f in values}
        if not paths:
            notes.append("SOURCE_IDENTITY_UNOBSERVED:" + source.source_sha256)
            continue
        if len(paths) != 1:
            raise ValueError("each independent financial attachment requires one source path")
        path = validate_source_path(next(iter(paths)))
        if path in hashes:
            raise ValueError("a financial attachment cannot be supplied twice")
        hashes[path] = source.source_sha256
        headers[path] = APFactSet(source.fields)
        rows = defaultdict(dict)
        for name, candidates in source.fields.items():
            match = _ROW.fullmatch(name)
            if match:
                rows[int(match[1])][match[2]] = candidates
            elif name.startswith("line."):
                notes.append(f"SOURCE_LINE_NAMESPACE_UNKNOWN:{path}:{name}")
        if not rows:
            notes.append("SOURCE_LINE_INVENTORY_UNOBSERVED:" + path)
        elif sorted(rows) != list(range(1, max(rows) + 1)):
            notes.append("SOURCE_LINE_INDEX_GAP:" + path)
        count = headers[path].integer("line_count")
        if count.candidates:
            proof.extend(count.evidence)
            if not count.known or count.value < 0 or count.value != len(rows):
                notes.append("SOURCE_LINE_COUNT_UNKNOWN_OR_INCOMPLETE:" + path)
        for index, fields in rows.items():
            actual[path, index] = APLineFacts(path, index, APFactSet(fields))

    if views is not None:
        supplied = {}
        for view in views:
            if not isinstance(view, APLineFacts):
                raise ValueError("source views require APLineFacts")
            key = (view.source_path, view.index)
            if key in supplied or key not in actual:
                raise ValueError("source view identity is duplicated or absent from financial sources")
            if _signature(view.facts.fields) != _signature(actual[key].facts.fields):
                raise ValueError("source view fields/evidence differ from accepted financial observations")
            supplied[key] = view
        if set(supplied) != set(actual):
            notes.append("SOURCE_VIEWS_INCOMPLETE")

    by_line, bound, seen_bindings, line_sources = defaultdict(list), set(), set(), set()
    for binding in bindings:
        if binding.line_id not in valued:
            raise ValueError("source binding identifies an unvalued posting line")
        key = (binding.source_path, binding.index)
        if key in seen_bindings:
            raise ValueError("a source row cannot be reused for multiple posting lines or bindings")
        seen_bindings.add(key)
        source_line = (binding.line_id, binding.source_path)
        if source_line in line_sources:
            raise ValueError("a posting line cannot merge distinct rows of one financial source")
        line_sources.add(source_line)
        if key not in actual:
            notes.append(f"SOURCE_ROW_UNOBSERVED:{binding.source_path}:{binding.index}")
            continue
        bound.add(key)
        by_line[binding.line_id].append(actual[key])
    for path, index in sorted(set(actual) - bound):
        notes.append(f"SOURCE_ROW_UNBOUND:{path}:{index}")
    for line_id in valued:
        if not by_line[line_id]:
            notes.append("POSTING_LINE_SOURCE_UNOBSERVED:" + line_id)
    if not valued:
        notes.append("POSTING_LINE_INVENTORY_UNOBSERVED")

    def unknown(field, label):
        proof.extend(field.evidence)
        if not field.known:
            notes.append(f"{label}:{field.status}")
            notes.extend(field.diagnostics)
            return True
        return False

    for line_id, line in valued.items():
        linked = by_line[line_id]
        if not linked:
            continue
        observed_currency = []
        for view in linked:
            row_currency = view.facts.field("currency", kind="currency")
            observed_currency.extend((row_currency,
                headers[view.source_path].field("currency", kind="currency")))
        currencies = _consensus("currency", observed_currency, "currency")
        if currencies.candidates:
            if not unknown(currencies, "SOURCE_LINE_CURRENCY_UNKNOWN:" + line_id):
                if currency is not None and currencies.value != currency:
                    raise ValueError("posting currency contradicts the financial source line")

        source_amounts = tuple(_net_observation(view) for view in linked)
        amount = _consensus("amount_doc", source_amounts, "integer")
        if amounts_required:
            for view, source_amount in zip(linked, source_amounts):
                unknown(source_amount, f"SOURCE_LINE_NET_UNKNOWN:{view.source_path}:{view.index}")
            if not unknown(amount, "SOURCE_LINE_NET_CONSENSUS_UNKNOWN:" + line_id):
                if amount.value != line.amount_doc:
                    raise ValueError("valued amount contradicts the observed financial source line net")
        elif amount.known:
            proof.extend(amount.evidence)
            if amount.value != line.amount_doc:
                raise ValueError("valued amount contradicts the observed financial source line net")

        quantity_line, price_line = quantified.get(line_id), priced.get(line_id)
        needs_quantity = quantity_line is not None or price_line is not None or line.quantity_milli is not None
        if needs_quantity:
            quantity = _consensus("quantity_milli", (view.quantity_milli for view in linked), "integer")
            if not unknown(quantity, "SOURCE_LINE_QUANTITY_UNKNOWN:" + line_id):
                quantities = [line.quantity_milli] if line.quantity_milli is not None else []
                if quantity_line is not None:
                    quantities.append(quantity_line.quantity_milli)
                if price_line is not None:
                    if any(type(portion.quantity_milli) is not int for portion in price_line.portions):
                        raise ValueError("price portion quantities require exact integer thousandths")
                    quantities.append(sum(portion.quantity_milli for portion in price_line.portions))
                if any(type(value) is not int or value != quantity.value for value in quantities):
                    raise ValueError("posting quantity contradicts the observed financial source line")
            if quantity_line is not None:
                uom = _consensus("uom", (view.uom for view in linked), "text")
                if not unknown(uom, "SOURCE_LINE_UOM_UNKNOWN:" + line_id):
                    if quantity_line.uom != uom.value:
                        raise ValueError("posting unit contradicts the observed financial source line")

        if price_line is not None:
            price = _consensus("unit_price_cents", (view.unit_price_cents for view in linked), "decimal")
            if not unknown(price, "SOURCE_LINE_UNIT_PRICE_UNKNOWN:" + line_id):
                candidates = []
                for fact in price_line.invoice_unit_price_cents:
                    if not isinstance(fact, Fact):
                        raise ValueError("invoice price observations require Fact/Evidence")
                    try:
                        value = None if fact.value is None else decimal(fact.value)
                    except (TypeError, ValueError, DecimalException):
                        raise ValueError("invoice price observations require exact finite numbers") from None
                    candidates.append(Fact(value, fact.evidence))
                supplied_price = APFactSet({"unit_price_cents": candidates}).field("unit_price_cents", kind="decimal")
                if not unknown(supplied_price, "POSTING_LINE_UNIT_PRICE_UNKNOWN:" + line_id):
                    if supplied_price.value != price.value:
                        raise ValueError("invoice price check contradicts the observed financial source line")

    return APLineSourceResult("UNKNOWN" if notes else "CLEAR", tuple(dict.fromkeys(proof)),
        tuple(dict.fromkeys(notes)), bindings, tuple(actual[key] for key in sorted(actual)),
        tuple(sorted(hashes.items())))
