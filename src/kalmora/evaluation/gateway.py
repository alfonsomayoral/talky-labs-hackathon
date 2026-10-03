"""Evaluator side of the application ports: the only place the API reaches ``evaluation``."""
from pathlib import Path
from typing import Any

from ..app.errors import DomainError
from .report import evaluate, write_report


class EvaluatorGateway:
    """``root/<phase>/golden`` must exist for a phase to be evaluated; ``root=None`` disables scoring."""

    def __init__(self, root: Path | None, reports_dir: Path) -> None:
        self._root = Path(root) if root is not None else None
        self._reports = Path(reports_dir)

    @property
    def enabled(self) -> bool:
        return self._root is not None

    def evaluate(self, phase: str, phase_dir: Path, submission_dir: Path) -> dict[str, Any]:
        if self._root is None:
            raise DomainError("evaluation.unavailable", "The evaluator is not enabled in this process.")
        evaluator_dir = self._root / phase
        if not (evaluator_dir / "golden").is_dir():
            raise DomainError("evaluation.unavailable", f"Phase '{phase}' has no golden: it cannot be scored.")
        if not submission_dir.is_dir():
            raise DomainError("submission.not_found", f"No submission folder for {phase}.")
        try:
            report = evaluate(phase_dir, submission_dir, evaluator_dir)
        except (ValueError, FileNotFoundError, KeyError) as exc:
            raise DomainError("evaluation.failed", str(exc)) from None
        write_report(report, self._reports)
        return {"report_id": report["report_id"], "total": report["headline"]["total"],
                "module_scores": {name: {"score": m["score"]} for name, m in report["modules"].items()},
                "reconciliation_ok": report["reconciliation_ok"], "separation": report["separation"],
                "modules": report["modules"]}
