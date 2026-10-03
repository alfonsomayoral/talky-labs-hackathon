#!/usr/bin/env python3
"""Capture original sample sources without importing any evaluator or labels."""
from __future__ import annotations
import argparse
import asyncio
from contextvars import ContextVar
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time

from kalmora.data import PhaseData
from kalmora.facts import atomic_json, _encode_value
from kalmora.documents.contracts import Candidate, ResolutionRequest
from kalmora.documents.router import DocumentRouter
from kalmora.documents.extractor import LLMDocumentExtractor, LLMSemanticResolver
from kalmora.documents.composition import compose_native_invoice
from kalmora.documents.native_table import extract_native_table
from kalmora.documents.xml_extractor import XMLDocumentExtractor, XML_EXTRACTOR_VERSION
from kalmora.documents.staged import HEADER_STATE_FIELDS, capture_stages
from kalmora.documents.replay import RecordingConfig, RecordingStore, RecordedExtractor, RecordedResolver
from kalmora.llm.client import AsyncLLMClient, LLMConfig
from kalmora.runlog import RunRecorder

ACTIVE_CASE = ContextVar('active_capture_case', default=None)


class RecorderMux:
    """One actual call registered globally; its record is attributed to one case."""
    def __init__(self, global_recorder):
        self.global_recorder = global_recorder
        self.report = global_recorder.report

    def record_call(self, *args, **kwargs):
        call = self.global_recorder.record_call(*args, **kwargs)
        recorder = ACTIVE_CASE.get()
        if recorder is not None:
            recorder.report['calls'].append(dict(call))
        return call

    def record_cache_hit(self):
        self.global_recorder.record_cache_hit()
        recorder = ACTIVE_CASE.get()
        if recorder is not None:
            recorder.record_cache_hit()


def exact_json(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def checked_source(root, entry):
    relative = Path(entry['path'])
    if relative.is_absolute() or '..' in relative.parts or 'golden' in relative.parts or 'phase_test' in relative.parts:
        raise ValueError('Manifest source is outside the permitted development originals')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Manifest source escapes participant root or is missing')
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError(f'Original source hash mismatch: {relative}')
    return path


def observed(facts, *names):
    return {str(fact.value) for name in names for fact in facts.fields.get(name, ())
            if fact.value is not None and str(fact.value).strip()}


def semantic_requests(document, facts, data):
    """Bounded reference queries from observations and ERP identity, never labels."""
    taxes = observed(facts, 'supplier_tax_id')
    vendor_rows = [row for row in data.table('vendors') if taxes & {row.get('tax_id'), row.get('vat_id')}]
    vendors = {row['id'] for row in vendor_rows}
    requests = []
    if vendor_rows:
        candidates = tuple(Candidate(str(row['id']), {key: row.get(key) for key in ('tax_id', 'vat_id', 'name')})
                           for row in vendor_rows)
        requests.append(ResolutionRequest(document, candidates, {'reference_kind': 'supplier'}))
    if len(vendors) != 1:
        return requests
    vendor = next(iter(vendors))
    recipient = observed(facts, 'recipient_tax_id', 'customer_tax_id', 'buyer_tax_id')
    companies = {str(row['code']) for row in data.companies if recipient & {row.get('tax_id'), row.get('vat_id')}}
    if len(companies) != 1:
        return requests
    company = next(iter(companies))
    po_refs = observed(facts, *[name for name in facts.fields if name.rsplit('.', 1)[-1] in {'po_reference', 'purchase_order_reference'}])
    if po_refs:
        candidates = [Candidate(str(row['id']), {'reference': str(row['id']), 'vendor': vendor,
                      'company': company, 'description': row.get('text', '')})
                      for row in data.table('purchase_orders')
                      if row.get('vendor') == vendor and str(row.get('company')) == company and str(row['id']) in po_refs]
        if candidates:
            requests.append(ResolutionRequest(document, tuple(candidates),
                            {'hard_constraints': {'vendor': vendor, 'company': company}, 'reference_kind': 'purchase_order'}))
    delivery_refs = observed(facts, *[name for name in facts.fields if name.rsplit('.', 1)[-1] in {'delivery_reference', 'receipt_reference'}])
    starts = observed(facts, 'period_start', 'service_period_start')
    ends = observed(facts, 'period_end', 'service_period_end')
    # Reference identity can be unique after exact vendor/company filtering.
    # A period narrows it only when dates are actually established; no date is invented.
    import re
    if delivery_refs:
        start = next(iter(starts)) if len(starts) == 1 else None
        end = next(iter(ends)) if len(ends) == 1 else None
        interval = (start is not None and end is not None and
                    re.fullmatch(r'\d{4}-\d{2}-\d{2}', start) and
                    re.fullmatch(r'\d{4}-\d{2}-\d{2}', end) and start <= end)
        candidates = [Candidate(str(row['id']), {'reference': row['reference'], 'vendor': vendor,
                      'company': company, 'posting_date': row['posting_date'], 'po': row['po']})
                      for row in data.table('goods_receipts') if row.get('vendor') == vendor
                      and str(row.get('company')) == company and row.get('reference') in delivery_refs
                      and (not interval or start <= row.get('posting_date', '') <= end)]
        if candidates:
            context = {'hard_constraints': {'vendor': vendor, 'company': company}, 'reference_kind': 'goods_receipt'}
            if interval:
                context.update(period_start=start, period_end=end)
            requests.append(ResolutionRequest(document, tuple(candidates), context))
    return requests


async def capture(args):
    root = args.participant_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError('Capture output must be outside original participant data')
    manifest = json.loads(args.manifest.read_text(), parse_float=Decimal)
    if manifest.get('phase') != 'phase_dev':
        raise ValueError('Only the frozen development source sample is accepted')
    cases = [case for case in manifest['cases'] if case['split'] == args.partition
             and (not args.case or case['case_id'] in args.case)]
    if not cases or (args.case and set(args.case) != {case['case_id'] for case in cases}):
        raise ValueError('Case selection is empty or crosses the selected partition')
    # Validate every selected original before provider construction or paid work.
    for case in cases:
        for source in [*case['attachments'], case['message']]:
            checked_source(root, source)
    config = LLMConfig(args.model, args.budget, args.input_usd_per_million / Decimal(1_000_000),
                       args.output_usd_per_million / Decimal(1_000_000), args.pricing_provenance,
                       reasoning_effort=args.reasoning_effort, concurrency=2, timeout_seconds=args.timeout_seconds,
                       max_attempts=args.transport_attempts if args.transport_attempts is not None else (1 if args.native_tables else 2), max_output_tokens=args.max_output_tokens,
                       model_output_capacity_tokens=128_000,
                       image_detail=args.image_detail, max_input_tokens=args.max_input_tokens)
    processor = None
    if args.pdf_ocr or args.renderer_only:
        from kalmora.documents.ocr import PDFVisionConfig, PDFVisionProcessor
        processor_config = PDFVisionConfig(**{name: value for name, value in
            (("renderer", args.pdf_renderer), ("tesseract", args.tesseract)) if value})
        if args.renderer_only:
            from dataclasses import replace
            processor_config = replace(processor_config, ocr_enabled=False)
        processor = PDFVisionProcessor(root / 'phase_dev', processor_config)
    args.output.mkdir(parents=True, exist_ok=True)
    global_recorder = RunRecorder(args.output / 'reports', sys.argv,
                                   {'partition': args.partition, 'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                                    'capture_mode': 'captured_live', 'transport_mode': 'default', 'response_source': 'provider_api'})
    with global_recorder:
        mux = RecorderMux(global_recorder)
        client = AsyncLLMClient(config, mux)
        extractor = LLMDocumentExtractor(client, include_processing_aids=not args.omit_ocr_aids,
                                         max_validation_attempts=args.validation_attempts,
                                         require_line_descriptions=args.require_line_descriptions,
                                         require_page_coverage=False)
        resolver = LLMSemanticResolver(client)
        extraction_config = RecordingConfig.from_adapter(extractor)
        resolution_config = RecordingConfig.from_adapter(resolver)
        router = DocumentRouter(root / 'phase_dev')
        data = PhaseData(root / 'phase_dev') if args.semantic else None
        slots = asyncio.Semaphore(2)

        async def one(case):
            async with slots:
                started = time.perf_counter()
                directory = args.output / case['case_id']
                recorder = RunRecorder(directory / 'reports', ['capture_document_sample', case['case_id']],
                                       {'partition': args.partition, 'case_id': case['case_id'],
                                        'capture_mode': 'captured_live', 'transport_mode': 'default', 'response_source': 'provider_api'})
                status = {'case_id': case['case_id'], 'partition': args.partition, 'attachments': [],
                          'status': 'completed', 'new_capture': False}
                token = ACTIVE_CASE.set(recorder)
                try:
                    with recorder:
                        atomic_json(directory / 'config.json', exact_json({'llm': asdict(config),
                                    'extraction': extraction_config.to_dict(), 'resolution': resolution_config.to_dict(),
                                    'source_tools': {'name': 'xml-source-extractor', 'version': XML_EXTRACTOR_VERSION},
                                    'capture_options': {'native_tables': args.native_tables, 'renderer_only': args.renderer_only,
                                        'staged': getattr(args, 'staged', False),
                                        'require_page_coverage': args.require_page_coverage,
                                        'require_native_row_coverage': args.require_native_row_coverage}}))
                        store = RecordingStore(directory / 'recordings')
                        semantic = RecordedResolver(store, resolution_config, mode='record',
                                   callback=resolver.resolve_with_response, budget_usd=args.budget, recorder=mux)
                        for entry in case['attachments']:
                            item = {'path': entry['path'], 'sha256': entry['sha256'], 'status': 'completed'}
                            try:
                                document = router.parse(Path(entry['path']).relative_to('phase_dev').as_posix())
                                if processor is not None and document.media_type == 'application/pdf' and any(
                                        warning.endswith(':vision_required') for warning in document.warnings):
                                    document = await asyncio.to_thread(processor.process, document,
                                        artifact_dir=directory / 'pdf-tools' / entry['sha256'])
                                if args.page_strips and document.images:
                                    from kalmora.documents.vision import add_page_strips
                                    document = add_page_strips(document)
                                source_archive = directory / 'sources' / (entry['sha256'] + '.json')
                                atomic_json(source_archive, document.to_dict(include_images=True))
                                item.update(transformation_sha256=document.transformation_sha256,
                                    parsed_document_sha256=hashlib.sha256(source_archive.read_bytes()).hexdigest())
                                table = (extract_native_table(document) if args.native_tables and
                                         document.media_type == 'application/pdf' else None)
                                table_is_complete = table is not None and table.status == 'complete'
                                if document.media_type in {'application/xml', 'text/xml'}:
                                    xml_extractor = XMLDocumentExtractor()
                                    raw_facts = await xml_extractor.extract(document)
                                    tool_spec = __import__('kalmora.documents.xml_extractor', fromlist=['__file__'])
                                    adapter_hash = hashlib.sha256(Path(tool_spec.__file__).read_bytes()).hexdigest()
                                    artifact_dict = {'facts': raw_facts.to_dict(), 'raw_response': None, 'unknowns': [],
                                        'request_metadata': {'transformation_sha256': document.transformation_sha256},
                                        'provenance': {'response_source': 'source_tools', 'extractor_version': XML_EXTRACTOR_VERSION}}
                                    config_source = {'name': 'xml-source-extractor', 'version': XML_EXTRACTOR_VERSION}
                                    item.update(processing_kind='source_tools', cache_hit=False,
                                        source_tools={'adapter_name': 'xml-source-extractor', 'adapter_version': XML_EXTRACTOR_VERSION,
                                            'adapter_sha256': adapter_hash, 'config_sha256': __import__('kalmora.documents.contracts', fromlist=['fingerprint']).fingerprint(config_source),
                                            'source_sha256': entry['sha256'], 'transformation_sha256': document.transformation_sha256,
                                            'fresh_processing': True})
                                    atomic_json(directory / 'artifacts' / (entry['sha256'] + '.json'), exact_json(artifact_dict))
                                    raw_model_facts = raw_facts
                                else:
                                    scoped_options = dict(
                                        include_processing_aids=not args.omit_ocr_aids,
                                        max_validation_attempts=args.validation_attempts,
                                        require_line_descriptions=args.require_line_descriptions,
                                        require_page_coverage=False)
                                    if (getattr(args, 'staged', False) and not table_is_complete
                                            and (document.images or (table is not None and table.status == 'incomplete'))):
                                        header = LLMDocumentExtractor(client, **scoped_options,
                                            extraction_scope='header_footer_only', required_header_fields=HEADER_STATE_FIELDS,
                                            preserve_partial_on_failure=True)
                                        rows = LLMDocumentExtractor(client, **scoped_options,
                                            extraction_scope='tables_only', preserve_partial_on_failure=True)
                                        boundaries = [RecordedExtractor(store, RecordingConfig.from_adapter(adapter), mode='record',
                                            callback=adapter.extract_with_response, budget_usd=args.budget, recorder=mux)
                                            for adapter in (header, rows)]
                                        item['extraction_stages'] = [{'config': boundary.config.to_dict(), 'key': boundary.key(document)}
                                                                     for boundary in boundaries]
                                        artifact = await capture_stages(document, *boundaries)
                                        item.update(processing_kind='staged_model',
                                            cache_hit=any(stage.provenance['cache_hit'] for stage in artifact.stages))
                                    else:
                                        document_extractor = LLMDocumentExtractor(client, **scoped_options,
                                            extraction_scope=('outside_native_invoice_table' if table_is_complete else 'complete'),
                                            required_header_fields=(HEADER_STATE_FIELDS if getattr(args, 'staged', False) else ()),
                                            preserve_partial_on_failure=getattr(args, 'staged', False))
                                        document_config = RecordingConfig.from_adapter(document_extractor)
                                        item['extraction_config'] = document_config.to_dict()
                                        recorded = RecordedExtractor(store, document_config, mode='record',
                                            callback=document_extractor.extract_with_response,
                                            budget_usd=args.budget, recorder=mux)
                                        artifact = await recorded.extract_with_response(document)
                                        item.update(processing_kind='model', recording_key=recorded.key(document), cache_hit=artifact.provenance['cache_hit'])
                                    atomic_json(directory / 'artifacts' / (entry['sha256'] + '.json'), exact_json(artifact.to_dict()))
                                    raw_model_facts = artifact.facts
                                final_facts = raw_model_facts
                                if table_is_complete:
                                    composition = compose_native_invoice(document, raw_model_facts, table)
                                    composition_path = directory / 'compositions' / (entry['sha256'] + '.json')
                                    atomic_json(composition_path, {'facts': composition.facts.to_dict(), 'provenance': composition.provenance,
                                        'raw_model_facts_sha256': composition.provenance['recorded_model_facts_sha256']})
                                    final_facts = composition.facts
                                    item['composition_sha256'] = hashlib.sha256(composition_path.read_bytes()).hexdigest()
                                    item['native_row_count'] = table.expected_count
                                if args.require_native_row_coverage:
                                    from kalmora.documents.coverage import native_row_coverage
                                    coverage = native_row_coverage(document, final_facts.fields)
                                    item['native_row_coverage'] = coverage.to_dict()
                                    if coverage.status == 'incomplete':
                                        raise ValueError('composed native row coverage failed: ' + coverage.status)
                                if args.require_page_coverage:
                                    required_pages = ({block.page for block in document.blocks if block.page is not None and block.text.strip()}
                                        | {image.page for image in document.images})
                                    cited_pages = {fact.evidence.page for values in final_facts.fields.values() for fact in values}
                                    missing_pages = sorted(required_pages - cited_pages)
                                    if missing_pages or (required_pages and not final_facts.fields):
                                        raise ValueError('prepared-source page coverage failed: ' + str(missing_pages))
                                item['semantic'] = []
                                if data is not None:
                                    for request in semantic_requests(document, final_facts, data):
                                        atomic_json(directory / 'requests' / (semantic.key(request) + '.json'),
                                            _encode_value({'candidates': [{'id': candidate.id, 'attributes': candidate.attributes}
                                                for candidate in request.candidates], 'context': request.context,
                                                'request_sha256': request.sha256,
                                                'transformation_sha256': document.transformation_sha256}))
                                        result = await semantic.resolve_with_response(request)
                                        atomic_json(directory / 'semantic' / (semantic.key(request) + '.json'), exact_json(result.to_dict()))
                                        item['semantic'].append({'key': semantic.key(request), 'cache_hit': result.provenance['cache_hit']})
                            except Exception as error:
                                item.update(status='failed', error_type=type(error).__name__, category=getattr(error, 'category', 'parse_or_capture'))
                                atomic_json(directory / 'errors' / (entry['sha256'] + '.json'), item)
                                status['status'] = 'failed'
                            status['attachments'].append(item)
                        status['new_capture'] = bool(recorder.report['calls'])
                        status['source_tools_only'] = bool(status['attachments']) and all(
                            row.get('processing_kind') == 'source_tools' and row.get('status') == 'completed'
                            for row in status['attachments'])
                        status['cache_hits'] = recorder.report['cache_hits']
                        status['live_evaluation_eligible'] = (status['status'] == 'completed' and not status['cache_hits']
                            and (status['new_capture'] or status['source_tools_only']))
                        status['elapsed_seconds'] = time.perf_counter() - started
                        recorder.report['exit_code'] = int(status['status'] != 'completed')
                        recorder.report['llm_budget'] = dict(mux.report['llm_budget'])
                        atomic_json(directory / 'capture.json', status)
                finally:
                    ACTIVE_CASE.reset(token)
                return status

        results = await asyncio.gather(*(one(case) for case in cases))
        global_recorder.report['exit_code'] = int(any(row['status'] != 'completed' for row in results))
        atomic_json(args.output / 'capture.json', {'partition': args.partition, 'cases': results,
                    'budget': mux.report['llm_budget'], 'evaluation_performed': False})
        return global_recorder.report['exit_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--participant-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partition', choices=('tuning', 'holdout'), required=True)
    parser.add_argument('--case', action='append')
    parser.add_argument('--budget', type=Decimal, default=Decimal('1'))
    parser.add_argument('--model', default='gpt-6-luna')
    parser.add_argument('--reasoning-effort', default='low')
    parser.add_argument('--timeout-seconds', type=float, default=None, help='Optional explicit request deadline; default has no temporal limit')
    parser.add_argument('--max-output-tokens', type=int, default=None)
    parser.add_argument('--image-detail', choices=('auto', 'low', 'high'), default='high')
    parser.add_argument('--max-input-tokens', type=int, default=200_000,
                        help='Conservative input spending bound; raise for multiple images within verified model capacity')
    parser.add_argument('--page-strips', action='store_true', help='Add source-bound overlapping crops for dense page images')
    parser.add_argument('--validation-attempts', type=int, default=1, help='Source-only schema/grounding repair attempts (1 to 3)')
    parser.add_argument('--transport-attempts', type=int, choices=(1, 2), help='Maximum transport attempts per actual model request')
    parser.add_argument('--require-line-descriptions', action='store_true', help='Require a literal description/material or explicit unknown per invoice row')
    parser.add_argument('--pdf-ocr', action='store_true', help='Render scanned PDF pages and include unverified local OCR aids')
    parser.add_argument('--renderer-only', action='store_true', help='Render full original PDF pages without OCR')
    parser.add_argument('--native-tables', action='store_true', help='Use outside-table model scope and compose complete native invoice rows')
    parser.add_argument('--require-page-coverage', action='store_true', help='Require observed facts on every prepared source page')
    parser.add_argument('--require-native-row-coverage', action='store_true', help='Require every printed native invoice row after composition')
    parser.add_argument('--omit-ocr-aids', action='store_true', help='Preserve OCR in source archive but exclude it from extraction prompts')
    parser.add_argument('--pdf-renderer', help='Explicit pdftoppm executable, otherwise discover on PATH')
    parser.add_argument('--tesseract', help='Explicit Tesseract executable, otherwise discover on PATH')
    parser.add_argument('--input-usd-per-million', type=Decimal, default=Decimal('0.125'))
    parser.add_argument('--output-usd-per-million', type=Decimal, default=Decimal('0.50'))
    parser.add_argument('--pricing-provenance', default='https://developers.openai.com/api/docs/pricing 2026-10-03; Luna standard short-context USD/M input 0.10 x cache-write ceiling 1.25, output 0.50; conservative estimate, not invoice')
    parser.add_argument('--semantic', action='store_true')
    parser.add_argument('--staged', action='store_true', help='Explicit header states and separately recorded header/table extraction')
    args = parser.parse_args()
    if args.require_native_row_coverage and not args.native_tables:
        parser.error('--require-native-row-coverage requires --native-tables')
    if args.native_tables and args.validation_attempts > 2:
        parser.error('--native-tables supports at most two validation attempts')
    return asyncio.run(capture(args))


if __name__ == '__main__':
    raise SystemExit(main())
