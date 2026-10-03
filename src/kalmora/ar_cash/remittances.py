"""Read explicit applications from the challenge's remittance-advice table.

Unknown layouts, currency disagreements and incomplete tables stay unresolved.
This adapter does not allocate money or select an invoice by amount.
"""
from datetime import datetime
import csv
import io
import re

from ..data import PhaseData
from ..documents.router import DocumentRouter, ParseError


def _money(value: str) -> int:
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}", value):
        raise ValueError("unsupported remittance amount")
    whole, fraction = value.replace(".", "").split(",")
    return int(whole) * 100 + int(fraction)


def read_applications(data: PhaseData, router: DocumentRouter, notices: str,
                      company: str, receipt_date: str, amount: int, currency: str
                      ) -> tuple[list[tuple[str, int]] | None, list[str]]:
    """Accept a unique notice matching beneficiary, value date, currency and total."""
    accepted: list[list[tuple[str, int]]] = []
    diagnostics = []
    try:
        company_names = {row["name"] for row in data.companies if str(row["code"]) == company}
    except KeyError:
        return None, ["remittance cannot be validated: company master is unavailable"]
    for notice_name in notices.split(", "):
        metadata = data.table("inbox/ar/remittances/" + notice_name)
        filename = metadata.get("file")
        if not isinstance(filename, str) or "/" in filename or "\\" in filename:
            diagnostics.append(f"invalid remittance attachment in {notice_name}")
            continue
        relative = "inbox/ar/remittances/" + filename
        try:
            document = router.parse(relative)
        except (ParseError, ValueError) as error:
            diagnostics.append(f"remittance unavailable: {error}")
            continue
        if document.warnings:
            diagnostics.append(f"remittance requires image interpretation: {relative}")
            continue
        text = "\n".join(block.text for block in document.blocks)
        header = re.search(r"Beneficiario:\s*(.*?)\s*·\s*Fecha valor:\s*(\d{2}/\d{2}/\d{4})", text)
        total = re.search(r"Importe total transferido:\s*([\d.,]+)\s+([A-Z]{3})", text)
        rows = re.findall(r"^\s*([^\n]+?)\s{2,}([\d.,]+)\s+([A-Z]{3})\s*$", text, re.MULTILINE)
        if not header or not total or not rows:
            diagnostics.append(f"unsupported/incomplete remittance table: {relative}")
            continue
        try:
            observed_date = datetime.strptime(header[2], "%d/%m/%Y").date().isoformat()
            applications = [(reference.strip(), _money(value)) for reference, value, _ in rows]
            valid = (header[1].strip() in company_names and observed_date == receipt_date
                     and total[2] == currency and _money(total[1]) == amount
                     and all(code == currency and value > 0 for (_, value), (_, _, code)
                             in zip(applications, rows))
                     and sum(value for _, value in applications) == amount
                     and len({reference for reference, _ in applications}) == len(applications))
        except ValueError:
            valid = False
        if valid:
            accepted.append(applications)
            diagnostics.append(f"explicit remittance applications: {relative} sha256={document.source_sha256}")
        else:
            diagnostics.append(f"remittance beneficiary/date/currency/total mismatch: {relative}")
    if len(accepted) == 1:
        return accepted[0], diagnostics
    if accepted:
        diagnostics.append("multiple matching remittance tables; left unresolved")
    return None, diagnostics


def read_face_application(data: PhaseData, router: DocumentRouter, company: str,
                          receipt_date: str, amount: int, currency: str,
                          customer: str | None) -> tuple[list[tuple[str, int]] | None, list[str]]:
    """Use a unique paid FACe invoice as exact, date-bound corroboration for a receipt."""
    directory = data.phase_dir / "inbox" / "ar" / "remittances"
    files = sorted(directory.glob("FACe*.csv")) if directory.is_dir() else []
    if not files:
        return None, []
    invoices = {str(row["id"]): row for row in data.table("ar_invoices")}
    matches: dict[str, str] = {}
    diagnostics = []
    for path in files:
        relative = path.relative_to(data.phase_dir).as_posix()
        try:
            document = router.parse(relative)
        except (ParseError, ValueError) as error:
            diagnostics.append(f"FACe unavailable: {error}")
            continue
        if document.warnings or len(document.blocks) != 1:
            diagnostics.append(f"FACe requires interpretation: {relative}")
            continue
        try:
            rows = csv.DictReader(io.StringIO(document.blocks[0].text), delimiter=";")
            required = {"numero_factura", "importe_pagado", "estado", "fecha_estado"}
            if not required.issubset(rows.fieldnames or ()):
                raise ValueError("unsupported FACe columns")
            for row in rows:
                invoice = invoices.get(row["numero_factura"])
                if invoice is None or row["estado"].strip().upper() != "PAGADA":
                    continue
                paid_date = datetime.strptime(row["fecha_estado"], "%d/%m/%Y").date().isoformat()
                paid_amount = _money(row["importe_pagado"])
                if (paid_date == receipt_date and paid_amount == amount
                        and str(invoice["company"]) == company
                        and str(invoice.get("currency", "")) == currency
                        and (customer is None or str(invoice["customer"]) == customer)):
                    matches[str(invoice["id"])] = document.source_sha256
        except (KeyError, TypeError, ValueError):
            diagnostics.append(f"unsupported FACe row: {relative}")
    if len(matches) == 1:
        invoice_id, proof = next(iter(matches.items()))
        return [(invoice_id, amount)], [f"exact FACe paid-invoice match: {invoice_id} sha256={proof}"]
    if len(matches) > 1:
        diagnostics.append("multiple FACe invoices match receipt date and total; left unresolved")
    return None, diagnostics
