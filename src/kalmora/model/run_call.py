from typing import TypedDict

from .pricing import Pricing


class RunCall(TypedDict):
    """One real call to an LLM provider, as recorded in a run report.

    Only genuine provider calls are recorded; a result served from ``FactsCache`` is
    counted separately as a cache hit. That separation is what makes the cost per
    extraction auditable.
    """

    provider: str
    model: str

    input_tokens: int | None
    """Input tokens; ``None`` if the provider did not report usage (the cost is then unknown)."""

    output_tokens: int | None

    usage: object | None
    """Provider usage payload, kept verbatim and uninterpreted."""

    pricing: Pricing | None

    estimated_cost: str | None
    """``input_rate x input_tokens + output_rate x output_tokens`` as an exact decimal.
    ``None`` when pricing or usage is missing: an unknown cost is reported as unknown, never as zero."""

    assumptions: list[str]
    """Limits of the estimate (tokens only; excludes taxes and discounts)."""
