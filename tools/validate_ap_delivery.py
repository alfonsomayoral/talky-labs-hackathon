"""Read-only AP RunBundle audit. Never fills rows, invokes providers or reads golden."""
import argparse
import json
from pathlib import Path

from kalmora.ap_acceptance import audit_ap_delivery, compare_ap_acceptance
from kalmora.ap_output import _pinned_ap_directory, _publish_ap_payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--sources", type=Path, help="Existing phase-sources.json; no recording is attempted")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--against", type=Path, help="Previous acceptance report, checked by its self-hash")
    parser.add_argument("--independent-phase", action="store_true",
                        help="Require frozen rules/policy/format but independent phase inputs")
    parser.add_argument("--project-v0", action="store_true", help="Audit an explicit contract view; retain raw bytes/hash and every omitted value")
    parser.add_argument("--documentary-acceptance-reference", help="Explicit user authorization for provisional documentary scope; unknowns and replay blockers remain")
    args = parser.parse_args(argv)
    if args.independent_phase and args.against is None:
        parser.error("--independent-phase requires --against")
    destination = args.report.resolve()
    phase = args.phase.resolve()
    if (destination.is_relative_to(phase) or "golden" in destination.parts
            or "golden" in args.report.parts or destination.is_relative_to(args.bundle.resolve())
            or (args.sources and destination.is_relative_to(args.sources.resolve().parent))):
        parser.error("report must be separate from originals, saved sources and RunBundle")
    try:
        report = audit_ap_delivery(phase_path=args.phase, bundle_path=args.bundle,
                                  policy_path=args.policy, source_manifest_path=args.sources,
                                  project_v0=args.project_v0,
                                  documentary_acceptance_reference=args.documentary_acceptance_reference)
        comparison = None
        if args.against:
            if "golden" in args.against.parts or "golden" in args.against.resolve().parts:
                raise ValueError("evaluation data cannot supply a prior acceptance report")
            comparison = compare_ap_acceptance(json.loads(args.against.read_bytes()), report,
                                               independent_phase=args.independent_phase)
        payload = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        with _pinned_ap_directory(destination, create=True) as descriptor:
            _publish_ap_payload(destination, payload, descriptor=descriptor, overwrite=False)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps(dict(status="AUDIT_FAILED", error=str(exc))))
        return 2
    coverage = report["coverage"]
    summary = {key: coverage[key] for key in ("expected", "rows", "exact")}
    summary.update({key: len(coverage[key]) for key in ("missing", "extra", "duplicate")})
    print(json.dumps(dict(status=report["status"], scope=report["scope"], coverage=summary,
                          blockers=report["blockers"], accounting_summary=report["accounting_summary"],
                          criteria_summary=report["criteria_summary"], report=str(destination), comparison=comparison)))
    # An incomplete acceptance artifact is useful evidence but never a green exit.
    return 0 if report["status"] == "READY_FOR_EVALUATION" and (comparison is None or comparison["compatible"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
