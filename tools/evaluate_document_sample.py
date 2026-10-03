#!/usr/bin/env python3
"""Offline evaluation of archived captures; annotations stay evaluator-only.

Use --verify-replay --case T01 without --annotations to prove provider-free replay.
This command never constructs an LLM client. Holdout annotations are read only
when an evaluator explicitly invokes --partition holdout after the formal freeze.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import builtins
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from kalmora.documents.contracts import Candidate, ResolutionRequest, ParsedDocument, fingerprint
from kalmora.documents.normalization import normalize_document_facts
from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore, ReplayError
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, _decode_value


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def selected_cases(manifest, partition, requested):
    cases = [case for case in manifest['cases'] if case['split'] == partition
             and (not requested or case['case_id'] in requested)]
    if not cases or (requested and set(requested) != {case['case_id'] for case in cases}):
        raise ValueError('Case selection is empty or crosses the selected partition')
    return cases


def original_document(router, entry, root):
    relative = Path(entry['path'])
    if relative.is_absolute() or '..' in relative.parts or any(part in relative.parts for part in ('golden', 'phase_test')):
        raise ValueError('Source is outside development originals')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('Original source hash mismatch')
    return router.parse(relative.relative_to('phase_dev').as_posix())


def captured_document(directory, item, entry, artifact, router, root):
    archive = directory / 'sources' / (entry['sha256'] + '.json')
    if not archive.exists():
        return original_document(router, entry, root)
    encoded = archive.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != item.get('parsed_document_sha256'):
        raise ValueError('Parsed document archive differs from captured file hash')
    document = ParsedDocument.from_dict(json.loads(encoded))
    original = (root / entry['path']).resolve()
    if (not original.is_relative_to(root) or document.source_sha256 != entry['sha256']
            or hashlib.sha256(original.read_bytes()).hexdigest() != entry['sha256']
            or document.path != Path(entry['path']).relative_to('phase_dev').as_posix()
            or document.transformation_sha256 != item.get('transformation_sha256')
            or document.transformation_sha256 != artifact['request_metadata'].get('transformation_sha256')):
        raise ValueError('Parsed document archive source/transformation identity mismatch')
    images = {(image.page, image.sha256) for image in document.images}
    for aid in document.processing_aids:
        provenance = aid.provenance
        if (provenance.get('source_sha256') != document.source_sha256
                or provenance.get('source_path') != document.path
                or provenance.get('page') != aid.page
                or (aid.page, provenance.get('image_sha256')) not in images
                or hashlib.sha256(aid.text.encode()).hexdigest() != provenance.get('text_sha256')
                or provenance.get('authoritative') is not False
                or not isinstance(provenance.get('config'), dict)):
            raise ValueError('Unverified processing aid provenance does not match captured original/image')
        for tool in ('renderer', 'ocr'):
            info = provenance.get('tools', {}).get(tool, {})
            if not info.get('version') or not isinstance(info.get('binary_sha256'), str) or len(info['binary_sha256']) != 64:
                raise ValueError('Processing aid tool provenance is missing')
    return document


def source_requests(document, facts, data):
    """Reuse only the capturer's identity helpers, without importing its provider.

    Legacy recordings stored request hashes but not request contents. Rebuild from
    observed source facts and ERP masters, then verify the archived request hash.
    No annotation values enter this helper or the source/candidate construction.
    """
    tree = ast.parse(Path(__file__).with_name('capture_document_sample.py').read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'observed', 'semantic_requests'}]
    if {node.name for node in functions} != {'observed', 'semantic_requests'}:
        raise ValueError('Original candidate identity helpers are unavailable')
    namespace = {'Candidate': Candidate, 'ResolutionRequest': ResolutionRequest}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<source-identity-helpers>', 'exec'), namespace)
    return namespace['semantic_requests'](document, facts, data)


def semantic_capture(directory, attachment, document, facts, config, data):
    captures = []
    for item in attachment.get('semantic', []):
        key = item['key']
        artifact = read_json(directory / 'semantic' / (key + '.json'))
        envelope = RecordingStore(directory / 'recordings')._read(key, 'resolve')
        # A typed envelope is checksum-verified by RecordingStore, not raw JSON
        # guessed to have payload.request. New artifacts can archive source here.
        archive = directory / 'requests' / (key + '.json')
        archived = read_json(archive) if archive.exists() else None
        if archived and 'payload' in archived:
            archived = _decode_value(archived['payload'])
        if archived and archived.get('type') == 'dict':
            archived = _decode_value(archived)
        source = ((archived or {}).get('source') or archived
                  or artifact.get('provenance', {}).get('source')
                  or envelope.get('artifact_provenance', {}).get('source'))
        if source:
            if isinstance(source, dict) and source.get('type') == 'dict':
                source = _decode_value(source)
            request = ResolutionRequest(document, tuple(Candidate(candidate['id'], candidate['attributes'])
                                        for candidate in source['candidates']), source.get('context', {}))
            requests = [request]
        else:
            requests = source_requests(document, facts, data)
        matching = [request for request in requests
                    if request.sha256 == artifact['request_metadata']['resolution_request_sha256']
                    and RecordingStore.key('resolve', request, config) == key]
        if len(matching) != 1:
            raise ValueError('Archived semantic request cannot be reconstructed uniquely from original inputs')
        request = matching[0]
        accepted = RecordingStore(directory / 'recordings').load('resolve', request, config, mode='replay')
        if accepted.result.to_dict() != artifact['result']:
            raise ValueError('Semantic artifact differs from validated recording')
        captures.append({'kind': request.context.get('reference_kind'),
                         'result': accepted.result.to_dict(), 'candidates': [candidate.id for candidate in request.candidates]})
    return captures


def live_report(directory, status):
    reports = [read_json(path) for path in sorted((directory / 'reports').glob('*.json'))]
    reports = [report for report in reports if report.get('input_metadata', {}).get('case_id') == status['case_id']]
    if not reports:
        return {}
    report = deepcopy(max(reports, key=lambda value: value.get('started_at', '')))
    attachments = status.get('attachments', [])
    if attachments and all(item.get('processing_kind') == 'source_tools' for item in attachments):
        proofs = [item.get('source_tools', {}) for item in attachments]
        spec = importlib.util.find_spec('kalmora.documents.xml_extractor')
        adapter_hash = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest() if spec and spec.origin else None
        module = __import__('kalmora.documents.xml_extractor', fromlist=['EXTRACTOR_VERSION']) if spec else None
        version = getattr(module, 'EXTRACTOR_VERSION', getattr(module, 'XML_EXTRACTOR_VERSION', None))
        config = read_json(directory / 'config.json').get('source_tools')
        valid = bool(adapter_hash and version and config is not None)
        for item, proof in zip(attachments, proofs):
            valid = valid and (proof.get('adapter_sha256') == adapter_hash and proof.get('adapter_version') == version
                and proof.get('config_sha256') == fingerprint(config)
                and proof.get('source_sha256') == item.get('sha256')
                and proof.get('transformation_sha256') == item.get('transformation_sha256')
                and item.get('_source_validated') is True and proof.get('fresh_processing') is True)
        if valid and status.get('live_evaluation_eligible') and not status.get('cache_hits') and not report.get('calls'):
            report.setdefault('input_metadata', {}).update(capture_mode='fresh_source_tools',
                response_source='source_tools', transport_mode='local', source_tools_validated=True, source_tools=proofs)
            return report
    if not status.get('live_evaluation_eligible') or status.get('cache_hits') or not status.get('new_capture'):
        report.setdefault('input_metadata', {})['capture_mode'] = 'cached_or_ineligible'
    return report


def semantic_kind(check):
    explicit = check.get('reference_kind')
    if explicit:
        return explicit
    # Select the question's original master kind, never its expected row/ID.
    master = Path(check.get('evidence', {}).get('document', '')).name
    return {'purchase_orders.jsonl': 'purchase_order', 'goods_receipts.jsonl': 'goods_receipt'}.get(master)


def offline_guards():
    original_import = builtins.__import__
    forbidden = ('openai', 'pydantic_ai', 'pydantic', 'pydantic_core', 'httpx', 'kalmora.llm', 'kalmora.documents.extractor')
    if any(any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden) for name in sys.modules):
        raise AssertionError('Provider modules were imported before offline replay/evaluation')
    def guarded_import(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden):
            raise AssertionError('Provider import forbidden during replay: ' + name)
        return original_import(name, *args, **kwargs)
    def denied_network(*args, **kwargs):
        raise AssertionError('Network forbidden during offline evaluation/replay')
    builtins.__import__ = guarded_import
    socket.create_connection = denied_network
    socket.socket.connect = denied_network
    socket.socket.connect_ex = denied_network
    socket.getaddrinfo = denied_network


async def verify_replay(args, cases):
    offline_guards()
    root = args.participant_root.resolve()
    router = DocumentRouter(root / 'phase_dev')
    verified = 0
    for case in cases:
        directory = args.captures_dir / case['case_id']
        config = RecordingConfig.from_dict(read_json(directory / 'config.json')['extraction'])
        replay = RecordedExtractor(RecordingStore(directory / 'recordings'), config, mode='replay')
        for entry in case['attachments']:
            artifact_path = directory / 'artifacts' / (entry['sha256'] + '.json')
            if not artifact_path.exists():
                raise ValueError('Replay requires every selected attachment to have an accepted capture')
            artifact = read_json(artifact_path)
            status = read_json(directory / 'capture.json')
            item = next(item for item in status['attachments'] if item['sha256'] == entry['sha256'])
            document = captured_document(directory, item, entry, artifact, router, root)
            replayed = await replay.extract_with_response(document)
            if replayed.facts.to_dict() != read_json(artifact_path)['facts']:
                raise ValueError('Replay facts differ from captured facts')
            if replayed.provenance.get('new_provider_calls') != 0 or replay.capture_calls:
                raise AssertionError('Replay attempted a provider capture')
            verified += 1
    print(json.dumps({'replay_verified': verified, 'provider_calls': 0, 'network_allowed': False}))
    return 0


def evaluate(args, manifest, cases):
    from kalmora.documents.evaluation import evaluate_sample
    from kalmora.documents.image_reviews import load_registry
    from kalmora.data import PhaseData
    if args.annotations is None:
        raise ValueError('--annotations is required for evaluator mode')
    offline_guards()
    root = args.participant_root.resolve()
    router, data = DocumentRouter(root / 'phase_dev'), PhaseData(root / 'phase_dev')
    captures, reports, semantics, request_errors = {}, {}, {}, []
    parsed_documents, transformation_hashes = {}, {}
    for case in cases:
        cid = case['case_id']
        directory = args.captures_dir / cid
        status = read_json(directory / 'capture.json') if (directory / 'capture.json').exists() else {'case_id': cid}
        config_path = directory / 'config.json'
        config = RecordingConfig.from_dict(read_json(config_path)['resolution']) if config_path.exists() else None
        raw, normalized, case_semantic = [], [], []
        for entry in case['attachments']:
            path = directory / 'artifacts' / (entry['sha256'] + '.json')
            if not path.exists():
                continue
            artifact = read_json(path)
            facts = DocumentFacts.from_dict(artifact['facts'])
            if facts.source_sha256 != entry['sha256']:
                raise ValueError('Artifact source hash does not match manifest')
            raw.append(facts.to_dict())
            normalized.append(normalize_document_facts(facts).facts.to_dict())
            recorded_attachment = next((item for item in status.get('attachments', []) if item['sha256'] == entry['sha256']), {})
            document = captured_document(directory, recorded_attachment, entry, artifact, router, root)
            recorded_attachment['_source_validated'] = True
            parsed_documents[entry['path']] = document
            transformation_hashes[entry['path']] = artifact['request_metadata'].get('transformation_sha256')
            if recorded_attachment.get('semantic'):
                try:
                    case_semantic.extend(semantic_capture(directory, recorded_attachment, document, facts, config, data))
                except (ValueError, KeyError, TypeError, ReplayError) as error:
                    request_errors.append({'case_id': cid, 'code': 'semantic_request_archive_mismatch',
                                           'reason': str(error)})
        captures[cid] = {'raw_facts': raw, 'normalized_facts': normalized}
        reports[cid] = live_report(directory, status)
        semantics[cid] = case_semantic
    # This is the first boundary that reads evaluator labels. Candidate requests
    # above were built solely from captures + original ERP identity.
    annotations = read_json(args.annotations)
    semantic_results, candidate_sets = {}, {}
    for check in annotations.get('semantic_candidates', []):
        key = check.get('check_id', check['case_id'])
        choices = [item for item in semantics.get(check['case_id'], []) if item['kind'] == semantic_kind(check)]
        if len(choices) == 1:
            semantic_results[key] = choices[0]['result']
            candidate_sets[key] = choices[0]['candidates']
    result = evaluate_sample(manifest, annotations, captures, source_root=root,
        semantic_results=semantic_results, candidate_sets=candidate_sets, run_reports=reports,
        scope=args.partition, output_path=args.output, parsed_documents=parsed_documents,
        transformation_hashes=transformation_hashes,
        image_reviews=load_registry(args.image_reviews) if args.image_reviews else None)
    if request_errors:
        from kalmora.facts import atomic_json
        result['violations'].extend(request_errors)
        result['passed'] = result['capture_correctness_passed'] = False
        atomic_json(args.output, result)
    summary = {key: result[key] for key in ('passed', 'capture_correctness_passed', 'live_capture_confirmed', 'metrics')}
    if args.partition == 'tuning':
        summary['failed_fields'] = {cid: [field['field'] for field in case['fields'] if not field['exact'] or not field['grounded']]
                                    for cid, case in result['cases'].items()}
    print(json.dumps(summary, sort_keys=True))
    return int(not result['passed'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--image-reviews', type=Path, help='Evaluator-only exact original-image quotation reviews')
    parser.add_argument('--captures-dir', type=Path, required=True)
    parser.add_argument('--participant-root', type=Path, required=True)
    parser.add_argument('--partition', choices=('tuning', 'holdout'), required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', action='append')
    parser.add_argument('--verify-replay', action='store_true')
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    cases = selected_cases(manifest, args.partition, args.case)
    if args.verify_replay:
        return asyncio.run(verify_replay(args, cases))
    if args.output is None:
        parser.error('--output is required for evaluator mode')
    if args.output.resolve().is_relative_to(args.participant_root.resolve()):
        parser.error('Evaluation output must be outside original participant data')
    return evaluate(args, manifest, cases)


if __name__ == '__main__':
    raise SystemExit(main())
