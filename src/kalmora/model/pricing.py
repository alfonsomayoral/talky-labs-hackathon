from decimal import Decimal
from typing import Literal, TypedDict


class PricingInput(TypedDict):
    """Rate **supplied by the caller** to ``RunRecorder.record_call``.

    The recorder holds no price list: a real run must pass the rate it was actually
    billed, so reported cost is never an assumption baked into the code.
    """

    unit: Literal["per_token"]
    currency: str
    """Currency of the rate. Costs in different currencies are never summed or converted."""

    provenance: str
    """Where the rate comes from (URL, date, contract). Mandatory: without it no cost is
    estimated, because an unsourced price is not auditable."""

    input_rate: Decimal | int | str
    """Price per input token, non-negative."""

    output_rate: Decimal | int | str
    """Price per output token, non-negative."""


class Pricing(TypedDict):
    """Rate as stored in the report: rates are serialized as exact decimal text so no
    precision is lost through JSON floats."""

    unit: Literal["per_token"]
    currency: str
    provenance: str
    input_rate: str
    output_rate: str
