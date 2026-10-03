"""Policy observations for one invoice, with supporting events."""
from dataclasses import dataclass
from .ap_event import ApEvent


@dataclass(frozen=True)
class InvoiceEventState:
    certificate_valid: bool | None
    factoring_active: bool | None
    embargo_active: bool | None
    bank_change_supported: bool | None
    certificate: ApEvent | None = None
    factoring: ApEvent | None = None
    embargo: ApEvent | None = None
    bank_change: ApEvent | None = None
    diagnostics: tuple[str, ...] = ()
    factoring_bank_supported: bool | None = None
