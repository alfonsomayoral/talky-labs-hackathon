"""JSONL delivery writer for AR cash application results."""
import json
import os
from pathlib import Path
import tempfile

from .engine import ArCashRun, to_row


def write_ar_cash(run: ArCashRun, destination: Path) -> Path:
    """Write delivery rows atomically; the phase inputs remain read-only."""
    target = Path(destination).expanduser()
    if target.suffix.lower() != ".jsonl":
        raise ValueError("AR cash output must use a .jsonl extension")
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
