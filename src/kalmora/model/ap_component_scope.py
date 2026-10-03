from dataclasses import dataclass


@dataclass(frozen=True)
class APComponentScope:
    """Factory input identity carried by a monetary AP calculation.

    Standalone tax calculations may omit vendor/invoice identity. Such partial
    scopes cannot authorize journal assembly; all fields must match the invoice.
    """

    company: str
    vendor: str | None
    currency: str
    invoice_id: str | None
    invoice_date: str
    decision: str
