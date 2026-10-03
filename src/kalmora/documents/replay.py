"""Atomic record/replay boundaries. Importing this module needs no provider extras."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from kalmora.facts import DocumentFacts, atomic_json, _encode_value, _decode_value
from .contracts import ParsedDocument, ResolutionRequest, ResolutionResult, fingerprint, valid_hash

SECRET_KEYS = {'authorization', 'api_key', 'openai_api_key', 'headers', 'access_token',
               'refresh_token', 'password', 'client_secret', 'x_api_key'}


class ReplayError(Exception):
    """Identifiable operational/cache failure; never an accounting result."""
    def __init__(self, category: str, *, stage: str, key: str, origin: str | None = None):
        super().__init__(f'{category}: stage={stage}, key={key}')
        self.category, self.stage, self.key, self.origin = category, stage, key, origin


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: '[redacted]' if key.lower().replace('-', '_') in SECRET_KEYS else _sanitize(child)
                for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(child) for child in value]
    if isinstance(value, str):
        return re.sub(r'(?i)bearer\s+[^\s"\']+', 'Bearer [redacted]',
                      re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', value))
    return value


def _checksum(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _cost(metadata: dict[str, Any]) -> str | None:
    value = metadata.get('capture_cost_usd')
    if value is None:
        return None
    if isinstance(value, float):
        raise ValueError('Capture cost must be an exact decimal string/Decimal')
    result = Decimal(value)
    if not result.is_finite() or result < 0:
        raise ValueError('Capture cost must be finite and nonnegative')
    return str(result)


def _raw_success(raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict):
        raise ValueError('Raw response must be an object')
    if raw.get('status') is not None and raw['status'] != 'completed':
        raise ValueError('An incomplete response cannot become accepted facts')
    for item in raw.get('output', []):
        if any(content.get('type') == 'refusal' for content in item.get('content', [])):
            raise ValueError('A refusal cannot become accepted facts')


def _result_dict(result: ResolutionResult) -> dict[str, Any]:
    return result.to_dict()


def _result_from_dict(value: dict[str, Any]) -> ResolutionResult:
    return ResolutionResult.from_dict(value)


def _literal(value: Any, quote: str) -> bool:
    quote = ' '.join(quote.split())
    if type(value) is bool:
        return any(re.search(r'(?<!\w)' + token + r'(?!\w)', quote, re.I)
                   for token in (('true', 'yes', 'sí') if value else ('false', 'no')))
    if isinstance(value, (str, int, Decimal)) and not isinstance(value, bool):
        literal = ' '.join(str(value).split())
        boundary = r'[\w.,]' if type(value) is int else r'\w'
        return bool(literal and re.search(r'(?<!' + boundary + ')' + re.escape(literal) + r'(?!' + boundary + ')', quote))
    return False


def validate_facts(document: ParsedDocument, facts: DocumentFacts, extractor_version: str,
                   provenance: dict[str, Any] | None = None) -> None:
    if facts.source_sha256 != document.source_sha256 or facts.extractor_version != extractor_version:
        raise ValueError('Accepted facts have a different source/extractor identity')
    line_ids = sorted({int(match.group(1)) for name in facts.fields
                       if (match := re.fullmatch(r'line\.([1-9]\d*)\.[a-z][a-z0-9_]*', name))})
    for name, values in facts.fields.items():
        for fact in values:
            evidence = fact.evidence
            if evidence.document != document.path:
                raise ValueError('Evidence belongs to another source')
            blocks = [block for block in document.blocks
                      if evidence.field == (block.source_field or block.id) and evidence.page == block.page]
            if name == 'line_count':
                derived = (provenance or {}).get('derived_fields', {}).get('line_count', {})
                fields = sorted({item.evidence.field for key, entries in facts.fields.items()
                                 if key.startswith('line.') for item in entries})
                if (type(fact.value) is not int or fact.value != len(line_ids)
                        or line_ids != list(range(1, len(line_ids)+1)) or not line_ids
                        or derived.get('method') != 'count_unique_contiguous_line_ids'
                        or derived.get('line_ids') != line_ids or derived.get('source_fields') != fields):
                    raise ValueError('Derived line count does not match accepted contiguous source lines')
                # The locator/quotation must still point to an actual source.
                literal_ok = True
            else:
                literal_ok = isinstance(evidence.quote, str) and _literal(fact.value, evidence.quote)
            if (fact.value is None and document.media_type == 'application/xml' and evidence.quote == ''
                    and any(block.source_field is not None and block.text == '' for block in blocks)):
                continue
            if fact.value is None and isinstance(evidence.quote, str):
                literal_ok = bool(re.search(r'(?i)\b(no|sin|not|missing|absent|ausente)\b', evidence.quote))
            if (blocks and isinstance(evidence.quote, str) and evidence.quote.strip()
                    and literal_ok and any(' '.join(evidence.quote.split()) in ' '.join(block.text.split()) for block in blocks)):
                continue
            images = [image for image in document.images if image.page == evidence.page]
            if images and literal_ok and isinstance(evidence.quote, str) and evidence.quote.strip() and any(evidence.field == f'image:{image.sha256}' for image in images):
                continue
            raise ValueError('Evidence locator/quotation does not match the parsed source')


def validate_resolution(request: ResolutionRequest, result: ResolutionResult) -> None:
    if not isinstance(result, ResolutionResult) or not set(result.selected_ids) <= {candidate.id for candidate in request.candidates}:
        raise ValueError('Resolution selects an ID outside current candidates')
    candidates = {candidate.id: candidate for candidate in request.candidates}
    constraints = request.context.get('hard_constraints', {})
    excluded = request.context.get('excluded_ids', [])
    for selected in result.selected_ids:
        if selected in excluded or any(fingerprint(candidates[selected].attributes.get(key)) != fingerprint(value) for key, value in constraints.items()):
            raise ValueError('Selection violates current hard constraints')
    proved = set()
    for evidence in result.evidence:
        if not isinstance(evidence, dict):
            raise ValueError('Resolution evidence must be an object')
        if evidence.get('source_sha256') != request.document.source_sha256:
            raise ValueError('Resolution evidence belongs to another source')
        candidate = candidates.get(evidence.get('candidate_id'))
        attribute = evidence.get('candidate_attribute')
        if (candidate is None or candidate.id not in result.selected_ids or attribute not in candidate.attributes
                or fingerprint(candidate.attributes[attribute]) != fingerprint(evidence.get('candidate_value'))):
            raise ValueError('Candidate proof does not match current attributes')
        proved.add(candidate.id)
        locator, quote = evidence.get('block_id'), evidence.get('quote')
        blocks = [block for block in request.document.blocks if locator == block.id]
        if (blocks and evidence.get('image_sha256') is None and isinstance(quote, str) and quote.strip()
                and _literal(evidence.get('source_value'), quote)
                and any(' '.join(quote.split()) in ' '.join(block.text.split()) for block in blocks)):
            continue
        images = [image for image in request.document.images if image.page == evidence.get('image_page')]
        if (images and blocks and isinstance(quote, str) and quote.strip()
                and _literal(evidence.get('source_value'), quote)
                and any(evidence.get('image_sha256') == image.sha256 and any(block.page == image.page for block in blocks) for image in images)):
            continue
        raise ValueError('Resolution evidence does not match the actual source')
    if proved != set(result.selected_ids):
        raise ValueError('A semantic selection requires source evidence')


@dataclass(frozen=True)
class RecordingConfig:
    provider: str
    model: str
    extractor_version: str
    prompt_version: str
    prompt_sha256: str
    schema_version: str
    schema_sha256: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if any(not isinstance(getattr(self, name), str) or not getattr(self, name)
               for name in ('provider', 'model', 'extractor_version', 'prompt_version', 'schema_version')):
            raise ValueError('Recording configuration requires explicit identities')
        if 'astra' in self.model.lower():
            raise ValueError('Astra is excluded')
        valid_hash(self.prompt_sha256)
        valid_hash(self.schema_sha256)
        if _sanitize(self.parameters) != self.parameters:
            raise ValueError('Credentials are forbidden in recording configuration')
        fingerprint(self.parameters)

    def to_dict(self):
        return {name: getattr(self, name) for name in ('provider', 'model', 'extractor_version',
                'prompt_version', 'prompt_sha256', 'schema_version', 'schema_sha256', 'parameters')}

    @classmethod
    def from_dict(cls, value):
        return cls(**value)

    @property
    def sha256(self):
        return fingerprint(self.to_dict())


@dataclass(frozen=True)
class ExtractionCapture:
    facts: DocumentFacts
    raw_response: dict[str, Any]
    request_metadata: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)
    unknowns: tuple[Any, ...] = ()

    def to_dict(self):
        return {'facts': self.facts.to_dict(), 'raw_response': self.raw_response,
                'request_metadata': self.request_metadata, 'provenance': self.provenance,
                'unknowns': list(self.unknowns)}


@dataclass(frozen=True)
class ResolutionCapture:
    result: ResolutionResult
    raw_response: dict[str, Any]
    request_metadata: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {'result': _result_dict(self.result), 'raw_response': self.raw_response,
                'request_metadata': self.request_metadata, 'provenance': self.provenance}


class RecordingStore:
    """Successful envelopes and error states are separate, checksum-verified JSON."""
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        if 'golden' in self.directory.resolve().parts:
            raise ValueError('Recording storage cannot use golden')

    @staticmethod
    def key(stage: str, source: ParsedDocument | ResolutionRequest, config: RecordingConfig) -> str:
        document = source.document if isinstance(source, ResolutionRequest) else source
        return fingerprint({'stage': stage, 'source_sha256': document.source_sha256,
                            'transformation_sha256': document.transformation_sha256,
                            'parser_version': document.parser_version,
                            'request_sha256': source.sha256 if isinstance(source, ResolutionRequest) else None,
                            'config': config.to_dict()})

    def _path(self, key: str, *, failure=False) -> Path:
        valid_hash(key)
        return self.directory / ('failures' if failure else 'entries') / (key + '.json')

    def _write(self, key: str, envelope: dict[str, Any], *, failure=False):
        encoded = _encode_value(envelope)
        payload = {'schema_version': 1, 'key': key, 'payload': encoded, 'sha256': _checksum(encoded)}
        # Retain every capture, including regenerated observations, before the
        # current pointer switches. Raw response and typed result share a commit.
        atomic_json(self.directory/'history'/key/(payload['sha256']+'.json'), payload)
        atomic_json(self._path(key, failure=failure), payload)

    def save(self, stage: str, source: ParsedDocument | ResolutionRequest, config: RecordingConfig,
             artifact: Any, *, origin: str = 'recorded') -> str:
        if origin not in {'recorded', 'synthetic'}:
            raise ValueError('Capture origin must be recorded or synthetic')
        if stage == 'extract' and isinstance(source, ParsedDocument):
            validate_facts(source, artifact.facts, config.extractor_version, getattr(artifact, 'provenance', {}))
            accepted = artifact.facts.to_dict()
        elif stage == 'resolve' and isinstance(source, ResolutionRequest):
            validate_resolution(source, artifact.result)
            accepted = _result_dict(artifact.result)
        else:
            raise ValueError('Stage/input mismatch')
        key = self.key(stage, source, config)
        _raw_success(artifact.raw_response)
        _cost(artifact.request_metadata)
        expected_metadata = {'model': config.model, 'prompt_version': config.prompt_version,
                             'prompt_sha256': config.prompt_sha256, 'schema_sha256': config.schema_sha256}
        if any(name in artifact.request_metadata and artifact.request_metadata[name] != value
               for name, value in expected_metadata.items()):
            raise ValueError('Capture metadata does not match declared model/prompt/schema configuration')
        self._write(key, {'status': 'accepted', 'stage': stage, 'origin': origin,
                         'config_sha256': config.sha256, 'config': config.to_dict(), 'accepted': accepted,
                         'raw_response': _sanitize(artifact.raw_response),
                         'request_metadata': _sanitize(artifact.request_metadata),
                         'unknowns': list(getattr(artifact, 'unknowns', ())),
                         'artifact_provenance': _sanitize(getattr(artifact, 'provenance', {}))})
        return key

    def save_failure(self, stage: str, source: ParsedDocument | ResolutionRequest,
                     config: RecordingConfig, category: str, *, origin='recorded',
                     raw_response=None, metadata=None):
        if origin not in {'recorded', 'synthetic'}:
            raise ValueError('Invalid failure origin')
        key = self.key(stage, source, config)
        self._write(key, {'status': 'failed', 'stage': stage, 'origin': origin,
                         'config_sha256': config.sha256, 'config': config.to_dict(), 'category': category,
                         'raw_response': _sanitize(raw_response or {}),
                         'request_metadata': _sanitize(metadata or {})}, failure=True)

    def _read(self, key: str, stage: str, *, failure=False):
        try:
            payload = json.loads(self._path(key, failure=failure).read_text(encoding='utf-8'))
            if (payload['schema_version'] != 1 or payload['key'] != key
                    or payload['sha256'] != _checksum(payload['payload'])):
                raise ValueError('Envelope identity/checksum mismatch')
            return _decode_value(payload['payload'])
        except FileNotFoundError:
            raise ReplayError('missing', stage=stage, key=key) from None
        except (ValueError, KeyError, TypeError, OSError):
            raise ReplayError('invalid_recording', stage=stage, key=key) from None

    def load(self, stage: str, source: ParsedDocument | ResolutionRequest, config: RecordingConfig,
             *, mode: str):
        if mode not in {'record', 'replay', 'fixture'}:
            raise ValueError('Explicit execution mode is required')
        key = self.key(stage, source, config)
        try:
            envelope = self._read(key, stage)
        except ReplayError as error:
            if error.category != 'missing':
                raise
            try:
                failure = self._read(key, stage, failure=True)
            except ReplayError as failure_error:
                if failure_error.category == 'missing':
                    raise error
                raise
            expected = 'synthetic' if mode == 'fixture' else 'recorded'
            if (failure.get('origin') != expected or failure.get('config_sha256') != config.sha256
                    or fingerprint(failure.get('config')) != config.sha256
                    or failure.get('status') != 'failed' or failure.get('stage') != stage):
                raise ReplayError('incompatible_recording', stage=stage, key=key)
            raise ReplayError(failure['category'], stage=stage, key=key, origin=failure['origin'])
        expected = 'synthetic' if mode == 'fixture' else 'recorded'
        try:
            if (envelope['status'] != 'accepted' or envelope['stage'] != stage
                    or envelope['config_sha256'] != config.sha256
                    or fingerprint(envelope['config']) != config.sha256 or envelope['origin'] != expected):
                raise ValueError('Incompatible capture')
            provenance = {**envelope['artifact_provenance'], 'mode': mode, 'origin': envelope['origin'],
                          'recording_key': key, 'cache_hit': True, 'new_provider_calls': 0,
                          'new_provider_cost_usd': '0',
                          'historical_capture_cost_usd': _cost(envelope['request_metadata'])}
            _raw_success(envelope['raw_response'])
            if stage == 'extract':
                facts = DocumentFacts.from_dict(envelope['accepted'])
                validate_facts(source, facts, config.extractor_version, envelope['artifact_provenance'])
                return ExtractionCapture(facts, envelope['raw_response'], envelope['request_metadata'],
                                         provenance, tuple(envelope['unknowns']))
            result = _result_from_dict(envelope['accepted'])
            validate_resolution(source, result)
            return ResolutionCapture(result, envelope['raw_response'], envelope['request_metadata'], provenance)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ReplayError('incompatible_recording', stage=stage, key=key) from None


class _RecordedBoundary:
    def __init__(self, store: RecordingStore, config: RecordingConfig, *, mode: str,
                 callback: Callable | None = None, budget_usd: Decimal | None = None, recorder=None):
        if mode not in {'record', 'replay', 'fixture'}:
            raise ValueError('Explicit record/replay/fixture mode is required')
        if mode == 'record':
            if not callable(callback) or not isinstance(budget_usd, Decimal) or not budget_usd.is_finite() or budget_usd <= 0:
                raise ValueError('Record mode requires a bounded callback and explicit positive Decimal budget')
            live_config = getattr(getattr(getattr(callback, '__self__', None), 'client', None), 'config', None)
            if live_config is not None:
                if getattr(live_config, 'model', config.model) != config.model:
                    raise ValueError('Bound client model differs from recording configuration')
                if getattr(live_config, 'budget_usd', budget_usd) > budget_usd:
                    raise ValueError('Bound client cap exceeds explicitly authorized recording budget')
        elif callback is not None:
            raise ValueError('Replay/fixture cannot receive a provider callback')
        self.store, self.config, self.mode = store, config, mode
        self.callback, self.budget_usd, self.recorder = callback, budget_usd, recorder
        self.cache_hits = self.capture_calls = self.failures = 0
        self._locks: dict[str, asyncio.Lock] = {}

    def key(self, source) -> str:
        return self.store.key(self.stage, source, self.config)

    def read(self, source):
        artifact = self.store.load(self.stage, source, self.config, mode=self.mode)
        self.cache_hits += 1
        if self.recorder is not None:
            self.recorder.record_cache_hit()
        return artifact

    async def _run(self, source, *, regenerate=False):
        key = self.key(source)
        async with self._locks.setdefault(key, asyncio.Lock()):
            if not regenerate or self.mode != 'record':
                try:
                    return self.read(source)
                except ReplayError as error:
                    if self.mode != 'record' or (error.category != 'missing' and error.origin != 'recorded'):
                        raise
            if self.mode != 'record':
                raise ReplayError('regeneration_requires_record', stage=self.stage, key=key)
            try:
                self.capture_calls += 1
                config_sha256 = self.config.sha256
                artifact = await self.callback(source)
                if self.config.sha256 != config_sha256:
                    raise ValueError('Recording configuration changed during the request')
                self.store.save(self.stage, source, self.config, artifact)
                loaded = self.store.load(self.stage, source, self.config, mode='record')
                attempts = artifact.request_metadata.get('attempt_metrics')
                loaded.provenance.update(cache_hit=False, new_provider_calls=len(attempts) if isinstance(attempts, list) else None,
                                         new_provider_cost_usd=_cost(artifact.request_metadata),
                                         budget_usd=str(self.budget_usd))
                return loaded
            except asyncio.CancelledError:
                self.store.save_failure(self.stage, source, self.config, 'cancelled')
                self.failures += 1
                raise
            except Exception as exc:
                category = getattr(exc, 'category', 'timeout' if isinstance(exc, TimeoutError) else 'invalid_response')
                metadata = {'capture_cost_usd': None, **getattr(exc, 'request_metadata', {}),
                            'budget_usd': str(self.budget_usd)}
                self.store.save_failure(self.stage, source, self.config, category,
                                        raw_response=getattr(exc, 'raw_response', getattr(exc, 'raw', {})),
                                        metadata=metadata)
                self.failures += 1
                raise ReplayError(category, stage=self.stage, key=key, origin='recorded') from None


class RecordedExtractor(_RecordedBoundary):
    stage = 'extract'

    async def extract_with_response(self, document: ParsedDocument, *, regenerate=False) -> ExtractionCapture:
        return await self._run(document, regenerate=regenerate)

    async def extract(self, document: ParsedDocument) -> DocumentFacts:
        return (await self.extract_with_response(document)).facts


class RecordedResolver(_RecordedBoundary):
    stage = 'resolve'

    async def resolve_with_response(self, request: ResolutionRequest, *, regenerate=False) -> ResolutionCapture:
        return await self._run(request, regenerate=regenerate)

    async def resolve(self, request: ResolutionRequest) -> ResolutionResult:
        return (await self.resolve_with_response(request)).result


__all__ = ['RecordingConfig', 'RecordingStore', 'RecordedExtractor', 'RecordedResolver',
           'ReplayError', 'ExtractionCapture', 'ResolutionCapture']
