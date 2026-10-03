"""Command-line entry point; M0 provides infrastructure, not an AP solver."""

import argparse
import json
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
    arguments = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(arguments)
    from .runlog import RunRecorder
    metadata = {"package_version": __version__}
    for name in ("phase", "archive", "destination"):
        if hasattr(args, name):
            metadata[name] = str(getattr(args, name).resolve())
    with RunRecorder(args.run_dir, ["kalmora", *arguments], metadata) as run:
        status = _execute(args)
        run.report["exit_code"] = status
    return status


def _execute(args) -> int:
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
    return 2
