"""Conservative extraction of explicit rows from native-layout PDF tables.

The parser only handles printed invoice tables with a recognizable five-column
header and a physical row whose final columns are quantity, known unit, price,
and amount. It never reads OCR aids or joins wrapped text into a guessed row.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from kalmora.facts import Evidence, Fact
from .contracts import ParsedDocument


_UNIT = (
    r"(?:t|tn|ton|tons|tonelada|toneladas|h|hr|hrs|hora|horas|kg|kgs|kilogramo|kilogramos|"
    r"m|ml|km|m2|m²|m3|m³|u|ud|uds|un|uns|unidad|unidades|unit|units|pieza|piezas|pza|pzas|"
    r"caja|cajas|caixa|caixas|saco|sacos|pa|lote|lotes|día|dias|dia|mes|meses|servicio|servicios|viaje|viajes)"
    r"\.?"
)
_QUANTITY = r"[+-]?\d[\d.,]*"
_MONEY = r"[+-]?(?:\d{1,3}(?:[.,]\d{3})*|\d+)[.,]\d{2}"
_ROW = re.compile(
    rf"(?<!\S)(?P<quantity>{_QUANTITY})\s+(?P<unit>{_UNIT})\s+"
    rf"(?P<unit_price>{_MONEY})\s+(?P<amount>{_MONEY})"
    r"(?:\s*(?:EUR|MXN|USD|€|\$))?\s*$",
    re.IGNORECASE,
)
_ROWISH = re.compile(
    rf"(?<!\S){_QUANTITY}\s+{_UNIT}(?:\s+\S+){{0,4}}\s*$",
    re.IGNORECASE,
)
_SUMMARY = re.compile(
    r"^\s*(?:base\s+(?:imponible|impositiva|taxable)|subtotal|iva\b|impuesto\b|"
    r"total\s+(?:factura|a\s+pagar|liquidado|due|payable)|total\b|importe\s+total|"
    r"grand\s+total|tax\b|incidencia\b|certificado\s+a\s+origen\b|"
    r"certificado\s+anterior\b|importe\s+de\s+esta\s+certificacion\b)",
    re.IGNORECASE,
)
_ROW_FIELD = re.compile(r"^(?:line|lines|detail_lines)\.(\d+)\.")
_DELIVERY_REFERENCE = re.compile(r"(?<![A-Za-z0-9])(?:AL|GR)-\d+(?!\d)")
_PAGE_FOOTER = re.compile(r"^\s*(?:p[aá]gina|page)\s+\d+\s*$", re.IGNORECASE)
_LEGAL_FOOTER = re.compile(
    r"^\s*[^·]{2,120},\s*S\.L\.U\.\s*·\s*[^·]{3,100}\s*·\s*"
    r"\d{5}\s+[^·]{2,100}\s*·\s*[A-Z]\d{8}\s*$",
    re.IGNORECASE,
)
_SYNTHETIC_FOOTER = re.compile(
    r"^\s*synthetic test document\s*[–—-]\s*no fiscal validity\s*$",
    re.IGNORECASE,
)
_SUPPLEMENTAL_TIMESHEET = re.compile(
    r"^\s*parte\s+de\s+trabajo\s*/\s*hoja\s+de\s+horas\s*$",
    re.IGNORECASE,
)
_CODE_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]*$")
_CODE_PREFIX = re.compile(
    r"^(?P<material>[A-Z0-9][A-Z0-9._/-]*)(?P<separator>\s{2,})"
    r"(?P<description>\S(?:.*\S)?)\s*$"
)


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _header(text: str) -> bool:
    tokens = list(re.finditer(r"[a-z0-9]+", _plain(text)))
    positions = [
        [match.start() for match in tokens if match.group() in labels]
        for labels in (
            {"descripcion", "descricao", "description"},
            {"cant", "cantidad", "quantity", "qty", "qtd"},
            {"ud", "uds", "un", "uns", "unidad", "unidades", "unit", "units"},
            {"precio", "preco", "price"},
            {"importe", "amount", "valor"},
        )
    ]
    if any(not group for group in positions):
        return False
    previous = -1
    for group in positions:
        following = next((position for position in group if position > previous), None)
        if following is None:
            return False
        previous = following
    return True


def _has_code_column(text: str) -> bool:
    tokens = list(re.finditer(r"[a-z0-9]+", _plain(text)))
    code_positions = [match.start() for match in tokens if match.group() in {"codigo", "code"}]
    description_positions = [match.start() for match in tokens
                             if match.group() in {"descripcion", "descricao", "description"}]
    return bool(_header(text) and code_positions and description_positions
                and min(code_positions) < min(description_positions))


def _native_pages(document: ParsedDocument) -> dict[int, str]:
    """Return only canonical page-layout blocks emitted by the source router."""
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
class NativeTableRow:
    """One row with explicit values copied from a single physical source line."""

    index: int
    page: int
    description: str
    quantity: str
    unit: str
    unit_price: str
    amount: str
    quote: str
    material: str | None = None
    delivery_reference: str | None = None

    def facts(self, document: ParsedDocument) -> dict[str, Fact]:
        evidence = lambda: Evidence(document.path, f"page.{self.page}", self.page, self.quote)
        fields = {
            f"line.{self.index}.description": Fact(self.description, evidence()),
            f"line.{self.index}.quantity": Fact(self.quantity, evidence()),
            f"line.{self.index}.uom": Fact(self.unit, evidence()),
            f"line.{self.index}.unit_price": Fact(self.unit_price, evidence()),
            f"line.{self.index}.amount": Fact(self.amount, evidence()),
        }
        if self.material is not None:
            fields[f"line.{self.index}.material"] = Fact(self.material, evidence())
        if self.delivery_reference is not None:
            fields[f"line.{self.index}.delivery_reference"] = Fact(
                self.delivery_reference, evidence())
        return fields


@dataclass(frozen=True)
class NativeTableResult:
    """Rows plus an explicit statement about whether parsing was complete."""

    status: str
    rows: tuple[NativeTableRow, ...] = ()
    expected_count: int | None = None
    reason: str | None = None
    table_pages: tuple[int, ...] = ()

    def to_facts(self, document: ParsedDocument) -> dict[str, list[Fact]]:
        """Return source-cited line facts only when the whole detected table is clear."""
        if self.status != "complete":
            return {}
        fields: dict[str, list[Fact]] = {}
        for row in self.rows:
            for field, fact in row.facts(document).items():
                fields.setdefault(field, []).append(fact)
        return fields


def _looks_like_row(line: str) -> bool:
    return _ROW.search(line) is not None


def _explicit_footer(line: str) -> bool:
    return bool(_PAGE_FOOTER.fullmatch(line) or _LEGAL_FOOTER.fullmatch(line)
                or _SYNTHETIC_FOOTER.fullmatch(line))


def _parse_row(line: str, *, index: int, page: int,
               has_code_column: bool = False) -> NativeTableRow | None:
    match = _ROW.search(line)
    if match is None:
        return None
    description = line[:match.start()].strip()
    material = None
    if has_code_column:
        code = _CODE_PREFIX.fullmatch(description)
        if code is not None and _CODE_TOKEN.fullmatch(code.group("material")):
            material = code.group("material")
            description = code.group("description")
    # Requiring explicit alphabetic description text avoids interpreting a
    # numeric footer or an orphaned quantity/price/amount as an item row.
    if not description or not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", description):
        return None
    return NativeTableRow(
        index=index,
        page=page,
        description=description,
        quantity=match.group("quantity"),
        unit=match.group("unit"),
        unit_price=match.group("unit_price"),
        amount=match.group("amount"),
        quote=line,
        material=material,
        delivery_reference=(
            references[0] if len(references := _DELIVERY_REFERENCE.findall(description)) == 1
            else None
        ),
    )


def _parse_page_rows(text: str, *, page: int, start_index: int,
                     has_local_header: bool) -> tuple[list[NativeTableRow], bool]:
    lines = text.splitlines()
    if any(_SUPPLEMENTAL_TIMESHEET.fullmatch(_plain(line)) for line in lines[:5]):
        return [], False
    header_positions = [i for i, line in enumerate(lines) if _header(line)]
    start = min(header_positions) + 1 if header_positions else 0
    has_code_column = any(_has_code_column(lines[index]) for index in header_positions)
    rows: list[NativeTableRow] = []
    ambiguous = False
    seen_row = False
    pending_text = False
    footer_seen = False
    for line in lines[start:]:
        if _SUMMARY.search(_plain(line)):
            break
        if not line.strip() or _header(line):
            continue
        if _explicit_footer(line):
            footer_seen = True
            continue
        parsed = _parse_row(line, index=start_index + len(rows), page=page,
                            has_code_column=has_code_column)
        if parsed is not None:
            if pending_text or footer_seen:
                ambiguous = True
            pending_text = False
            rows.append(parsed)
            seen_row = True
            continue
        if _ROWISH.search(line):
            # A quantity/unit tail with an unsupported numeric shape is a row
            # candidate, but the parser cannot safely emit its fields.
            ambiguous = True
        elif line.strip():
            # Any unparsed content after a row may be a wrapped description,
            # including a numeric-only continuation at end of page. Keep it
            # pending so it can never be silently discarded as a complete row.
            # Summary totals above are the only recognized boundary here.
            pending_text = pending_text or seen_row or has_local_header
    if pending_text:
        ambiguous = True
    return rows, ambiguous


def extract_native_table(document: ParsedDocument) -> NativeTableResult:
    """Extract a narrow, source-bound native PDF table without model inference.

    Supported rows occupy one physical layout line and end in explicit
    quantity, known unit, unit price, and amount columns. Description wrapping,
    malformed number columns, or unexplained text inside the table produce an
    ``ambiguous`` result. ``to_facts`` then abstains rather than emitting a
    partial table. Pages without native text and files without a recognized
    table header are ``not_applicable``.
    """
    if document.images or any(warning.endswith(":vision_required")
                              for warning in document.warnings):
        return NativeTableResult("ambiguous", reason="document_requires_vision")

    pages = _native_pages(document)
    text_pages = {page: text for page, text in sorted(pages.items()) if text.strip()}
    if not text_pages:
        return NativeTableResult("not_applicable", reason="no_native_page_text")

    header_pages = tuple(page for page, text in text_pages.items()
                         if any(_header(line) for line in text.splitlines()))
    if not header_pages:
        return NativeTableResult("not_applicable", reason="no_recognized_table_header")

    rows: list[NativeTableRow] = []
    ambiguous_pages: list[int] = []
    for page, text in text_pages.items():
        local_header = page in header_pages
        page_rows, ambiguous = _parse_page_rows(
            text, page=page, start_index=len(rows) + 1, has_local_header=local_header)
        rows.extend(page_rows)
        if ambiguous:
            ambiguous_pages.append(page)

    if not rows:
        return NativeTableResult(
            "ambiguous", (), 0, "header_without_supported_rows", header_pages)
    if ambiguous_pages:
        return NativeTableResult(
            "ambiguous", tuple(rows), len(rows),
            "unsupported_or_wrapped_table_text_on_pages:" + ",".join(map(str, ambiguous_pages)),
            header_pages,
        )
    return NativeTableResult("complete", tuple(rows), len(rows), None, header_pages)
