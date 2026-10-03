"""Active-phase AP source preparation: metadata/XML first, residual capture next.

One packet per canonical task, every attachment/page retained, no accounting
decision or AP output fabricated from an extraction failure. Golden is unavailable.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from .ap_phase_export import load_ap_task_inventory
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

SOURCE_RUNNER_VERSION = "ap-source-runner-v1"
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
