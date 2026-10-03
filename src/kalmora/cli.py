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
    ar_cash.add_argument("--ap", type=Path, help="This month's ap.jsonl: its posted payables can be netted")
    cash_projection = commands.add_parser("project-ar-cash", help="Publish M3/M4 projected balances and unresolved receipts")
    cash_projection.add_argument("phase", type=Path)
    cash_projection.add_argument("--output", type=Path, required=True)
    cash_projection.add_argument("--use-preparsed", action="store_true")
    cash_projection.add_argument("--normalized-dir", type=Path)
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
    ap_solve = commands.add_parser("run-ap", help="Evaluate saved AP facts; export only complete evidenced decisions")
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
    solve_billing = commands.add_parser("solve-ar-billing", help="Extract evidenced AR facts and invoice current tasks")
    solve_billing.add_argument("phase", type=Path)
    solve_billing.add_argument("--output", type=Path, required=True, help="Destination ar_billing.jsonl")
    solve_billing.add_argument("--work-dir", type=Path, help="AR recordings and evidence (default: next to output)")
    solve_billing.add_argument("--mode", choices=("record", "replay"), default="record",
                               help="Capture local source extraction or replay saved literal facts")
    solve_billing.add_argument("--engine", choices=("sources", "v0"), default="sources",
                               help="Use the evidenced billing engine (default) or explicit legacy v0")
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
    serve.add_argument("--mcp", action="store_true", help="Also serve the read-only MCP server at /mcp/ from the same memory")
    serve.add_argument("--no-restore", action="store_true", help="Do not reload packages already in --data-dir")
    serve.add_argument("--close-command", help="Command POST /v1/phases/{phase}/runs launches, with {phase}, {phase_dir}, "
                       "{month} and {out}; it writes the six JSONL under {out}/deliverables/")
    serve.add_argument("--serve-golden", action="store_true",
                       help="Also serve each phase's golden/ under /files, so the web app can score runs (evaluator side)")
    mcp = commands.add_parser("mcp", help="Run the read-only MCP server (needs the 'mcp' package)")
    mcp.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8001)
    mcp.add_argument("--data-dir", type=Path, default=Path("outputs/data"), help="Where uploaded packages are extracted")
    mcp.add_argument("--submissions-dir", type=Path, default=Path("outputs/submissions"))
    mcp.add_argument("--evaluator", type=Path, help="Enable get_run_evaluation: <dir>/<phase>/golden must exist")
    mcp.add_argument("--reports-dir", type=Path, default=Path("outputs/evaluations"))
    chat = commands.add_parser("chat", help="Run the read-only chat assistant (POST /api/chat, needs the API with --mcp)",
                               description="Provider and model come from the environment (see kalmora.assistant.config); flags override.")
    chat.add_argument("--provider", choices=("ollama", "openai"), help="Overrides KALMORA_AI_PROVIDER")
    chat.add_argument("--model", help="Overrides KALMORA_AI_MODEL (mode deep)")
    chat.add_argument("--fast-model", help="Overrides KALMORA_AI_FAST_MODEL")
    chat.add_argument("--env-file", type=Path, help="Variables file (default: .env if present). Real environment variables win")
    chat.add_argument("--mcp-url", help="Overrides KALMORA_MCP_URL")
    chat.add_argument("--host", default="127.0.0.1")
    chat.add_argument("--port", type=int, default=8100)
    chat.add_argument("--ollama-url", help="Overrides OLLAMA_HOST / KALMORA_OLLAMA_URL")
    chat.add_argument("--num-ctx", type=int, help="Overrides KALMORA_OLLAMA_NUM_CTX")
    chat.add_argument("--think", action="store_true", help="Overrides KALMORA_OLLAMA_THINK")
    chat.add_argument("--openai-base-url", help="Overrides OPENAI_BASE_URL")
    chat.add_argument("--trace-dir", type=Path, help="Overrides KALMORA_CHAT_TRACE_DIR")
    chat.add_argument("--no-store-text", action="store_true", help="Overrides KALMORA_CHAT_STORE_TEXT")
    chat.add_argument("--allow-evaluation", action="store_true", help="Offer get_run_evaluation (development phases only)")
    chat.add_argument("--compact-knowledge", action="store_true", help="Leave the workflows and examples out of the prompt")
    chat.add_argument("--cors-origin", action="append")
    chat.add_argument("--deep-timeout", type=float, help="Overrides KALMORA_AI_DEEP_TIMEOUT")
    chat.add_argument("--fast-timeout", type=float, help="Overrides KALMORA_AI_FAST_TIMEOUT")
    chat.add_argument("--no-warm-up", action="store_true", help="Do not prefill the model's prompt cache at start")
    arguments = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(arguments)
    if args.command == "solve-ar-billing":
        phase = args.phase.resolve()
        work = args.work_dir or args.output.parent / ".ar-billing-state"
        for destination in (args.output, args.output.with_name("pending_wip.jsonl"), work, args.run_dir):
            resolved = destination.resolve()
            if resolved.is_relative_to(phase) or any(part.lower() == "golden" for part in resolved.parts):
                print(json.dumps({"error": "AR outputs, recordings and run reports must be outside source data and golden"}),
                      file=sys.stderr)
                return 1
        if args.engine == "v0" and args.mode == "replay":
            print(json.dumps({"error": "v0 does not implement AR capture replay"}), file=sys.stderr)
            return 1
    if args.command in {"prepare-ap", "plan-ap", "run-ap"}:
        destinations = [args.run_dir] + ([args.output] if args.command == "plan-ap" else [])
        if args.command == "run-ap":
            destinations.extend((args.output, args.report))
        protected = [args.phase.resolve()]
        if args.command in {"plan-ap", "run-ap"}:
            protected.append(args.sources.resolve().parent)
        if args.command == "run-ap":
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
    identity: dict[str, object] = {}
    if args.command == "close":
        out = args.out.resolve()
        if out.is_relative_to(args.phase.resolve()) or "golden" in out.parts:
            print(json.dumps({"error": "close output must be outside the read-only phase directory"}), file=sys.stderr)
            return 1
        # The report goes inside the bundle, under the run id the bundle already has (kalmora serve), so one
        # run has one id: its manifest, events and report all live in --out.
        try:
            started = json.loads((args.out / "manifest.json").read_text(encoding="utf-8")).get("run_id")
        except (OSError, ValueError, AttributeError):
            started = None
        identity = {"run_id": started if isinstance(started, str) and started else None, "path": args.out / "run.json"}
    with RunRecorder(args.run_dir, ["kalmora", *arguments], metadata, **identity) as run:
        status = _execute(args, recorder=run)
        run.report["exit_code"] = status
    return status


def _execute(args: argparse.Namespace, recorder=None) -> int:
    if args.command == "run-ap":
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
        from decimal import InvalidOperation
        from .ap_sources import prepare_ap_sources, residual_extractor
        from .data import load_json
        from .facts import atomic_json
        try:
            extractor = None
            if args.mode == "deterministic":
                if args.config or args.captures or args.budget_usd:
                    raise ValueError("deterministic mode cannot accept provider/capture configuration")
            else:
                if args.config is None or args.captures is None:
                    raise ValueError("residual mode requires --config and --captures")
                extractor = residual_extractor(args.mode, load_json(args.config), args.captures,
                                               args.budget_usd, recorder)
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
    if args.command == "project-ar-cash":
        from .ar_cash import build_ar_cash
        from .ar_cash.projection import project_cash, projection_report
        from .bankrec import build_bank_rec
        from .data import PhaseData
        import os
        import tempfile
        temporary = None
        try:
            phase, output = args.phase.resolve(), args.output.expanduser().resolve()
            if output.is_relative_to(phase) or "golden" in output.parts:
                raise ValueError("projection output must be outside source/golden directories")
            data = PhaseData(phase)
            cash = build_ar_cash(data, use_preparsed=args.use_preparsed, normalized_dir=args.normalized_dir)
            report = projection_report(project_cash(data, cash, build_bank_rec(data)))
            report["diagnostics"] = {str(r.row["bank_line"]): list(r.diagnostics)
                                     for r in cash.results if r.diagnostics}
            report["run_diagnostics"] = list(cash.diagnostics)
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
                temporary = handle.name
                json.dump(report, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
            temporary = None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        print(json.dumps({"output": str(output), "complete": report["complete"],
                          "unresolved_receipts": report["unresolved_receipts"]}))
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
            ap = ([json.loads(line) for line in args.ap.read_text(encoding="utf-8").splitlines() if line.strip()]
                  if args.ap else [])
            run = build_ar_cash(PhaseData(phase), use_preparsed=args.use_preparsed,
                                normalized_dir=args.normalized_dir, billing=billing, ap=ap)
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
    if args.command == "solve-ar-billing" and args.engine == "sources":
        import asyncio
        from .billing.source_runner import build_billing_from_sources
        from .billing.io import write_billing_files
        from .data import PhaseData
        try:
            source = asyncio.run(build_billing_from_sources(PhaseData(args.phase.resolve()),
                work_dir=args.work_dir or args.output.parent / ".ar-billing-state", mode=args.mode))
            if not source.complete:
                print(json.dumps({"error": "AR billing has unresolved sources or accounting inputs",
                                  "report": str(source.report_path), "coverage": source.report["coverage"]}),
                      file=sys.stderr)
                return 1
            written = write_billing_files(source.billing, args.output)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps({"output": str(written), "rows": len(source.billing.results),
                          "pending_wip": len(source.billing.pending_wip), "report": str(source.report_path),
                          "stable_output_sha256": source.stable_sha256, "mode": args.mode}))
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
            result = run_close(args.phase, args.out, args.module, args.from_submissions, recorder=recorder)
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
        print(json.dumps({"recovered_runs": services.recover_runs()}), file=sys.stderr)
        uvicorn.run(create_app(services, mcp=args.mcp), host=args.host, port=args.port, log_level="info")
        return 0
    if args.command == "chat":
        try:
            import uvicorn
            from .assistant.config import ConfigError, chat_settings, describe, load_environment
            from .assistant.service import build_assistant, create_app as create_chat_app
        except ImportError as exc:
            print(json.dumps({"error": f"{exc}. Install the extras: pip install 'kalmora-close[assistant]'"}), file=sys.stderr)
            return 2
        try:
            chat_cfg = chat_settings(load_environment(env_file=args.env_file), provider=args.provider, model=args.model,
                                     fast_model=args.fast_model, mcp_url=args.mcp_url, ollama_url=args.ollama_url, num_ctx=args.num_ctx,
                                     think=args.think, openai_base_url=args.openai_base_url, trace_dir=args.trace_dir,
                                     no_store_text=args.no_store_text, allow_evaluation=args.allow_evaluation,
                                     compact=args.compact_knowledge, cors_origins=args.cors_origin, deep_timeout=args.deep_timeout,
                                     fast_timeout=args.fast_timeout, no_warm_up=args.no_warm_up)
            assistant = build_assistant(chat_cfg)
        except (ConfigError, RuntimeError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps({"assistant": describe(chat_cfg)}), file=sys.stderr)
        uvicorn.run(create_chat_app(assistant, chat_cfg), host=args.host, port=args.port, log_level="info")
        return 0
    if args.command == "mcp":
        try:
            from .mcp.server import create_server
        except ImportError as exc:
            print(json.dumps({"error": f"{exc}. Install the MCP SDK: pip install mcp"}), file=sys.stderr)
            return 2
        from .app.container import Services, Settings
        from .evaluation.gateway import EvaluatorGateway
        settings = Settings(data_dir=args.data_dir, run_dir=args.run_dir, submissions_dir=args.submissions_dir)
        services = Services(settings, EvaluatorGateway(args.evaluator, args.reports_dir))
        # stdout belongs to the protocol on stdio: everything else goes to stderr
        print(json.dumps({"restored_packages": services.ingest.restore()}), file=sys.stderr)
        server = create_server(services)
        server.settings.host, server.settings.port = args.host, args.port
        server.run(transport=args.transport)
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
