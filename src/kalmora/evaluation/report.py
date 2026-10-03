"""Assemble, write and print the evaluation report."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

from ..data import PhaseData
from .boundary import check_boundary
from .compare import (compare_ap, compare_ar_billing, compare_ar_cash, compare_bank, compare_close, compare_ic,
                      compare_tb)
from .diagnostics import check_submission, phase_ids
from .scorer import load_scorer, sha256_file

MODULES = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")
COMPARERS = {"ap": compare_ap, "ar_billing": compare_ar_billing, "ar_cash": compare_ar_cash,
             "bank_rec": compare_bank, "ic": compare_ic, "close": compare_close}
SCHEMA_VERSION = 1


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _hashes(directory: Path, names: list[str]) -> dict[str, str | None]:
    return {name: sha256_file(directory / name) if (directory / name).is_file() else None for name in names}


def evaluate(phase_dir: Path, submission_dir: Path, evaluator_dir: Path | None = None,
             scorer_path: Path | None = None) -> dict[str, Any]:
    """Compare a submission with the golden; without an evaluator directory only check its structure."""
    phase = PhaseData(phase_dir)
    submission_dir = Path(submission_dir)
    if not submission_dir.is_dir():
        raise FileNotFoundError(f"Submission directory not found: {submission_dir}")
    files = [f"{name}.jsonl" for name in MODULES]
    subs = {name: _load_rows(submission_dir / f"{name}.jsonl") for name in MODULES}
    journal_ids = {entry["id"] for entry in phase.iter_journal() if entry.get("id")}
    ids = phase_ids(phase, journal_ids)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "report_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(), "month": phase.month,
        "mode": "structure_only" if evaluator_dir is None else "compare",
        "provenance": {"phase": str(phase.phase_dir), "submission": str(submission_dir.resolve()),
                       "submission_sha256": _hashes(submission_dir, files)},
        "separation": check_boundary(),
        "files": {name: {"present": (submission_dir / f"{name}.jsonl").is_file(), "rows": len(subs[name])} for name in MODULES},
    }
    gold: dict[str, list[dict[str, Any]]] | None = None
    if evaluator_dir is not None:
        evaluator_dir = Path(evaluator_dir)
        golden_dir = evaluator_dir / "golden"
        if not golden_dir.is_dir():
            raise FileNotFoundError(f"No golden in {evaluator_dir}: this phase cannot be scored")
        scorer_file = scorer_path or evaluator_dir.parent / "score.py"
        manifest = evaluator_dir.parent.parent / "manifest.json"
        scorer, scorer_info = load_scorer(scorer_file, manifest)
        gold = {name: _load_rows(golden_dir / f"{name}.jsonl") for name in MODULES}
        headline = scorer.main(str(evaluator_dir), str(phase.phase_dir), str(submission_dir))
        modules: dict[str, Any] = {}
        for name in MODULES:
            result = COMPARERS[name](scorer, gold[name], subs[name])
            result["file_present"] = report["files"][name]["present"]
            modules[name] = result
        modules["trial_balance"] = compare_tb(scorer, str(evaluator_dir), subs)
        for name, result in modules.items():
            if abs(result["score"] - headline[name]["score"]) > 5e-5:
                result["reconciliation"]["ok"] = False
                result["reconciliation"]["checks"].append({"name": name + ".headline", "official": headline[name]["score"],
                                                           "derived": result["score"], "ok": False})
        report["headline"] = headline
        report["modules"] = modules
        report["reconciliation_ok"] = all(m["reconciliation"]["ok"] for m in modules.values())
        report["provenance"]["scorer"] = scorer_info
        report["provenance"]["golden_sha256"] = _hashes(
            golden_dir, files + ["trial_balance_truth.jsonl", "trial_balance_recorded.jsonl"])
    report["diagnostics"] = check_submission(subs, phase.month, ids, gold)
    counts: dict[str, int] = {}
    for item in report["diagnostics"]:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    report["diagnostic_counts"] = counts
    return report


def write_report(report: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['report_id']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return path


def summary(report: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": report["mode"], "month": report["month"], "diagnostics": report["diagnostic_counts"],
                              "separation_violations": len(report["separation"]["violations"])}
    if "headline" in report:
        result["total"] = report["headline"]["total"]
        result["modules"] = {name: m["score"] for name, m in report["modules"].items()}
        result["reconciliation_ok"] = report["reconciliation_ok"]
    return result


def text_summary(report: dict[str, Any]) -> str:
    lines = [f"Kalmora evaluation · {report['month']} · {report['mode']}"]
    if "modules" in report:
        lines.append(f"{'module':<14}{'score':>8}  {'answered':>9}  statuses")
        for name, m in report["modules"].items():
            counts = " ".join(f"{k}={v}" for k, v in sorted(m["status_counts"].items()))
            present = "" if m.get("file_present", True) else "  [file missing]"
            unscored = f"  unscored={m['unscored_differences']}" if m.get("unscored_differences") else ""
            lines.append(f"{name:<14}{m['score']:>8.4f}  {m['answered']:>4}/{m['total']:<4}  {counts}{unscored}{present}")
        lines.append(f"total {report['headline']['total']}  ·  reconciliation {'ok' if report['reconciliation_ok'] else 'FAILED'}")
    if report["diagnostic_counts"]:
        lines.append("diagnostics: " + ", ".join(f"{k}={v}" for k, v in sorted(report["diagnostic_counts"].items())))
    return "\n".join(lines)
