"""Validate a credit restoration and return its delivery/state snapshots together.

The monthly runner owns publication and stores all three snapshots atomically.
This boundary never edits the originals, publishes a row or resets phase state.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json

from .ap_allocation import ConsumptionState
from .ap_journal import AdvanceState
from .ap_output import APHeader, POSTING, build_ap_row
from .ap_restoration import (
    ReceiptRestoration, ReceiptRestorationState, prepare_ap_credit_restoration,
)
from .ap_tax import TaxCatalog
from .facts import Evidence
from .model.validation_context import ValidationContext
from .output_models.ap import ApLine, ApRow


@dataclass(frozen=True)
class APCreditDelivery:
    row_json: bytes
    advances: AdvanceState
    consumption: ConsumptionState
    restoration_state: ReceiptRestorationState
    evidence: tuple[Evidence, ...]

    @property
    def row(self) -> ApRow:
        """Return a copy; a caller cannot mutate the validated delivery bytes."""
        return json.loads(self.row_json)


def build_ap_credit_delivery(*, journal_arguments: Mapping, header: APHeader,
                             lines: Sequence[ApLine], consumption: ConsumptionState,
                             receipt_restorations: tuple[ReceiptRestoration, ...] = (),
                             restoration_state: ReceiptRestorationState = ReceiptRestorationState(),
                             evidence: tuple[Evidence, ...], tax_catalog: TaxCatalog,
                             context: ValidationContext | None = None,
                             payment_block: str | None = None) -> APCreditDelivery:
    """Expose restored capacity only with an accepted real AP delivery row.

    All resolved monetary factories are supplied in ``journal_arguments`` using
    the existing journal contract. The advance baseline and receipt sidecar must
    come from this phase's current snapshot. A failed journal, header, dimension
    or output validation raises without changing any input snapshot.
    """
    if (not isinstance(header, APHeader) or not isinstance(tax_catalog, TaxCatalog)
            or not isinstance(consumption, ConsumptionState)
            or not isinstance(restoration_state, ReceiptRestorationState)):
        raise TypeError("typed header, catalog and restoration snapshots required")
    if (not isinstance(evidence, tuple) or not evidence
            or any(not isinstance(item, Evidence) for item in evidence)):
        raise ValueError("credit delivery requires structured source evidence")
    arguments = dict(journal_arguments)
    if arguments.get("decision") not in POSTING or arguments.get("document_type") != "CREDIT_NOTE":
        raise ValueError("credit delivery requires a resolved posting credit note")
    if (header.company, header.vendor_id, header.currency, header.invoice_number, header.invoice_date) != (
            arguments.get("company"), arguments.get("vendor"), arguments.get("currency"),
            arguments.get("invoice_number"), arguments.get("invoice_date")):
        raise ValueError("credit header differs from resolved journal scope")
    tentative = prepare_ap_credit_restoration(journal_arguments=arguments, consumption=consumption,
        receipt_restorations=receipt_restorations, restoration_state=restoration_state)
    row = build_ap_row(doc_id=arguments["doc_id"], document_type="CREDIT_NOTE",
        decision=arguments["decision"], header=header, lines=lines,
        journal_entry=tentative.journal.journal_entry, payment_block=payment_block,
        tax_catalog=tax_catalog, context=context)
    return APCreditDelivery(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode(),
        tentative.journal.state, tentative.consumption, tentative.restoration_state,
        tuple(dict.fromkeys((*evidence, *tentative.evidence))),
    )
