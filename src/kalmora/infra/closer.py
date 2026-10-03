"""Launches the configured close command on a phase and records the run in its bundle folder.

The command (``kalmora serve --close-command``) receives ``{phase}``, ``{phase_dir}``, ``{month}`` and ``{out}``
and must write the six JSONL under ``{out}/deliverables/``. It may also write ``{out}/manifest.json`` (models,
cost) and ``{out}/trace/``; the closer keeps those fields and adds status, exit code and timing.
"""
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, manifest: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


class CommandCloser:
    def __init__(self, command: tuple[str, ...], run_dir: Path) -> None:
        self._command, self._run_dir = command, Path(run_dir)

    def start(self, phase: str, phase_dir: Path, month: str) -> str:
        run_id = str(uuid.uuid4())
        out = self._run_dir / run_id
        out.mkdir(parents=True)
        values = {"{phase}": phase, "{phase_dir}": str(phase_dir), "{month}": month, "{out}": str(out)}
        args = []
        for part in self._command:
            for key, value in values.items():
                part = part.replace(key, value)
            args.append(part)
        identity = {"run_id": run_id, "dataset": phase, "month": month}
        _write(out / "manifest.json", {**identity, "status": "running", "started_at": _now(), "command": args})
        threading.Thread(target=self._run, args=(args, out, identity), daemon=True).start()
        return run_id

    def _run(self, args: list[str], out: Path, identity: dict[str, str]) -> None:
        began = time.monotonic()
        with open(out / "run.log", "wb") as log:
            try:
                code = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
            except OSError as exc:
                log.write(f"{type(exc).__name__}: {exc}\n".encode())
                code = -1
        try:
            written = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            written = {}
        manifest = {**written, **identity, "status": "completed" if code == 0 else "failed", "exit_code": code}
        manifest.setdefault("finished_at", _now())
        manifest.setdefault("runtime_s", round(time.monotonic() - began, 3))
        _write(out / "manifest.json", manifest)
