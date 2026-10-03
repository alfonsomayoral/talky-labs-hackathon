"""Compose deterministic invoice rows with separately recorded model facts."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from kalmora.facts import DocumentFacts, Evidence, Fact
from .contracts import ParsedDocument, fingerprint
from .native_table import NativeTableResult, extract_native_table
from .native_timesheet import extract_native_timesheet

COMPOSITION_VERSION = 'native-invoice-composition-v1'


@dataclass(frozen=True)
class NativeInvoiceComposition:
    facts: DocumentFacts
    provenance: dict


def compose_native_invoice(document: ParsedDocument, extracted: DocumentFacts,
                           table: NativeTableResult | None = None, *,
                           project_recorded_rows: bool = False) -> NativeInvoiceComposition:
    """Preserve non-invoice facts and attach independently parsed literal rows.

    Normal callers record the model with ``outside_native_invoice_table`` scope.
    Explicit projection can migrate an old full capture: its row fields are
    listed as superseded, the original facts remain fingerprinted, and callers
    must retain the original capture. A new version never masquerades as that
    raw model result. Supplemental detail/statement facts remain unchanged.
    """
    if extracted.source_sha256 != document.source_sha256:
        raise ValueError('model facts refer to a different original source')
    verified = extract_native_table(document)
    if table is not None and table != verified:
        raise ValueError('native table does not match the prepared source')
    table = verified
    if table.status != 'complete' or not table.rows or document.images:
        raise ValueError('native invoice table is not safely complete')
    excluded = sorted(name for name in extracted.fields
                      if name.startswith('line.') or name == 'line_count')
    if excluded and not project_recorded_rows:
        raise ValueError('model invoice rows require explicit archived-capture projection')
    fields = {name: list(values) for name, values in extracted.fields.items() if name not in excluded}
    native_fields = table.to_facts(document)
    timesheet = extract_native_timesheet(document)
    timesheet_composed = (timesheet.status == 'complete' and not any(
        fact.evidence.page not in timesheet.table_pages
        for name, values in extracted.fields.items() if name.startswith('detail_lines.')
        for fact in values))
    if timesheet_composed:
        excluded += sorted(name for name in extracted.fields
                           if name.startswith('detail_lines.') or name == 'detail_line_count')
        fields = {name: list(values) for name, values in extracted.fields.items() if name not in excluded}
        native_fields.update(timesheet.to_facts(document))
    fields.update(native_fields)
    first = table.rows[0]
    fields['line_count'] = [Fact(len(table.rows), Evidence(document.path,
        f'page.{first.page}', first.page, first.quote))]
    provenance = {
        'composition_version': COMPOSITION_VERSION,
        'source_sha256': document.source_sha256,
        'transformation_sha256': document.transformation_sha256,
        'native_parser_version': 'native-invoice-table-v1',
        'native_table_sha256': fingerprint(asdict(table)),
        'recorded_model_extractor_version': extracted.extractor_version,
        'recorded_model_facts_sha256': fingerprint(extracted.to_dict()),
        'superseded_model_fields': excluded,
        'native_fields': sorted(native_fields),
        'derived_fields': {'line_count': {'method': 'count_physical_native_invoice_rows',
                           'row_count': len(table.rows)}},
        'composed_invoice_rows_origin': 'deterministic_native_source',
    }
    if timesheet_composed:
        first_detail = timesheet.rows[0]
        fields['detail_line_count'] = [Fact(len(timesheet.rows), Evidence(document.path,
            f'page.{first_detail.page}', first_detail.page, first_detail.row_quote))]
        provenance.update(native_timesheet_parser_version='native-timesheet-v1',
                          native_timesheet_sha256=fingerprint(asdict(timesheet)))
        provenance['derived_fields']['detail_line_count'] = {
            'method': 'count_physical_native_timesheet_rows', 'row_count': len(timesheet.rows)}
    version = f'{COMPOSITION_VERSION}:{fingerprint(provenance)}'
    return NativeInvoiceComposition(DocumentFacts(document.source_sha256, version, fields), provenance)
