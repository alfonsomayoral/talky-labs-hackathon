"""Convert AR Cash decisions into provenance-owned ledger entries."""
from ..data import PhaseData
from ..model import JournalEntry
from ..validation import validate_entry
from ..money import integer, company_local_currency
from .engine import ArCashRun


def journal_entries(data: PhaseData, run: ArCashRun) -> tuple[JournalEntry, ...]:
    """Return one cash-application entry per decided receipt with a journal adjustment."""
    accounts = {str(row["id"]): row for row in data.table("bank_accounts")}
    lines_by_id = {}
    for account_id in sorted(accounts):
        for line in data.bank_lines(account_id, data.month):
            line_id = str(line["bank_line"])
            if line_id in lines_by_id:
                raise ValueError(f"duplicate bank_line across accounts: {line_id}")
            lines_by_id[line_id] = (line, accounts[account_id])

    result_entries: list[JournalEntry] = []
    owners: set[tuple[str, str]] = set()
    for result in run.results:
        row = result.row
        adjustment = row["adjustment"]
        if not adjustment:
            continue
        line_id = str(row["bank_line"])
        if line_id not in lines_by_id:
            raise ValueError(f"AR Cash receipt has no bank line: {line_id}")
        bank_line, account = lines_by_id[line_id]
        company = str(account["company"])
        currency = company_local_currency(company)
        if account["currency"] != currency:
            raise ValueError(f"AR Cash projection requires local-currency receipt: {line_id}")
        owner = (line_id, "cash_application")
        if owner in owners:
            raise ValueError(f"duplicate AR Cash application owner: {owner}")
        owners.add(owner)
        journal_lines = []
        for number, item in enumerate(adjustment, 1):
            if str(item.get("company")) != company:
                raise ValueError(f"AR Cash adjustment company mismatch for {line_id}")
            debit, credit = integer(item["debit"]), integer(item["credit"])
            line = {"line": number, "company": company, "account": str(item["account"]),
                    "debit": debit, "credit": credit, "currency": currency,
                    "amount_doc": max(debit, credit)}
            for field in ("partner", "assignment", "cost_center", "wbs"):
                if item.get(field) is not None:
                    line[field] = item[field]
            journal_lines.append(line)
        entry: JournalEntry = {
            "company": company, "currency": currency,
            "posting_date": str(bank_line["value_date"]),
            "document_date": str(bank_line["booking_date"]),
            "doc_type": "DZ", "source": "AR_CASH",
            "reference": line_id, "header_text": "AR cash application",
            "provenance": {"event_id": line_id, "stage": "cash_application"},
            "lines": journal_lines,
        }
        problems = validate_entry(entry)
        if problems:
            raise ValueError(f"invalid AR Cash journal entry for {line_id}: {'; '.join(problems)}")
        result_entries.append(entry)
    return tuple(result_entries)
