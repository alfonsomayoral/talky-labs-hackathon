"""Record and replay each AP task's inbox sources through the existing document chain.

Recording runs router -> LLMDocumentExtractor -> RecordedExtractor/StageRunner for
non-XML attachments and stores envelopes outside the repository. XML uses the
provider-free XMLDocumentExtractor at load time. Loading is replay-only: it never
builds a client or provider and returns explicit errors for missing or failed captures.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from typing import Any

from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts
from .classification import DocumentClassification, classify_document
from .contracts import ParsedDocument
from .normalization import NormalizedDocument, normalize_document_facts
from .replay import RecordedExtractor, RecordingConfig, RecordingStore, ReplayError
from .router import DocumentRouter
from .runner import StageRunner
from .xml_extractor import XMLDocumentExtractor, XMLExtractionError

CONFIG_FILE = "extraction-config.json"
MESSAGE = "message.json"
MODEL = "gpt-6-luna"
# Same conservative USD-per-token rates as tools/capture_document_sample.py.
PRICING = {"input_rate": Decimal("0.000000125"), "output_rate": Decimal("0.0000005"),
           "pricing_provenance": "https://developers.openai.com/api/docs/pricing 2026-10-03; Luna standard "
                                 "short-context USD/M input 0.10 x cache-write ceiling 1.25, output 0.50; "
                                 "conservative estimate, not invoice"}


@dataclass(frozen=True)
class APMessage:
    """message.json as received; ``raw`` keeps every original key (mailbox, uploaded_by...)."""
    path: str
    source_sha256: str
    received_at: str | None
    channel: str | None
    sender: str | None
    to: str | None
    subject: str | None
    body: str | None
    attachments: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class APAttachment:
    """One attachment's accepted facts, or an explicit operational error."""
    path: str
    document: ParsedDocument | None
    facts: DocumentFacts | None = None
    unknowns: tuple[Any, ...] = ()
    normalized: NormalizedDocument | None = None
    classification: DocumentClassification | None = None
    error: str | None = None


@dataclass(frozen=True)
class APTaskSources:
    doc_id: str
    message: APMessage
    attachments: tuple[APAttachment, ...]


def _folders(phase_dir: Path, doc_ids=None):
    tasks = PhaseData(phase_dir).table("tasks/ap_documents")
    if doc_ids:
        if not set(doc_ids) <= set(tasks):
            raise ValueError(f"Unknown AP tasks: {sorted(set(doc_ids) - set(tasks))}")
        tasks = [doc_id for doc_id in tasks if doc_id in doc_ids]
    router = DocumentRouter(phase_dir)
    return [(doc_id, router.parse_folder(f"inbox/ap/{doc_id}")) for doc_id in tasks]


def _is_message(path: str) -> bool:
    return path.rsplit("/", 1)[-1] == MESSAGE


def _needs_llm(document: ParsedDocument) -> bool:
    return not _is_message(document.path) and document.media_type != "application/xml"


def _save_config(state_dir: Path, config: RecordingConfig) -> None:
    path = state_dir / CONFIG_FILE
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != config.to_dict():
            raise ValueError(f"{path} holds another extraction configuration; use a new state directory")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=1, sort_keys=True), encoding="utf-8")


async def record_ap_sources(phase_dir: str | Path, state_dir: str | Path, client, *,
                            doc_ids=None, concurrency: int = 8) -> dict[str, Any]:
    """Capture every non-XML AP attachment with ``client``; failures are retried, successes reused."""
    from .extractor import LLMDocumentExtractor
    phase_dir, state_dir = Path(phase_dir), Path(state_dir)
    live = LLMDocumentExtractor(client)
    config = RecordingConfig.from_adapter(live)
    _save_config(state_dir, config)
    capture = RecordedExtractor(RecordingStore(state_dir / "recordings"), config, mode="record",
                                callback=live.extract_with_response,
                                budget_usd=client.config.budget_usd, recorder=client.recorder)
    folders = _folders(phase_dir, doc_ids)
    documents = [d for _, folder in folders for d in folder.documents if _needs_llm(d)]
    parse_errors = [{"path": e.path, "error": e.category} for _, folder in folders for e in folder.errors]
    batch = await StageRunner(state_dir / "stages", capture, concurrency=concurrency).run(
        documents, phase=phase_dir.resolve().name)
    failed = [{"path": run.path, "error": stage.error} for run in batch.documents
              for stage in run.stages if stage.status != "ACCEPTED"]
    return {"tasks": len(folders), "attachments": len(documents),
            "accepted": len(documents) - len(failed), "failed": failed, "parse_errors": parse_errors,
            "cache_hits": batch.report["cache_hits"]}


def load_ap_sources(phase_dir: str | Path, state_dir: str | Path) -> dict[str, APTaskSources]:
    """Replay-only: message metadata plus each attachment's recorded, normalized, classified facts."""
    phase_dir, state_dir = Path(phase_dir), Path(state_dir)
    config = RecordingConfig.from_dict(json.loads((state_dir / CONFIG_FILE).read_text(encoding="utf-8")))
    extractor = RecordedExtractor(RecordingStore(state_dir / "recordings"), config, mode="replay")
    sources = {}
    for doc_id, folder in _folders(phase_dir):
        message_error = next((e for e in folder.errors if _is_message(e.path)), None)
        if message_error is not None:
            raise ValueError(f"{message_error.path}: {message_error.category}")
        message_document = next(d for d in folder.documents if _is_message(d.path))
        raw = json.loads(message_document.blocks[0].text)
        message = APMessage(message_document.path, message_document.source_sha256, raw.get("received_at"),
                            raw.get("channel"), raw.get("from"), raw.get("to"), raw.get("subject"),
                            raw.get("body"), tuple(raw.get("attachments", ())), raw)
        attachments = [APAttachment(e.path, None, error=e.category) for e in folder.errors]
        for document in folder.documents:
            if _is_message(document.path):
                continue
            try:
                if _needs_llm(document):
                    capture = extractor.read(document)
                    facts, unknowns = capture.facts, capture.unknowns
                else:
                    facts, unknowns = asyncio.run(XMLDocumentExtractor().extract(document)), ()
            except ReplayError as error:
                attachments.append(APAttachment(document.path, document, error=error.category))
                continue
            except XMLExtractionError as error:
                attachments.append(APAttachment(document.path, document, error=error.code))
                continue
            attachments.append(APAttachment(document.path, document, facts, unknowns,
                                            normalize_document_facts(facts), classify_document(facts)))
        sources[doc_id] = APTaskSources(doc_id, message, tuple(sorted(attachments, key=lambda a: a.path)))
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kalmora.documents.ap_sources",
                                     description="Record or replay AP inbox source facts")
    parser.add_argument("command", choices=("record", "replay"))
    parser.add_argument("phase", type=Path, help="Phase directory with tasks/ and inbox/ap/")
    parser.add_argument("state", type=Path, help="External state/cache directory")
    parser.add_argument("--doc-id", action="append", help="Record only these AP tasks (repeatable)")
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("40"))
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    arguments = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(arguments)
    if args.command == "replay":
        sources = load_ap_sources(args.phase, args.state)
        attachments = [a for task in sources.values() for a in task.attachments]
        print(json.dumps({"tasks": len(sources), "attachments": len(attachments),
                          "with_facts": sum(a.facts is not None for a in attachments),
                          "errors": [{"path": a.path, "error": a.error} for a in attachments if a.error],
                          "classification": Counter(f"{a.classification.status}:{a.classification.document_type}"
                                                    for a in attachments if a.classification)}, indent=1))
        return 0
    from kalmora.llm.client import AsyncLLMClient, LLMConfig
    from kalmora.runlog import RunRecorder
    config = LLMConfig(MODEL, args.budget_usd, reasoning_effort="low", concurrency=args.concurrency,
                       timeout_seconds=args.timeout_seconds, image_detail="high", **PRICING)
    started = time.perf_counter()
    with RunRecorder(args.state / "runs", ["kalmora.documents.ap_sources", *arguments],
                     {"phase": str(args.phase.resolve())}) as run:
        summary = asyncio.run(record_ap_sources(args.phase, args.state, AsyncLLMClient(config, run),
                                                doc_ids=args.doc_id, concurrency=args.concurrency))
        run.report["ap_sources"] = summary
    summary.update(elapsed_seconds=round(time.perf_counter() - started, 1), run_report=str(run.path),
                   provider_calls=len(run.report["calls"]), cost=run.report["cost"],
                   llm_budget=run.report["llm_budget"])
    print(json.dumps(summary, indent=1))
    return 0 if not summary["failed"] and not summary["parse_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
