from typing import Literal, TypedDict


class CostSummary(TypedDict):
    """Cost summary of a run, distinguishing *zero* from *unknown*."""

    status: Literal["no_llm", "estimated", "unknown"]
    """``no_llm``: the run made no provider calls, so its cost is truly zero (deterministic
    code). ``estimated``: every call has a cost. ``unknown``: at least one call lacks
    pricing or usage, so no total can be claimed."""

    total: str | None
    """``"0"`` only with ``no_llm``; otherwise ``None``, because there is one total per currency."""

    estimated_by_currency: dict[str, str]
    """Sum per currency over the calls that do have a cost. Never converted or mixed."""

    unknown_calls: int
    """Number of calls whose cost could not be estimated."""
