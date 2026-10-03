"""Load the organizer's scorer unchanged and record its identity."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

SCORER_MEMBER = "participant/score.py"


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_scorer(path: Path, manifest_path: Path | None = None) -> tuple[ModuleType, dict[str, Any]]:
    """Import ``score.py`` as a module; verify it against a package manifest when given."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Scorer not found: {path}")
    digest = sha256_file(path)
    verified: bool | None = None
    if manifest_path is not None:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Package manifest not found: {manifest_path}; register the package with import-package")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = next((item["sha256"] for item in manifest.get("files", [])
                         if item.get("path") == SCORER_MEMBER), None)
        if expected is None:
            raise ValueError(f"Manifest does not list {SCORER_MEMBER}: {manifest_path}")
        if expected != digest:
            raise ValueError(f"Scorer hash {digest} does not match manifest {expected}")
        verified = True
    spec = importlib.util.spec_from_file_location("kalmora_official_score", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load scorer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, {"path": str(path.resolve()), "sha256": digest, "manifest_verified": verified}
