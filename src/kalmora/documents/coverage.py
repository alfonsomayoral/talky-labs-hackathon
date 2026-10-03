"""Source-only checks for high-confidence native PDF table-row omissions.

This diagnostic counts printed rows only when a native page layout contains a
table header and a row ends with quantity, known unit, unit price, and amount.
It does not inspect OCR aids or infer rows from expected labels.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Mapping, Sequence

from .contracts import ParsedDocument


_ROW_FIELD = re.compile(r"^(?:line|lines|detail_lines)\.(\d+)\.")
_UNIT = (
    r"(?:t|tn|ton|tons|tonelada|toneladas|h|hr|hrs|hora|horas|kg|kgs|kilogramo|kilogramos|"
    r"m|ml|km|m2|m²|m3|m³|u|ud|uds|unidad|unidades|unit|units|pieza|piezas|pza|pzas|"
    r"caja|cajas|lote|lotes|día|dias|dia|mes|meses|servicio|servicios|viaje|viajes)"
    r"\.?"
)
_QUANTITY = r"[+-]?\d[\d.,]*"
_MONEY = r"[+-]?\d[\d.,]*[.,]\d{2}"
_ROW_SUFFIX = re.compile(
    rf"(?<!\S)({_QUANTITY})\s+({_UNIT})\s+({_MONEY})\s+({_MONEY})"
    r"(?:\s*(?:EUR|MXN|USD|€|\$))?\s*$",
    re.IGNORECASE)
_SUMMARY = re.compile(
    r"^\s*(?:base\s+(?:imponible|impositiva|taxable)|subtotal|iva\b|impuesto\b|"
    r"total\s+(?:factura|a\s+pagar|liquidado|due|payable)|importe\s+total|grand\s+total|tax\b)",
    re.IGNORECASE)


def _plain(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _has_table_header(text: str) -> bool:
    """Recognize a narrow Spanish or English invoice-column heading."""
    words = set(re.findall(r"[a-z0-9]+", _plain(text)))
    description = bool(words & {"descripcion", "description"})
    quantity = bool(words & {"cant", "cantidad", "quantity", "qty"})
    unit = bool(words & {"ud", "unidad", "unidades", "unit", "units"})
    price = bool(words & {"precio", "price"})
    amount = bool(words & {"importe", "amount"})
    return description and quantity and unit and price and amount


def _source_row_count(text: str) -> int:
    lines = text.splitlines()
    header_lines = [index for index, line in enumerate(lines) if _has_table_header(line)]
    # A native header bounds the table start. Headerless later pages are
    # continuations. Totals end the item region and prevent prose below them
    # from looking like another numerical row.
    start = min(header_lines) + 1 if header_lines else 0
    count = 0
    for line in lines[start:]:
        if _SUMMARY.search(_plain(line)):
            break
        if _ROW_SUFFIX.search(line):
            count += 1
    return count


def _native_page_blocks(document: ParsedDocument) -> dict[int, str]:
    """Use only the router's original ``page.N`` PDF layout blocks.

    Other block IDs and image/OCR-derived content are intentionally excluded.
    A canonical page block is accepted once, so duplicate visitor-like blocks
    cannot multiply the source row count.
    """
    if document.media_type != "application/pdf":
        return {}
    pages: dict[int, str] = {}
    for block in document.blocks:
        if (block.page is None or block.id != f"page.{block.page}"
                or block.source_field is not None or block.page in pages):
            continue
        pages[block.page] = block.text
    return pages


@dataclass(frozen=True)
class NativeRowCoverage:
    status: str
    expected_count: int | None
    observed_count: int
    missing_count: int
    table_pages: tuple[int, ...] = ()
    source_row_counts: tuple[tuple[int, int], ...] = ()
    observed_row_counts: tuple[tuple[int, int], ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "expected_count": self.expected_count,
            "observed_count": self.observed_count,
            "missing_count": self.missing_count,
            "table_pages": list(self.table_pages),
            "source_row_counts": {str(page): count for page, count in self.source_row_counts},
            "observed_row_counts": {str(page): count for page, count in self.observed_row_counts},
            "reason": self.reason,
        }


def native_row_coverage(
    document: ParsedDocument,
    facts: Mapping[str, Sequence[object]] | Sequence[str],
) -> NativeRowCoverage:
    """Compare native table-row candidates with returned line-group IDs.

    ``facts`` may be the extractor's field-to-facts mapping (facts with an
    ``evidence.page`` attribute) or just field names. A source row is counted
    once for every matching native layout line, including identical printed
    rows at different positions. ``complete`` only means that no detected
    source row is missing; it does not certify field accuracy or table recall.
    """
    if document.media_type != "application/pdf":
        return NativeRowCoverage("not_applicable", None, 0, 0, reason="not_pdf")

    pages = _native_page_blocks(document)
    text_pages = {page: text for page, text in pages.items() if text.strip()}
    if not text_pages:
        return NativeRowCoverage("not_applicable", None, 0, 0, reason="no_native_page_text")

    if not any(_has_table_header(text) for text in text_pages.values()):
        return NativeRowCoverage("not_applicable", None, 0, 0, reason="no_recognized_table_header")

    # Once a table header is present, scan every native page. This includes
    # continued table pages where the source omits a repeated header.
    per_page = {page: _source_row_count(text) for page, text in sorted(text_pages.items())}
    table_pages = tuple(page for page, count in per_page.items() if count)
    expected = sum(per_page.values())

    if isinstance(facts, Mapping):
        field_items = facts.items()
    else:
        field_items = ((name, ()) for name in facts)
    observed_by_page: dict[int | None, set[int]] = {}
    observed_ids: set[int] = set()
    for name, values in field_items:
        match = _ROW_FIELD.match(name)
        if match is None:
            continue
        row_id = int(match.group(1))
        observed_ids.add(row_id)
        for fact in values:
            page = getattr(getattr(fact, "evidence", None), "page", None)
            if page is not None:
                observed_by_page.setdefault(page, set()).add(row_id)

    observed = len(observed_ids)
    missing = max(expected - observed, 0)
    status = "incomplete" if missing else "complete"
    source_counts = tuple((page, count) for page, count in per_page.items() if count)
    observed_counts = tuple((page, len(row_ids)) for page, row_ids in sorted(observed_by_page.items())
                            if page is not None and row_ids)
    return NativeRowCoverage(
        status, expected, observed, missing, table_pages, source_counts, observed_counts,
        "native_table_rows_missing" if missing else None,
    )
