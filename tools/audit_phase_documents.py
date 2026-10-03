#!/usr/bin/env python3
"""Inventory original inbox sources and optionally capture their interpretation.

This production audit never imports labels, golden, or an accounting evaluator.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import uuid
import zipfile

from kalmora.facts import atomic_json
from kalmora.documents.router import DocumentRouter

ARCHIVE_PREFIX = PurePosixPath('participant/phase_test')
SOURCE_DIRECTORIES = {'inbox', 'tasks', 'erp'}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_value(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def extract_sources(archive: Path, destination: Path):
    """Validate every ZIP name/type/size before extracting only source allowlist.

    Existing destinations are immutable: a complete identical extraction can be
    reused; changed or incomplete destinations fail without overwriting a file.
    """
    archive = archive.resolve(strict=True)
    destination = destination.absolute()
    if destination.is_symlink() or 'golden' in destination.parts:
        raise ValueError('Unsafe extraction destination')
    archive_hash = sha256(archive)
    selected = []
    with zipfile.ZipFile(archive) as container:
        entries = container.infolist()
        if len(entries) > 20_000 or sum(item.file_size for item in entries) > 500_000_000:
            raise ValueError('Archive expanded-size or entry-count limit')
        names = set()
        for item in entries:
            name = item.filename
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (not name or '\\' in name or path.is_absolute() or '..' in path.parts
                    or ':' in path.parts[0] or path.as_posix().rstrip('/') != name.rstrip('/')
                    or '\x00' in name or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
                    or item.flag_bits & 1):
                raise ValueError(f'Unsafe ZIP entry: {name!r}')
            if name.rstrip('/') in names:
                raise ValueError(f'Duplicate ZIP entry: {name}')
            names.add(name.rstrip('/'))
            if item.file_size > 64_000_000 or item.file_size < 0:
                raise ValueError(f'Archive member-size limit: {name}')
            if not path.is_relative_to(ARCHIVE_PREFIX) or item.is_dir():
                continue
            relative = path.relative_to(ARCHIVE_PREFIX)
            if relative.parts and relative.parts[0] in SOURCE_DIRECTORIES and 'golden' not in relative.parts:
                selected.append((item, relative))
        if not selected:
            raise ValueError('Archive has no allowlisted September sources')
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock_path = destination.parent / ('.' + destination.name + '.extract.lock')
        with lock_path.open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with tempfile.TemporaryDirectory(prefix='septiembre-', dir=destination.parent) as directory:
                staged = Path(directory) / 'phase_test'
                staged.mkdir()
                files = []
                for item, relative in selected:
                    output = staged / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with container.open(item) as source, output.open('xb') as target:
                        shutil.copyfileobj(source, target, length=1_048_576)
                    files.append({'path': relative.as_posix(), 'bytes': output.stat().st_size, 'sha256': sha256(output)})
                manifest = {'schema_version': 1, 'phase': 'phase_test', 'archive_sha256': archive_hash,
                            'archive_bytes': archive.stat().st_size, 'files': files,
                            'excluded_entries': len(entries) - len(files),
                            'allowlist': sorted(SOURCE_DIRECTORIES)}
                atomic_json(staged / 'source-manifest.json', manifest)
                if destination.exists():
                    if not destination.is_dir() or (destination / 'source-manifest.json').is_symlink():
                        raise ValueError('Existing destination is unsafe')
                    prior = json.loads((destination / 'source-manifest.json').read_text())
                    if prior != manifest:
                        raise ValueError('Existing extraction differs; select a new destination')
                    for entry in files:
                        source = destination / entry['path']
                        if source.is_symlink() or not source.resolve().is_relative_to(destination.resolve()) or sha256(source) != entry['sha256']:
                            raise ValueError(f'Existing source differs: {entry["path"]}')
                else:
                    os.rename(staged, destination)
    return destination.resolve(), manifest


def original_files(phase_root):
    root = phase_root.resolve(strict=True)
    if 'golden' in root.parts:
        raise ValueError('golden cannot be an audit source')
    inbox = root / 'inbox'
    if inbox.is_symlink() or not inbox.is_dir():
        raise ValueError('Missing or symlinked inbox')
    sources = []
    for directory, directories, files in os.walk(inbox, followlinks=False):
        for name in [*directories, *files]:
            path = Path(directory) / name
            if path.is_symlink() or 'golden' in path.relative_to(root).parts:
                raise ValueError(f'Unsafe inbox source: {path.name}')
        for name in files:
            source = Path(directory) / name
            sources.append({'path': source.relative_to(root).as_posix(), 'sha256': sha256(source),
                            'bytes': source.stat().st_size, 'suffix': source.suffix.lower()})
    return sorted(sources, key=lambda item: item['path'])


def inventory(phase_root):
    """Independent native-text coverage, followed by the production router."""
    sources = original_files(phase_root)
    router = DocumentRouter(phase_root)
    for item in sources:
        if item['suffix'] != '.pdf':
            continue
        item['pages'] = []
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO((phase_root / item['path']).read_bytes()), strict=True)
            if reader.is_encrypted:
                raise ValueError('encrypted_pdf')
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text(extraction_mode='layout') or ''
                item['pages'].append({'page': number, 'native_characters': len(text),
                                      'native_nonwhitespace_characters': len(''.join(text.split())),
                                      'native_sha256': hashlib.sha256(text.encode()).hexdigest(),
                                      'vision_required': len(text.strip()) < 15})
            item['page_count'] = len(item['pages'])
            parsed = router.parse(item['path'])
            item.update(parse_status='parsed', parser_version=parsed.parser_version,
                        transformation_sha256=parsed.transformation_sha256)
        except Exception as error:
            item.update(parse_status='failed', error_type=type(error).__name__,
                        error_category=getattr(error, 'category', str(error)))
    pdfs = [item for item in sources if item['suffix'] == '.pdf']
    return {'schema_version': 1, 'phase': 'phase_test', 'source_root': str(phase_root.resolve()),
            'source_only': True, 'evaluation_performed': False, 'official_golden_available': False,
            'sources': sources, 'summary': {'sources': len(sources), 'formats': dict(Counter(item['suffix'] for item in sources)),
                'pdfs': len(pdfs), 'pages': sum(item.get('page_count', 0) for item in pdfs),
                'multipage_pdfs': sum(item.get('page_count', 0) > 1 for item in pdfs),
                'vision_required_pdfs': sum(any(page['vision_required'] for page in item['pages']) for item in pdfs),
                'vision_required_pages': sum(page['vision_required'] for item in pdfs for page in item['pages']),
                'parse_failures': sum(item['parse_status'] == 'failed' for item in pdfs)}}


def source_coverage(document, facts, pages):
    cited_pages = {fact.evidence.page for values in facts.fields.values() for fact in values
                   if fact.evidence.page is not None}
    return [{'page': row['page'], 'source_present': any(block.page == row['page'] for block in document.blocks),
             'image_present': any(image.page == row['page'] for image in document.images),
             'fact_citation_present': row['page'] in cited_pages,
             'literal_fidelity_independently_verified': False} for row in pages]


async def capture(args, manifest, run_directory):
    # Imports are deliberately live-mode-only: dry inventory needs no provider/key.
    from kalmora.documents.classification import classify_document
    from kalmora.documents.normalization import normalize_document_facts
    from kalmora.documents.ocr import PDFVisionConfig, PDFVisionProcessor
    from kalmora.documents.extractor import LLMDocumentExtractor
    from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore
    from kalmora.documents.xml_extractor import XMLDocumentExtractor
    from kalmora.llm.client import AsyncLLMClient, LLMConfig
    from kalmora.runlog import RunRecorder

    if args.budget is None or args.input_usd_per_million is None or args.output_usd_per_million is None or not args.pricing_provenance:
        raise ValueError('Paid capture requires an explicit budget, prices, and pricing provenance')
    config = LLMConfig(args.model, args.budget, args.input_usd_per_million / Decimal(1_000_000),
                       args.output_usd_per_million / Decimal(1_000_000), args.pricing_provenance,
                       reasoning_effort=args.reasoning_effort, concurrency=args.concurrency,
                       image_detail='high', timeout_seconds=None, max_output_tokens=None,
                       max_input_tokens=900_000 if args.page_strips else 200_000)
    selected = [item for item in manifest['sources'] if item['suffix'] in ('.pdf', '.xml')]
    if args.path:
        paths = set(args.path)
        selected = [item for item in selected if item['path'] in paths]
        if paths != {item['path'] for item in selected}:
            raise ValueError('Selected paths must be original PDF/XML inbox sources')
    if not selected:
        raise ValueError('No original PDF/XML sources selected')
    recorder = RunRecorder(run_directory / 'reports', ['audit_phase_documents', '--capture'],
                           {'phase': 'phase_test', 'source_only': True, 'experimental_model': args.model != 'gpt-6-luna',
                            'capture_mode': 'captured_live', 'transport_mode': 'default', 'response_source': 'provider_api'})
    with recorder:
        client = AsyncLLMClient(config, recorder)
        extractor = LLMDocumentExtractor(client, include_processing_aids=not args.omit_ocr_aids)
        recording_config = RecordingConfig.from_adapter(extractor)
        identity = recording_config.sha256
        bundle = args.output / 'configurations' / identity
        bundle.mkdir(parents=True, exist_ok=True)
        atomic_json(run_directory / 'config.json', json_value({'llm': asdict(config), 'extraction': recording_config.to_dict()}))
        recorded = RecordedExtractor(RecordingStore(bundle / 'recordings'), recording_config, mode='record',
                                     callback=extractor.extract_with_response, budget_usd=args.budget, recorder=recorder)
        router = DocumentRouter(args.phase_root)
        max_pages = max((item.get('page_count', 1) for item in selected), default=1)
        processor = PDFVisionProcessor(args.phase_root, PDFVisionConfig(max_pages=max(4, max_pages),
                    renderer=args.pdf_renderer, tesseract=args.tesseract, timeout_seconds=args.tool_timeout_seconds))
        semaphore = asyncio.Semaphore(args.concurrency)

        async def one(source):
            async with semaphore:
                item = {'path': source['path'], 'sha256': source['sha256'], 'status': 'failed'}
                try:
                    if sha256(args.phase_root / source['path']) != source['sha256']:
                        raise ValueError('Original source changed since inventory')
                    document = await asyncio.to_thread(router.parse, source['path'])
                    if document.media_type == 'application/pdf' and any(warning.endswith(':vision_required') for warning in document.warnings):
                        document = await asyncio.to_thread(processor.process, document,
                            artifact_dir=args.output / 'pdf-tools' / source['sha256'])
                    if args.page_strips and document.images:
                        from kalmora.documents.vision import add_page_strips
                        document = await asyncio.to_thread(add_page_strips, document)
                    parsed_path = args.output / 'parsed' / source['sha256'] / (document.transformation_sha256 + '.json')
                    atomic_json(parsed_path, document.to_dict(include_images=True))
                    if document.media_type == 'application/xml':
                        facts = await XMLDocumentExtractor().extract(document)
                        item.update(origin='deterministic_xml', cache_hit=False, new_provider_calls=0)
                    else:
                        artifact = await recorded.extract_with_response(document, regenerate=args.fresh)
                        facts = artifact.facts
                        item.update(origin='recorded', recording_key=recorded.key(document),
                                    cache_hit=artifact.provenance['cache_hit'], unknowns=list(artifact.unknowns),
                                    new_provider_calls=artifact.provenance.get('new_provider_calls'),
                                    new_provider_cost_usd=artifact.provenance.get('new_provider_cost_usd'))
                        atomic_json(bundle / 'artifacts' / (recorded.key(document) + '.json'), json_value(artifact.to_dict()))
                    normalized = normalize_document_facts(facts)
                    classification = classify_document(normalized.facts)
                    item.update(status='completed', field_count=len(facts.fields),
                                transformation_sha256=document.transformation_sha256,
                                page_coverage=source_coverage(document, facts, source.get('pages', [])),
                                literal_fidelity_independently_verified=False,
                                native_or_xml_literal_proven_facts=sum(not fact.evidence.field.startswith('image:')
                                    for values in facts.fields.values() for fact in values),
                                image_literal_unverified_facts=sum(fact.evidence.field.startswith('image:')
                                    for values in facts.fields.values() for fact in values),
                                normalization_diagnostic_categories=dict(Counter(
                                    value.code for value in normalized.diagnostics)),
                                normalization_failed_fields=sorted({value.field for value in normalized.diagnostics}),
                                classification_status=classification.status,
                                classification_type=classification.document_type)
                    atomic_json(bundle / 'facts' / (document.transformation_sha256 + '.json'), json_value({
                        'raw': facts.to_dict(), 'normalized': normalized.facts.to_dict(),
                        'normalization_diagnostics': [asdict(value) for value in normalized.diagnostics],
                        'classification': asdict(classification)}))
                except Exception as error:
                    item.update(error_type=type(error).__name__, error_category=getattr(error, 'category', 'parse_or_capture'),
                                error_message=str(error))
                atomic_json(run_directory / 'documents' / (hashlib.sha256(source['path'].encode()).hexdigest() + '.json'), item)
                print(json.dumps({'path': item['path'], 'status': item['status'], 'error_category': item.get('error_category')}, ensure_ascii=False), flush=True)
                return item

        results = await asyncio.gather(*(one(source) for source in selected))
        recorder.report['exit_code'] = int(any(item['status'] != 'completed' for item in results))
        report = {'schema_version': 1, 'phase': 'phase_test', 'source_only': True,
                  'evaluation_performed': False, 'official_golden_available': False,
                  'literal_fidelity_independently_verified': False,
                  'config_sha256': identity, 'selected_documents': len(selected), 'documents': results,
                  'summary': {'statuses': dict(Counter(item['status'] for item in results)),
                      'error_categories': dict(Counter(item['error_category'] for item in results if item['status'] == 'failed')),
                      'native_or_xml_literal_proven_facts': sum(item.get('native_or_xml_literal_proven_facts', 0) for item in results),
                      'image_literal_unverified_facts': sum(item.get('image_literal_unverified_facts', 0) for item in results),
                      'pages_in_inventory': sum(source.get('page_count', 0) for source in selected),
                      'pages_with_fact_citation': sum(page['fact_citation_present'] for item in results for page in item.get('page_coverage', [])),
                      'cache_hits': sum(bool(item.get('cache_hit')) for item in results)},
                  'budget': recorder.report.get('llm_budget'), 'run_report': str(recorder.path)}
        atomic_json(run_directory / 'capture.json', report)
    return recorder.report['exit_code']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase-root', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--extract-to', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capture', action='store_true', help='Explicit paid original-source capture; default is dry inventory')
    parser.add_argument('--fresh', action='store_true', help='Archive a new capture even when a compatible recording exists')
    parser.add_argument('--path', action='append', help='Optional relative original inbox PDF/XML path; default is every PDF/XML')
    parser.add_argument('--model', choices=('gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-sol'), default='gpt-6-luna')
    parser.add_argument('--reasoning-effort', default='low')
    parser.add_argument('--budget', type=Decimal)
    parser.add_argument('--input-usd-per-million', type=Decimal)
    parser.add_argument('--output-usd-per-million', type=Decimal)
    parser.add_argument('--pricing-provenance')
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--page-strips', action='store_true', help='Add original-page overlapping strips after rendering; raises guarded input capacity to 900000')
    parser.add_argument('--include-ocr-aids', dest='omit_ocr_aids', action='store_false',
                        help='Include unverified OCR locator aids in prompts; default omits them')
    parser.set_defaults(omit_ocr_aids=True)
    parser.add_argument('--pdf-renderer')
    parser.add_argument('--tesseract')
    parser.add_argument('--tool-timeout-seconds', type=float, default=120, help='Local rendering/OCR guard; no provider/run deadline')
    args = parser.parse_args(argv)
    if args.concurrency < 1:
        parser.error('--concurrency must be positive')
    if args.archive:
        if not args.extract_to or args.phase_root:
            parser.error('--archive requires --extract-to and forbids --phase-root')
        args.phase_root, _ = extract_sources(args.archive, args.extract_to)
    elif not args.phase_root:
        parser.error('--phase-root or --archive is required')
    args.phase_root = args.phase_root.resolve(strict=True)
    args.output = args.output.resolve()
    if args.output.is_relative_to(args.phase_root) or args.phase_root.is_relative_to(args.output):
        parser.error('Output must be separate from original phase sources')
    args.output.mkdir(parents=True, exist_ok=True)
    run_directory = args.output / 'runs' / uuid.uuid4().hex
    run_directory.mkdir(parents=True)
    manifest = inventory(args.phase_root)
    atomic_json(run_directory / 'inventory.json', manifest)
    print(json.dumps({'inventory': str(run_directory / 'inventory.json'), **manifest['summary']}), flush=True)
    if args.capture:
        return asyncio.run(capture(args, manifest, run_directory))
    return int(bool(manifest['summary']['parse_failures']))


if __name__ == '__main__':
    raise SystemExit(main())
