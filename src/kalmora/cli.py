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
    ar_cash = commands.add_parser("solve-ar-cash", help="Apply AR cash receipts from ERP and bank evidence")
    ar_cash.add_argument("phase", type=Path)
    ar_cash.add_argument("--output", type=Path, required=True, help="Destination ar_cash.jsonl")
    ar_cash.add_argument("--billing", type=Path, help="This month's ar_billing.jsonl: its invoices can be applied")
    ap_prepare = commands.add_parser("prepare-ap", help="Prepare AP source facts; does not post or export AP decisions")
    ap_prepare.add_argument("phase", type=Path)
    ap_prepare.add_argument("--state-dir", type=Path, required=True, help="Source state outside the original phase")
    ap_prepare.add_argument("--mode", choices=("deterministic", "record", "replay", "fixture"), default="deterministic")
    ap_prepare.add_argument("--captures", type=Path, help="Shared document capture directory")
    ap_prepare.add_argument("--config", type=Path, help="LLM settings for record; saved RecordingConfig for replay/fixture")
    ap_prepare.add_argument("--budget-usd", help="Explicit positive provider budget; required for record")
    ap_prepare.add_argument("--pdf-vision", action="store_true", help="Preserve native page renders and unverified OCR aids")
    ap_plan = commands.add_parser("plan-ap", help="Audit prepared AP sources and ERP context; does not post or export AP decisions")
    ap_plan.add_argument("phase", type=Path)
    ap_plan.add_argument("--sources", type=Path, required=True, help="Verified phase-sources.json manifest")
    ap_plan.add_argument("--output", type=Path, required=True, help="Audit JSON outside original and prepared sources")
    ap_plan.add_argument("--receipt-cutoff-fact", type=Path,
                         help="Optional JSON {value: YYYY-MM-DD, evidence: {...}} with an observed receipt cutoff")
    ap_solve = commands.add_parser("solve-ap", help="Evaluate saved AP facts; export only complete evidenced decisions")
    ap_solve.add_argument("phase", type=Path)
    ap_solve.add_argument("--sources", type=Path, required=True, help="Verified phase-sources.json manifest")
    ap_solve.add_argument("--output", type=Path, required=True, help="Complete AP JSONL outside source inputs")
    ap_solve.add_argument("--report", type=Path, required=True, help="Audit JSON, also written for unresolved tasks")
    ap_solve.add_argument("--receipt-cutoff-fact", type=Path, help="JSON Fact with an explicit receipt processing cutoff")
    ap_solve.add_argument("--posting-date-fact", type=Path, help="JSON Fact with an explicit posting date")
    ap_solve.add_argument("--overwrite", action="store_true", help="Replace a complete prior AP file after successful validation")
    ar_cash.add_argument("--use-preparsed", action="store_true",
                         help="Development shortcut: load remittance source snapshots instead of parsing originals")
    ar_cash.add_argument("--normalized-dir", type=Path,
                         help="Source snapshot root (default: <phase-parent>/normalized_sources)")
    bank_rec = commands.add_parser("solve-bank-rec", help="Reconcile bank statements and journal entries")
    bank_rec.add_argument("phase", type=Path)
    bank_rec.add_argument("--output", type=Path, required=True, help="Destination bank_rec.jsonl")
    bank_rec.add_argument("--ap", type=Path, help="This month's ap.jsonl: direct debits post only for posted invoices")
    solve_ap = commands.add_parser("solve-ap", help="Decide, code and post every AP task (v0 rules)")
    solve_ap.add_argument("phase", type=Path)
    solve_ap.add_argument("--output", type=Path, required=True, help="Destination ap.jsonl")
    solve_billing = commands.add_parser("solve-ar-billing", help="Invoice every AR billing item from its documents (v0 rules)")
    solve_billing.add_argument("phase", type=Path)
    solve_billing.add_argument("--output", type=Path, required=True, help="Destination ar_billing.jsonl")
    close = commands.add_parser("close", help="Run the available engines and write a run bundle (serve --close-command)")
    close.add_argument("phase", type=Path)
    close.add_argument("--out", type=Path, required=True, help="Bundle folder: deliverables/, trace/, manifest.json")
    close.add_argument("--module", action="append", choices=("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close"),
                       help="Only these modules (default: all)")
    close.add_argument("--from-submissions", type=Path,
                       help="Folder with <module>.jsonl for modules that have no engine here (e.g. AP)")
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
    if args.command in {"prepare-ap", "plan-ap", "solve-ap"}:
        destinations = [args.run_dir] + ([args.output] if args.command == "plan-ap" else [])
        if args.command == "solve-ap":
            destinations.extend((args.output, args.report))
        protected = [args.phase.resolve()]
        if args.command in {"plan-ap", "solve-ap"}:
            protected.append(args.sources.resolve().parent)
        if args.command == "solve-ap":
            input_files = [args.sources, args.receipt_cutoff_fact, args.posting_date_fact]
            if (args.output.resolve() == args.report.resolve() or any(
                    destination.resolve() == source.resolve()
                    for destination in (args.output, args.report)
                    for source in input_files if source is not None)):
                print(json.dumps({"error": "AP output, audit and execution facts require distinct paths"}), file=sys.stderr)
                return 1
        for destination in destinations:
            resolved = destination.resolve()
            if (any(resolved.is_relative_to(source) for source in protected)
                    or any(part.lower() == "golden" for part in (*resolved.parts, *destination.parts))):
                print(json.dumps({"error": "AP outputs and run reports must be outside original sources, prepared source state and Golden"}), file=sys.stderr)
                return 1
    from .runlog import RunRecorder
    metadata: dict[str, object] = {"package_version": __version__}
    for name in ("phase", "archive", "destination", "submission", "evaluator", "output"):
        if getattr(args, name, None) is not None:
            metadata[name] = str(getattr(args, name).resolve())
    with RunRecorder(args.run_dir, ["kalmora", *arguments], metadata) as run:
        status = _execute(args, recorder=run)
        run.report["exit_code"] = status
    return status


def _execute(args: argparse.Namespace, recorder=None) -> int:
    if args.command == "solve-ap":
        import asyncio
        from dataclasses import asdict
        from .ap_phase_runner import run_ap_phase
        from .ap_phase_export import write_phase_ap_jsonl
        from .data import load_json
        from .facts import Evidence, Fact, atomic_json
        def execution_fact(path):
            if path is None:
                return None
            actual = path.resolve()
            if any(part.lower() == "golden" for part in (*path.parts, *actual.parts)):
                raise ValueError("AP execution facts cannot be loaded from Golden")
            raw = load_json(actual)
            if not isinstance(raw, dict) or set(raw) != {"value", "evidence"}:
                raise ValueError("AP execution date requires a value and structured evidence")
            return Fact(raw["value"], Evidence(**raw["evidence"]))
        try:
            result = asyncio.run(run_ap_phase(args.phase, args.sources,
                receipt_as_of=execution_fact(args.receipt_cutoff_fact),
                posting_date=execution_fact(args.posting_date_fact)))
            report = dict(result.report)
            receipt = None
            if result.complete:
                receipt = write_phase_ap_jsonl(args.output, result.rows, phase_path=args.phase,
                    tax_catalog=result.tax_catalog, overwrite=args.overwrite)
                report["export"] = {name: str(value) if isinstance(value, Path) else value
                                    for name, value in asdict(receipt).items()}
            report["publication"] = dict(exported=receipt is not None,
                output=str(args.output.resolve()) if receipt is not None else None)
            atomic_json(args.report, report)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"report": str(args.report.resolve()), "accounting_run": True,
            "complete": result.complete, "exported": receipt is not None,
            "output": str(args.output.resolve()) if receipt is not None else None,
            "stable_run_sha256": result.report["stable_run_sha256"], **result.report["summary"]}))
        return 0 if result.complete else 1
    if args.command == "plan-ap":
        import asyncio
        from .ap_source_plan import plan_ap_sources
        from .data import load_json
        from .facts import Evidence, Fact, atomic_json
        try:
            cutoff = None
            if args.receipt_cutoff_fact is not None:
                source = args.receipt_cutoff_fact.resolve()
                if any(part.lower() == "golden" for part in (*source.parts, *args.receipt_cutoff_fact.parts)):
                    raise ValueError("AP cutoff evidence cannot be loaded from Golden")
                raw = load_json(source)
                if not isinstance(raw, dict) or set(raw) != {"value", "evidence"}:
                    raise ValueError("receipt cutoff requires a value and structured evidence")
                cutoff = Fact(raw["value"], Evidence(**raw["evidence"]))
            plan = asyncio.run(plan_ap_sources(args.phase, args.sources, receipt_as_of=cutoff))
            atomic_json(args.output, plan)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"output": str(args.output.resolve()), "accounting_run": False,
                          "stable_plan_sha256": plan["stable_plan_sha256"], **plan["summary"]}))
        statuses = plan["summary"]["statuses"]
        return 0 if not (statuses["UNKNOWN"] or statuses["UNSUPPORTED"]) else 1
    if args.command == "prepare-ap":
        import asyncio
        from decimal import Decimal, InvalidOperation
        from .ap_sources import prepare_ap_sources
        from .data import load_json
        from .documents.replay import RecordedExtractor, RecordingConfig, RecordingStore
        from .facts import atomic_json
        try:
            extractor = None
            if args.mode == "deterministic":
                if args.config or args.captures or args.budget_usd:
                    raise ValueError("deterministic mode cannot accept provider/capture configuration")
            else:
                if args.config is None or args.captures is None:
                    raise ValueError("residual mode requires --config and --captures")
                raw_config = load_json(args.config)
                if args.mode == "record":
                    if args.budget_usd is None:
                        raise ValueError("record mode requires an explicitly authorized --budget-usd")
                    budget = Decimal(args.budget_usd)
                    if not budget.is_finite() or budget <= 0:
                        raise ValueError("record mode requires a positive finite provider budget")
                    from .llm.client import AsyncLLMClient, LLMConfig
                    from .documents.extractor import LLMDocumentExtractor
                    settings = dict(raw_config)
                    include_aids = settings.pop("include_processing_aids", True)
                    for name in ("input_rate", "output_rate"):
                        if isinstance(settings[name], bool):
                            raise ValueError("model pricing must use exact numeric rates")
                        settings[name] = Decimal(settings[name])
                    client = AsyncLLMClient(LLMConfig(budget_usd=budget, **settings), recorder)
                    adapter = LLMDocumentExtractor(client, include_processing_aids=include_aids)
                    config = RecordingConfig.from_adapter(adapter)
                    extractor = RecordedExtractor(RecordingStore(args.captures), config, mode="record",
                        callback=adapter.extract_with_response, budget_usd=budget, recorder=recorder)
                else:
                    if args.budget_usd is not None:
                        raise ValueError("replay/fixture cannot accept a provider budget")
                    config = RecordingConfig.from_dict(raw_config)
                    extractor = RecordedExtractor(RecordingStore(args.captures), config, mode=args.mode, recorder=recorder)
            transform = None
            if args.pdf_vision:
                from .documents.ocr import PDFVisionProcessor
                transform = PDFVisionProcessor(args.phase).process
            result = asyncio.run(prepare_ap_sources(args.phase, args.state_dir, mode=args.mode,
                                                   extractor=extractor, transform=transform))
            if extractor is not None:
                atomic_json(args.state_dir / "residual-identity.json", extractor.config.to_dict())
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"manifest": str(result.manifest_path), "month": result.manifest["month"],
                          "accounting_run": False, **result.manifest["report"]}))
        return 0 if not (result.manifest["report"]["unknown_sources"]
                         or result.manifest["report"]["incomplete_tasks"]) else 1
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
            billing = ([json.loads(line) for line in args.billing.read_text(encoding="utf-8").splitlines() if line.strip()]
                       if args.billing else [])
            run = build_ar_cash(PhaseData(phase), use_preparsed=args.use_preparsed,
                                normalized_dir=args.normalized_dir, billing=billing)
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
    if args.command in ("solve-ap", "solve-ar-billing"):
        from .v0.solve import solve_ap, solve_billing, write_jsonl
        phase, output = args.phase.resolve(), args.output.expanduser().resolve()
        if output.is_relative_to(phase):
            print(json.dumps({"error": "output must be outside the read-only phase directory"}), file=sys.stderr)
            return 1
        if args.command == "solve-ap":
            rows, errors = solve_ap(phase)
            write_jsonl(output, rows)
            print(json.dumps({"output": str(output), "rows": len(rows), "coding_errors": errors}))
            return 0
        rows, pending = solve_billing(phase)
        write_jsonl(output, rows)
        write_jsonl(output.with_name("pending_wip.jsonl"), pending)
        print(json.dumps({"output": str(output), "rows": len(rows), "pending_wip": len(pending)}))
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
            ap_rows = ([json.loads(line) for line in args.ap.read_text(encoding="utf-8").splitlines() if line.strip()]
                       if args.ap else None)
            run = build_bank_rec(data, ap_rows=ap_rows)
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
    if args.command == "close":
        from .closing import run_close
        try:
            result = run_close(args.phase, args.out, args.module, args.from_submissions)
        except (OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"out": str(args.out.resolve()), "ok": result["ok"],
                          "tasks": {m: t.get("state") for m, t in result["tasks"].items()}}))
        return 0 if result["ok"] else 1
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
