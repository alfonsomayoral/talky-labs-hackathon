from typing import TypedDict


class Provenance(TypedDict):
    """Why an adjustment entry exists: the business event that caused it and the step it implements.

    The historical journal is already recorded and must not be posted again; only the
    *adjustments* the solver produces carry provenance. The pair ``(event_id, stage)``
    is the adjustment's identity: the ledger refuses to repeat it, also when it is
    rebuilt from stored entries. This is what makes re-running a close idempotent.

    One business event can legitimately produce several entries, as long as each is a
    different stage. A customer receipt is the textbook case: the bank import books
    Dr 572 / Cr 555, and the later cash application books Dr 555 / Cr 430.
    """

    event_id: str
    """Stable identifier of the triggering fact: a bank line (``BL0002743``), an AP document
    (``API005263``), a close item. Must be reproducible across runs."""

    stage: str
    """Accounting step of that fact, e.g. ``bank_import`` (Dr 572 / Cr 555) or
    ``cash_application`` (Dr 555 / Cr 430). Two stages of one event are distinct entries."""
