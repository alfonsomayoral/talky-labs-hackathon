"""Standalone M5 command, leaving the shared CLI and other engines untouched."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from kalmora.data import PhaseData, _input_path
from kalmora.facts import atomic_json
from kalmora.ledger import Ledger
from kalmora.runlog import RunRecorder
from .adapters import load_upstream
from .engine import reconcile
from .model import Upstream


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M5 intercompany reconciliation; exit 3 means incomplete integration")
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--recorded-only", action="store_true", help="Explicitly acknowledge missing AP/bank deliveries")
    group.add_argument("--upstream", type=Path, help="Explicit AP/bank/prior projection manifest")
    parser.add_argument("--package", type=Path, help="Original organizer ZIP: hash only, never read by solver")
    parser.add_argument("--backend-commit", required=True, help="Verified backend base SHA, recorded as caller-supplied metadata")
    parser.add_argument("--write-projection", action="store_true", help="Also write the full corrected ledger")
    args = parser.parse_args(argv)
    phase = _input_path(args.phase).resolve()
    output = args.out.resolve()
    if output.is_relative_to(phase):
        parser.error("Output must be outside the immutable input phase")
    if args.package is not None and args.package.resolve().is_relative_to(output):
        parser.error("Output directory cannot contain the original package")
    data = PhaseData(phase)
    upstream = load_upstream(args.upstream) if args.upstream else Upstream.missing()
    metadata = {"backend_base_commit": args.backend_commit, "phase_path": str(phase),
                "journal_file_sha256": sha256(data._path("journal_entries")),
                "upstream_manifest_sha256": sha256(args.upstream) if args.upstream else None,
                "package_sha256": sha256(args.package) if args.package else None,
                "python": sys.version.split()[0], "golden_access": "none; original ZIP only hashed as bytes"}
    try:
        metadata["working_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        metadata["working_commit"] = None
    module_dir = Path(__file__).parent
    metadata["solver_file_sha256"] = {p.name: sha256(p) for p in sorted(module_dir.glob("*.py"))}
    command = ["python", "-m", "kalmora.ic", *(sys.argv[1:] if argv is None else argv)]
    with RunRecorder(output / "runs", command, metadata) as recorder:
        book = Ledger.from_entries(data.iter_journal())
        result = reconcile(data, recorded=book, upstream=upstream, metadata=metadata)
        write_jsonl(output / "ic.jsonl", result.records)
        # Append-only projection delta includes AP/bank owners, not just IC lines.
        original_ids = {e["id"] for e in book.iter_entries()}
        write_jsonl(output / "projection.adjustments.jsonl",
                    (e for e in result.projection.iter_entries() if e["id"] not in original_ids))
        if args.write_projection:
            write_jsonl(output / "projected_journal.jsonl", result.projection.iter_entries())
        audit = result.audit()
        audit["metadata"]["ic_jsonl_sha256"] = sha256(output / "ic.jsonl")
        audit["metadata"]["projection_adjustments_sha256"] = sha256(output / "projection.adjustments.jsonl")
        audit["metadata"]["task_file_sha256"] = sha256(data._path("tasks/intercompany"))
        atomic_json(output / "audit.json", audit)
        code = 0 if result.complete else 3
        recorder.report.update(exit_code=code, modular_contracts_complete=result.complete,
                               integration_mode=result.metadata["integration_mode"], real_flow_verified=False,
                               findings=len(result.findings), diagnostics=[d.code for d in result.diagnostics],
                               ic_jsonl_sha256=audit["metadata"]["ic_jsonl_sha256"])
        print(json.dumps({"complete": result.complete, "integration_mode": result.metadata["integration_mode"],
                          "real_flow_verified": False, "records": len(result.findings),
                          "diagnostics": [d.code for d in result.diagnostics], "out": str(output)}))
        return code


if __name__ == "__main__":
    raise SystemExit(main())
