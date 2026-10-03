#!/usr/bin/env python3
"""Replay-only July evaluation of AP duplicate decisions; golden is read only here."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kalmora.ap_duplicate_sources import month_duplicate_results
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default=ROOT / "participant/phase_dev", type=Path)
    parser.add_argument("--state", default=ROOT / ".kalmora-cache/july", type=Path)
    args = parser.parse_args()
    sources = load_ap_sources(args.phase, args.state)
    results = month_duplicate_results(sources.values(), PhaseData(args.phase))
    golden = {row["doc_id"]: row for row in map(json.loads, (args.phase / "golden/ap.jsonl").open())}
    counts, mismatches = Counter(), []
    for doc_id in sorted(sources):
        expected = golden[doc_id]
        result = results.get(doc_id)
        status = result.status if result else "OUT_OF_SCOPE"
        counts[status] += 1
        is_dup, want_dup = status == "DUPLICATE", expected["decision"] == "DUPLICATE"
        if is_dup and want_dup and result.duplicate_of == expected["duplicate_of"]:
            counts["true_duplicate"] += 1
        elif is_dup or want_dup:
            kind = "wrong_root" if is_dup and want_dup else "false_duplicate" if is_dup else "missed_duplicate"
            counts[kind] += 1
            mismatches.append({"doc_id": doc_id, "kind": kind, "status": status,
                               "duplicate_of": result.duplicate_of if result else None,
                               "expected_duplicate_of": expected["duplicate_of"],
                               "diagnostics": list(result.diagnostics) if result else []})
    print(json.dumps({"tasks": len(sources), "golden_duplicates": sum(
        golden[d]["decision"] == "DUPLICATE" for d in sources), "counts": dict(sorted(counts.items())),
        "mismatches": mismatches}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
