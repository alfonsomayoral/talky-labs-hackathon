"""M6 fed by real deliveries and the verified IC audit/owned projection."""
from __future__ import annotations
import json
from pathlib import Path
import sys

from ..data import PhaseData
from ..close.contracts import encoded, file_hash, seal
from ..ic.model import digest as ic_digest
from ..close.rules import month_bounds
from .upstream import load_deliveries

TOOLS = Path(__file__).resolve().parents[3] / "tools"


def _ic_inputs(phase, deliverables):
    directory = deliverables.parent / "handoffs" / "ic"
    audit_path = directory / "audit.json"
    audit = json.loads(audit_path.read_text())
    upstream_path = directory / "upstream.json"
    upstream = json.loads(upstream_path.read_text())
    producer = json.loads((directory / "producer-manifest.json").read_text())
    metadata = audit["metadata"]
    data = PhaseData(phase)
    task = data.table("tasks/intercompany")
    coverage = metadata.get("task_coverage") or {}
    expected = sorted("/".join(sorted(p)) for p in task["pairs"])
    observed = sorted("/".join(sorted(p)) for p in coverage.get("pairs", []))
    if (not audit.get("complete") or not coverage.get("complete") or observed != expected
            or coverage.get("accounts") != sorted(task["accounts"])
            or coverage.get("month") != data.month
            or coverage.get("as_of") != month_bounds(data.month)[1].isoformat()
            or len(coverage.get("rules", [])) != 5):
        raise ValueError("IC audit is incomplete or does not cover the phase pairs/accounts")
    if (metadata["task_file_sha256"] != file_hash(data._path("tasks/intercompany"))
            or metadata["journal_file_sha256"] != file_hash(data._path("journal_entries"))
            or metadata["ic_jsonl_sha256"] != file_hash(deliverables / "ic.jsonl")
            or metadata["upstream_manifest_sha256"] != file_hash(upstream_path)
            or metadata["projection_adjustments_sha256"] != file_hash(directory / "projection.adjustments.jsonl")
            or coverage["positions_sha256"] != ic_digest(audit["positions"])):
        raise ValueError("IC audit/output/source hash mismatch")
    provenance = upstream["provenance"]
    if (provenance.get("kind") != "real" or provenance.get("month") != data.month
            or provenance.get("phase") != phase.name
            or provenance["producer_manifest_sha256"] != file_hash(directory / "producer-manifest.json")
            or metadata["dependency_provenance"] != provenance):
        raise ValueError("IC producer provenance mismatch")
    for relative, hashed in producer["sources"].items():
        path = (phase / relative).resolve()
        if not path.is_relative_to(phase.resolve()) or "golden" in path.parts or file_hash(path) != hashed:
            raise ValueError("IC source changed: " + relative)
    for name in ("ap", "bank_rec"):
        if provenance["deliveries_sha256"][name] != file_hash(deliverables / (name + ".jsonl")):
            raise ValueError("IC consumed a different producer delivery: " + name)
    result = {"complete": True, "coverage": {"expected": expected, "observed": observed,
              "mode": "reconciled_pairs", "audit_sha256": file_hash(audit_path),
              "upstream_sha256": file_hash(upstream_path), "limitations": []}}
    postings = {}
    for name, values in (("ap", upstream["ap_entries"]), ("bank_rec", upstream["banks"]["entries"])):
        postings[name] = [{"event_id": v["event_id"], "stage": v["stage"],
                          "business_key": "producer:" + v["event_id"],
                          "journal_entry": v["entry"], "recorded_ids": [], "evidence": [v["evidence"]]}
                         for v in values]
    postings["ic"] = []
    for line in (directory / "projection.adjustments.jsonl").read_text().splitlines():
        entry = json.loads(line)
        owner = entry["provenance"]
        if owner["stage"] == "intercompany":
            findings = [f for f in audit["findings"] if f["event_id"] == owner["event_id"]]
            if len(findings) != 1:
                raise ValueError("IC owned adjustment has no unique audited finding")
            postings["ic"].append({**owner, "business_key": owner["event_id"],
                                   "journal_entry": entry, "recorded_ids": [],
                                   "evidence": findings[0]["evidence"]})
    # Preserve AP business identity independently of transient journal IDs.
    ap = {r["doc_id"]: r for r in load_deliveries(phase, deliverables, ("ap",))["ap"]}
    import m6_fixture
    for posting in postings["ap"]:
        row = ap[posting["event_id"]]
        posting["business_key"] = m6_fixture.ap_key(row["company"], row["vendor_id"], row["invoice_number"])
    return result, postings


def run_close(phase: Path, deliverables: Path, work: Path) -> Path:
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    import m6_fixture
    from ..close.__main__ import execute

    coverage, postings = _ic_inputs(phase, deliverables)
    rows = load_deliveries(phase, deliverables, ("ap", "ar_billing", "bank_rec", "ar_cash", "ic"))

    def loader(_phase, producer):
        return rows[producer], file_hash(deliverables / (producer + ".jsonl"))

    bundle = m6_fixture.build(phase, loader=loader, provenance="real",
                             coverage_overrides={"ic": coverage}, owned_postings=postings)
    work.mkdir(parents=True, exist_ok=True)
    handoff = work / "dependencies.json"
    handoff.write_bytes(encoded(seal(bundle)))
    execute(phase, handoff, work / "frozen")
    return work / "frozen" / "close.jsonl"
