"""Static check that solver modules do not import the evaluator package."""
import ast
from pathlib import Path
from typing import Any

EVALUATOR_PACKAGE = "evaluation"
# cli.py is the single dispatcher; it imports the evaluator lazily, per command.
ALLOWED = {"cli.py"}


def _imports_evaluator(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            if EVALUATOR_PACKAGE in parts or (node.level and any(a.name == EVALUATOR_PACKAGE for a in node.names)):
                lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(EVALUATOR_PACKAGE in a.name.split(".") for a in node.names):
                lines.append(node.lineno)
    return lines


def check_boundary(package_dir: Path | None = None) -> dict[str, Any]:
    root = package_dir or Path(__file__).resolve().parents[1]
    scanned, violations = 0, []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] == EVALUATOR_PACKAGE or relative.name in ALLOWED and len(relative.parts) == 1:
            continue
        scanned += 1
        for line in _imports_evaluator(ast.parse(path.read_text(encoding="utf-8"))):
            violations.append({"file": relative.as_posix(), "line": line})
    return {"scanned_modules": scanned, "allowed_dispatchers": sorted(ALLOWED), "violations": violations}
