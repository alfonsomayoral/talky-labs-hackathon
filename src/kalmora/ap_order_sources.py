"""Observed document rows/PO portions to deterministic order queries (#43).

Identity is supplied by the identity resolver. No supplier, unit, quantity,
approval or MULTI_PO distribution is inferred from prices or ERP capacity.
"""
from dataclasses import dataclass
import re

from .ap_orders import POQuery, POQueryLine, validate_query_lines
from .documents.normalization import normalize_document_facts
from .facts import DocumentFacts, Evidence, Fact


@dataclass(frozen=True)
class DocumentOrderQueries:
    status: str  # READY or UNKNOWN; UNKNOWN is never a partial invoice approval
    source_sha256: str
    invoice_date: str | None
    lines: tuple[POQueryLine, ...]
    diagnostics: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


def order_queries_from_facts(facts: DocumentFacts, *, company: str, vendor: str,
                             currency: str) -> DocumentOrderQueries:
    """Accept canonical flat rows or observed `lines`/`po_portions` dictionaries.

    Nested portions must carry their own positive quantity (or quantity_milli).
    Flatten before the existing normalizer so locale/precision/conflicts have the
    same meaning as other document consumers. Evidence stays on the source fact.
    """
    if not isinstance(facts, DocumentFacts):
        raise TypeError("source DocumentFacts required")
    for value in (company, vendor, currency):
        if not isinstance(value, str) or not value:
            raise ValueError("resolved company/vendor/currency required")
    fields: dict[str, list[Fact]] = {}
    early = []
    def add(key, fact):
        prefix, separator, leaf = key.rpartition(".")
        # Existing extractor vocabulary: a reference is still only a printed
        # lookup constraint, never proof that the delivery was received.
        leaf = {"receipt_reference": "receipt_references", "project_reference": "project"}.get(leaf, leaf)
        key = prefix + separator + leaf
        fields.setdefault(key, []).append(fact)
    def row(prefix, values, proof):
        if not isinstance(values, dict):
            early.append(prefix + ":INVALID_ROW")
            return
        for key, value in values.items():
            if key == "po_portions":
                if not isinstance(value, list) or not value:
                    early.append(prefix + ":PORTIONS_UNKNOWN")
                else:
                    for index, portion in enumerate(value, 1):
                        row(prefix + f".portion.{index}", portion, proof)
            else:
                add(prefix + "." + key, Fact(value, proof))
    for key, candidates in facts.fields.items():
        for fact in candidates:
            if key == "lines" and isinstance(fact.value, list):
                for index, values in enumerate(fact.value, 1):
                    row(f"line.{index}", values, fact.evidence)
            elif re.fullmatch(r"line\.\d+\.po_portions", key):
                row(key.rsplit(".", 1)[0], {"po_portions": fact.value}, fact.evidence)
            else:
                add(key, fact)
    normalized = normalize_document_facts(DocumentFacts(facts.source_sha256, facts.extractor_version, fields))
    diagnostics = [*early, *(f"{d.field}:{d.code}" for d in normalized.diagnostics
                           if d.code != "ROUNDED_HALF_UP")]
    fields = normalized.facts.fields
    proof: list[Evidence] = []
    def value(key, default=None):
        candidates = fields.get(key, ())
        if not candidates:
            return default
        proof.extend(f.evidence for f in candidates)
        if key in normalized.conflicts:
            raise ValueError(key + ":CONFLICT")
        return candidates[0].value
    def literal(key, fallback=None):
        result = value(key, fallback)
        if result is not None and (not isinstance(result, str) or not result.strip()):
            raise ValueError(key + ":LITERAL_UNKNOWN")
        return result
    def quantity(key):
        result = value(key)
        if type(result) is not int or result <= 0:
            raise ValueError(key + ":POSITIVE_QUANTITY_UNKNOWN")
        return result
    def position(key):
        result = value(key)
        if isinstance(result, str) and result.isascii() and result.isdigit():
            result = int(result)
        if result is not None and (type(result) is not int or result <= 0):
            raise ValueError(key + ":POSITION_UNKNOWN")
        return result
    def references(prefix):
        refs = []
        prefix = prefix + "." if prefix else ""
        for key in (prefix + "receipt_references", prefix + "delivery_reference"):
            observed = value(key)
            if observed is None:
                continue
            observed = [observed] if isinstance(observed, str) else observed
            if (not isinstance(observed, list) or not observed
                    or any(not isinstance(v, str) or not v for v in observed)):
                raise ValueError(key + ":REFERENCES_UNKNOWN")
            refs.extend(observed)
        for key in sorted(fields):
            if re.fullmatch(re.escape(prefix) + r"delivery\.\d+\.document_number", key):
                refs.append(literal(key))
        return tuple(dict.fromkeys(refs))
    invoice_date, lines = None, []
    try:
        invoice_date = literal("document_date")
        if invoice_date is None:
            raise ValueError("document_date:UNKNOWN")
        observed_currency = literal("currency")
        if observed_currency != currency:
            raise ValueError("currency:IDENTITY_SCOPE_MISMATCH_OR_UNKNOWN")
        header_po, project = literal("po_reference"), literal("project")
        header_refs = references("")
        indices = sorted({int(m[1]) for key in fields if (m := re.match(r"line\.(\d+)\.", key))})
        count = value("line_count", len(indices))
        if isinstance(count, str) and count.isascii() and count.isdigit():
            count = int(count)
        if type(count) is not int or count <= 0 or indices != list(range(1, count + 1)):
            raise ValueError("lines:INCOMPLETE_OBSERVED_ROWS")
        for index in indices:
            prefix = f"line.{index}"
            total, uom = quantity(prefix + ".quantity_milli"), literal(prefix + ".uom")
            if uom is None:
                raise ValueError(prefix + ":UNIT_UNKNOWN")
            if literal(prefix + ".currency", currency) != currency:
                raise ValueError(prefix + ":CURRENCY_SCOPE_MISMATCH")
            parts = sorted({int(m[1]) for key in fields
                if (m := re.match(re.escape(prefix) + r"\.portion\.(\d+)\.", key))})
            if parts and parts != list(range(1, len(parts) + 1)):
                raise ValueError(prefix + ":INCOMPLETE_OBSERVED_PORTIONS")
            line_po = literal(prefix + ".po_reference", header_po)
            line_refs = references(prefix)
            if count == 1 and not parts:
                line_refs = tuple(dict.fromkeys((*line_refs, *header_refs)))
            if parts and line_refs:
                # References of the whole row do not identify a particular split.
                raise ValueError(prefix + ":RECEIPT_PORTION_BINDING_UNKNOWN")
            portions = []
            for part in parts or [1]:
                p = prefix + f".portion.{part}" if parts else prefix
                po = literal(p + ".po_reference", line_po)
                if po is not None and po.upper() == "MULTI_PO":
                    raise ValueError(p + ":MULTI_PO_PORTIONS_UNKNOWN")
                part_uom = literal(p + ".uom", uom)
                if part_uom != uom:
                    raise ValueError(p + ":UNIT_MISMATCH")
                if literal(p + ".currency", currency) != currency:
                    raise ValueError(p + ":CURRENCY_SCOPE_MISMATCH")
                q = quantity(p + ".quantity_milli") if parts else total
                material = literal(p + ".material", literal(prefix + ".material"))
                description = literal(p + ".description", literal(prefix + ".description"))
                part_project = literal(p + ".project", literal(prefix + ".project", project))
                item = position(p + ".po_item")
                refs = references(p) if parts else line_refs
                # Includes line total and the original relation/quantity proofs.
                portions.append(POQuery(prefix, company, vendor, currency, q, uom,
                    tuple(dict.fromkeys(proof)), str(part), po, item, refs,
                    part_project, material, description))
            lines.append(POQueryLine(prefix, total, uom, tuple(portions)))
        bound_refs = {ref for line in lines for q in line.portions for ref in q.receipt_references}
        if not set(header_refs) <= bound_refs:
            raise ValueError("header_receipts:OBSERVED_LINE_BINDING_UNKNOWN")
        validate_query_lines(lines)
    except ValueError as error:
        diagnostics.append(str(error))
    if diagnostics:
        # No apparently successful subset may be used as a complete invoice.
        return DocumentOrderQueries("UNKNOWN", facts.source_sha256, invoice_date, (),
            tuple(dict.fromkeys(diagnostics)), tuple(dict.fromkeys(proof)))
    return DocumentOrderQueries("READY", facts.source_sha256, invoice_date, tuple(lines),
                               evidence=tuple(dict.fromkeys(proof)))
