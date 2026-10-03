"""Export AP against the active phase's task inventory, without evaluation access."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from collections.abc import Iterable

from .ap_output import write_ap_jsonl
from .ap_tax import TaxCatalog
from .model.validation_context import ValidationContext
from .output_models.ap import ApRow


@dataclass(frozen=True)
class APTaskInventory:
    phase_path: Path
    source_sha256: str
    doc_ids: tuple[str, ...]
    source: str = "tasks/ap_documents.json"


@dataclass(frozen=True)
class APExportReceipt:
    phase_path: Path
    task_source: str
    task_sha256: str
    output_path: Path
    output_sha256: str
    row_count: int


def load_ap_task_inventory(phase_path: str | Path) -> APTaskInventory:
    """Read only the phase's canonical task list; IDs are opaque and unmodified."""
    phase = Path(phase_path).resolve()
    if "golden" in phase.parts:
        raise ValueError("golden is not an AP task source")
    path = (phase / "tasks" / "ap_documents.json").resolve()
    if not path.is_relative_to(phase) or "golden" in path.parts:
        raise ValueError("AP task source escapes the active phase")
    payload = path.read_bytes()
    ids = json.loads(payload.decode("utf-8"))
    if (not isinstance(ids, list) or any(not isinstance(ident, str) or not ident
            or ident.strip() != ident for ident in ids) or len(set(ids)) != len(ids)):
        raise ValueError("AP tasks require an array of unique nonempty exact IDs")
    return APTaskInventory(phase, hashlib.sha256(payload).hexdigest(), tuple(ids))


def write_phase_ap_jsonl(path: str | Path, rows: Iterable[ApRow], *,
                        phase_path: str | Path, context: ValidationContext | None = None,
                        tax_catalog: TaxCatalog | None = None,
                        overwrite: bool = False) -> APExportReceipt:
    """Bind validated atomic export to a source snapshot and return its hashes.

    Expected IDs come exclusively from tasks, never attachments or a caller's
    guessed count. The destination must be separate from the source phase.
    Export does not post journals, consume balances or invent missing results.
    """
    inventory = load_ap_task_inventory(phase_path)
    output = Path(path).resolve()
    if output.is_relative_to(inventory.phase_path):
        raise ValueError("AP export destination must be outside the source phase")
    write_ap_jsonl(output, rows, expected_doc_ids=inventory.doc_ids,
                   context=context, tax_catalog=tax_catalog, overwrite=overwrite)
    return APExportReceipt(inventory.phase_path, inventory.source, inventory.source_sha256,
                           output, hashlib.sha256(output.read_bytes()).hexdigest(), len(inventory.doc_ids))
