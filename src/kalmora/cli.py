"""Command-line entry point for the Kalmora close backend and solver modules."""

import argparse
import json
import shlex
from pathlib import Path
import sys
from zipfile import BadZipFile

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kalmora", description="Kalmora close backend")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--run-dir", type=Path, default=Path("outputs/runs"),
                        help="Directory for UUID execution reports (default: outputs/runs)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check the Python runtime")
    ingest = commands.add_parser("import-package", help="Preserve and inventory a participant ZIP")
    ingest.add_argument("archive", type=Path)
    ingest.add_argument("--destination", type=Path, required=True, help="New package directory")
    inspect = commands.add_parser("inspect", help="Inspect a phase's solver inputs")
    inspect.add_argument("phase", type=Path)
    ledger = commands.add_parser("ledger-summary", help="Reconstruct the recorded book and summarize its dimensions")
    ledger.add_argument("phase", type=Path)
    ar_cash = commands.add_parser("solve-ar-cash", help="Apply AR cash receipts from JSON/JSONL phase data")
    ar_cash.add_argument("phase", type=Path)
    ar_cash.add_argument("--output", type=Path, required=True, help="Destination ar_cash.jsonl")
    bank_rec = commands.add_parser("solve-bank-rec", help="Reconcile bank statements and journal entries")
    bank_rec.add_argument("phase", type=Path)
    bank_rec.add_argument("--output", type=Path, required=True, help="Destination bank_rec.jsonl")
    evaluate = commands.add_parser("evaluate", help="Compare a submission with the golden (evaluator side)")
    evaluate.add_argument("phase", type=Path, help="Phase directory with the solver inputs")
    evaluate.add_argument("submission", type=Path, help="Directory with the delivery .jsonl files")
    evaluate.add_argument("--evaluator", type=Path, help="Phase directory that holds golden/")
    evaluate.add_argument("--scorer", type=Path, help="score.py (default: next to the evaluator phase)")
    evaluate.add_argument("--structure-only", action="store_true", help="Check the submission without the golden")
    evaluate.add_argument("--report-dir", type=Path, default=Path("outputs/evaluations"))
    evaluate.add_argument("--text", action="store_true", help="Print a readable table instead of JSON")
    serve = commands.add_parser("serve", help="Run the HTTP API (needs the 'api' extra)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data-dir", type=Path, default=Path("outputs/data"), help="Where uploaded packages are extracted")
    serve.add_argument("--submissions-dir", type=Path, default=Path("outputs/submissions"), help="<dir>/<phase>/<module>.jsonl")
    serve.add_argument("--evaluator", type=Path, help="Enable scoring: <dir>/<phase>/golden must exist (evaluator side)")
    serve.add_argument("--reports-dir", type=Path, default=Path("outputs/evaluations"))
    serve.add_argument("--max-upload-mb", type=int, default=256)
    serve.add_argument("--cors-origin", action="append", help="Allowed browser origin (default: localhost only)")
    serve.add_argument("--no-restore", action="store_true", help="Do not reload packages already in --data-dir")
    serve.add_argument("--close-command", help="Command POST /v1/phases/{phase}/runs launches, with {phase}, {phase_dir}, "
                       "{month} and {out}; it writes the six JSONL under {out}/deliverables/")
    serve.add_argument("--serve-golden", action="store_true",
                       help="Also serve each phase's golden/ under /files, so the web app can score runs (evaluator side)")
    arguments = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(arguments)
    from .runlog import RunRecorder
    metadata: dict[str, object] = {"package_version": __version__}
    for name in ("phase", "archive", "destination", "submission", "evaluator", "output"):
        if getattr(args, name, None) is not None:
            metadata[name] = str(getattr(args, name).resolve())
    with RunRecorder(args.run_dir, ["kalmora", *arguments], metadata) as run:
        status = _execute(args)
        run.report["exit_code"] = status
    return status


def _execute(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        supported = sys.version_info >= (3, 12)
        print(json.dumps({"version": __version__, "python": sys.version.split()[0], "supported": supported}))
        return 0 if supported else 1
    if args.command == "import-package":
        from .package import register_package
        try:
            manifest = register_package(args.archive, args.destination)
        except (OSError, ValueError, BadZipFile) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"destination": str(args.destination.resolve()),
                          "archive_sha256": manifest["archive_sha256"],
                          "file_count": len(manifest["files"]),
                          "phases": manifest["phases"]}))
        return 0
    if args.command == "inspect":
        from .data import PhaseData
        try:
            data = PhaseData(args.phase)
            summary = {"phase": data.phase_dir.name, "month": data.month,
                       "companies": len(data.companies), "tasks": sorted(data.tasks),
                       "journal_entries": sum(1 for _ in data.iter_journal()),
                       "document_messages": len(data.table("document_messages")),
                       "bank_lines": len(data.table("bank_lines"))}
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(summary))
        return 0
    if args.command == "ledger-summary":
        from .data import PhaseData
        from .ledger import Ledger
        try:
            data = PhaseData(args.phase)
            book = Ledger.from_entries(data.iter_journal())
            balances = book.balances()
            summary = {"phase": data.phase_dir.name, "month": data.month,
                       "journal_entries": sum(1 for _ in book.iter_entries()),
                       "balance_accounts": len(balances), "open_item_keys": len(book.open_items()),
                       "companies": sorted({company for company, _ in balances})}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(summary))
        return 0
    if args.command == "solve-ar-cash":
        from .ar_cash import build_ar_cash
        from .ar_cash.io import write_ar_cash
        from .data import PhaseData
        try:
            phase = args.phase.resolve()
            output = args.output.expanduser().resolve()
            if output.is_relative_to(phase):
                raise ValueError("AR cash output must be outside the read-only phase directory")
            run = build_ar_cash(PhaseData(phase))
            written = write_ar_cash(run, output)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        resolved = sum(bool(result.row["applications"] or result.row["residuals"])
                       for result in run.results)
        print(json.dumps({"output": str(written), "rows": len(run.results),
                          "with_decision": resolved,
                          "unresolved": len(run.results) - resolved,
                          "diagnostics": sum(bool(result.diagnostics) for result in run.results)}))
        return 0
    if args.command == "solve-bank-rec":
        from .bankrec import build_bank_rec
        from .bankrec.io import write_bank_rec
        from .data import PhaseData
        try:
            phase = args.phase.resolve()
            output = args.output.expanduser().resolve()
            if output.is_relative_to(phase):
                raise ValueError("bank reconciliation output must be outside the read-only phase directory")
            data = PhaseData(phase)
            run = build_bank_rec(data)
            if run.unresolved:
                details = "; ".join(f"{item.account}: {', '.join(item.reasons)}"
                                     for item in run.unresolved)
                raise ValueError(f"bank reconciliation has unresolved accounts: {details}")
            expected_accounts = list(data.table("tasks/bank_accounts"))
            actual_accounts = [result.account.id for result in run.results]
            if actual_accounts != expected_accounts:
                raise ValueError("bank reconciliation did not resolve every task account")
            written = write_bank_rec(run, output)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"output": str(written), "accounts": len(run.results),
                          "matches": sum(len(result.matches) for result in run.results),
                          "unmatched_bank": sum(len(result.unmatched_bank) for result in run.results),
                          "unmatched_book": sum(len(result.unmatched_book) for result in run.results),
                          "adjustments": sum(len(result.adjustments) for result in run.results),
                          "diagnostics": sum(len(result.diagnostics) for result in run.results)}))
        return 0
    if args.command == "serve":
        try:
            import uvicorn
            from .api.app import create_app
        except ImportError as exc:
            print(json.dumps({"error": f"{exc}. Install the extra: pip install 'kalmora-close[api]'"}), file=sys.stderr)
            return 2
        from .app.container import Services, Settings
        from .evaluation.gateway import EvaluatorGateway
        settings = Settings(data_dir=args.data_dir, run_dir=args.run_dir, submissions_dir=args.submissions_dir,
                            max_upload_bytes=args.max_upload_mb * 1024 * 1024,
                            cors_origins=tuple(args.cors_origin or ()), serve_golden=args.serve_golden,
                            close_command=tuple(shlex.split(args.close_command or "")))
        services = Services(settings, EvaluatorGateway(args.evaluator, args.reports_dir))
        if not args.no_restore:
            print(json.dumps({"restored_packages": services.ingest.restore()}), file=sys.stderr)
        uvicorn.run(create_app(services), host=args.host, port=args.port, log_level="info")
        return 0
    if args.command == "evaluate":
        from .evaluation.report import evaluate, text_summary, write_report
        from .evaluation.report import summary as report_summary
        if args.evaluator is None and not args.structure_only:
            print(json.dumps({"error": "--evaluator is required unless --structure-only is given"}), file=sys.stderr)
            return 2
        try:
            report = evaluate(args.phase, args.submission, None if args.structure_only else args.evaluator, args.scorer)
            path = write_report(report, args.report_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(text_summary(report) if args.text else json.dumps({"report": str(path.resolve()), **report_summary(report)}))
        valid_structure = not report["diagnostic_counts"].get("INVALID_STRUCTURE")
        return 0 if valid_structure and report.get("reconciliation_ok", True) and not report["separation"]["violations"] else 1
    return 2
