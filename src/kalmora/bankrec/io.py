"""JSONL delivery writer for a complete bank reconciliation run."""
import json
import os
from pathlib import Path
import tempfile

from .model import BankRecRun
from .rows import to_row


def write_bank_rec(run: BankRecRun, destination: Path) -> Path:
    """Write all reconciled accounts atomically; incomplete runs are not deliverable."""
    if run.unresolved:
        accounts = ", ".join(result.account for result in run.unresolved)
        raise ValueError(f"bank reconciliation has unresolved accounts: {accounts}")
    target = Path(destination).expanduser()
    if target.suffix.lower() != ".jsonl":
        raise ValueError("bank reconciliation output must use a .jsonl extension")
    if "golden" in target.parts:
        raise ValueError("solver output cannot be written under a golden directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=f".{target.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            for result in run.results:
                handle.write(json.dumps(to_row(result), ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        return target
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
