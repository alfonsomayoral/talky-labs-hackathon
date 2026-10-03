"""Publish a complete billing run and its close input in a new output directory."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from ..output_validation import check_structure
from .journal import to_pending_row, to_row
from .model import BillingRun, Decision


def write_billing(run: BillingRun, destination: str | Path) -> Path:
    """Refuse unresolved runs and existing destinations; publish both UTF-8 JSONL files."""
    if run.unresolved:
        raise ValueError("cannot publish billing with unresolved items")
    ids = [r.item.id for r in run.results]
    pending_ids = [p.item.id for p in run.pending_wip]
    expected = {r.item.id: r.item for r in run.results if r.decision is Decision.SKIP_PENDING_APPROVAL}
    if (len(set(ids)) != len(ids) or len(set(pending_ids)) != len(pending_ids)
            or set(pending_ids) != set(expected)
            or any(p.item != expected.get(p.item.id) for p in run.pending_wip)):
        raise ValueError("billing coverage and pending WIP are inconsistent")
    rows = [to_row(x) for x in run.results]
    errors = check_structure({"ar_billing": rows})
    if errors:
        raise ValueError(errors[0]["message"])
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".billing-", dir=destination.parent))
    try:
        for name, values in (("ar_billing", rows), ("pending_wip", [to_pending_row(x) for x in run.pending_wip])):
            (staging / f"{name}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in values), encoding="utf-8")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def write_billing_files(run: BillingRun, output: str | Path) -> Path:
    """Validate the complete run before replacing either standalone delivery file."""
    output = Path(output).expanduser().resolve()
    if output.name == "pending_wip.jsonl":
        raise ValueError("billing output and pending WIP require distinct paths")
    pending = output.with_name("pending_wip.jsonl")
    for target in (output, pending):
        if target.exists() and not target.is_file():
            raise ValueError(f"delivery target is not a file: {target}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".billing-publish-", dir=output.parent))
    cleanup = True
    try:
        bundle = write_billing(run, staging / "validated")
        backup = staging / "previous-pending.jsonl"
        existed = pending.exists()
        if existed:
            shutil.copyfile(pending, backup)
        os.replace(bundle / "pending_wip.jsonl", pending)
        try:
            os.replace(bundle / "ar_billing.jsonl", output)
        except OSError as publication_error:
            try:
                if existed:
                    os.replace(backup, pending)
                else:
                    pending.unlink(missing_ok=True)
            except OSError as recovery_error:
                cleanup = False
                raise OSError(f"publication and recovery failed; artifacts retained at {staging}") from recovery_error
            raise publication_error
    finally:
        if cleanup:
            shutil.rmtree(staging, ignore_errors=True)
    return output
