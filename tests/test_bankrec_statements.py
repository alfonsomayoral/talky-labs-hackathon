from pathlib import Path
import tempfile
import unittest

from kalmora.bankrec.model import BankAccount
from kalmora.bankrec.statements import StatementError, read_statement, read_statements
from kalmora.data import PhaseData
from bankrec_support import write_n43, write_twin


class StatementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for area in ("erp", "tasks", "bank/BIN-1100", "bank/BLC-2100", "bank/BANH-3100-MXN"):
            (self.root / area).mkdir(parents=True)
        (self.root / "tasks/close.json").write_text('{"month":"2026-07"}')
        self.data = PhaseData(self.root)
        self.account = BankAccount("BIN-1100", "1100", "57200001", "EUR", "n43")

    def twin(self, month, rows):
        write_twin(self.root / f"bank/BIN-1100/{month}.lines.jsonl",
                   [{"bank_line": f"BL{month[-2:]}{i}", "booking_date": d, "value_date": d, "amount": a,
                     "currency": "EUR", "text": t} for i, (d, a, t) in enumerate(rows)])

    def n43(self, month, opening, moves):
        return write_n43(self.root / f"bank/BIN-1100/{month}.n43", opening, moves)

    def test_n43_details_come_from_the_original_and_ids_from_the_twin(self):
        concepts = [("01", "RECIBO ELÉCTRICA DEL LLANO", "REF. MANDATO V100028-1100"), ("02", "FRA 2026-037541", "")]
        self.n43("2026-07", 1000, [("2026-07-01", -90596, "176555693718", "2026-037541", concepts)])
        self.twin("2026-07", [("2026-07-01", -90596, "RECIBO ELÉCTRICA DEL LLANO")])
        statement = read_statement(self.data, self.account, "2026-07")
        line = statement.lines[0]
        self.assertEqual((line.id, line.amount, line.mandate, line.invoice), ("BL070", -90596, "V100028-1100", "2026-037541"))
        self.assertEqual((statement.opening, statement.closing), (1000, 1000 - 90596))

    def test_returned_receipt_and_motive(self):
        concepts = [("01", "DEVOLUCION RECIBO MD06", "MANDATO KSU-00042"), ("02", "MOTIVO MD06", "")]
        self.n43("2026-07", 0, [("2026-07-08", -29410, "SDD202607120", "RC26-00306", concepts)])
        self.twin("2026-07", [("2026-07-08", -29410, "DEVOLUCION RECIBO MD06")])
        line = read_statement(self.data, self.account, "2026-07").lines[0]
        self.assertEqual((line.receipt, line.motive), ("RC26-00306", "MD06"))

    def test_amount_mismatch_with_twin_is_rejected(self):
        self.n43("2026-07", 0, [("2026-07-01", -500, "", "", [])])
        self.twin("2026-07", [("2026-07-01", -501, "X")])
        with self.assertRaisesRegex(StatementError, "differ"):
            read_statement(self.data, self.account, "2026-07")

    def test_months_must_chain(self):
        self.n43("2026-06", 0, [("2026-06-01", 100, "", "", [])])
        self.twin("2026-06", [("2026-06-01", 100, "A")])
        self.n43("2026-07", 99, [("2026-07-01", 1, "", "", [])])
        self.twin("2026-07", [("2026-07-01", 1, "B")])
        with self.assertRaisesRegex(StatementError, "closing differs"):
            read_statements(self.data, self.account, "2026-07")
        self.n43("2026-07", 100, [("2026-07-01", 1, "", "", [])])
        self.assertEqual([s.month for s in read_statements(self.data, self.account, "2026-07")], ["2026-06", "2026-07"])

    def test_camt_carries_ids_and_signed_amounts(self):
        xml = ('<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>'
               '<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">10.00</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
               '<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">6.50</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal>'
               '<Ntry><NtryRef>BLX1</NtryRef><Amt Ccy="EUR">3.50</Amt><CdtDbtInd>DBIT</CdtDbtInd>'
               '<NtryDtls><TxDtls><Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs></TxDtls></NtryDtls></Ntry>'
               '</Stmt></BkToCstmrStmt></Document>')
        (self.root / "bank/BLC-2100/2026-07.camt053.xml").write_text(xml)
        write_twin(self.root / "bank/BLC-2100/2026-07.lines.jsonl", [{"bank_line": "BLX1", "booking_date": "2026-07-09",
                   "value_date": "2026-07-09", "amount": -350, "currency": "EUR", "text": "PAGO"}])
        statement = read_statement(self.data, BankAccount("BLC-2100", "2100", "57200004", "EUR", "camt053"), "2026-07")
        self.assertEqual((statement.opening, statement.closing, statement.lines[0].amount), (1000, 650, -350))

    def test_csv_balances_and_amounts(self):
        csv = ("Cuenta,9018,Moneda,MXN,Periodo,01/07/2026 al 31/07/2026,Saldo inicial,100.00\n"
               "Fecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo\n"
               "10/07/2026,TRANSFERENCIA A X PAGO FRAS F1,REF,TRK,40.00,0.00,60.00\n"
               "11/07/2026,COMISION,,,0.00,5.00,65.00\n")
        (self.root / "bank/BANH-3100-MXN/2026-07.csv").write_text(csv)
        write_twin(self.root / "bank/BANH-3100-MXN/2026-07.lines.jsonl", [
            {"bank_line": "M1", "booking_date": "2026-07-10", "value_date": "2026-07-10", "amount": -4000, "currency": "MXN", "text": "A"},
            {"bank_line": "M2", "booking_date": "2026-07-11", "value_date": "2026-07-11", "amount": 500, "currency": "MXN", "text": "B"}])
        statement = read_statement(self.data, BankAccount("BANH-3100-MXN", "3100", "57200005", "MXN", "csv_mx"), "2026-07")
        self.assertEqual((statement.opening, statement.closing, statement.lines[0].invoice), (10000, 6500, "F1"))


if __name__ == "__main__":
    unittest.main()
