"""Compare replayed July HOLD gates with golden/ap.jsonl (evaluation only; reads golden).

PYTHONPATH=src .venv/bin/python tools/validate_ap_holds_july.py \
    [--phase participant/phase_dev] [--state ../.kalmora-cache/july] [--verbose]
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from kalmora.ap_chronology_sources import notice_events
from kalmora.ap_hold_sources import resolve_hold_sources
from kalmora.data import PhaseData
from kalmora.documents.ap_sources import load_ap_sources


def predict(sources, data):
    notices = []
    for task in sources.values():
        documents = [(a.normalized.facts, a.classification.document_type)
                     for a in task.attachments if a.normalized is not None]
        notices.extend(notice_events(task.message.raw, documents, data).events)
    predictions = {}
    for doc_id, task in sources.items():
        invoices = [a.normalized.facts for a in task.attachments
                    if a.normalized is not None and a.classification.document_type == "INVOICE"]
        if not invoices:
            predictions[doc_id] = ("NO_INVOICE_FACTS", ())
            continue
        result = resolve_hold_sources(doc_id=doc_id, documents=invoices, message=task.message.raw,
                                      data=data, notices=notices)
        stage = result.stage
        predictions[doc_id] = (stage.reason if stage.status == "HOLD" else stage.status, result.diagnostics)
    return predictions


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="/Users/alfonsomayoral/Talky/participant/phase_dev")
    parser.add_argument("--state", default=str(root.parent / ".kalmora-cache/july"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    phase = Path(args.phase)
    predictions = predict(load_ap_sources(phase, args.state), PhaseData(phase))
    golden = {row["doc_id"]: row for row in map(json.loads, (phase / "golden/ap.jsonl").open(encoding="utf-8"))}
    groups = Counter()
    for doc_id, row in sorted(golden.items()):
        predicted, diagnostics = predictions[doc_id]
        expected = row["reasons"][0] if row["decision"] == "HOLD" else None
        if expected:
            group = "hold_match" if predicted == expected else "hold_miss"
        elif row["decision"] in {"POST", "POST_PAYMENT_BLOCK"}:
            group = "false_hold" if predicted not in {"CLEAR", "UNKNOWN", "NO_INVOICE_FACTS"} else "post_" + predicted
        else:
            group = f"{row['decision'].lower()}_{'hold' if predicted not in {'CLEAR', 'UNKNOWN', 'NO_INVOICE_FACTS'} else predicted}"
        groups[group] += 1
        if group in {"hold_miss", "false_hold"} or (args.verbose and group.endswith("UNKNOWN")):
            print(f"{group:12} {doc_id} golden={expected or row['decision']} predicted={predicted} "
                  f"diagnostics={list(diagnostics)[-6:]}")
    by_reason = Counter((row["reasons"][0], predictions[d][0] == row["reasons"][0])
                        for d, row in golden.items() if row["decision"] == "HOLD")
    print(json.dumps({"tasks": len(golden), "groups": dict(sorted(groups.items())),
                      "holds_by_reason": {f"{r}:{'ok' if ok else 'miss'}": n for (r, ok), n in sorted(by_reason.items())}},
                     indent=1))


if __name__ == "__main__":
    main()
