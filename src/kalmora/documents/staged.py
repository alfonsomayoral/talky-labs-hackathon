"""Compose separately recorded header/table stages without a provider import.

Each stage must pass its own recording boundary. A failed table stage never
turns a successful header stage into a complete document; the recorded header
remains available for diagnosis and an explicitly authorized retry.
"""
from dataclasses import dataclass
from decimal import Decimal

from kalmora.facts import DocumentFacts
from .contracts import ParsedDocument, fingerprint
from .replay import ExtractionCapture, RecordedExtractor, RecordingConfig, validate_facts, validate_state_coverage

STAGED_VERSION = 'source-staged-extraction-v1'
# State coverage, not default answers: each field needs a literal observation or
# an explicit reasoned unknown. Missing states are never synthesized by code.
HEADER_STATE_FIELDS = (
    'document_type_hint', 'document_number', 'document_date',
    'supplier_name', 'supplier_tax_id', 'recipient_name', 'recipient_tax_id',
    'currency', 'net', 'tax', 'gross', 'payable', 'po_reference',
    'iban', 'period_start', 'period_end',
)


@dataclass(frozen=True)
class StagedCapture:
    facts: DocumentFacts
    unknowns: tuple
    provenance: dict
    request_metadata: dict
    stages: tuple

    def to_dict(self):
        return {'facts': self.facts.to_dict(), 'unknowns': list(self.unknowns),
                'provenance': self.provenance, 'request_metadata': self.request_metadata,
                # This is a composition, never a synthetic single provider call.
                'raw_response': {'stage_responses': [stage.raw_response for stage in self.stages]}}


def compose_stages(document: ParsedDocument, headers: ExtractionCapture,
                   tables: ExtractionCapture, header_config: RecordingConfig,
                   table_config: RecordingConfig) -> StagedCapture:
    """Retain source-bound facts from both accepted, strictly disjoint stages."""
    configs = (header_config, table_config)
    captures = (headers, tables)
    scopes = ('header_footer_only', 'tables_only')
    for capture, config, scope in zip(captures, configs, scopes):
        if config.parameters.get('prompt_extras', {}).get('extraction_scope') != scope:
            raise ValueError('Staged extraction requires distinct header/table scopes')
        if capture.provenance.get('mode') not in {'record', 'replay', 'fixture'}:
            raise ValueError('Only checked recording-boundary captures can be composed')
        validate_facts(document, capture.facts, config.extractor_version, capture.provenance)
        validate_state_coverage(config, capture.facts, capture.unknowns)
        for name in capture.facts.fields:
            is_row = name.startswith(('line.', 'statement.', 'detail_lines.')) or name in {
                'line_count', 'statement_row_count', 'detail_line_count'}
            if is_row != (scope == 'tables_only'):
                raise ValueError('A staged fact violates its recorded extraction scope')
    fields = {name: list(values) for capture in captures for name, values in capture.facts.fields.items()}
    unknowns = tuple(state for capture in captures for state in capture.unknowns)
    identities = [{'config_sha256': config.sha256,
                   'facts_sha256': fingerprint(capture.facts.to_dict()),
                   'unknowns_sha256': fingerprint(list(capture.unknowns)),
                   'scope': scope}
                  for config, capture, scope in zip(configs, captures, scopes)]
    provenance = {'composition_version': STAGED_VERSION,
                  'source_sha256': document.source_sha256,
                  'transformation_sha256': document.transformation_sha256,
                  'stage_identities': identities,
                  'capture_valid': True,
                  'source_table_coverage': 'unverified',
                  'accounting_eligibility': 'not_evaluated',
                  'unresolved_fields': sorted({state['field'] for state in unknowns}),
                  'derived_fields': tables.provenance.get('derived_fields', {})}
    version = STAGED_VERSION + ':' + fingerprint(provenance)
    costs = [capture.request_metadata.get('capture_cost_usd') for capture in captures]
    metadata = {'transformation_sha256': document.transformation_sha256,
                'source_sha256': document.source_sha256,
                'response_source': 'composed_model_stages',
                'capture_cost_usd': (str(sum((Decimal(value) for value in costs), Decimal(0)))
                                     if all(value is not None for value in costs) else None),
                'stage_request_metadata': [capture.request_metadata for capture in captures]}
    return StagedCapture(DocumentFacts(document.source_sha256, version, fields),
                         unknowns, provenance, metadata, captures)


async def capture_stages(document: ParsedDocument, headers: RecordedExtractor,
                         tables: RecordedExtractor) -> StagedCapture:
    """Two explicit recorded calls; successful headers survive a failed table."""
    header_result = await headers.extract_with_response(document)
    table_result = await tables.extract_with_response(document)
    return compose_stages(document, header_result, table_result, headers.config, tables.config)
