"""File-backed stores: extracted packages, run reports and submissions."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..app.errors import DomainError
from ..app.types import PackageRecord
from ..model import Manifest
from ..package import register_package

MODULES = ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")
_RUN_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_PACKAGE_ID = re.compile(r"^[0-9a-f]{64}$")


class FilePackageStore:
    """Packages live at ``<root>/<archive_sha256>/`` and are never modified."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def root(self, package_id: str) -> Path:
        return self._root / package_id

    def manifest(self, package_id: str) -> Manifest:
        path = self.root(package_id) / "manifest.json"
        if not _PACKAGE_ID.match(package_id) or not path.is_file():
            raise DomainError("package.not_found", f"No package '{package_id}'.")
        return json.loads(path.read_text(encoding="utf-8"))

    def get(self, package_id: str) -> PackageRecord | None:
        try:
            manifest = self.manifest(package_id)
        except DomainError:
            return None
        stamp = (self.root(package_id) / "manifest.json").stat().st_mtime
        return {"package_id": package_id, "file_count": len(manifest["files"]),
                "registered_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                "phases": [dict(p) for p in manifest["phases"]]}

    def list(self) -> list[PackageRecord]:
        records = [self.get(p.name) for p in sorted(self._root.iterdir()) if p.is_dir()]
        return [r for r in records if r is not None]

    def register(self, archive: Path, package_id: str) -> Manifest:
        manifest = register_package(archive, self.root(package_id))
        if manifest["archive_sha256"] != package_id:
            raise ValueError("archive hash changed during registration")
        return manifest


class FileRunStore:
    """Reads the reports ``RunRecorder`` writes to ``outputs/runs``. A run may also have a bundle folder
    ``outputs/runs/<run_id>/`` (deliverables, trace, ``manifest.json``); a bundle alone is listed too."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list(self) -> list[dict[str, Any]]:
        runs: dict[str, dict[str, Any]] = {}
        for path in [*self._directory.glob("*.json"), *self._directory.glob("*/manifest.json")]:
            run = self._read(path)
            if run is not None and run.get("run_id") and run["run_id"] not in runs:
                runs[run["run_id"]] = {**run, "has_files": (self._directory / str(run["run_id"])).is_dir()}
        return sorted(runs.values(), key=lambda r: r.get("started_at", ""), reverse=True)

    def get(self, run_id: str) -> dict[str, Any]:
        root = self.files_root(run_id)
        for path in (self._directory / f"{run_id}.json", root / "manifest.json"):
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        raise DomainError("run.not_found", f"No run '{run_id}'.")

    def files_root(self, run_id: str) -> Path:
        if not _RUN_ID.match(run_id) or not ((self._directory / f"{run_id}.json").is_file()
                                            or (self._directory / run_id).is_dir()):
            raise DomainError("run.not_found", f"No run '{run_id}'.")
        return self._directory / run_id


class FileSubmissionStore:
    """A submission is the folder ``<root>/<phase>/`` with up to six ``<module>.jsonl`` files."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def directory(self, phase: str) -> Path:
        return self._root / phase

    def rows(self, phase: str, module: str) -> list[dict[str, Any]]:
        if module not in MODULES:
            raise DomainError("request.invalid", f"module must be one of: {', '.join(MODULES)}.")
        path = self.directory(phase) / f"{module}.jsonl"
        if not path.is_file():
            raise DomainError("submission.not_found", f"No {module}.jsonl submitted for {phase}.")
        rows = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise DomainError("submission.invalid", f"{module}.jsonl:{number}: {exc}") from None
        return rows

    def files(self, phase: str) -> dict[str, dict[str, Any]]:
        result = {}
        for module in MODULES:
            path = self.directory(phase) / f"{module}.jsonl"
            present = path.is_file()
            result[module] = {"present": present,
                              "rows": sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip()) if present else 0}
        return result
