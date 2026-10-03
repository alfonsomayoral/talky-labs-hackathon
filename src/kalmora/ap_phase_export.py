"""Export AP against the active phase's task inventory, without evaluation access."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from collections.abc import Iterable

from .ap_output import _pinned_ap_directory, _prepare_ap_payload, _publish_ap_payload
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
    with _pinned_ap_directory(path) as descriptor:
        with os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW,
                               dir_fd=descriptor), "rb") as stream:
            payload = stream.read()
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
    if output.is_relative_to(inventory.phase_path) or "golden" in output.parts:
        raise ValueError("AP export destination must be outside the source phase")
    # Pin before consuming a lazy producer, which may take time or mutate paths.
    with _pinned_ap_directory(output, create=True) as descriptor:
        payload = _prepare_ap_payload(rows, expected_doc_ids=inventory.doc_ids,
                                      context=context, tax_catalog=tax_catalog)
        receipt = APExportReceipt(inventory.phase_path, inventory.source, inventory.source_sha256,
                                  output, hashlib.sha256(payload).hexdigest(), len(inventory.doc_ids))
        def unchanged_inventory():
            if load_ap_task_inventory(inventory.phase_path) != inventory:
                raise ValueError("AP task inventory changed during export")
        _publish_ap_payload(output, payload, descriptor=descriptor, overwrite=overwrite,
                            before_publish=unchanged_inventory)
    return receipt


def verify_ap_export_receipt(receipt: APExportReceipt) -> bool:
    """Verify current task/output bytes and exact coverage against a prior receipt.

    This verifies export identity, not the factual provenance of accounting
    decisions. Facts, masters and rule-version compatibility belong upstream.
    Reads only canonical tasks and the supplied output, never evaluation data.
    """
    if not isinstance(receipt, APExportReceipt):
        raise TypeError("APExportReceipt required")
    inventory = load_ap_task_inventory(receipt.phase_path)
    if (receipt.task_source != inventory.source or receipt.task_sha256 != inventory.source_sha256
            or type(receipt.row_count) is not int or receipt.row_count != len(inventory.doc_ids)):
        raise ValueError("AP receipt differs from the current task inventory")
    output = Path(receipt.output_path).absolute()
    if output.resolve().is_relative_to(inventory.phase_path) or "golden" in output.resolve().parts:
        raise ValueError("AP receipt output must be outside source/evaluation data")
    with _pinned_ap_directory(output) as descriptor:
        with os.fdopen(os.open(output.name, os.O_RDONLY | os.O_NOFOLLOW,
                               dir_fd=descriptor), "rb") as stream:
            payload = stream.read()
    if hashlib.sha256(payload).hexdigest() != receipt.output_sha256:
        raise ValueError("AP output hash differs from receipt")
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
        ids = [row["doc_id"] for row in rows]
        if (len(ids) != receipt.row_count or any(not isinstance(ident, str) for ident in ids)
                or len(set(ids)) != len(ids) or set(ids) != set(inventory.doc_ids)):
            raise ValueError("AP receipt output coverage differs from tasks")
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("invalid AP receipt output") from error
    if load_ap_task_inventory(inventory.phase_path) != inventory:
        raise ValueError("AP task inventory changed during receipt verification")
    return True
