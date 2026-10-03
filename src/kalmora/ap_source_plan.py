"""Read-only, replayable audit of AP sources and ordinary invoice contexts (#140)."""
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
from time import perf_counter_ns

from .ap_document_bridge import APField, DOCUMENT_BRIDGE_VERSION
from .ap_erp import load_ap_erp_baseline
from .ap_invoice_context import (
    CONTEXT_VERSION, _prepare_invoice_context_batch, resolve_ap_invoice_context,
)
from .ap_order_bridge import BRIDGE_VERSION
from .ap_sources import _read_prepared_source_bytes, load_prepared_ap_sources
from .ap_transaction import APTransactionState
from .data import PhaseData
from .documents.contracts import digest, fingerprint
from .facts import Evidence, Fact, _encode_value

SOURCE_PLAN_VERSION = "ap-source-plan-v1"


def _json(value):
    """Facts use the existing typed-v1 codec; display amounts never become floats."""
    if isinstance(value, Fact):
        return dict(value=_encode_value(value.value), evidence=asdict(value.evidence))
    if isinstance(value, Evidence):
        return asdict(value)
    if isinstance(value, APField):
        return dict(name=value.name, status=value.status, value=_encode_value(value.value),
            candidates=[_json(fact) for fact in value.candidates],
            evidence=[asdict(proof) for proof in value.evidence], diagnostics=list(value.diagnostics))
    if isinstance(value, Decimal):
        return _encode_value(value)
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {name: _json(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value  # preserve raw nonmonetary/invalid-source observations, never calculate money
    raise TypeError(f"unsupported source audit value: {type(value).__name__}")


def _source_audit(attachment, view, stage, artifact):
    parsed = attachment.document
    return dict(path=attachment.path,
        source_sha256=parsed.source_sha256 if parsed is not None else artifact["source_sha256"],
        artifact=stage["artifact"], artifact_sha256=stage["artifact_sha256"],
        stage_status=stage["status"], origin=stage["origin"],
        capture_origin=artifact.get("capture_origin"), recording_key=artifact.get("recording_key"),
        parsed=None if parsed is None else dict(media_type=parsed.media_type,
            parser_version=parsed.parser_version, block_count=len(parsed.blocks),
            page_image_count=len(parsed.images)),
        source_role="UNKNOWN" if view is None or view.classification.status != "CLASSIFIED"
            else "FINANCIAL" if view.classification.document_type in {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"}
            else "AUXILIARY",
        classification=_json(attachment.classification), error=attachment.error,
        extraction_unknowns=_json(attachment.unknowns),
        raw_facts=attachment.facts.to_dict() if attachment.facts is not None else None,
        normalized_facts=attachment.normalized.facts.to_dict() if attachment.normalized is not None else None,
        normalization_diagnostics=_json(attachment.normalized.diagnostics) if attachment.normalized is not None else [],
        header=None if view is None else _json(view.header),
        source_diagnostics=[] if view is None else list(view.diagnostics))


def _context_audit(context):
    request = context.request
    return dict(status=context.status,
        primary_source=None if context.primary_source is None else context.primary_source.source_path,
        financial_sources=[source.source_path for source in context.financial_sources],
        financial_header=_json(context.financial_facts.header), identity=_json(context.identity),
        scope=_json(context.scope), expected_company=_json(context.expected_company),
        observation=_json(context.observation), received_at=_json(context.received_at),
        invoice_date=_json(context.invoice_date), order_snapshot_sha256=context.order_snapshot_sha256,
        lines=[dict(line_id=line.source.line_id, source_path=line.source.source_path,
            quantity_milli=_json(line.source.quantity_milli), uom=_json(line.source.uom),
            unit_price_e4=_json(line.source.unit_price_e4), amount_cents=_json(line.source.amount_cents),
            references=_json(line.source.references), query=_json(line.query), match=_json(line.match),
            candidates=_json(line.candidates), diagnostics=list(line.diagnostics)) for line in context.lines],
        rejection_fields=_json(context.rejection_fields), hold_fields=_json(context.hold_fields),
        request_available=request is not None,
        request_summary=None if request is None else dict(
            amount_source_sha256s=[source.source_sha256 for source in request.amount_sources],
            receipt_as_of=_json(request.receipt_as_of),
            receipt_inventory_complete=_json(request.receipt_inventory_complete),
            duplicate_inventory_complete=_json(request.duplicate_inventory_complete),
            construction_subcontractor=_json(request.construction_subcontractor),
            guarantee_applicable=_json(request.guarantee_applicable),
            source_payable_basis=_json(request.source_payable_basis),
            header_available=request.header is not None, posting_available=request.posting is not None,
            line_source_bindings_status="NOT_EVALUATED"),
        evidence=_json(context.evidence), diagnostics=list(context.diagnostics))


async def plan_ap_sources(phase_path, manifest_path, *, receipt_as_of: Fact | None = None) -> dict:
    """Audit every prepared task; return JSON for the CLI to save outside source inputs.

    READY_CONTEXT is structural readiness only. No accounting decision, row,
    journal, provider/extractor/resolver call or output write occurs here. No
    cutoff/expected company is invented. A receipt-only state is used solely for
    PO capacity observations; advance/credit opening state is NOT_EVALUATED.
    """
    started = perf_counter_ns()
    if receipt_as_of is not None and not isinstance(receipt_as_of, Fact):
        raise TypeError("a receipt cutoff requires an observed Fact, not a date option")
    data = PhaseData(Path(phase_path))
    path = Path(manifest_path).resolve()
    prepared = load_prepared_ap_sources(data.phase_dir, path)
    manifest_bytes = _read_prepared_source_bytes(path, data.phase_dir)
    manifest_sha256 = digest(manifest_bytes)
    manifest = json.loads(manifest_bytes)
    if manifest["stable_source_sha256"] != prepared.stable_source_sha256:
        raise ValueError("prepared manifest changed before source planning")
    # This is the policy's AP GR/IR account (§2.3), not a phase/vendor/month rule.
    baseline = load_ap_erp_baseline(data.phase_dir, grir_account="40090000")
    batch = _prepare_invoice_context_batch(data, baseline)
    state = APTransactionState(consumption=baseline.history.consumption)
    packets = {packet["doc_id"]: packet for packet in manifest["documents"]}
    audits = []
    for doc_id, task in prepared.items():
        context = await resolve_ap_invoice_context(task, data=batch.data, baseline=baseline,
            state=state, receipt_as_of=receipt_as_of, _batch=batch)
        packet = packets[doc_id]
        views = {source.source_path: source for source in context.bridge.sources}
        stages = {stage["path"]: stage for stage in packet["attachments"]}
        sources = []
        for attachment in task.attachments:
            stage = stages[attachment.path]
            artifact_bytes = _read_prepared_source_bytes(path.parent / stage["artifact"], data.phase_dir)
            if digest(artifact_bytes) != stage["artifact_sha256"]:
                raise ValueError("prepared source artifact changed during source planning")
            artifact = json.loads(artifact_bytes)
            sources.append(_source_audit(attachment, views.get(attachment.path), stage, artifact))
        source_notes = tuple(prepared.diagnostics[doc_id])
        status = ("READY_CONTEXT" if context.status == "RESOLVED" and not source_notes else
                  "UNSUPPORTED" if context.status == "UNSUPPORTED" else "UNKNOWN")
        audits.append(dict(task_key=doc_id, status=status, source_diagnostics=list(source_notes),
            classification=_json(context.bridge.classification),
            message=dict(path=task.message.path, source_sha256=task.message.source_sha256,
                         fields=_json(task.message.raw)),
            attachments=sources, context=_context_audit(context),
            fiscal_decision_status="NOT_EVALUATED", monetary_posting_status="NOT_EVALUATED"))

    # Only publish a plan for a single, unchanged set of masters and originals.
    batch.verify()
    checked = load_prepared_ap_sources(data.phase_dir, path)
    if (digest(_read_prepared_source_bytes(path, data.phase_dir)) != manifest_sha256
            or checked.stable_source_sha256 != prepared.stable_source_sha256
            or checked.source_mode != prepared.source_mode or tuple(checked) != tuple(prepared)):
        raise ValueError("prepared sources changed during source planning")
    hashes = [dict(path=source.relative_to(data.phase_dir).as_posix(), sha256=sha)
              for source, sha in batch.source_hashes]
    certainty = baseline.history.certainties
    statuses = Counter(audit["status"] for audit in audits)
    stable = dict(schema_version=1, source_plan_version=SOURCE_PLAN_VERSION,
        run=dict(accounting_run=False, exportsAP=False, purpose="SOURCE_CONTEXT_AUDIT",
                 advances_opening_status="NOT_EVALUATED", credits_opening_status="NOT_EVALUATED"),
        versions=dict(invoice_context=CONTEXT_VERSION, document_bridge=DOCUMENT_BRIDGE_VERSION,
                      order_bridge=BRIDGE_VERSION),
        source_manifest=dict(mode=prepared.source_mode,
            stable_source_sha256=prepared.stable_source_sha256, month=manifest["month"],
            task_sha256=manifest["task_sha256"], close_sha256=manifest["close_sha256"],
            configuration=manifest["configuration"], configuration_sha256=fingerprint(manifest["configuration"])),
        active_erp=dict(month=baseline.month, sources=hashes,
            source_sha256=fingerprint(dict(month=baseline.month, sources=hashes)),
            order_snapshot_sha256=batch.orders.snapshot_sha256,
            historical_receipts=dict(count=len(certainty),
                known_capacity=sum(item.consumed_milli is not None for item in certainty),
                unknown_capacity=sum(item.consumed_milli is None for item in certainty),
                established_usages=len(baseline.history.consumption.usages),
                recorded_invoice_identities=len(baseline.history.consumption.invoices))),
        observed_receipt_cutoff=_json(receipt_as_of), task_keys=list(prepared),
        summary=dict(task_count=len(audits), attachment_count=sum(len(task.attachments) for task in prepared.values()),
                     statuses={status: statuses.get(status, 0) for status in ("READY_CONTEXT", "UNKNOWN", "UNSUPPORTED")}),
        tasks=audits)
    return dict(**stable, stable_plan_sha256=fingerprint(stable),
        execution=dict(phase_path=str(data.phase_dir), manifest_path=str(path),
            manifest_sha256=manifest_sha256,
            elapsed_ms=(perf_counter_ns() - started) // 1_000_000,
            new_provider_calls=0, new_provider_cost_usd="0"))
