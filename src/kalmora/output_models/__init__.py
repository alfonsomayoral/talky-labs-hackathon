"""Row shapes of the six delivery files (``FORMATO_ENTREGA.md``), one module per file.

Types only, no logic: they describe what a solver writes, not what the evaluator reads.
Journal entries and lines reuse ``kalmora.model``.
"""
from .ap import Action, ApLine, ApPayee, ApRow, Decision, DocumentType, PaymentBlock
from .ar_billing import ArBillingRow, ArDeduction, ArFace, ArInvoice, ArInvoiceLine
from .ar_cash import ArApplication, ArCashRow, ArResidual, ResidualType
from .bank_rec import (BankAdjustment, BankMatch, BankRecRow, BankUnmatchedBank,
                       BankUnmatchedBook)
from .close import CloseRow, CloseType
from .ic import IcRow

__all__ = [
    "Action", "ApLine", "ApPayee", "ApRow", "ArApplication", "ArBillingRow", "ArCashRow",
    "ArDeduction", "ArFace", "ArInvoice", "ArInvoiceLine", "ArResidual", "BankAdjustment",
    "BankMatch", "BankRecRow", "BankUnmatchedBank", "BankUnmatchedBook", "CloseRow",
    "CloseType", "Decision", "DocumentType", "IcRow", "PaymentBlock", "ResidualType",
]
