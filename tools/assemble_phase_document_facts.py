"""Assemble audited source captures without provider calls or organizer labels.

Later --capture-root entries take precedence for each successfully captured
source. Every selection and optional native-row projection retains its lineage.
This report describes extraction coverage, never an official quality score.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path

from kalmora.documents.classification import classify_document
from kalmora.documents.composition import compose_native_invoice
from kalmora.documents.contracts import ParsedDocument, fingerprint
from kalmora.documents.coverage import native_row_coverage
from kalmora.documents.extractor import _normal, _value_in_quote
from kalmora.documents.native_table import extract_native_table
from kalmora.documents.normalization import normalize_document_facts
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, atomic_json


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_literals(document, facts):
    """Recheck source locations; derived counts and image quotes have distinct limits."""
    if facts.source_sha256 != document.source_sha256:
        raise ValueError('capture refers to different original bytes')
    images = {image.sha256: image for image in document.images}
    blocks = {block.source_field or block.id: block for block in document.blocks}
    for name, values in facts.fields.items():
        for fact in values:
            evidence = fact.evidence
            if evidence.document != document.path:
                raise ValueError(f'{name}: capture belongs to another document path')
            if name in {'line_count', 'detail_line_count', 'statement_row_count'}:
                continue  # Derived values are not literal source tokens.
            if evidence.field.startswith('image:'):
                image = images.get(evidence.field[6:])
                if image is None or image.page != evidence.page:
                    raise ValueError(f'{name}: image proof has no retained original image')
            else:
                block = blocks.get(evidence.field)
                if block is None or block.page != evidence.page:
                    raise ValueError(f'{name}: nonexistent source block/page')
                if _normal(evidence.quote or '') not in _normal(block.text):
                    raise ValueError(f'{name}: quote is not in the native source')
            empty_xml = (document.media_type == 'application/xml' and not evidence.field.startswith('image:')
                         and block.text == '' and evidence.quote == '' and fact.value in ('', None))
            if not empty_xml and fact.value is not None and not _value_in_quote(fact.value, evidence.quote or ''):
                raise ValueError(f'{name}: value is not in its quote')


def assemble(phase_root, capture_roots, output, *, native_tables=False):
    phase_root = Path(phase_root).resolve(strict=True)
    output = Path(output).resolve()
    if output.is_relative_to(phase_root) or phase_root.is_relative_to(output):
        raise ValueError('Output must be separate from original sources')
    router = DocumentRouter(phase_root)
    sources = {path.relative_to(phase_root).as_posix(): path
               for path in sorted((phase_root / 'inbox').rglob('*'))
               if path.is_file() and path.suffix.lower() in {'.pdf', '.xml'}}
    selected = {}
    for root in map(Path, capture_roots):
        reports = [(run, json.loads(run.read_text())) for run in (root / 'runs').glob('*/capture.json')]
        reports.sort(key=lambda pair: pair[1].get('started_at') or datetime.fromtimestamp(
            pair[0].stat().st_mtime, timezone.utc).isoformat())
        for run, report in reports:
            for item in report['documents']:
                if item['status'] != 'completed':
                    continue
                transformation = item['transformation_sha256']
                config = item.get('config_sha256') or report.get('config_sha256')
                if (not item.get('config_sha256') and item.get('origin') == 'recorded_with_deterministic_native_rows'
                        and (run.parent / 'native-table-config.json').exists()):
                    config = fingerprint(json.loads((run.parent / 'native-table-config.json').read_text()))
                if config is not None and not re.fullmatch(r'[a-f0-9]{64}', config):
                    raise ValueError('invalid source-capture configuration identity')
                candidates = ([root / 'configurations' / config / 'facts' / (transformation + '.json')]
                              if config else list((root / 'configurations').glob(f'*/facts/{transformation}.json')))
                if len(candidates) != 1:
                    raise ValueError(f'{item["path"]}: ambiguous or missing facts capture')
                if not candidates[0].is_file():
                    raise ValueError(f'{item["path"]}: selected configuration has no facts capture')
                parsed = root / 'parsed' / item['sha256'] / (transformation + '.json')
                selected[item['path']] = (item, candidates[0], parsed, run)
    records = []
    for relative, source in sources.items():
        row = {'path': relative, 'sha256': file_sha(source), 'status': 'failed'}
        try:
            if source.is_symlink() or not source.resolve().is_relative_to(phase_root):
                raise ValueError('escaped or symlinked source')
            if relative not in selected:
                raise ValueError('no successful source capture')
            item, capture, parsed_path, run = selected[relative]
            if item['sha256'] != row['sha256']:
                raise ValueError('original source changed since capture')
            document = ParsedDocument.from_dict(json.loads(parsed_path.read_text()))
            if (document.source_sha256 != item['sha256'] or document.path != relative
                    or document.transformation_sha256 != item['transformation_sha256']):
                raise ValueError('parsed capture source/path/transformation differs from the selected original')
            original_facts = DocumentFacts.from_dict(json.loads(capture.read_text())['raw'])
            validate_literals(document, original_facts)
            facts = original_facts
            unknowns = item.get('unknowns', [])
            lineage = {'capture': str(capture.resolve()), 'capture_sha256': file_sha(capture),
                       'parsed_source': str(parsed_path.resolve()), 'parsed_sha256': file_sha(parsed_path),
                       'run_capture': str(run.resolve()), 'run_capture_sha256': file_sha(run),
                       'recorded_extractor_version': facts.extractor_version,
                       'source_only': True, 'new_provider_calls': 0}
            if native_tables and source.suffix.lower() == '.pdf' and not document.images:
                native_document = router.parse(relative)
                table = extract_native_table(native_document)
                row['native_table_parser_status'] = table.status
                if table.status == 'complete':
                    composed = compose_native_invoice(native_document, facts, table, project_recorded_rows=True)
                    facts = composed.facts
                    document = native_document
                    lineage['native_composition'] = composed.provenance
                    resolved = set(composed.provenance['native_fields'])
                    lineage['resolved_model_unknowns'] = [state for state in unknowns if state['field'] in resolved]
                    unknowns = [state for state in unknowns if state['field'] not in resolved]
                    validate_literals(document, facts)
            coverage = native_row_coverage(document, facts.fields)
            row['native_row_coverage'] = coverage.to_dict()
            if coverage.status == 'incomplete':
                raise ValueError('detected native invoice rows were omitted')
            normalized = normalize_document_facts(facts)
            classification = classify_document(normalized.facts)
            destination = output / 'facts' / (hashlib.sha256(relative.encode()).hexdigest() + '.json')
            atomic_json(destination, json.loads(json.dumps({
                'raw': facts.to_dict(), 'normalized': normalized.facts.to_dict(),
                'unknowns': unknowns, 'lineage': lineage,
                'normalization_diagnostics': [asdict(d) for d in normalized.diagnostics],
                'classification': asdict(classification)}, default=str)))
            cited = {fact.evidence.page for values in facts.fields.values() for fact in values}
            pages = {block.page for block in document.blocks if block.page is not None}
            row.update(status='assembled', facts_file=str(destination.resolve()),
                       facts_sha256=file_sha(destination), field_count=len(facts.fields),
                       uncited_pages=sorted(pages - cited),
                       image_literal_fidelity_independently_verified=False,
                       source_capture=str(capture.resolve()))
            if row['uncited_pages']:
                raise ValueError('source pages have no observed facts')
        except Exception as error:
            row.update(status='failed', error=str(error))
        records.append(row)
    report = {'schema_version': 1, 'phase': 'phase_test', 'source_only': True,
              'official_score_computed': False, 'organizer_golden_used': False,
              'new_provider_calls': 0, 'documents': records,
              'summary': {'original_documents': len(sources),
                          'statuses': dict(Counter(row['status'] for row in records)),
                          'native_row_coverage': dict(Counter(row.get('native_row_coverage', {}).get('status', 'unavailable') for row in records))}}
    atomic_json(output / 'manifest.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase-root', type=Path, required=True)
    parser.add_argument('--capture-root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-tables', action='store_true')
    args = parser.parse_args()
    report = assemble(args.phase_root, args.capture_root, args.output, native_tables=args.native_tables)
    print(json.dumps(report['summary']))
    return int(any(row['status'] != 'assembled' for row in report['documents']))


if __name__ == '__main__':
    raise SystemExit(main())
