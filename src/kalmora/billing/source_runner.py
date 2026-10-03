"""Original AR sources -> recorded literal facts -> a current-phase billing run."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from ..data import PhaseData
from ..documents.contracts import ParsedDocument, SemanticResolver, digest, fingerprint
from ..documents.replay import RecordedExtractor, RecordedResolver, RecordingConfig, RecordingStore, ReplayError
from ..documents.router import DocumentRouter, ParseError
from ..documents.runner import StageRunner
from ..facts import DocumentFacts, atomic_json
from .engine import build_ar_billing
from .extraction import AR_NORMALIZATION_VERSION, NativeBillingExtractor, normalize_billing_facts
from .model import BillingItem, BillingRun, BillingType, Unresolved
from .observations import AR_OBSERVATIONS_VERSION, adapt_billing_sources
from .numbering import NUMBERING_VERSION, allocate_invoice_numbers
from .resolution import resolve_billing_references


SOURCE_RUNNER_VERSION = "ar-source-runner-v2"
# The shared recording boundary requires a positive cap even for a local parser.
# Native captures always declare zero provider attempts and zero actual cost.
_NATIVE_CAPTURE_CAP = Decimal("0.000001")


@dataclass(frozen=True)
class BillingSourceRun:
    billing: BillingRun
    report: dict[str, Any]
    report_path: Path

    @property
    def complete(self) -> bool:
        return self.report["coverage"]["unresolved_count"] == 0

    @property
    def stable_sha256(self) -> str:
        return self.report["stable_output_sha256"]


def _json(value: Any) -> Any:
    if isinstance(value, DocumentFacts):
        return value.to_dict()
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(child) for child in value]
    return value


def _output_path(root: Path, relative: str, phase: Path) -> Path:
    path = root / relative
    resolved = path.resolve()
    if (not resolved.is_relative_to(root) or resolved.is_relative_to(phase)
            or "golden" in resolved.parts):
        raise ValueError("AR artifact path escapes its work directory")
    return path


def _task_ids(data: PhaseData) -> tuple[str, ...]:
    values = data.table("tasks/ar_billing_items")
    if (not isinstance(values, list) or any(not isinstance(value, str) or not value
            or "/" in value or "\\" in value or value in {".", "..", "golden"} for value in values)
            or len(set(values)) != len(values)):
        raise ValueError("AR task inventory requires unique safe billing item IDs")
    return tuple(values)


def _input_snapshot(phase: Path, ids: tuple[str, ...]) -> dict[str, str]:
    paths = [phase / "tasks/close.json", phase / "tasks/ar_billing_items.json"]
    paths.extend(path for path in sorted((phase / "erp").iterdir())
                 if path.is_file() and path.suffix in {".json", ".jsonl"})
    for item_id in ids:
        folder = phase / "inbox/ar/billing" / item_id
        if folder.is_dir():
            paths.extend(path for path in sorted(folder.iterdir()) if path.is_file())
    result = {}
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(phase) or "golden" in resolved.parts:
            raise ValueError("AR input path escapes the active phase")
        result[path.relative_to(phase).as_posix()] = digest(path.read_bytes())
    return result


def _item(metadata: dict[str, Any], item_id: str) -> BillingItem:
    if not isinstance(metadata, dict) or metadata.get("billing_item") != item_id:
        raise ValueError("billing item metadata identity differs from the task")
    for name in ("company", "contract", "customer", "month", "type"):
        if not isinstance(metadata.get(name), str) or not metadata[name].strip():
            raise ValueError(f"billing item metadata requires {name}")
    return BillingItem(item_id, BillingType(metadata["type"]), metadata["company"],
                       metadata["contract"], metadata["customer"], metadata["month"])


def _resolver_boundary(resolver: SemanticResolver | None, config: RecordingConfig | None,
                       *, mode: str, store: RecordingStore, budget_usd: Decimal | None):
    if isinstance(resolver, RecordedResolver):
        if resolver.mode != mode:
            raise ValueError("AR extraction and resolution must share record/replay mode")
        if config is not None and config != resolver.config:
            raise ValueError("AR resolver configuration differs from its recorded boundary")
        return resolver
    if mode == "replay" and resolver is not None:
        raise ValueError("AR replay cannot receive a provider resolver callback")
    if resolver is not None:
        if not callable(getattr(resolver, "resolve_with_response", None)):
            raise ValueError("AR semantic capture requires resolve_with_response and recording identity")
        config = config or RecordingConfig.from_adapter(resolver)
    if config is None:
        return None
    if mode == "record" and resolver is None:
        raise ValueError("AR record resolution requires an explicitly supplied resolver")
    return RecordedResolver(store, config, mode=mode,
                            **({"callback": resolver.resolve_with_response, "budget_usd": budget_usd}
                               if mode == "record" else {}))


class _ResolutionStage:
    """Bind residual replay keys to literal extraction and this phase context."""
    def __init__(self, boundary: RecordedResolver, context: dict[str, Any]):
        self.boundary, self.context = boundary, context
        self.literals: dict[str, DocumentFacts] = {}
        self.captures: list[dict[str, Any]] = []

    async def resolve(self, request):
        prepared = StageRunner.prepare_resolution(request, self.literals[request.document.path],
                                                   phase=self.context["phase"], context=self.context)
        try:
            artifact = await self.boundary.resolve_with_response(prepared)
        except ReplayError as error:
            self.captures.append({"path": request.document.path, "request_sha256": prepared.sha256,
                "configuration": self.boundary.config.to_dict(), "error": error.category,
                "provenance": {"new_provider_calls": 0 if self.boundary.mode == "replay" else None,
                               "new_provider_cost_usd": "0" if self.boundary.mode == "replay" else None}})
            raise
        self.captures.append({"path": request.document.path, "request_sha256": prepared.sha256,
                              "configuration": self.boundary.config.to_dict(),
                              "provenance": artifact.provenance})
        return artifact.result


async def build_billing_from_sources(data: PhaseData, *, work_dir: str | Path,
                                     mode: str = "record", router: DocumentRouter | None = None,
                                     semantic_resolver: SemanticResolver | None = None,
                                     resolver_config: RecordingConfig | None = None,
                                     budget_usd: Decimal | None = None,
                                     concurrency: int = 2) -> BillingSourceRun:
    """Build current task outcomes with strict source coverage and capture identity.

    The default reader is local and incurs no provider cost. An optional semantic
    resolver requires an explicit record budget and is consulted only after exact
    matching. Replay supplies its configuration, never its provider callback.
    Publishing remains the caller's separate ``write_billing`` operation, and
    callers must require ``complete`` before publishing (metadata may be absent).
    """
    if mode not in {"record", "replay"}:
        raise ValueError("AR sources require explicit record or replay mode")
    if type(concurrency) is not int or concurrency < 1:
        raise ValueError("AR source concurrency must be a positive integer")
    phase, work = data.phase_dir.resolve(), Path(work_dir).resolve()
    if "golden" in work.parts or work.is_relative_to(phase):
        raise ValueError("AR work directory must be outside original phase data and golden")
    router = router or DocumentRouter(phase)
    if router.phase_path != phase:
        raise ValueError("AR router must read this exact active phase")
    ids = _task_ids(data)
    snapshot = _input_snapshot(phase, ids)
    context = {"runner_version": SOURCE_RUNNER_VERSION,
               "numbering_version": NUMBERING_VERSION,
               "normalization_version": AR_NORMALIZATION_VERSION,
               "observations_version": AR_OBSERVATIONS_VERSION,
               "phase": phase.name, "month": data.month,
               "phase_inputs_sha256": fingerprint(snapshot)}
    store = RecordingStore(_output_path(work, "recordings", phase))
    resolver = _resolver_boundary(semantic_resolver, resolver_config, mode=mode,
                                  store=store, budget_usd=budget_usd)
    resolution_stage = _ResolutionStage(resolver, context) if resolver is not None else None
    packets, items, parsed = [], [], {}
    for item_id in ids:
        folder = phase / "inbox/ar/billing" / item_id
        prefix = f"inbox/ar/billing/{item_id}/"
        children = ([path for path in sorted(folder.iterdir()) if path.is_file() and path.name != "item.json"]
                    if folder.is_dir() else [])
        packet: dict[str, Any] = {"billing_item": item_id, "metadata": None,
            "attachments": [{"path": prefix + path.name, "status": "UNRESOLVED"} for path in children],
            "diagnostics": []}
        packets.append(packet)
        try:
            metadata_document = router.parse(prefix + "item.json")
            packet["metadata"] = {"parsed": metadata_document.to_dict(), "value": None}
            metadata = json.loads(metadata_document.blocks[0].text)
            packet["metadata"]["value"] = metadata
            item = _item(metadata, item_id)
            declared = metadata.get("documents", [])
            if (not isinstance(declared, list) or len(set(declared)) != len(declared)
                    or any(not isinstance(name, str) or not name or "/" in name or "\\" in name
                           or name in {".", "..", "item.json"} for name in declared)):
                raise ValueError("billing document inventory requires unique safe filenames")
        except (ParseError, ValueError, KeyError, TypeError) as error:
            packet["diagnostics"].append({"code": "INVALID_ITEM_METADATA",
                "message": getattr(error, "category", str(error)), "source": prefix + "item.json"})
            for attachment in packet["attachments"]:
                attachment["error"] = "unresolved_item_metadata"
            continue
        items.append(item)
        packet["item"] = _json(item)
        for name in declared:
            if name not in {path.name for path in children}:
                packet["attachments"].append({"path": prefix + name, "status": "UNRESOLVED",
                                              "error": "missing_source"})
                packet["diagnostics"].append({"code": "MISSING_DOCUMENT_SOURCE", "source": prefix + name,
                                               "message": "declared supporting attachment is missing"})
        for attachment in packet["attachments"]:
            if attachment.get("error") == "missing_source":
                continue
            try:
                document = router.parse(attachment["path"])
                if document.source_sha256 != snapshot[attachment["path"]]:
                    raise ValueError("source changed during AR parsing")
                parsed[document.path] = (item, document, attachment)
            except (ParseError, ValueError) as error:
                attachment["error"] = getattr(error, "category", str(error))
                packet["diagnostics"].append({"code": "SOURCE_PARSE_FAILED", "source": attachment["path"],
                                               "message": attachment["error"]})
        if not children:
            packet["diagnostics"].append({"code": "MISSING_DOCUMENT_SOURCE", "message": "item has no supporting attachment"})

    async def extract_group(kind: BillingType):
        native = NativeBillingExtractor(kind)
        config = RecordingConfig.from_adapter(native)
        boundary = RecordedExtractor(store, config, mode=mode,
            **({"callback": native.extract_with_response, "budget_usd": _NATIVE_CAPTURE_CAP}
               if mode == "record" else {}))
        stage = StageRunner(_output_path(work, "stages/" + kind.value, phase), boundary,
                            concurrency=concurrency)
        documents = [document for item, document, _ in parsed.values() if item.type is kind]
        batch = await stage.run(documents, phase=phase.name, context=context)
        return kind, config, batch

    kinds = [kind for kind in BillingType if any(item.type is kind for item, _, _ in parsed.values())]
    batches = await asyncio.gather(*(extract_group(kind) for kind in kinds))
    prepared: dict[str, list[tuple[Any, ParsedDocument, Any]]] = {}
    stable_sources = []
    stage_reports = []
    for kind, config, batch in batches:
        stage_reports.append({"type": kind.value, "configuration": config.to_dict(), "report": batch.report})
        for document_run in batch.documents:
            item, document, attachment = parsed[document_run.path]
            outcome = document_run.stages[-1]
            artifact = {"schema_version": 1, "parsed": document.to_dict(),
                        "configuration": config.to_dict(), "extraction": _json(outcome)}
            attachment.update(source_sha256=document.source_sha256,
                              transformation_sha256=document.transformation_sha256)
            if outcome.status == "ACCEPTED":
                current_stage = "normalize"
                try:
                    observations = normalize_billing_facts(kind, outcome.value, document)
                    if resolution_stage is not None:
                        resolution_stage.literals[document.path] = outcome.value
                    current_stage = "resolve"
                    references = await resolve_billing_references(data, item, observations, document,
                        resolver=resolution_stage, raw_facts=outcome.value)
                    artifact.update(normalized=observations.to_dict(), resolution=_json(references))
                    artifact["resolution_captures"] = ([capture for capture in resolution_stage.captures
                        if capture["path"] == document.path] if resolution_stage is not None else [])
                    attachment["status"] = "PREPARED"
                    prepared.setdefault(item.id, []).append((observations, document, references))
                except (ValueError, TypeError, KeyError, ReplayError) as error:
                    attachment["error"] = getattr(error, "category", str(error))
                    artifact[current_stage + "_error"] = attachment["error"]
            else:
                attachment["error"] = outcome.error
            stable_sources.append({"path": document.path, "source_sha256": document.source_sha256,
                "transformation_sha256": document.transformation_sha256,
                "literal_facts": outcome.value.to_dict() if isinstance(outcome.value, DocumentFacts) else None,
                "unknowns": _json(outcome.unknowns), "normalized": artifact.get("normalized"),
                "resolution": artifact.get("resolution"), "error": attachment.get("error")})
            relative = "evidence/" + fingerprint({"path": document.path, "context": context,
                                                   "config": config.to_dict()}) + ".json"
            attachment["artifact"] = relative
            atomic_json(_output_path(work, relative, phase), artifact)

    facts, source_reasons = {}, {}
    for packet in packets:
        item_id = packet["billing_item"]
        attachments = packet["attachments"]
        if "item" not in packet:
            continue
        if packet["diagnostics"] or any(source["status"] != "PREPARED" for source in attachments):
            source_reasons[item_id] = tuple(
                [f"sources: {entry['code']}: {entry['message']}" for entry in packet["diagnostics"]]
                + [f"sources: {source['path']}: {source.get('error', 'unresolved')}"
                   for source in attachments if source["status"] != "PREPARED"])
            continue
        inputs = prepared[item_id]
        item = next(item for item in items if item.id == item_id)
        adaptation = adapt_billing_sources(data, item,
            tuple((observations, document) for observations, document, _ in inputs),
            references=tuple(references for _, _, references in inputs))
        packet["adaptation"] = _json(adaptation.diagnostics)
        if adaptation.facts is None:
            source_reasons[item_id] = tuple(f"sources: {entry.code}: {entry.field}: {entry.message}"
                                           for entry in adaptation.diagnostics)
        else:
            facts[item_id] = adaptation.facts

    preliminary = build_ar_billing(data, items, facts)
    numbers = allocate_invoice_numbers(data, items, preliminary)
    billing = build_ar_billing(data, items, facts, invoice_numbers=numbers)
    billing = BillingRun(billing.results, tuple(Unresolved(unresolved.item,
        source_reasons.get(unresolved.item.id, unresolved.reasons)) for unresolved in billing.unresolved),
        billing.pending_wip)
    resolved = {result.item.id: result for result in billing.results}
    failures = {unresolved.item.id: unresolved for unresolved in billing.unresolved}
    for packet in packets:
        result = resolved.get(packet["billing_item"])
        packet["status"] = "RESOLVED" if result else "UNRESOLVED"
        packet["decision"] = result.decision.value if result else None
        packet["outcome_evidence"] = _json(result.evidence) if result else []
        if packet["billing_item"] in failures:
            packet["engine_diagnostics"] = list(failures[packet["billing_item"]].reasons)
    if _input_snapshot(phase, ids) != snapshot:
        raise ValueError("original AR sources or phase inputs changed during the run")
    report = {"schema_version": 1, "runner_version": SOURCE_RUNNER_VERSION, "mode": mode,
              "phase": phase.name, "month": data.month, "context": context,
              "coverage": {"task_count": len(ids), "resolved_count": len(resolved),
                           "unresolved_count": len(ids) - len(resolved),
                           "attachment_count": sum(len(packet["attachments"]) for packet in packets),
                           "pending_wip_count": len(billing.pending_wip)},
              "stages": stage_reports, "items": packets,
              "stable_output_sha256": fingerprint({"context": context, "sources": stable_sources,
                                                     "billing": _json(billing)})}
    report["resolution_captures"] = resolution_stage.captures if resolution_stage is not None else []
    # All extraction here is native, including failures. Replay has no callbacks.
    costs = [capture["provenance"] for capture in report["resolution_captures"]]
    calls = [cost.get("new_provider_calls") for cost in costs]
    dollars = [cost.get("new_provider_cost_usd") for cost in costs]
    report["new_provider_calls"] = sum(calls) if all(type(value) is int for value in calls) else None
    report["new_provider_cost_usd"] = (str(sum((Decimal(value) for value in dollars), Decimal(0)))
        if all(value is not None for value in dollars) else None)
    report_path = _output_path(work, "ar-source-report.json", phase)
    atomic_json(report_path, report)
    return BillingSourceRun(billing, report, report_path)


__all__ = ["BillingSourceRun", "build_billing_from_sources", "SOURCE_RUNNER_VERSION"]
