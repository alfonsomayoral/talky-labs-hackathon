"""Bounded document stages; deterministic coordination, no accounting writes."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable

from kalmora.facts import DocumentFacts, atomic_json
from .contracts import ParsedDocument, ResolutionRequest, ResolutionResult, fingerprint
from .replay import RecordedExtractor, RecordedResolver, ReplayError, _result_dict


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    key: str
    value: DocumentFacts | ResolutionResult | None = None
    error: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    unknowns: tuple[Any, ...] = ()

    def stable_dict(self):
        value = self.value.to_dict() if isinstance(self.value, DocumentFacts) else (
            _result_dict(self.value) if isinstance(self.value, ResolutionResult) else None)
        return {'stage': self.stage, 'status': self.status, 'value': value, 'error': self.error,
                'unknowns': list(self.unknowns)}


@dataclass(frozen=True)
class DocumentRun:
    path: str
    source_sha256: str
    stages: tuple[StageResult, ...]

    def stable_dict(self):
        return {'path': self.path, 'source_sha256': self.source_sha256,
                'stages': [stage.stable_dict() for stage in self.stages]}


@dataclass(frozen=True)
class BatchResult:
    documents: tuple[DocumentRun, ...]
    report: dict[str, Any]

    @property
    def stable_sha256(self):
        """Accepted values/statuses only: mode/cost/timing never affect output identity."""
        return fingerprint([document.stable_dict() for document in self.documents])


class StageRunner:
    """Run extraction/resolution with ordered owner-thread landing writes.

    ``request_builder(document, facts)`` supplies current bounded candidates and
    masters/state context. Facts/phase/run-context hashes are added automatically.
    The caller applies deterministic AP policy and chronology to returned results.
    """
    def __init__(self, state_dir: str | Path, extractor: RecordedExtractor, *,
                 resolver: RecordedResolver | None = None, concurrency: int = 2,
                 landing=None):
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError('Concurrency must be a positive integer')
        if resolver is not None and resolver.mode != extractor.mode:
            raise ValueError('Extractor and resolver must share an explicit mode')
        self.state_dir, self.extractor, self.resolver = Path(state_dir), extractor, resolver
        if 'golden' in self.state_dir.resolve().parts:
            raise ValueError('Stage state cannot use golden')
        self.concurrency, self.landing = concurrency, landing
        self._owner = (os.getpid(), threading.get_ident())
        self._running = False

    def _state_key(self, phase, document, stage, input_key, context):
        return fingerprint({'phase': phase, 'path': document.path, 'source_sha256': document.source_sha256,
                            'transformation_sha256': document.transformation_sha256,
                            'stage': stage, 'input_key': input_key, 'run_context': context})

    def _state(self, key, *, phase, path, stage, status, input_key, error=None, provenance=None):
        # State is operational metadata, never a source of successful facts.
        atomic_json(self.state_dir/(key+'.json'), {'schema_version': 1, 'key': key,
                    'phase': phase, 'path': path, 'stage': stage, 'status': status,
                    'input_key': input_key, 'error': error, 'provenance': provenance or {}})

    @staticmethod
    def prepare_resolution(request: ResolutionRequest, facts: DocumentFacts, *, phase: str,
                           context: dict[str, Any] | None = None) -> ResolutionRequest:
        """Stable context augmentation, also used when authoring offline fixtures."""
        return ResolutionRequest(request.document, request.candidates, {
            **request.context, '_extraction_sha256': fingerprint(facts.to_dict()),
            '_phase': phase, '_run_context_sha256': fingerprint(context or {})})

    async def run(self, documents: list[ParsedDocument] | tuple[ParsedDocument, ...], *,
                  phase: str, stages: tuple[str, ...] = ('extract',),
                  selected_paths: set[str] | None = None,
                  regenerate_paths: set[str] | None = None,
                  regenerate_stages: set[str] | None = None,
                  request_builder: Callable | None = None,
                  context: dict[str, Any] | None = None) -> BatchResult:
        if (os.getpid(), threading.get_ident()) != self._owner or self._running:
            raise RuntimeError('StageRunner has one owner and cannot run overlapping batches')
        if not isinstance(phase, str) or not phase or phase == 'golden':
            raise ValueError('Explicit solver phase is required')
        if not stages or len(set(stages)) != len(stages) or any(stage not in {'extract', 'resolve'} for stage in stages):
            raise ValueError('Select extract and/or resolve stages explicitly')
        if tuple(stage for stage in ('extract', 'resolve') if stage in stages) != stages:
            raise ValueError('Extraction must precede semantic resolution')
        if 'resolve' in stages and (self.resolver is None or not callable(request_builder)):
            raise ValueError('Resolution requires a resolver and current request builder')
        if any(not isinstance(document, ParsedDocument) for document in documents):
            raise ValueError('Runner inputs must be ParsedDocument objects')
        paths = {document.path for document in documents}
        if len(paths) != len(documents):
            raise ValueError('A source may occur only once per batch')
        if selected_paths is not None and not selected_paths <= paths:
            raise ValueError('Selected documents are not present in the batch')
        regenerate_paths = regenerate_paths or set()
        regenerate_stages = regenerate_stages or set()
        if not regenerate_paths <= paths or not regenerate_stages <= set(stages):
            raise ValueError('Regeneration selection is outside this batch/stages')
        if (regenerate_paths or regenerate_stages) and self.extractor.mode != 'record':
            raise ValueError('Regeneration requires explicit budgeted record mode')
        chosen = [document for document in documents if selected_paths is None or document.path in selected_paths]
        if not regenerate_paths <= {document.path for document in chosen}:
            raise ValueError('Regenerated documents must also be selected')
        run_context = context or {}
        fingerprint(run_context)
        semaphore = asyncio.Semaphore(self.concurrency)
        self._running = True
        async def one(document):
            outcomes = []
            facts = None
            current_stage = stages[0]
            input_key = self.extractor.key(document)
            state_key = self._state_key(phase, document, current_stage, input_key, run_context)
            try:
                async with semaphore:
                    if 'extract' not in stages:
                        # Resolve-only cannot silently capture omitted extraction.
                        facts = self.extractor.read(document).facts
                    for stage in stages:
                        current_stage = stage
                        if stage == 'extract':
                            source, boundary = document, self.extractor
                        else:
                            request = request_builder(document, facts)
                            if not isinstance(request, ResolutionRequest) or request.document != document:
                                raise ValueError('Request builder must refer to this exact parsed source')
                            source = self.prepare_resolution(request, facts, phase=phase, context=run_context)
                            boundary = self.resolver
                        input_key = boundary.key(source)
                        state_key = self._state_key(phase, document, stage, input_key, run_context)
                        self._state(state_key, phase=phase, path=document.path, stage=stage,
                                    status='RUNNING', input_key=input_key)
                        regenerate = ((not regenerate_paths or document.path in regenerate_paths)
                                      and (not regenerate_stages or stage in regenerate_stages)
                                      and bool(regenerate_paths or regenerate_stages))
                        artifact = await boundary._run(source, regenerate=regenerate)
                        value = artifact.facts if stage == 'extract' else artifact.result
                        if stage == 'extract':
                            facts = value
                        outcomes.append(StageResult(stage, 'ACCEPTED', state_key, value, provenance=artifact.provenance,
                                                    unknowns=tuple(getattr(artifact, 'unknowns', ()))))
                        self._state(state_key, phase=phase, path=document.path, stage=stage,
                                    status='ACCEPTED', input_key=input_key, provenance=artifact.provenance)
            except asyncio.CancelledError:
                self._state(state_key, phase=phase, path=document.path, stage=current_stage,
                            status='CANCELLED', input_key=input_key, error='cancelled')
                raise
            except Exception as exc:
                category = getattr(exc, 'category', 'invalid_stage_input')
                self._state(state_key, phase=phase, path=document.path, stage=current_stage,
                            status='FAILED', input_key=input_key, error=category)
                outcomes.append(StageResult(current_stage, 'FAILED', state_key, error=category,
                                provenance={'origin': getattr(exc, 'origin', None) or (
                                    'synthetic' if self.extractor.mode == 'fixture' else 'recorded'),
                                    'new_provider_calls': 0 if self.extractor.mode != 'record' else None,
                                    'new_provider_cost_usd': '0' if self.extractor.mode != 'record' else None}))
            return DocumentRun(document.path, document.source_sha256, tuple(outcomes))
        tasks = [asyncio.create_task(one(document)) for document in chosen]
        try:
            results = await asyncio.gather(*tasks)
            # Gather preserves caller chronology regardless of completion order.
            coordinated = []
            for result in results:
                stages_out = []
                for outcome in result.stages:
                    if outcome.stage == 'extract' and outcome.status == 'ACCEPTED' and self.landing is not None:
                        try:
                            self.landing.store_facts(result.path, outcome.value)
                        except Exception:
                            self._state(outcome.key, phase=phase, path=result.path, stage='extract',
                                        status='WRITE_FAILED', input_key=self.extractor.key(next(d for d in chosen if d.path == result.path)),
                                        error='landing_write_failed', provenance=outcome.provenance)
                            outcome = StageResult('extract', 'WRITE_FAILED', outcome.key, error='landing_write_failed',
                                                  provenance=outcome.provenance, unknowns=outcome.unknowns)
                    stages_out.append(outcome)
                coordinated.append(DocumentRun(result.path, result.source_sha256, tuple(stages_out)))
            outcomes_all = [outcome for doc in coordinated for outcome in doc.stages]
            current_calls = [outcome.provenance.get('new_provider_calls') for outcome in outcomes_all]
            current_costs = [outcome.provenance.get('new_provider_cost_usd') for outcome in outcomes_all]
            report = {'schema_version': 1, 'mode': self.extractor.mode, 'phase': phase,
                      'selected_paths': [document.path for document in chosen], 'stages': list(stages),
                      'regenerate_paths': sorted(regenerate_paths), 'regenerate_stages': sorted(regenerate_stages),
                      'origins': sorted({outcome.provenance.get('origin', 'unknown') for doc in coordinated for outcome in doc.stages}),
                      'cache_hits': sum(outcome.provenance.get('cache_hit', False) for doc in coordinated for outcome in doc.stages),
                      'new_provider_calls': sum(current_calls) if all(type(value) is int for value in current_calls) else None,
                      'new_provider_cost_usd': str(sum((Decimal(value) for value in current_costs), Decimal(0)))
                                              if all(value is not None for value in current_costs) else None,
                      'historical_capture_costs_usd': [outcome.provenance.get('historical_capture_cost_usd')
                                                     for doc in coordinated for outcome in doc.stages],
                      'unknown_capture_costs': sum(outcome.provenance.get('historical_capture_cost_usd') is None
                                                   for doc in coordinated for outcome in doc.stages)}
            batch = BatchResult(tuple(coordinated), report)
            report['stable_output_sha256'] = batch.stable_sha256
            atomic_json(self.state_dir/'last-run.json', report)
            return batch
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            atomic_json(self.state_dir/'last-run.json', {'schema_version': 1, 'mode': self.extractor.mode,
                        'phase': phase, 'status': 'CANCELLED', 'selected_paths': [d.path for d in chosen]})
            raise
        finally:
            self._running = False


__all__ = ['StageRunner', 'StageResult', 'DocumentRun', 'BatchResult']
