"""Compare replayed July rejection gates with golden/ap.jsonl (evaluation only).

Usage: PYTHONPATH=src python tools/validate_ap_rejections_july.py PHASE_DIR STATE_DIR [--details]
Golden is read only here. VENDOR_NOT_IN_MASTER is a HOLD (identity) and is reported apart.
REJECT outcomes feed duplicate detection as month statuses; DUPLICATE wins over REJECT (§2.2).
"""
from collections import Counter
import json
from pathlib import Path
import sys

from kalmora.ap_duplicate_sources import month_duplicate_results
from kalmora.ap_rejection_sources import invoice_sources, rejection_stage
from kalmora.ap_rejections import REJECTION_CODES
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources


def predict(task, data):
    invoices = invoice_sources(task.attachments)
    if not invoices:
        failed = [a.path for a in task.attachments if a.error]
        return "NO_INVOICE_SOURCE" if not failed else "EXTRACTION_FAILED", None, ()
    stage = rejection_stage(invoices, task.message.raw, data)
    blocking = next((c for c in stage.checks if c.violation is not False), None)
    return stage.status, stage.reason, () if blocking is None else (blocking.code, *blocking.diagnostics)


def main(phase_dir, state_dir, details=False):
    phase_dir = Path(phase_dir)
    data = PhaseData(phase_dir)
    golden = {row["doc_id"]: row for row in map(json.loads, (phase_dir / "golden/ap.jsonl").open())}
    sources = load_ap_sources(phase_dir, state_dir)
    summary, rows, combined = Counter(), [], Counter()
    predictions = {doc_id: predict(task, data) for doc_id, task in sources.items()}
    duplicates = month_duplicate_results(sources.values(), data, statuses={
        doc_id: "REJECT" for doc_id, (status, _, _) in predictions.items() if status == "REJECT"})
    for doc_id, task in sources.items():
        expected = golden[doc_id]
        reason = next((r for r in expected["reasons"] if r in REJECTION_CODES), None)
        status, predicted, blocking = predictions[doc_id]
        duplicate = duplicates.get(doc_id)
        decision = ("DUPLICATE" if duplicate is not None and duplicate.status == "DUPLICATE" else
                    "REJECT" if status == "REJECT" else None)
        want = expected["decision"] if expected["decision"] in {"DUPLICATE", "REJECT"} else None
        right = (decision == want and (decision != "DUPLICATE" or duplicate.duplicate_of == expected["duplicate_of"])
                 and (decision != "REJECT" or predicted == reason))
        key = f"{want or 'OTHER'}->{decision or 'OTHER'}" + ("" if right or not decision else ":WRONG_DETAIL")
        combined[key] += 1
        if not right and (want or decision):
            rows.append({"doc_id": doc_id, "outcome": "COMBINED " + key, "golden": [expected["decision"],
                         expected["duplicate_of"], *expected["reasons"]], "predicted": [decision,
                         duplicate.duplicate_of if decision == "DUPLICATE" else predicted], "blocking": []})
        if decision == "DUPLICATE":
            status, predicted = "DUPLICATE", None
        if expected["decision"] == "DUPLICATE" and status == "DUPLICATE":
            outcome = "DUPLICATE_PRECEDES"
        elif expected["decision"] == "REJECT":
            outcome = "MATCH" if predicted == reason else "MISSED"
        elif "VENDOR_NOT_IN_MASTER" in expected["reasons"]:
            outcome = "VENDOR_NOT_IN_MASTER_" + status
        else:
            outcome = "FALSE_REJECT" if status == "REJECT" else "OK_" + status
        summary[outcome] += 1
        if outcome in {"MISSED", "FALSE_REJECT"} or (details and status == "UNKNOWN"):
            rows.append({"doc_id": doc_id, "outcome": outcome, "golden": [expected["decision"], *expected["reasons"]],
                         "predicted": [status, predicted], "blocking": list(blocking)})
    golden_rejects = Counter(r for row in golden.values() if row["decision"] == "REJECT" for r in row["reasons"])
    print(json.dumps({"tasks": len(sources), "golden_rejects": golden_rejects, "summary": summary, "combined_duplicate_reject": combined,
                      "blocking_unknown": Counter(row["blocking"][1] if len(row["blocking"]) > 1 else row["blocking"][0]
                                                  for row in rows if row["predicted"][0] == "UNKNOWN" and row["blocking"]),
                      "mismatches": rows}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--details" in sys.argv)
