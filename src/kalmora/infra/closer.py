"""Launches the configured close command on a phase and records the run in its bundle folder.

The command (``kalmora serve --close-command``) receives ``{phase}``, ``{phase_dir}``, ``{month}`` and ``{out}``
and must write the delivery JSONL under ``{out}/deliverables/``. It may also write ``{out}/manifest.json`` (models,
cost, task timings) and ``{out}/trace/``; the closer keeps those fields and adds status, exit code, timing and a
summary of the deliverables. One run per phase at a time; runs left ``running`` by a dead server are closed
as ``failed`` (``interrupted``) when the server starts.
"""
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..app.errors import DomainError
from ..app.params import valid_phase_name

MODULES = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, manifest: dict[str, Any]) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def summarize_deliverables(out: Path) -> dict[str, dict[str, Any]]:
    summary = {}
    for module in MODULES:
        path = out / "deliverables" / f"{module}.jsonl"
        present = path.is_file()
        rows = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if present else 0
        summary[module] = {"present": present, "rows": rows}
    return summary


class CommandCloser:
    def __init__(self, command: tuple[str, ...], run_dir: Path) -> None:
        self._command, self._run_dir = command, Path(run_dir)
        self._active: dict[str, str] = {}
        self._lock = threading.Lock()
        self.recover()      # a run left "running" by a stopped server can never finish: close it when the server starts

    def start(self, phase: str, phase_dir: Path, month: str) -> str:
        if not valid_phase_name(phase):
            raise DomainError("request.invalid", f"'{phase}' is not a valid phase name.")
        run_id = str(uuid.uuid4())
        with self._lock:
            if phase in self._active:
                raise DomainError("run.busy", f"Run {self._active[phase]} of phase '{phase}' is still running.")
            self._active[phase] = run_id
        try:
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
            threading.Thread(target=self._run, args=(args, out, identity, phase), daemon=True).start()
        except BaseException:
            with self._lock:
                self._active.pop(phase, None)
            raise
        return run_id

    def _run(self, args: list[str], out: Path, identity: dict[str, str], phase: str) -> None:
        began = time.monotonic()
        error = None
        try:
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
            deliverables = summarize_deliverables(out)
            status = "completed" if code == 0 else "failed"
            if code == 0 and not any(item["present"] for item in deliverables.values()):
                status, error = "failed", "The command exited 0 but wrote no deliverables under deliverables/."
            manifest = {**written, **identity, "status": status, "exit_code": code, "deliverables": deliverables}
            if error:
                manifest["error"] = error
            manifest.setdefault("finished_at", _now())
            manifest.setdefault("runtime_s", round(time.monotonic() - began, 3))
            _write(out / "manifest.json", manifest)
        finally:
            with self._lock:
                self._active.pop(phase, None)

    def recover(self) -> int:
        """Close runs a previous server left ``running``. Returns how many were recovered."""
        count = 0
        for path in self._run_dir.glob("*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            with self._lock:
                owned = manifest.get("run_id") in self._active.values()
            if manifest.get("status") == "running" and not owned:
                _write(path, {**manifest, "status": "failed", "exit_code": -2, "interrupted": True,
                              "error": "interrupted: the server stopped during the run",
                              "finished_at": _now(), "deliverables": summarize_deliverables(path.parent)})
                count += 1
        return count
