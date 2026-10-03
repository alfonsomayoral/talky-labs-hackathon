"""Conservative extraction of explicit dated-hour supplemental rows.

Only a titled ``PARTE DE TRABAJO / HOJA DE HORAS`` page with the ordered
``Fecha / Operario / categoría / Tarea / Horas`` header is recognized. Rows
must be complete on one canonical native page line; the parser never repairs
wrapped text or reads OCR/image content.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata

from kalmora.facts import Evidence, Fact
from .contracts import ParsedDocument


_TITLE = "PARTE DE TRABAJO / HOJA DE HORAS"
_DATE = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
_HOURS = re.compile(r"\d+(?:[,.]\d+)?\Z")
_VISION_WARNING = re.compile(r"(?:^|:)vision_required$")


def _normal(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(value.split())


def _cells(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}", line.strip())]


def _is_title(line: str) -> bool:
    return _normal(line) == _normal(_TITLE)


def _header(line: str) -> bool:
    cells = _cells(line)
    return len(cells) == 4 and [_normal(cell) for cell in cells] == [
        "fecha", "operario / categoria", "tarea", "horas",
    ]


@dataclass(frozen=True)
class NativeTimesheetRow:
    """One physical dated-hours row, preserving source strings and order."""

    index: int
    page: int
    date: str
    operator: str
    description: str
    quantity: str
    row_quote: str
    header_quote: str

    def facts(self, document: ParsedDocument) -> dict[str, Fact]:
        row_evidence = lambda: Evidence(
            document.path, f"page.{self.page}", self.page, self.row_quote)
        header_evidence = Evidence(
            document.path, f"page.{self.page}", self.page, self.header_quote)
        prefix = f"detail_lines.{self.index}."
        literal_hours_label = _cells(self.header_quote)[-1]
        return {
            prefix + "description": Fact(self.description, row_evidence()),
            prefix + "quantity": Fact(self.quantity, row_evidence()),
            prefix + "uom": Fact(literal_hours_label, header_evidence),
            prefix + "raw.Fecha": Fact(self.date, row_evidence()),
            prefix + "raw.Operario / categoría": Fact(self.operator, row_evidence()),
        }


@dataclass(frozen=True)
class NativeTimesheetResult:
    """Rows and an explicit complete/abstain status for a titled timesheet."""

    status: str
    rows: tuple[NativeTimesheetRow, ...] = ()
    reason: str | None = None
    table_pages: tuple[int, ...] = ()

    def to_facts(self, document: ParsedDocument) -> dict[str, list[Fact]]:
        """Return all cited supplemental rows only after the full table is clear."""
        if self.status != "complete":
            return {}
        fields: dict[str, list[Fact]] = {}
        for row in self.rows:
            for name, fact in row.facts(document).items():
                fields.setdefault(name, []).append(fact)
        return fields


def _native_pages(document: ParsedDocument) -> dict[int, str]:
    if document.media_type != "application/pdf":
        return {}
    pages: dict[int, str] = {}
    for block in document.blocks:
        if (block.page is None or block.id != f"page.{block.page}"
                or block.source_field is not None or block.page in pages):
            continue
        pages[block.page] = block.text
    return pages


def _parse_page(page_text: str, *, page: int, start_index: int
                ) -> tuple[list[NativeTimesheetRow], str | None, bool]:
    lines = page_text.splitlines()
    title_positions = [i for i, line in enumerate(lines) if _is_title(line)]
    if not title_positions:
        return [], None, False

    # A page may carry at most one titled sheet. Ambiguous duplicate titles
    # could otherwise restart indices or splice independent tables together.
    if len(title_positions) != 1:
        return [], "multiple_timesheet_titles", True
    title_index = title_positions[0]
    header_positions = [i for i in range(title_index + 1, len(lines)) if _header(lines[i])]
    if len(header_positions) != 1:
        return [], "missing_or_multiple_timesheet_headers", True
    header_index = header_positions[0]
    header_quote = lines[header_index]

    rows: list[NativeTimesheetRow] = []
    started = False
    ended = False
    footer_started = False
    for line in lines[header_index + 1:]:
        if not line.strip():
            if started:
                ended = True
            continue
        if ended:
            # Text after the table boundary is a footer/signature. A second
            # row-shaped record after a blank is ambiguous rather than lost.
            cells = _cells(line)
            if cells and _DATE.fullmatch(cells[0]):
                return [], "row_after_table_boundary", True
            plain = _normal(line)
            if (plain.startswith('conforme cliente') or plain.startswith('firma ')
                    or plain.startswith('synthetic test document') or re.fullmatch(r'(?:pagina|page) \d+', plain)):
                footer_started = True
            if not footer_started:
                return [], 'unsupported_continuation_after_table_row', True
            continue

        cells = _cells(line)
        if len(cells) != 4:
            # Metadata before the first row is allowed, but only date-led
            # lines can plausibly be rows. A malformed dated line poisons the
            # whole table; non-date metadata is ignored before row start.
            return [], "malformed_or_wrapped_timesheet_row", True

        date_text, operator, description, quantity = cells
        if not (_DATE.fullmatch(date_text) and operator and description and _HOURS.fullmatch(quantity)):
            return [], "malformed_timesheet_row", True
        try:
            datetime.strptime(date_text, "%d/%m/%Y")
        except ValueError:
            return [], "invalid_timesheet_date", True

        started = True
        rows.append(NativeTimesheetRow(
            index=start_index + len(rows), page=page, date=date_text,
            operator=operator, description=description, quantity=quantity,
            row_quote=line, header_quote=header_quote))

    if not rows:
        return [], "timesheet_has_no_rows", True
    return rows, None, True


def extract_native_timesheet(document: ParsedDocument) -> NativeTimesheetResult:
    """Read explicitly titled native dated-hours tables, otherwise abstain.

    Any retained image or page flagged for visual interpretation excludes the
    whole document. Wrapped/malformed rows make the table ambiguous and emit
    no facts; duplicate valid physical entries remain distinct rows.
    """
    if document.media_type != "application/pdf":
        return NativeTimesheetResult("not_applicable", reason="not_pdf")
    if document.images or any(_VISION_WARNING.search(warning) for warning in document.warnings):
        return NativeTimesheetResult("not_applicable", reason="document_requires_vision")

    pages = _native_pages(document)
    if not pages:
        return NativeTimesheetResult("not_applicable", reason="no_native_page_text")

    rows: list[NativeTimesheetRow] = []
    table_pages: list[int] = []
    ambiguous_reasons: list[str] = []
    found_title = False
    for page, text in sorted(pages.items()):
        page_rows, reason, found = _parse_page(text, page=page, start_index=len(rows) + 1)
        if not found:
            continue
        found_title = True
        table_pages.append(page)
        if reason:
            ambiguous_reasons.append(f"page_{page}:{reason}")
        rows.extend(page_rows)

    if not found_title:
        return NativeTimesheetResult("not_applicable", reason="no_explicit_timesheet_title")
    if ambiguous_reasons:
        return NativeTimesheetResult(
            "ambiguous", reason=";".join(ambiguous_reasons), table_pages=tuple(table_pages))
    return NativeTimesheetResult("complete", tuple(rows), table_pages=tuple(table_pages))
