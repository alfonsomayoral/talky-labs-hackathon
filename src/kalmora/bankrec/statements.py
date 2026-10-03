"""Statements: original N43 / CAMT.053 / Mexican CSV files aligned with the ``.lines.jsonl`` twin.

The twin supplies the delivered ``bank_line`` ids; the original file supplies the signed
amounts, the balances and the details the twin drops (mandate, invoice, returned receipt,
motive). Alignment is by position and every file is checked: count, signed amounts and
``opening + movements = closing``. Consecutive months must chain.
"""
import csv
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..data import PhaseData
from ..model import Month
from .model import BankAccount, Statement, StatementLine


class StatementError(ValueError):
    """The statement is inconsistent with its twin or with its own balances."""


def _cents(text: str) -> int:
    return int((Decimal(text.replace(" ", "").replace(",", "")) * 100).quantize(Decimal(1)))


def _n43(path: Path) -> tuple[int, int, list[dict]]:
    opening = closing = None
    moves: list[dict] = []
    for line in path.read_text(encoding="latin-1").splitlines():
        if line.startswith("11"):
            opening = (1 if line[32] == "2" else -1) * int(line[33:47])
        elif line.startswith("22"):
            moves.append({"amount": (1 if line[27] == "2" else -1) * int(line[28:42]),
                          "reference": line[52:64].strip(), "receipt": line[64:80].strip(), "concepts": []})
        elif line.startswith("23") and moves:
            moves[-1]["concepts"].append((line[2:4], line[4:42].rstrip(), line[42:80].rstrip()))
        elif line.startswith("33"):
            closing = (1 if line[58] == "2" else -1) * int(line[59:73])
    if opening is None or closing is None:
        raise StatementError(f"{path.name}: missing opening or closing balance record")
    return opening, closing, moves


def _n43_details(move: dict) -> dict:
    text = " ".join(part for _, a, b in move["concepts"] for part in (a, b))
    mandate = re.search(r"REF\. MANDATO (\S+)", text)
    invoice = re.search(r"\bFRA (\S+)", text)
    motive = re.search(r"\bMOTIVO (\S+)", text)
    receipt = move["receipt"] if re.fullmatch(r"[A-Z]{2}\d{2}-\d+", move["receipt"]) else None
    return {"mandate": mandate.group(1) if mandate else None, "invoice": invoice.group(1) if invoice else None,
            "receipt": receipt, "motive": motive.group(1) if motive else None,
            "reference": move["reference"] or None}


def _text(node: ET.Element, path: str, ns: dict[str, str]) -> str:
    found = node.find(path, ns)
    if found is None or found.text is None:
        raise StatementError(f"camt entry lacks {path}")
    return found.text


def _camt(path: Path) -> tuple[int, int, list[dict]]:
    root = ET.parse(path).getroot()
    ns = {"n": root.tag[1:root.tag.index("}")]}
    balances = {}
    for bal in root.iter(f"{{{ns['n']}}}Bal"):
        sign = 1 if _text(bal, "n:CdtDbtInd", ns) == "CRDT" else -1
        balances[_text(bal, "n:Tp/n:CdOrPrtry/n:Cd", ns)] = sign * _cents(_text(bal, "n:Amt", ns))
    moves = []
    for entry in root.iter(f"{{{ns['n']}}}Ntry"):
        sign = 1 if _text(entry, "n:CdtDbtInd", ns) == "CRDT" else -1
        end = entry.find("n:NtryDtls/n:TxDtls/n:Refs/n:EndToEndId", ns)
        moves.append({"amount": sign * _cents(_text(entry, "n:Amt", ns)), "id": _text(entry, "n:NtryRef", ns),
                      "reference": end.text if end is not None and end.text != "NOTPROVIDED" else None})
    if "OPBD" not in balances or "CLBD" not in balances:
        raise StatementError(f"{path.name}: missing opening or closing balance")
    return balances["OPBD"], balances["CLBD"], moves


def _csv(path: Path) -> tuple[int, int, list[dict]]:
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    opening = _cents(rows[0][7])
    moves, closing = [], opening
    for row in rows[2:]:
        if not row or not row[0]:
            continue
        concept = row[1]
        invoice = re.search(r"\bFRAS? (\S+)", concept)
        moves.append({"amount": _cents(row[5] or "0") - _cents(row[4] or "0"), "reference": row[2].strip() or None,
                      "invoice": invoice.group(1) if invoice else None})
        closing = _cents(row[6])
    return opening, closing, moves


_READERS = {"n43": ("n43", _n43), "camt053": ("camt053.xml", _camt), "csv_mx": ("csv", _csv)}


def receipt_narratives(data: PhaseData, account: str, month: Month) -> dict[str, str]:
    """Retain N43 references and concepts omitted by the JSONL movement twin.

    JSON-only fixtures have no original statement and receive no enrichment.
    An available original must align with the twin; corrupt sources fail closed.
    """
    path = data.phase_dir / "bank" / account / f"{month}.n43"
    if not path.is_file():
        return {}
    twin = list(data.bank_lines(account, month))
    opening, closing, moves = _n43(path)
    if len(twin) != len(moves) or any(line["amount"] != move["amount"] for line, move in zip(twin, moves)):
        raise StatementError(f"{account} {month}: original file and .lines.jsonl differ")
    if opening + sum(move["amount"] for move in moves) != closing:
        raise StatementError(f"{account} {month}: opening plus movements does not equal closing")
    return {
        line["bank_line"]: " ".join([line["text"], move["reference"], move["receipt"],
                                    *(part for _, a, b in move["concepts"] for part in (a, b))])
        for line, move in zip(twin, moves)
    }


def read_statement(data: PhaseData, account: BankAccount, month: Month) -> Statement:
    """One month of one account; StatementError if the files disagree or the balances do not close."""
    try:
        suffix, reader = _READERS[account.statement_format]
    except KeyError:
        raise StatementError(f"{account.id}: unsupported statement format {account.statement_format}") from None
    twin = list(data.bank_lines(account.id, month))
    opening, closing, moves = reader(data.phase_dir / "bank" / account.id / f"{month}.{suffix}")
    if len(twin) != len(moves) or any(line["amount"] != move["amount"] for line, move in zip(twin, moves)):
        raise StatementError(f"{account.id} {month}: original file and .lines.jsonl differ")
    if opening + sum(move["amount"] for move in moves) != closing:
        raise StatementError(f"{account.id} {month}: opening plus movements does not equal closing")
    lines = []
    for line, move in zip(twin, moves):
        details = _n43_details(move) if account.statement_format == "n43" else {
            "invoice": move.get("invoice"), "reference": move.get("reference")}
        lines.append(StatementLine(line["bank_line"], account.id, month, line["booking_date"], line["value_date"],
                                   line["amount"], line["currency"], line["text"], **details))
    return Statement(account.id, month, opening, closing, tuple(lines))


def statement_months(data: PhaseData, account: BankAccount, upto: Month) -> list[Month]:
    folder = data.phase_dir / "bank" / account.id
    return sorted(path.name[:7] for path in folder.glob("*.lines.jsonl") if path.name[:7] <= upto)


def read_statements(data: PhaseData, account: BankAccount, upto: Month) -> list[Statement]:
    """All months up to ``upto``; StatementError unless each closing equals the next opening."""
    statements = [read_statement(data, account, month) for month in statement_months(data, account, upto)]
    for before, after in zip(statements, statements[1:]):
        if before.closing != after.opening:
            raise StatementError(f"{account.id}: {before.month} closing differs from {after.month} opening")
    return statements
