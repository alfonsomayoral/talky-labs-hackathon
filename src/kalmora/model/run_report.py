from typing import Literal, NotRequired, TypedDict

from .cost_summary import CostSummary
from .run_call import RunCall


class RunReport(TypedDict):
    """Report of one execution (``outputs/runs/<uuid>.json``).

    Written on every run, including failed ones, so the cost and time of a solution can be
    audited after the fact. It is *execution* accounting (inputs, duration, status, LLM
    cost) — not a submission, and not part of the deliverable that gets scored.
    """

    schema_version: int
    run_id: str
    """UUID of the run; also the file name."""

    command: list[str]
    input_metadata: dict[str, object]
    """Identifying inputs: resolved paths, package version and, when the evaluator supplies
    them, the package hash, phase and month."""

    calls: list[RunCall]
    cache_hits: int
    """Times a ``FactsCache`` result replaced a provider call."""

    started_at: str
    ended_at: str
    """UTC ISO 8601 timestamps."""

    elapsed_seconds: float
    status: Literal["completed", "failed"]
    """``failed`` if an exception was raised or the exit code is nonzero."""

    error_type: str | None
    cost: CostSummary
    exit_code: NotRequired[int]
