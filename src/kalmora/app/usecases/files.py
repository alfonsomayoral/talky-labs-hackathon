"""Raw files of a phase or of a run bundle, for clients that parse them themselves (the web app's worker).

``__index.json`` lists ``[{path, size}]`` relative to the root; any other path returns that file. The
phase's ``golden/`` folder is never listed nor served: it belongs to the evaluator.
"""
from pathlib import Path
from typing import Any

from ..errors import DomainError
from ..ports import PhaseRepository, RunStore

INDEX = "__index.json"


def _hidden(relative: Path, hidden: tuple[str, ...]) -> bool:
    return bool(relative.parts) and relative.parts[0] in hidden


def serve_tree(root: Path, path: str, hidden: tuple[str, ...] = ()) -> list[dict[str, Any]] | Path:
    root = root.resolve()
    if path in ("", INDEX):
        files = (p for p in root.rglob("*") if p.is_file())
        return [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size}
                for p in sorted(files) if not _hidden(p.relative_to(root), hidden)]
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file() or _hidden(target.relative_to(root), hidden):
        raise DomainError("file.not_found", f"No file '{path}'.")
    return target


class GetPhaseFile:
    def __init__(self, repo: PhaseRepository) -> None:
        self._repo = repo

    def __call__(self, phase: str, path: str) -> list[dict[str, Any]] | Path:
        return serve_tree(self._repo.location(phase), path, hidden=("golden",))


class GetRunFile:
    def __init__(self, runs: RunStore) -> None:
        self._runs = runs

    def __call__(self, run_id: str, path: str) -> list[dict[str, Any]] | Path:
        root = self._runs.files_root(run_id)
        if not root.is_dir():
            if path in ("", INDEX):
                return []
            raise DomainError("file.not_found", f"No file '{path}'.")
        return serve_tree(root, path)
