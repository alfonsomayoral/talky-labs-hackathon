from typing import Any

from ..output_validation import check_structure


class StructureChecker:
    """Solver-side structure check of the six delivery files (shared contract, no golden)."""

    def check(self, rows_by_module: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        return check_structure(rows_by_module)
