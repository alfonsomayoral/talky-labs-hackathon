"""Journal entry and delivery row from a resolved invoice (policy §3.1 "Asiento")."""
from ..model import JournalEntry, JournalLine
from ..output_models import ArBillingRow, ArDeduction, ArFace, ArInvoice, ArInvoiceLine
from .model import BillingResult, Invoice

RECEIVABLE, GUARANTEE, ADVANCE, MX_LEVY, VAT = "43000000", "43000900", "43800000", "63100000", "47700000"
_DEDUCTION_ACCOUNT = {"MX5MILL": MX_LEVY, "ADV_AMORT": ADVANCE}
REVERSE_CHARGE_NOTICE = "Inversión del sujeto pasivo conforme al art. 84.Uno.2º f de la Ley del IVA."


def build_entry(invoice: Invoice, *, company: str, customer: str, customer_name: str) -> JournalEntry:
    """Dr receivable (payable), Dr guarantee, Dr deductions, Cr income by line, Cr VAT.

    Balanced by construction: debits sum to gross, credits to net + tax. A negative line
    (market deviations) is a debit on its income account.
    """
    lines: list[JournalLine] = []

    def add(account: str, debit: int, credit: int, **extra: object) -> None:
        lines.append(JournalLine(line=len(lines) + 1, account=account, debit=debit, credit=credit,
                                 currency=invoice.currency, amount_doc=max(debit, credit), **extra))  # type: ignore[typeddict-item]

    partner = dict(partner=customer, assignment=invoice.number)
    add(RECEIVABLE, invoice.payable, 0, text=f"Factura {invoice.number}", **partner)
    if invoice.retention:
        add(GUARANTEE, invoice.retention, 0, text="Retención de garantía", **partner)
    for deduction in invoice.deductions:
        if deduction.code == "MX5MILL":
            add(deduction.account, deduction.amount, 0, partner=None, text="Derecho de inspección 5 al millar")
        else:
            add(deduction.account, deduction.amount, 0, partner=customer, text="Amortización de anticipo")
    for line in invoice.lines:
        add(line.account, max(-line.amount, 0), max(line.amount, 0), partner=None, wbs=line.wbs,
            cost_center=line.cost_center, tax_code=invoice.tax_code, text=line.description)
    if invoice.tax:
        add(VAT, 0, invoice.tax, partner=None, tax_code=invoice.tax_code, text=f"IVA repercutido {invoice.tax_code}")
    header = f"Factura {customer_name}"
    if invoice.tax_code == "RISP":
        header += " — " + REVERSE_CHARGE_NOTICE
    return JournalEntry(company=company, doc_type="DR", posting_date=invoice.date, document_date=invoice.date,
                        reference=invoice.number, header_text=header, source="SD",
                        currency=invoice.currency, lines=lines)


def to_row(result: BillingResult) -> ArBillingRow:
    """Delivery row (``FORMATO_ENTREGA.md``) for one result."""
    item = result.item
    row = ArBillingRow(billing_item=item.id, expected=result.decision.value, company=item.company)
    invoice = result.invoice
    if invoice is None or result.journal_entry is None:
        return row
    body = ArInvoice(
        number=invoice.number, currency=invoice.currency, gross=invoice.gross,
        date=invoice.date, due_date=invoice.due_date, tax_code=invoice.tax_code, net=invoice.net,
        tax=invoice.tax, retention=invoice.retention, payable=invoice.payable,
        deductions=[ArDeduction(code=d.code, amount=d.amount, account=d.account) for d in invoice.deductions],
        lines=[ArInvoiceLine(description=x.description, amount=x.amount, account=x.account,
                             cost_center=x.cost_center, wbs=x.wbs) for x in invoice.lines])
    if invoice.face:
        body["face"] = ArFace(oficina_contable=invoice.face.oficina_contable,
                              organo_gestor=invoice.face.organo_gestor,
                              unidad_tramitadora=invoice.face.unidad_tramitadora)
    if invoice.tax_code == "RISP":
        body["legal_notice"] = REVERSE_CHARGE_NOTICE
    row["invoice"] = body
    row["journal_entry"] = result.journal_entry
    return row
