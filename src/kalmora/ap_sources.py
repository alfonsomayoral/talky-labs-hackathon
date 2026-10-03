"""Active-phase AP source preparation: metadata/XML first, residual capture next.

One packet per canonical task, every attachment/page retained, no accounting
decision or AP output fabricated from an extraction failure. Golden is unavailable.
"""
import asyncio
from dataclasses import asdict, dataclass
from decimal import Decimal
import os
from pathlib import Path

from .ap_phase_export import load_ap_task_inventory
from .ap_output import _pinned_ap_directory
from .data import PhaseData, load_json
from .documents.classification import (
    CLASSIFICATION_VERSION, ClassificationDiagnostic, DocumentClassification, classify_document,
)
from .documents.contracts import ParsedDocument, digest, fingerprint
from .documents.normalization import NORMALIZATION_VERSION, normalize_document_facts
from .documents.replay import RecordedExtractor
from .documents.router import DocumentRouter, PARSER_VERSION
from .documents.xml_extractor import XMLDocumentExtractor, XMLExtractionError, XML_EXTRACTOR_VERSION
from .facts import DocumentFacts, Evidence, Fact, atomic_json

SOURCE_RUNNER_VERSION = "ap-source-runner-v2"
_FACTURAE_CLASS = "/Facturae/Invoices[1]/Invoice[1]/InvoiceHeader[1]/InvoiceClass[1]"


def classify_ap_source(raw: DocumentFacts) -> DocumentClassification:
    """Compose literal classification with the supported XML format's class.

    OO/OC/CO/CC establish invoice type, OR/CR rectification. Copy classes do
    not establish DUPLICATE: that remains the historical duplicate policy.
    The original source candidates/evidence are retained, not rewritten as text.
    """
    base = classify_document(raw)
    if raw.extractor_version != XML_EXTRACTOR_VERSION:
        return base
    classes = tuple(f for f in raw.fields.get("raw.invoice_class", ())
                    if f.evidence.field == _FACTURAE_CLASS)
    if not classes:
        return base
    mapping = {"OO": "INVOICE", "OC": "INVOICE", "CO": "INVOICE", "CC": "INVOICE",
               "OR": "CREDIT_NOTE", "CR": "CREDIT_NOTE"}
    kinds = {mapping.get(f.value) for f in classes}
    diagnostics = (*base.diagnostics,)
    proof = (*base.evidence, *classes)
    if None in kinds:
        return DocumentClassification(None, "UNKNOWN", proof, (*diagnostics,
            ClassificationDiagnostic("UNSUPPORTED_FACTURAE_CLASS", "source class is not supported", classes)),
            SOURCE_RUNNER_VERSION + "/" + CLASSIFICATION_VERSION)
    if base.status == "CONFLICT" or len(kinds) > 1 or (base.document_type and base.document_type not in kinds):
        return DocumentClassification(None, "CONFLICT", proof, (*diagnostics,
            ClassificationDiagnostic("TYPE_CONFLICT", "Facturae class and source hints disagree", classes)),
            SOURCE_RUNNER_VERSION + "/" + CLASSIFICATION_VERSION)
    return DocumentClassification(next(iter(kinds)), "CLASSIFIED", proof, diagnostics,
                                  SOURCE_RUNNER_VERSION + "/" + CLASSIFICATION_VERSION)


@dataclass(frozen=True)
class APSourceRun:
    manifest_path: Path
    manifest: dict

    @property
    def stable_sha256(self):
        return self.manifest["stable_source_sha256"]


def _safe_file(phase: Path, relative: str) -> Path:
    path = phase / relative
    if (path.resolve().is_relative_to(phase) is False or "golden" in path.parts
            or "golden" in path.resolve().parts):
        raise ValueError("AP source escapes the active phase")
    return path


def _output_file(destination: Path, phase: Path, relative: str) -> Path:
    path = destination / relative
    resolved = path.resolve()
    if (not resolved.is_relative_to(destination) or resolved.is_relative_to(phase)
            or "golden" in resolved.parts):
        raise ValueError("source artifact path escapes its output directory")
    return path


def _inventory(phase: Path, doc_id: str) -> tuple[str, ...]:
    if Path(doc_id).name != doc_id or doc_id in (".", "..") or "\\" in doc_id:
        raise ValueError("AP task ID cannot be used as a document folder")
    folder = _safe_file(phase, f"inbox/ap/{doc_id}")
    if not folder.is_dir():
        return ()
    return tuple(sorted(child.relative_to(phase).as_posix() for child in folder.iterdir() if child.is_file()))


def _serializable(value):
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, Fact):
        return {"value": value.value, "evidence": asdict(value.evidence)}
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serializable(item) for item in value]
    return value


def residual_extractor(mode: str, raw_config: dict, captures, budget_usd=None, recorder=None) -> RecordedExtractor:
    """The recorded LLM boundary for residual sources. Record mode needs an explicit positive budget;
    the provider key comes from the environment, never from the configuration."""
    from .documents.replay import RecordingConfig, RecordingStore
    if mode == "record":
        if budget_usd is None:
            raise ValueError("record mode requires an explicitly authorized --budget-usd")
        budget = Decimal(budget_usd)
        if not budget.is_finite() or budget <= 0:
            raise ValueError("record mode requires a positive finite provider budget")
        from .llm.client import AsyncLLMClient, LLMConfig
        from .documents.extractor import LLMDocumentExtractor
        settings = dict(raw_config)
        include_aids = settings.pop("include_processing_aids", True)
        for name in ("input_rate", "output_rate"):
            if isinstance(settings[name], bool):
                raise ValueError("model pricing must use exact numeric rates")
            settings[name] = Decimal(settings[name])
        client = AsyncLLMClient(LLMConfig(budget_usd=budget, **settings), recorder)
        adapter = LLMDocumentExtractor(client, include_processing_aids=include_aids)
        return RecordedExtractor(RecordingStore(captures), RecordingConfig.from_adapter(adapter), mode="record",
                                 callback=adapter.extract_with_response, budget_usd=budget, recorder=recorder)
    if budget_usd is not None:
        raise ValueError("replay/fixture cannot accept a provider budget")
    return RecordedExtractor(RecordingStore(captures), RecordingConfig.from_dict(raw_config), mode=mode,
                             recorder=recorder)


PREFETCH_CONCURRENCY = 8


async def _prefetch_residuals(phase: Path, doc_ids, router, transform, extractor) -> None:
    """Record residual captures concurrently so the ordered pass reads them from the capture store.

    Only warms the store: any failure here is retried and reported by the ordered pass."""
    gate = asyncio.Semaphore(PREFETCH_CONCURRENCY)

    async def one(relative: str) -> None:
        async with gate:
            try:
                parsed = router.parse(relative)
                if transform is not None and parsed.media_type == "application/pdf":
                    parsed = await asyncio.to_thread(transform, parsed)
                if parsed.media_type not in {"application/xml", "text/xml"}:
                    await extractor.extract_with_response(parsed)
            except Exception:  # noqa: BLE001 - the ordered pass owns failures
                pass

    await asyncio.gather(*(one(relative) for doc_id in doc_ids for relative in _inventory(phase, doc_id)
                           if relative != f"inbox/ap/{doc_id}/message.json"))


async def prepare_ap_sources(phase_path: str | Path, destination: str | Path, *,
                             mode: str = "deterministic", extractor: RecordedExtractor | None = None,
                             transform=None) -> APSourceRun:
    """Prepare source packets; record mode requires the existing budget boundary.

    Replay/fixture adapters cannot contain provider callbacks. Supported XML and
    message metadata bypass that boundary in every mode. A transform can attach
    original page renderings; it must preserve source identity and every page.
    Residual source failures are explicit; no NOT_INVOICE/HOLD defaults are used.
    """
    if mode not in {"deterministic", "record", "replay", "fixture"}:
        raise ValueError("explicit source execution mode required")
    if extractor is not None and (not isinstance(extractor, RecordedExtractor) or extractor.mode != mode):
        raise ValueError("residual extraction requires the matching recorded boundary")
    if mode != "deterministic" and extractor is None:
        raise ValueError("record/replay/fixture requires an explicitly configured extractor")
    if mode == "deterministic" and extractor is not None:
        raise ValueError("deterministic source preparation cannot use a residual extractor")
    inventory = load_ap_task_inventory(phase_path)
    phase = inventory.phase_path
    destination = Path(destination).resolve()
    if destination.is_relative_to(phase) or "golden" in destination.parts:
        raise ValueError("AP source state must be outside the original phase and Golden")
    data, router, xml = PhaseData(phase), DocumentRouter(phase), XMLDocumentExtractor()
    if extractor is not None and Path(extractor.store.directory).resolve().is_relative_to(phase):
        raise ValueError("document captures must be outside the original phase")
    close_path = _safe_file(phase, "tasks/close.json")
    close_hash = digest(close_path.read_bytes())
    config = dict(source_runner=SOURCE_RUNNER_VERSION, parser=PARSER_VERSION,
        xml_extractor=XML_EXTRACTOR_VERSION, normalization=NORMALIZATION_VERSION,
        classification=CLASSIFICATION_VERSION,
        residual=extractor.config.to_dict() if extractor is not None else None)
    if extractor is not None and mode == "record":
        await _prefetch_residuals(phase, inventory.doc_ids, router, transform, extractor)
        # The ordered pass reads what was just recorded; a source whose capture failed stays unknown
        # instead of being retried one at a time.
        extractor = RecordedExtractor(extractor.store, extractor.config, mode="replay", recorder=extractor.recorder)
    packets, source_hashes, folder_inventories, provenance = [], {}, {}, []
    for doc_id in inventory.doc_ids:
        paths = _inventory(phase, doc_id)
        folder_inventories[doc_id] = paths
        for relative in paths:
            source_hashes[relative] = digest(_safe_file(phase, relative).read_bytes())
        message_path = f"inbox/ap/{doc_id}/message.json"
        errors, metadata = [], None
        attachments = [path for path in paths if path != message_path]
        if not attachments:
            errors.append("MISSING_DOCUMENT_SOURCE")
        if message_path not in paths:
            errors.append("MISSING_MESSAGE")
        else:
            message = load_json(_safe_file(phase, message_path))
            if not isinstance(message, dict) or message.get("doc_id") != doc_id:
                raise ValueError("AP message identity differs from its canonical task")
            metadata = DocumentFacts(source_hashes[message_path], "ap-message-source-v1", {
                key: [Fact(message[key], Evidence(message_path, "/" + key))]
                for key in message})
            declared = message.get("attachments")
            if (not isinstance(declared, list) or any(not isinstance(name, str) or not name
                    or Path(name).name != name or name in (".", "..", "message.json") or "\\" in name
                    for name in declared) or len(declared) != len(set(declared))):
                raise ValueError("message attachments require unique safe original filenames")
            missing = sorted(set(declared) - {Path(path).name for path in attachments})
            errors.extend("MISSING_ATTACHMENT:" + name for name in missing)
            # Preserve unlisted files too; a channel or message list cannot hide
            # an original invoice/DUA/time-sheet attachment from the workflow.
            errors.extend("UNLISTED_ATTACHMENT:" + Path(path).name for path in attachments
                          if Path(path).name not in declared)
        stages = []
        for relative in attachments:
            parsed, raw, origin, source_provenance, unknowns = None, None, None, {}, ()
            failure = None
            try:
                parsed = router.parse(relative)
                if parsed.source_sha256 != source_hashes[relative]:
                    raise ValueError("source changed before parsing")
                if transform is not None and parsed.media_type == "application/pdf":
                    transformed = transform(parsed)
                    if (not isinstance(transformed, ParsedDocument) or transformed.path != parsed.path
                            or transformed.source_sha256 != parsed.source_sha256
                            or {b.page for b in transformed.blocks} != {b.page for b in parsed.blocks}
                            or transformed.blocks != parsed.blocks):
                        raise ValueError("source transform cannot alter original blocks or discard pages")
                    parsed = transformed
                if parsed.media_type in {"application/xml", "text/xml"}:
                    try:
                        raw = await xml.extract(parsed)
                        origin = "deterministic_xml"
                    except XMLExtractionError:
                        pass  # unsupported XML is residual; never fabricate supported fields
                if raw is None:
                    if extractor is None:
                        failure = "RESIDUAL_EXTRACTION_REQUIRED"
                    else:
                        artifact = await extractor.extract_with_response(parsed)
                        raw, unknowns = artifact.facts, tuple(artifact.unknowns)
                        source_provenance = artifact.provenance
                        origin = "residual"
                if raw is not None and (raw.source_sha256 != parsed.source_sha256 or any(
                        f.evidence.document != relative for values in raw.fields.values() for f in values)):
                    raise ValueError("extracted facts belong to another attachment")
                if origin == "residual" and (
                        source_provenance.get("origin") != ("synthetic" if mode == "fixture" else "recorded")
                        or source_provenance.get("recording_key") != extractor.key(parsed)):
                    raise ValueError("residual capture origin/key differs from the configured source boundary")
            except Exception as exc:
                failure = getattr(exc, "category", getattr(exc, "code", "INVALID_SOURCE_STAGE"))
                source_provenance = dict(new_provider_calls=0 if mode != "record" else None,
                                         new_provider_cost_usd="0" if mode != "record" else None)
            normalized = normalize_document_facts(raw) if raw is not None and failure is None else None
            classification = classify_ap_source(raw) if normalized is not None else None
            if origin == "deterministic_xml" or mode == "deterministic":
                source_provenance = dict(new_provider_calls=0, new_provider_cost_usd="0")
            provenance.append(source_provenance)
            stable = dict(path=relative, source_sha256=source_hashes[relative],
                status="ACCEPTED" if normalized is not None else "UNKNOWN", error=failure,
                capture_origin=source_provenance.get("origin") if normalized is not None and origin == "residual" else None,
                recording_key=source_provenance.get("recording_key") if normalized is not None and origin == "residual" else None,
                parsed=parsed.to_dict() if parsed is not None else None,
                raw=raw.to_dict() if normalized is not None else None,
                normalized=normalized.facts.to_dict() if normalized is not None else None,
                normalization_diagnostics=_serializable([asdict(d) for d in normalized.diagnostics]) if normalized else [],
                classification=_serializable(asdict(classification)) if classification else None,
                unknowns=list(unknowns))
            artifact_key = fingerprint(dict(config=config, source=stable))
            artifact_path = _output_file(destination, phase, "sources/" + artifact_key + ".json")
            atomic_json(artifact_path, stable)
            stages.append(dict(path=relative, artifact=artifact_path.relative_to(destination).as_posix(),
                artifact_sha256=digest(artifact_path.read_bytes()), status=stable["status"], origin=origin,
                classification=classification.document_type if classification else None,
                classification_status=classification.status if classification else "UNKNOWN"))
        packets.append(dict(doc_id=doc_id, metadata=metadata.to_dict() if metadata else None,
                            attachments=stages, diagnostics=errors))
    if load_ap_task_inventory(phase).source_sha256 != inventory.source_sha256:
        raise ValueError("AP task inventory changed during source preparation")
    if digest(close_path.read_bytes()) != close_hash or load_json(close_path)["month"] != data.month:
        raise ValueError("phase clock changed during source preparation")
    if any(_inventory(phase, doc_id) != paths for doc_id, paths in folder_inventories.items()) or any(
            digest(_safe_file(phase, path).read_bytes()) != original for path, original in source_hashes.items()):
        raise ValueError("AP originals changed during source preparation")
    stable = dict(month=data.month, task_sha256=inventory.source_sha256,
                  close_sha256=close_hash, configuration=config, documents=packets)
    calls = [p.get("new_provider_calls") for p in provenance]
    costs = [p.get("new_provider_cost_usd") for p in provenance]
    attachments = [a for p in packets for a in p["attachments"]]
    manifest = dict(schema_version=1, mode=mode, accounting_run=False,
        stable_source_sha256=fingerprint(stable), **stable,
        report=dict(task_count=len(packets), attachment_count=len(attachments),
            incomplete_tasks=sum(any(not d.startswith("UNLISTED_ATTACHMENT:") for d in p["diagnostics"])
                                 for p in packets),
            deterministic_xml=sum(a["origin"] == "deterministic_xml" for a in attachments),
            unknown_sources=sum(a["status"] == "UNKNOWN" for a in attachments),
            new_provider_calls=sum(calls) if all(type(c) is int for c in calls) else None,
            new_provider_cost_usd=str(sum((Decimal(c) for c in costs), Decimal(0))) if all(c is not None for c in costs) else None))
    manifest_path = _output_file(destination, phase, "phase-sources.json")
    atomic_json(manifest_path, manifest)
    return APSourceRun(manifest_path, manifest)


class APPreparedSources(dict):
    """Task views with their preparation mode and operational diagnostics.

    Values retain the public APTaskSources contract. The mode describes the
    saved preparation; loading a fixture never upgrades it to a real recording.
    An absent message has an empty raw object/hash and an explicit diagnostic.
    """

    def __init__(self, *, manifest):
        super().__init__()
        self.source_mode = manifest["mode"]
        self.stable_source_sha256 = manifest["stable_source_sha256"]
        self.diagnostics = {}


def _read_prepared_source_bytes(path: Path, phase: Path) -> bytes:
    """Pin saved-source reads and reject redirects on every reopen."""
    path = Path(path).absolute()
    resolved = path.resolve()
    if (any(part.lower() == "golden" for part in (*path.parts, *resolved.parts))
            or resolved.is_relative_to(phase)):
        raise ValueError("prepared AP source redirected into original inputs or Golden")
    try:
        with _pinned_ap_directory(path) as directory:
            with os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory), "rb") as stream:
                return stream.read()
    except OSError as error:
        raise ValueError("prepared AP source path changed or contains a symlink") from error


def load_prepared_ap_sources(phase_path: str | Path, manifest_path: str | Path) -> APPreparedSources:
    """Load verified prepared views without a provider, callback or capture store.

    Originals, task/clock inventory, configuration versions, packet fingerprint
    and every content-addressed artifact must still agree. Normalization and
    classification are recomputed, preserving all candidates and unknowns.
    Default local PDF vision v2 is reproduced; other transformations are refused.
    Preparation failures remain attachment errors, never accounting decisions.
    """
    import json
    import re

    from .documents.ap_sources import APAttachment, APMessage, APTaskSources
    from .documents.contracts import source_path, valid_hash
    from .documents.replay import RecordingConfig, RecordingStore, validate_facts

    def read_snapshot(path):
        payload = _read_prepared_source_bytes(path, phase)
        value = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError("nonfinite prepared-source JSON")))
        if not isinstance(value, dict):
            raise ValueError("prepared source requires a JSON object")
        return value, digest(payload)

    inventory = load_ap_task_inventory(phase_path)
    phase = inventory.phase_path
    path = Path(manifest_path)
    if ("golden" in path.parts or "golden" in path.resolve().parts
            or path.resolve().is_relative_to(phase)):
        raise ValueError("prepared manifest must be outside the original phase and Golden")
    path = path.resolve()
    destination = path.parent
    manifest, manifest_hash = read_snapshot(path)
    if (manifest.get("schema_version") != 1 or manifest.get("accounting_run") is not False
            or manifest.get("mode") not in {"deterministic", "record", "replay", "fixture"}):
        raise ValueError("unsupported prepared-source manifest schema/mode")
    config = manifest.get("configuration")
    expected_versions = dict(source_runner=SOURCE_RUNNER_VERSION, parser=PARSER_VERSION,
        xml_extractor=XML_EXTRACTOR_VERSION, normalization=NORMALIZATION_VERSION,
        classification=CLASSIFICATION_VERSION)
    if (not isinstance(config, dict) or set(config) != {*expected_versions, "residual"}
            or any(config.get(key) != value for key, value in expected_versions.items())):
        raise ValueError("prepared source configuration versions differ from the current implementation")
    residual = config["residual"]
    if manifest["mode"] == "deterministic":
        if residual is not None:
            raise ValueError("deterministic prepared sources cannot contain residual configuration")
    else:
        if not isinstance(residual, dict) or RecordingConfig.from_dict(residual).to_dict() != residual:
            raise ValueError("prepared residual configuration is invalid")
    stable = {key: manifest.get(key) for key in (
        "month", "task_sha256", "close_sha256", "configuration", "documents")}
    valid_hash(manifest.get("stable_source_sha256"))
    if fingerprint(stable) != manifest["stable_source_sha256"]:
        raise ValueError("prepared source manifest fingerprint mismatch")
    close_path = _safe_file(phase, "tasks/close.json")
    close_hash = digest(close_path.read_bytes())
    if (manifest["task_sha256"] != inventory.source_sha256
            or manifest["close_sha256"] != close_hash
            or manifest["month"] != load_json(close_path)["month"]):
        raise ValueError("prepared source task inventory or phase clock changed")
    packets = manifest["documents"]
    if (not isinstance(packets, list) or any(not isinstance(p, dict) for p in packets)
            or tuple(p.get("doc_id") for p in packets) != inventory.doc_ids):
        raise ValueError("prepared packets differ from the exact canonical task inventory")

    result = APPreparedSources(manifest=manifest)
    router = DocumentRouter(phase)
    original_hashes, folder_inventories, artifact_hashes = {}, {}, {}
    for packet in packets:
        doc_id = packet["doc_id"]
        originals = _inventory(phase, doc_id)
        folder_inventories[doc_id] = originals
        for relative in originals:
            original_hashes[relative] = digest(_safe_file(phase, relative).read_bytes())
        message_path = f"inbox/ap/{doc_id}/message.json"
        attachments = tuple(relative for relative in originals if relative != message_path)
        diagnostics = ["MISSING_DOCUMENT_SOURCE"] if not attachments else []
        raw_message = {}
        message_hash = ""
        if message_path not in originals:
            diagnostics.append("MISSING_MESSAGE")
            if packet.get("metadata") is not None:
                raise ValueError("prepared metadata invents an absent message")
        else:
            raw_message = load_json(_safe_file(phase, message_path))
            if not isinstance(raw_message, dict) or raw_message.get("doc_id") != doc_id:
                raise ValueError("original message differs from its canonical AP task")
            message_hash = original_hashes[message_path]
            expected_metadata = DocumentFacts(message_hash, "ap-message-source-v1", {
                key: [Fact(raw_message[key], Evidence(message_path, "/" + key))]
                for key in raw_message})
            if packet.get("metadata") != expected_metadata.to_dict():
                raise ValueError("prepared metadata differs from all original message fields/hash")
            declared = raw_message.get("attachments")
            if (not isinstance(declared, list) or any(not isinstance(name, str) or not name
                    or Path(name).name != name or name in (".", "..", "message.json") or "\\" in name
                    for name in declared) or len(declared) != len(set(declared))):
                raise ValueError("message attachments require unique safe original filenames")
            diagnostics.extend("MISSING_ATTACHMENT:" + name for name in sorted(
                set(declared) - {Path(relative).name for relative in attachments}))
            diagnostics.extend("UNLISTED_ATTACHMENT:" + Path(relative).name for relative in attachments
                               if Path(relative).name not in declared)
        if packet.get("diagnostics") != diagnostics:
            raise ValueError("prepared packet diagnostics differ from original source inventory")
        stages = packet.get("attachments")
        if (not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages)
                or tuple(stage.get("path") for stage in stages) != attachments):
            raise ValueError("prepared attachments differ from every original attachment")
        views = []
        for stage in stages:
            relative = source_path(stage["path"])
            artifact_relative = source_path(stage.get("artifact"))
            artifact_path = _output_file(destination, phase, artifact_relative)
            artifact, artifact_hash = read_snapshot(artifact_path)
            valid_hash(stage.get("artifact_sha256"))
            if artifact_hash != stage["artifact_sha256"]:
                raise ValueError("prepared attachment artifact SHA-256 mismatch")
            artifact_hashes[artifact_path] = artifact_hash
            key = fingerprint(dict(config=config, source=artifact))
            if artifact_relative != "sources/" + key + ".json":
                raise ValueError("prepared attachment artifact configuration/content fingerprint mismatch")
            if (artifact.get("path") != relative
                    or artifact.get("source_sha256") != original_hashes[relative]):
                raise ValueError("prepared attachment differs from its exact original source/path")
            parsed = ParsedDocument.from_dict(artifact["parsed"]) if artifact.get("parsed") is not None else None
            if parsed is not None:
                _safe_file(phase, relative)
                current = router.parse(relative)
                if (parsed.path != relative or parsed.source_sha256 != original_hashes[relative]
                        or parsed.media_type != current.media_type or parsed.blocks != current.blocks):
                    raise ValueError("prepared parsed document differs from original blocks/pages/parser")
                if parsed.parser_version != current.parser_version:
                    if (current.media_type != "application/pdf" or not re.fullmatch(
                            re.escape(current.parser_version) + r"/pdf-vision-v2:[0-9a-f]{64}",
                            parsed.parser_version)):
                        raise ValueError("prepared parsed document differs from original blocks/pages/parser")
                    from .documents.ocr import PDFVisionConfig, PDFVisionProcessor

                    # Saved configuration is evidence to compare, never a source
                    # of executable tool paths or processing instructions.
                    default_config = PDFVisionConfig()
                    if (not parsed.processing_aids or any(aid.provenance.get("config")
                            != asdict(default_config) for aid in parsed.processing_aids)):
                        raise ValueError("prepared PDF vision requires the current local default configuration")
                    _safe_file(phase, relative)
                    current = PDFVisionProcessor(phase, default_config).process(current)
                # Authenticate the full view, including image bytes, warnings,
                # OCR aids and their provenance, even when hashes were rewritten.
                if parsed != current:
                    raise ValueError("prepared parsed document differs from original blocks/pages/parser")
            status, error, origin = artifact.get("status"), artifact.get("error"), stage.get("origin")
            if status != stage.get("status") or status not in {"ACCEPTED", "UNKNOWN"}:
                raise ValueError("prepared attachment status differs from its artifact")
            unknowns = artifact.get("unknowns")
            if not isinstance(unknowns, list):
                raise ValueError("prepared unknowns must preserve a list of source diagnostics")
            if status == "UNKNOWN":
                if (not isinstance(error, str) or not error or any(artifact.get(field) is not None
                        for field in ("raw", "normalized", "classification", "capture_origin", "recording_key"))
                        or artifact.get("normalization_diagnostics") != []
                        or stage.get("classification") is not None or stage.get("classification_status") != "UNKNOWN"):
                    raise ValueError("unknown prepared source cannot contain accepted observations")
                views.append(APAttachment(relative, parsed, unknowns=tuple(unknowns), error=error))
                continue
            if error is not None or parsed is None or origin not in {"deterministic_xml", "residual"}:
                raise ValueError("accepted prepared source requires an original and explicit extraction origin")
            if origin == "deterministic_xml":
                if artifact.get("capture_origin") is not None or artifact.get("recording_key") is not None:
                    raise ValueError("deterministic XML cannot contain residual capture provenance")
            else:
                expected_origin = "synthetic" if manifest["mode"] == "fixture" else "recorded"
                if (manifest["mode"] == "deterministic" or artifact.get("capture_origin") != expected_origin):
                    raise ValueError("prepared capture origin is incompatible with its manifest mode")
                valid_hash(artifact.get("recording_key"))
                if artifact["recording_key"] != RecordingStore.key(
                        "extract", parsed, RecordingConfig.from_dict(residual)):
                    raise ValueError("prepared recording key differs from source/configuration")
            raw = DocumentFacts.from_dict(artifact["raw"])
            version = XML_EXTRACTOR_VERSION if origin == "deterministic_xml" else (
                residual["extractor_version"] if residual is not None else None)
            if origin == "deterministic_xml" and parsed.media_type not in {"application/xml", "text/xml"}:
                raise ValueError("deterministic XML facts require an original XML source")
            derived = {}
            for name, namespace in {"line_count": "line", "statement_row_count": "statement",
                                    "detail_line_count": "detail_lines"}.items():
                if name in raw.fields:
                    indices = sorted({int(match[1]) for field in raw.fields if
                        (match := re.fullmatch(re.escape(namespace) + r"\.([1-9]\d*)\..+", field))})
                    fields = sorted({fact.evidence.field for field, facts in raw.fields.items()
                        if field.startswith(namespace + ".") for fact in facts})
                    derived[name] = dict(method="count_unique_contiguous_line_ids", line_ids=indices,
                                         source_fields=fields)
            if origin == "deterministic_xml":
                if raw.source_sha256 != parsed.source_sha256 or raw.extractor_version != version:
                    raise ValueError("prepared XML facts differ from original/extractor identity")
                leaves = {block.source_field: Fact(block.text, Evidence(
                    relative, block.source_field, block.page, block.text)) for block in parsed.blocks}
                if ({name: values for name, values in raw.fields.items() if name.startswith("raw.xml.")}
                        != {"raw.xml." + field: [fact] for field, fact in leaves.items()}
                        or any(fact != leaves.get(fact.evidence.field)
                               for values in raw.fields.values() for fact in values)):
                    raise ValueError("prepared XML observations differ from every original literal leaf")
            else:
                validate_facts(parsed, raw, version, dict(derived_fields=derived))
            normalized = normalize_document_facts(raw)
            classification = classify_ap_source(raw)
            if (artifact.get("normalized") != normalized.facts.to_dict()
                    or artifact.get("normalization_diagnostics") != _serializable(
                        [asdict(item) for item in normalized.diagnostics])
                    or artifact.get("classification") != _serializable(asdict(classification))
                    or stage.get("classification") != classification.document_type
                    or stage.get("classification_status") != classification.status):
                raise ValueError("prepared normalized observations/classification differ from current conversion")
            views.append(APAttachment(relative, parsed, raw, tuple(unknowns), normalized, classification))
        message = APMessage(message_path, message_hash, raw_message.get("received_at"),
            raw_message.get("channel"), raw_message.get("from"), raw_message.get("to"),
            raw_message.get("subject"), raw_message.get("body"), tuple(raw_message.get("attachments", ())), raw_message)
        result[doc_id] = APTaskSources(doc_id, message, tuple(views))
        result.diagnostics[doc_id] = tuple(diagnostics)
    if (digest(_read_prepared_source_bytes(path, phase)) != manifest_hash
            or load_ap_task_inventory(phase).source_sha256 != inventory.source_sha256
            or digest(close_path.read_bytes()) != close_hash
            or any(_inventory(phase, doc_id) != originals for doc_id, originals in folder_inventories.items())
            or any(digest(_safe_file(phase, relative).read_bytes()) != expected
                   for relative, expected in original_hashes.items())
            or any(digest(_read_prepared_source_bytes(artifact_path, phase)) != expected
                   for artifact_path, expected in artifact_hashes.items())):
        raise ValueError("prepared source snapshot changed while loading")
    return result
