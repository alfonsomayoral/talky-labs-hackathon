"""Synthetic helpers shared by the bank reconciliation tests."""
import json
from pathlib import Path

from kalmora.bankrec.model import BankAccount, BookLine, StatementLine

ACCOUNT = BankAccount("BIN-1100", "1100", "57200001", "EUR", "n43")
OTHER = BankAccount("CMA-1100", "1100", "57200002", "EUR", "n43")
USD = BankAccount("BANH-3100-USD", "3100", "57200006", "USD", "csv_mx")


def bank(id, date, amount, text, account="BIN-1100", **details):
    return StatementLine(id, account, date[:7], date, date, amount, "EUR", text, **details)


def book(id, date, amount, source="F110", reference="", text="", doc=None, entry=None, company="1100", currency="EUR"):
    return BookLine(id, entry or id.split("#")[0], company, date, amount, amount if doc is None else doc,
                    currency, source, reference, text)


def _n43_move(date, amount, ref1="", ref2="", concepts=()):
    yymmdd = date[2:4] + date[5:7] + date[8:10]
    head = "22" + " " * 4 + "0001" + yymmdd + yymmdd + "02" + "001" + ("2" if amount > 0 else "1") + f"{abs(amount):014d}"
    head += "0000000001" + ref1.ljust(12) + ref2.ljust(16)
    rows = [head]
    for code, left, right in concepts:
        rows.append("23" + code + left.ljust(38)[:38] + right.ljust(38)[:38])
    return rows


def write_n43(path: Path, opening: int, moves):
    """moves: (date, amount, ref1, ref2, concepts); the closing balance is computed."""
    closing = opening + sum(m[1] for m in moves)
    rows = ["11" + "9101" + "2938" + "2848142243" + "260701" + "260731" + ("2" if opening >= 0 else "1")
            + f"{abs(opening):014d}" + "978" + "3" + "ACCOUNT".ljust(26)]
    for move in moves:
        rows.extend(_n43_move(*move))
    rows.append("33" + "9101" + "2938" + "2848142243" + "00000" + "0" * 14 + "00000" + "0" * 14
                + ("2" if closing >= 0 else "1") + f"{abs(closing):014d}" + "978" + " " * 4)
    rows.append("88" + "9" * 18 + "0000" + "88")
    path.write_text("\n".join(rows) + "\n", encoding="latin-1")
    return closing


def write_twin(path: Path, lines):
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
