#!/usr/bin/env python3
"""M5-only evaluation supplement. Never imported by kalmora.ic.

Runs the unchanged organizer scorer, then audits IC's required fields that it
ignores. It does not implement or replace the shared #35 scorer/comparator.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

REQUIRED = ("pair", "cause", "amount", "responsible", "adjustment")
LINE_FIELDS = ("company", "account", "debit", "credit", "partner", "cost_center", "wbs")
CAUSES = {"INVOICE_IN_TRANSIT", "INTEREST_DAY_COUNT", "WRONG_TRADING_PARTNER", "DUPLICATE_POSTING", "POOLING_NOT_BOOKED"}


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def rows(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def identity(row):
    pair = row.get("pair")
    cause = row.get("cause") if isinstance(row.get("cause"), str) else "<invalid cause>"
    return (tuple(sorted(pair)), cause) if isinstance(pair, list) and all(isinstance(c, str) for c in pair) else ((), cause)


def finance(line):
    return tuple(value if isinstance(value, (str, int, type(None))) else json.dumps(value, sort_keys=True)
                 for value in (line.get(field) for field in LINE_FIELDS))


def required_field_audit(reference, submitted, *, currencies=None):
    """Exact M5 contract comparison, not a scoring formula or shared comparator."""
    currencies = currencies or {}
    expected, actual = defaultdict(list), defaultdict(list)
    for row in reference:
        expected[identity(row)].append(row)
    structural = []
    for index, row in enumerate(submitted):
        if not isinstance(row, dict):
            structural.append({"row": index, "error": "JSON object required"})
            continue
        actual[identity(row)].append(row)
        for key in REQUIRED:
            if key not in row:
                structural.append({"row": index, "field": key, "error": "missing required field"})
        pair = row.get("pair", [])
        valid_pair = isinstance(pair, list) and len(pair) == 2 and all(isinstance(c, str) for c in pair) and len(set(pair)) == 2
        if not valid_pair or row.get("responsible") not in pair:
            structural.append({"row": index, "field": "pair/responsible", "error": "invalid group identity"})
        if type(row.get("amount")) is not int:
            structural.append({"row": index, "field": "amount", "error": "integer cents required"})
        if not isinstance(row.get("cause"), str) or row.get("cause") not in CAUSES:
            structural.append({"row": index, "field": "cause", "error": "unknown cause"})
        sums = defaultdict(int)
        adjustment = row.get("adjustment", [])
        if not isinstance(adjustment, list):
            structural.append({"row": index, "field": "adjustment", "error": "array required"})
            adjustment = []
        for n, line in enumerate(adjustment):
            if not isinstance(line, dict):
                structural.append({"row": index, "line": n, "error": "journal line object required"})
                continue
            if any(type(line.get(k)) is not int or line[k] < 0 for k in ("debit", "credit")):
                structural.append({"row": index, "line": n, "error": "invalid debit/credit cents"})
                continue
            if line["debit"] and line["credit"]:
                structural.append({"row": index, "line": n, "error": "both debit and credit positive"})
            if not valid_pair or line.get("company") not in pair:
                structural.append({"row": index, "line": n, "error": "journal company outside pair"})
            company = line.get("company")
            if not isinstance(company, str):
                structural.append({"row": index, "line": n, "error": "company string required"})
            else:
                sums[company] += line["debit"] - line["credit"]
        if any(sums.values()):
            structural.append({"row": index, "error": "unbalanced adjustment by company", "balances": dict(sums)})
        if row.get("cause") == "POOLING_NOT_BOOKED" and row.get("adjustment"):
            structural.append({"row": index, "error": "pooling must have no IC adjustment"})
    duplicates = [{"pair": list(key[0]), "cause": key[1], "rows": len(values)}
                  for key, values in actual.items() if len(values) > 1]
    detailed = []
    for key in sorted(expected, key=repr):
        golds, candidates = expected[key], actual.get(key, [])
        if len(golds) != 1 or len(candidates) > 1:
            detailed.append({"pair": list(key[0]), "cause": key[1], "status": "ambiguous_duplicate_key",
                             "required_fields_exact": False})
            continue
        gold = golds[0]
        if not candidates:
            detailed.append({"pair": list(key[0]), "cause": key[1], "status": "missing",
                             "expected_amount": gold["amount"], "expected_responsible": gold["responsible"],
                             "required_fields_exact": False, "reference_only_detail": gold.get("detail")})
            continue
        actual_row = candidates[0]
        g_lines = gold.get("adjustment", [])
        raw_lines = actual_row.get("adjustment", [])
        a_lines = [line for line in raw_lines if isinstance(line, dict)] if isinstance(raw_lines, list) else []
        g_fin, a_fin = Counter(finance(l) for l in g_lines), Counter(finance(l) for l in a_lines)
        checks = {"pair": actual_row.get("pair") == gold["pair"], "cause": actual_row.get("cause") == gold["cause"],
                  "amount": type(actual_row.get("amount")) is int and actual_row.get("amount") == gold["amount"],
                  "responsible": actual_row.get("responsible") == gold["responsible"],
                  "adjustment_required_fields": g_fin == a_fin and isinstance(raw_lines, list) and len(a_lines) == len(raw_lines)}
        extras = []
        pool = list(a_lines)
        for g in g_lines:
            matching = [a for a in pool if finance(a) == finance(g)]
            if matching:
                a = matching[0]
                pool.remove(a)
                for field in sorted(g.keys() - set(LINE_FIELDS)):
                    if a.get(field) != g[field]:
                        extras.append({"company": g.get("company"), "account": g["account"], "partner": g.get("partner"),
                                       "field": field, "expected": g[field], "actual": a.get(field)})
        detailed.append({"pair": list(key[0]), "cause": key[1], "status": "matched",
                         "expected_amount": gold["amount"], "actual_amount": actual_row.get("amount"),
                         "amount_delta_cents": actual_row["amount"] - gold["amount"] if type(actual_row.get("amount")) is int else None,
                         "expected_responsible": gold["responsible"], "actual_responsible": actual_row.get("responsible"),
                         "checks": checks, "required_fields_exact": all(checks.values()),
                         "missing_financial_lines": [{**dict(zip(LINE_FIELDS, l)), "count": count} for l, count in (g_fin - a_fin).items()],
                         "extra_financial_lines": [{**dict(zip(LINE_FIELDS, l)), "count": count} for l, count in (a_fin - g_fin).items()],
                         "additional_reference_line_fields": extras,
                         "reference_only_metadata": {k: v for k, v in gold.items() if k not in REQUIRED},
                         "journal_currencies_from_company_master": {l["company"]: currencies.get(l["company"]) for l in a_lines if isinstance(l.get("company"), str)}})
    unexpected = [{"pair": list(k[0]), "cause": k[1], "rows": values} for k, values in actual.items() if k not in expected]
    matched = [r for r in detailed if r["status"] == "matched"]
    return {"expected_rows": len(reference), "submitted_rows": len(submitted), "matched_keys": len(matched),
            "required_fields_exact_rows": sum(row["required_fields_exact"] for row in detailed),
            "required_plus_reference_line_fields_exact_rows": sum(r["required_fields_exact"] and not r.get("additional_reference_line_fields") for r in detailed),
            "field_matches_over_matched_rows": {field: sum(row["checks"][field] for row in matched)
                 for field in ("pair", "cause", "amount", "responsible", "adjustment_required_fields")},
            "all_required_fields_exact": not structural and not duplicates and not unexpected and all(r["required_fields_exact"] for r in detailed),
            "structural_errors": structural, "duplicate_submission_keys": duplicates,
            "unexpected_rows": unexpected, "rows": detailed,
            "additional_field_scope": "all reference line dimensions beyond the common fields are compared, including assignment/tax/currency/amount_doc when present"}



def shared_comparison(scorer_path, manifest_path, reference, submitted, submission_hash, *, required=False):
    """Consume the actual #35 public functions; never implement their scoring code."""
    try:
        from kalmora.evaluation import compare, explain, scorer
    except ModuleNotFoundError as exc:
        if exc.name not in {"kalmora.evaluation", "kalmora.evaluation.compare", "kalmora.evaluation.explain",
                            "kalmora.evaluation.scorer"}:
            raise
        if required:
            raise RuntimeError("The real #35 comparator is unavailable in this checkout") from exc
        return None
    official, identity_info = scorer.load_scorer(scorer_path, manifest_path)
    result = compare.compare_ic(official, reference, submitted)
    sources = {}
    for module in (compare, explain, scorer):
        path = Path(module.__file__)
        data = path.read_bytes()
        sources[module.__name__] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
    return {"submission_sha256": submission_hash, "producer": "kalmora.evaluation.compare.compare_ic",
            "upstream_source_files": sources, "scorer": identity_info, "result": result}


def evaluate(args):
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    submitted_path = args.submission / "ic.jsonl"
    submitted = rows(submitted_path.read_text(encoding="utf-8"))
    freeze = json.loads(args.freeze.read_text()) if args.freeze else None
    unchanged = None
    if freeze:
        root = Path(__file__).resolve().parents[1]
        unchanged = all(sha(root / p) == digest for p, digest in freeze["sha256"].items())
        if not unchanged:
            raise ValueError("Solver differs from the supplied pre-evaluation freeze")
        if freeze.get("submission_sha256") != sha(submitted_path):
            raise ValueError("Submission differs from the supplied pre-evaluation freeze")
    solver_audit = json.loads((args.submission / "audit.json").read_text())
    integration_mode = solver_audit.get("metadata", {}).get("integration_mode", "undeclared")
    phase_prefix = f"participant/{args.phase_name}"
    with tempfile.TemporaryDirectory(prefix="m5-evaluation-") as folder:
        reference_root = Path(folder)
        with zipfile.ZipFile(args.package) as source:
            scorer = source.read("participant/score.py")
            reference_bytes = source.read(f"{phase_prefix}/golden/ic.jsonl")
            currencies = {c["code"]: c["currency"] for c in json.loads(source.read(f"{phase_prefix}/erp/companies.json"))}
            # Only the evaluation process extracts reference members. Never into the solver tree.
            for name in source.namelist():
                if name.startswith(phase_prefix + "/golden/") and not name.endswith("/"):
                    relative = Path(name).relative_to(phase_prefix)
                    if ".." in relative.parts or relative.is_absolute():
                        raise ValueError("Unsafe reference path")
                    target = reference_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read(name))
        scorer_path = reference_root / "score.py"
        scorer_path.write_bytes(scorer)
        official_path = output / "organizer-score.json"
        command = [sys.executable, str(scorer_path), str(reference_root), str(args.participant_phase),
                   str(args.submission.resolve()), "--json", str(official_path)]
        execution = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
        (output / "organizer-stdout.log").write_text(execution.stdout, encoding="utf-8")
        (output / "organizer-stderr.log").write_text(execution.stderr, encoding="utf-8")
        if execution.returncode:
            raise RuntimeError(f"Original scorer failed: {execution.returncode}: {execution.stderr}")
        official = json.loads(official_path.read_text())
        reference = rows(reference_bytes.decode())
        audit = required_field_audit(reference, submitted, currencies=currencies)
        manifest_path = reference_root / "package-manifest.json"
        manifest_path.write_text(json.dumps({"archive_sha256": sha(args.package), "files": [
            {"path": "participant/score.py", "sha256": hashlib.sha256(scorer).hexdigest()}]}) + "\n")
        shared = None if args.shared_report else shared_comparison(scorer_path, manifest_path, reference,
            submitted, sha(submitted_path), required=args.require_shared)

    if args.shared_report:
        shared = json.loads(args.shared_report.read_text())
        actual_hash = shared.get("submission_sha256") or shared.get("provenance", {}).get("submission_sha256", {}).get("ic.jsonl")
        if actual_hash != sha(submitted_path):
            raise ValueError("Shared evaluation artifact is not bound to this submission hash")
    if shared:
        shared_result = shared.get("result") or shared.get("modules", {}).get("ic")
        if not shared_result or abs(shared_result["score"] - official["ic"]["score"]) > 5e-5:
            raise ValueError("Shared #35 IC result does not reconcile with the original scorer")
        if not shared_result.get("reconciliation", {}).get("ok"):
            raise ValueError("Shared #35 comparator reported a reconciliation failure")
        (output / "shared-35.json").write_text(json.dumps(shared, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {"schema_version": 1, "evaluation_only": True, "integration_mode": integration_mode, "real_flow_verified": False, "created_utc": datetime.now(timezone.utc).isoformat(),
              "phase_name": args.phase_name, "archive_sha256": sha(args.package), "submission_sha256": sha(submitted_path),
              "scorer_sha256": hashlib.sha256(scorer).hexdigest(), "reference_ic_sha256": hashlib.sha256(reference_bytes).hexdigest(),
              "solver_freeze": freeze, "solver_unchanged_since_freeze": unchanged,
              "original_scorer_command": command, "original_scorer_exit_code": execution.returncode,
              "official_ic": official["ic"], "official_whole_submission_scope": "Only ic.jsonl supplied; overall total is not an M5 completion metric",
              "required_field_audit": audit, "shared_35_report": shared,
              "shared_35_integration": "executed actual #35 compare_ic" if shared and not args.shared_report else "hash-bound real #35 artifact consumed" if shared else "not executed in this checkout",
              "milestone_acceptance_proven": False,
              "note": "Reference observations are evaluation findings, never rules or parameters fed back to the frozen solver"}
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text = ["# M5 — Separate evaluation", "", f"Integration mode: **{integration_mode}**; real flow verified: **False**.", "", f"Official IC score: **{official['ic']['score']}**.",
            f"Detected: **{official['ic']['detected']} / {official['ic']['differences']}**.",
            f"All required fields exact: **{audit['required_fields_exact_rows']} / {audit['expected_rows']}** reference rows.",
            "", "| Pair | Cause | Expected amount | Actual amount | Required fields |", "| --- | --- | ---: | ---: | --- |"]
    for row in audit["rows"]:
        text.append(f"| {' / '.join(row['pair'])} | {row['cause']} | {row.get('expected_amount', '—')} | {row.get('actual_amount', 'MISSING')} | {'PASS' if row['required_fields_exact'] else 'FAIL'} |")
    text += ["", "Amounts above are integer cents, not currency-unit decimals.",
        f"Required plus additional reference line fields exact: **{audit['required_plus_reference_line_fields_exact_rows']} / {audit['expected_rows']}**.",
        "", "## Remaining differences", ""]
    for row in audit["rows"]:
        label = " / ".join(row["pair"]) + " — " + row["cause"]
        if row["status"] != "matched":
            text.append(f"{label}: **{row['status']}**.")
        elif not row["required_fields_exact"]:
            failed = ", ".join(field for field, ok in row["checks"].items() if not ok)
            text.append(f"{label}: required-field differences in **{failed}**.")
        for extra in row.get("additional_reference_line_fields", []):
            text.append(f"{label}: line {extra['company']}/{extra['account']} field `{extra['field']}`: "
                        f"expected `{extra['expected']}`, actual `{extra['actual']}`.")
    for extra in audit["unexpected_rows"]:
        for row in extra["rows"]:
            text.append(f"Unexpected row: {' / '.join(extra['pair'])} — {extra['cause']}; amount={row.get('amount')}; responsible={row.get('responsible')}.")
    text.append(f"Whole-output exact acceptance: **{audit['all_required_fields_exact']}** (extra rows are failures even when every reference row matches).")
    if audit["structural_errors"] or audit["duplicate_submission_keys"]:
        text.append("Additional structural or duplicate-key failures are recorded in evaluation.json.")
    text += ["", "## Integration is separate from score", "",
        "No reference row was injected into the solver. A matching empty pooling adjustment does not prove that the bank-owned correction was supplied.",
        "The solver audit contains the actual dependency diagnostics. A local supplemental field audit does not replace the real shared #35 producer.",
        "Reference-only account/detail/note metadata and additional line fields are compared or retained separately from the organizer's common example fields.",
        "", "## Provenance", "", f"Package SHA-256: `{report['archive_sha256']}`", f"Submission SHA-256: `{report['submission_sha256']}`",
        f"Original scorer SHA-256: `{report['scorer_sha256']}`", f"Solver unchanged since freeze: `{unchanged}`", "",
        "Full per-field differences, extra reference metadata, original scorer output and execution command are included in evaluation.json / organizer-score.json."]
    (output / "EVALUATION.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--phase-name", default="phase_dev")
    parser.add_argument("--participant-phase", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--require-shared", action="store_true", help="Fail unless the real shared #35 comparator is available")
    parser.add_argument("--shared-report", type=Path, help="Optional hash-bound artifact from the real #35 producer; not a substitute implementation")
    args = parser.parse_args()
    report = evaluate(args)
    print(json.dumps({"official_ic": report["official_ic"], "required_fields_exact_rows": report["required_field_audit"]["required_fields_exact_rows"],
                      "solver_unchanged": report["solver_unchanged_since_freeze"]}))
