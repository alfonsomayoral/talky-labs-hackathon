"""Publish a complete billing run and its close input in a new output directory."""
import json
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
