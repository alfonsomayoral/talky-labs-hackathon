"""Evaluate AP identity binding on replayed July sources against golden/ap.jsonl.

Default is replay only (no provider). ``--record-resolutions`` first records, with a
USD 1 budget, a bounded LLMSemanticResolver request for each task the binding leaves
with ambiguous master vendors; replay then passes the recorded result as ``semantic``.
Golden is read here, as evaluation, never by the binding or the requests.
Usage: PYTHONPATH=src .venv/bin/python tools/validate_ap_identity_july.py <phase> <state> [--record-resolutions]
"""
import asyncio
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys

from kalmora.ap_identity_sources import resolve_ap_identity
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import MODEL, PRICING, load_ap_sources
from kalmora.documents.contracts import Candidate, ResolutionRequest
from kalmora.documents.replay import RecordedResolver, RecordingConfig, RecordingStore, ReplayError
from kalmora.documents.runner import StageRunner
from kalmora.facts import DocumentFacts

IDENTITY_REASONS = ("VENDOR_NOT_IN_MASTER", "WRONG_ADDRESSEE")
RESOLUTION_CONFIG = "resolution-config.json"
BUDGET_USD = Decimal("1")


def supplier_request(task, binding, data, phase):
    """Vendor candidates come only from the master set the binding left ambiguous."""
    attachment = next((a for a in task.attachments if a.document is not None), None)
    if attachment is None or not binding.supplier_candidates:
        return None
    vendors = {row["id"]: row for row in data.table("vendors")}
    candidates = tuple(Candidate(vendor_id, {key: vendors[vendor_id].get(key)
                                             for key in ("name", "tax_id", "vat_id", "email", "address")})
                       for vendor_id in binding.supplier_candidates)
    request = ResolutionRequest(attachment.document, candidates,
                                {"reference_kind": "vendor", "role": "supplier issuing this document",
                                 "message_sender": task.message.raw.get("from") or task.message.raw.get("uploaded_by")})
    facts = attachment.facts or DocumentFacts(attachment.document.source_sha256, "unextracted", {})
    return StageRunner.prepare_resolution(request, facts, phase=phase)


def requests(sources, data, phase):
    for doc_id, task in sorted(sources.items()):
        documents = [a.normalized.facts for a in task.attachments if a.normalized is not None]
        binding = resolve_ap_identity(documents, task.message.raw, data)
        request = supplier_request(task, binding, data, phase)
        if request is not None:
            yield doc_id, request


def record(phase_dir: Path, state_dir: Path, sources, data) -> dict:
    from kalmora.documents.extractor import LLMSemanticResolver
    from kalmora.llm.client import AsyncLLMClient, LLMConfig
    from kalmora.runlog import RunRecorder
    config = LLMConfig(MODEL, BUDGET_USD, reasoning_effort="low", image_detail="high", **PRICING)
    with RunRecorder(state_dir / "runs", ["validate_ap_identity_july", "--record-resolutions"],
                     {"phase": str(phase_dir.resolve())}) as run:
        live = LLMSemanticResolver(AsyncLLMClient(config, run))
        resolution_config = RecordingConfig.from_adapter(live)
        (state_dir / RESOLUTION_CONFIG).write_text(json.dumps(resolution_config.to_dict(), indent=1, sort_keys=True),
                                                   encoding="utf-8")
        resolver = RecordedResolver(RecordingStore(state_dir / "recordings"), resolution_config, mode="record",
                                    callback=live.resolve_with_response, budget_usd=BUDGET_USD, recorder=run)

        async def capture():
            outcome = {}
            for doc_id, request in requests(sources, data, phase_dir.resolve().name):
                try:
                    outcome[doc_id] = (await resolver.resolve(request)).status
                except ReplayError as error:
                    outcome[doc_id] = error.category
            return outcome
        outcome = asyncio.run(capture())
    return {"resolutions": outcome, "provider_calls": len(run.report["calls"]), "cost": run.report["cost"]}


def recorded_results(state_dir: Path, sources, data, phase):
    path = state_dir / RESOLUTION_CONFIG
    if not path.exists():
        return {}
    resolver = RecordedResolver(RecordingStore(state_dir / "recordings"),
                                RecordingConfig.from_dict(json.loads(path.read_text(encoding="utf-8"))), mode="replay")
    results = {}
    for doc_id, request in requests(sources, data, phase):
        try:
            results[doc_id] = resolver.read(request).result
        except ReplayError:
            continue
    return results


def main(phase_dir: str, state_dir: str, *flags: str) -> int:
    phase, state = Path(phase_dir), Path(state_dir)
    data = PhaseData(phase)
    sources = load_ap_sources(phase, state)
    if "--record-resolutions" in flags:
        print(json.dumps(record(phase, state, sources, data), default=str))
    semantic = recorded_results(state, sources, data, phase.resolve().name)
    golden = {row["doc_id"]: row for row in map(json.loads, (phase / "golden" / "ap.jsonl").open(encoding="utf-8"))}
    counts, mismatches = Counter(), []
    for doc_id, task in sorted(sources.items()):
        documents = [a.normalized.facts for a in task.attachments if a.normalized is not None]
        failed = any(a.error is not None for a in task.attachments)
        result = resolve_ap_identity(documents, task.message.raw, data, semantic.get(doc_id))
        expected = golden[doc_id]
        got_reasons = {r for r in IDENTITY_REASONS if r in result.diagnostics}
        want_reasons = {r for r in IDENTITY_REASONS if r in expected["reasons"]}
        checks = {"company": result.company == expected["company"],
                  "vendor_id": result.vendor_id == expected["vendor_id"],
                  "reasons": got_reasons == want_reasons}
        counts["tasks"] += 1
        counts["extraction_failed"] += failed
        counts["semantic_replayed"] += doc_id in semantic
        for name, ok in checks.items():
            counts[f"{name}_ok"] += ok
        if not all(checks.values()):
            counts["mismatch_extraction_failed" if failed else "mismatch_extracted"] += 1
            mismatches.append({"doc_id": doc_id, "extraction_failed": failed,
                               "company": [result.company, expected["company"]],
                               "vendor_id": [result.vendor_id, expected["vendor_id"]],
                               "reasons": [sorted(got_reasons), sorted(want_reasons)],
                               "diagnostics": list(result.diagnostics)})
    for row in mismatches:
        print(json.dumps(row, ensure_ascii=False))
    print(json.dumps(dict(counts), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
