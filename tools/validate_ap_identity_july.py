"""Evaluate AP identity binding on replayed July sources against golden/ap.jsonl.

Replay only (no provider). Golden is read here, as evaluation, never by the binding.
Usage: PYTHONPATH=src .venv/bin/python tools/validate_ap_identity_july.py <phase_dir> <state_dir>
"""
from collections import Counter
import json
from pathlib import Path
import sys

from kalmora.ap_identity_sources import resolve_ap_identity
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources

IDENTITY_REASONS = ("VENDOR_NOT_IN_MASTER", "WRONG_ADDRESSEE")


def main(phase_dir: str, state_dir: str) -> int:
    phase = Path(phase_dir)
    data = PhaseData(phase)
    sources = load_ap_sources(phase, Path(state_dir))
    golden = {row["doc_id"]: row for row in map(json.loads, (phase / "golden" / "ap.jsonl").open(encoding="utf-8"))}
    counts, mismatches = Counter(), []
    for doc_id, task in sorted(sources.items()):
        documents = [a.normalized.facts for a in task.attachments if a.normalized is not None]
        failed = any(a.error is not None for a in task.attachments)
        result = resolve_ap_identity(documents, task.message.raw, data)
        expected = golden[doc_id]
        got_reasons = {r for r in IDENTITY_REASONS if r in result.diagnostics}
        want_reasons = {r for r in IDENTITY_REASONS if r in expected["reasons"]}
        checks = {"company": result.company == expected["company"],
                  "vendor_id": result.vendor_id == expected["vendor_id"],
                  "reasons": got_reasons == want_reasons}
        counts["tasks"] += 1
        counts["extraction_failed"] += failed
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
    sys.exit(main(*sys.argv[1:3]))
