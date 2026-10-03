"""Run deterministic close from saved handoffs: python -m kalmora.close."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import sys
import tempfile

from ..data import PhaseData
from ..facts import atomic_json
from ..money import RateTable
from ..runlog import RunRecorder
from .contracts import Handoff, encoded, file_hash, digest
from .engine import CloseEngine
from .projection import account_balances, dense_balances


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def execute(phase: Path, handoff_path: Path, output: Path, *, saved_facts_only: bool = False) -> dict:
    phase = phase.resolve()
    output = output.resolve()
    if output.is_relative_to(phase):
        raise ValueError("outputs must not overwrite ERP/inbox/tasks or source data")
    data = PhaseData(phase)
    handoff = Handoff.load(handoff_path, phase, verify_documents=not saved_facts_only)
    if handoff.payload["month"] != data.month:
        raise ValueError("handoff month differs from the close task")
    output.mkdir(parents=True, exist_ok=True)
    with RunRecorder(output / "runlogs", sys.argv, {"handoff_sha256": handoff.payload["payload_sha256"],
                     "phase": phase.name, "month": data.month, "python": platform.python_version()}) as recorder:
        engine = CloseEngine(data.iter_journal(), handoff, RateTable(data.table("fx_rates")),
                             data.table("customers"), data.table("ar_invoices"), data.table("promissory_notes"))
        result = engine.run()
        atomic_bytes(output / "close.jsonl", b"".join(encoded(row) for row in result.rows))
        atomic_bytes(output / "close_decisions.jsonl", b"".join(encoded(row) for row in result.decisions))
        atomic_bytes(output / "projection_events.jsonl", b"".join(encoded(row) for row in result.projection.log))
        snapshots = {"erp_original": result.projection.recorded,
                     "pre_m6": result.projection.pre_close, "final": result.final}
        for name, ledger in snapshots.items():
            atomic_bytes(output / (name + "_balance.json"), encoded(account_balances(ledger)))
            atomic_bytes(output / (name + "_positions.json"), encoded(dense_balances(ledger)))
        original, prior, final = (snapshots[k].balances() for k in ("erp_original", "pre_m6", "final"))
        impact = [{"company": key.company, "account": key.account, "original": original.get(key, 0),
                   "upstream_simulated_adjustment": prior.get(key, 0) - original.get(key, 0),
                   "m6_adjustment": final.get(key, 0) - prior.get(key, 0), "final": final.get(key, 0)}
                  for key in sorted(set(original) | set(prior) | set(final))]
        atomic_bytes(output / "balance_impact.json", encoded(impact))
        manifest = {"schema": "kalmora.close.freeze/v1", "phase": phase.name, "month": data.month,
            "integration": "simulated" if result.simulated else "real_audited_handoffs",
            "real_flow_gate": "OPEN: #171; module execution is not real M1-M5 integration evidence",
            "real_flow_verified": False,
            "integration_execution_complete": not result.simulated and handoff.complete and result.complete,
            "dependency_coverage_complete": handoff.complete, "engine_data_complete": result.complete,
            "estimation_limitations": handoff.payload["facts"].get("coverage_limitations", []),
            "handoff_sha256": handoff.payload["payload_sha256"], "handoff_file_sha256": file_hash(handoff_path),
            "solver_version": "m6_close/v1", "python": platform.python_version(),
            "solver_code_sha256": digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))}),
            "rows": len(result.rows), "types": dict(Counter(row["type"] for row in result.rows)),
            "projection_actions": dict(Counter(row["action"] for row in result.projection.log)),
            "files": {p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != "freeze.json"},
            "document_calls": 0, "llm_calls": 0, "saved_facts_only": saved_facts_only,
            "frozen_before_evaluation": True, "frozen_at": datetime.now(timezone.utc).isoformat()}
        atomic_json(output / "freeze.json", manifest)
        recorder.report["result"] = {"rows": len(result.rows), "close_sha256": manifest["files"]["close.jsonl"]}
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--saved-facts-only", action="store_true", help="verify ERP/tasks and sealed facts; do not reopen original documents")
    args = parser.parse_args()
    try:
        manifest = execute(args.phase, args.handoff, args.output, saved_facts_only=args.saved_facts_only)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"close: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(encoded({k: manifest[k] for k in ("integration", "rows", "types", "files", "engine_data_complete")}).decode(), end="")
    return 0 if manifest["engine_data_complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
