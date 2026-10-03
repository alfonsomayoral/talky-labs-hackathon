"""Format-only bank parsers; no reconciliation or posting decisions."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import io
from typing import Any
import xml.etree.ElementTree as ET


def cents(text: str) -> int:
    try:
        original = Decimal(text)
        with localcontext() as context:
            context.prec = max(28, len(original.as_tuple().digits) + 3)
            value = original * 100
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal bank amount') from exc
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError('Amount is not an exact number of cents')
    return int(value)


def xml_root(payload: bytes) -> ET.Element:
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('DTD/entity declarations are forbidden')
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f'Invalid XML: {exc}') from exc


def _date(raw: str, pattern: str = '%y%m%d') -> str:
    return datetime.strptime(raw, pattern).date().isoformat()


def _signed(raw: str, sign: str) -> int:
    if sign not in {'1', '2'}:
        raise ValueError('Unknown N43 debit/credit indicator')
    return int(raw) * (-1 if sign == '1' else 1)


def _currency(code: str) -> str:
    # ISO 4217 numeric identifiers, format mapping rather than company logic.
    currencies = {'978': 'EUR', '840': 'USD', '484': 'MXN', '826': 'GBP'}
    if code not in currencies:
        raise ValueError(f'Unsupported ISO numeric currency {code}')
    return currencies[code]


def n43(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = payload.decode('latin-1').splitlines()
    if not records or records[0][:2] != '11':
        raise ValueError('Missing N43 account header')
    header = records[0]
    # Validated bytes use the standard 10-character account at [10:20].
    # The reference HTML's [22:28] date offset does not match these inputs.
    statement = {'account_id_raw': header[2:20],
                 'date_from': _date(header[20:26]),
                 'date_to': _date(header[26:32]),
                 'opening_cents': _signed(header[33:47], header[32]),
                 'currency': _currency(header[47:50])}
    lines: list[dict[str, Any]] = []
    footer_seen = False
    for number, record in enumerate(records[1:], 2):
        kind = record[:2]
        if kind == '22':
            if len(record) < 64:
                raise ValueError(f'Short N43 movement at line {number}')
            lines.append({'booking_date': _date(record[10:16]),
                          'value_date': _date(record[16:22]),
                          'amount_cents': _signed(record[28:42], record[27]),
                          'currency': statement['currency'], 'text_full': '',
                          'reference': (record[52:64].strip() + ' ' + record[64:80].strip()).strip(),
                          'extra': {'common_code': record[22:24], 'own_code': record[24:27],
                                    'document_number': record[42:52], 'records_23': []},
                          'locator': f'line:{number}'})
        elif kind == '23' and lines:
            lines[-1]['extra']['records_23'].append(record)
            lines[-1]['text_full'] = (lines[-1]['text_full'] + ' ' + record[4:].strip()).strip()
        elif kind == '24' and lines:
            lines[-1]['orig_currency'] = _currency(record[4:7])
            lines[-1]['orig_amount_cents'] = int(record[7:21]) * (-1 if lines[-1]['amount_cents'] < 0 else 1)
        elif kind == '33':
            statement['closing_cents'] = _signed(record[59:73], record[58])
            footer_seen = True
        elif kind != '88':
            raise ValueError(f'Unsupported N43 record {kind} at line {number}')
    if not footer_seen:
        raise ValueError('Missing N43 account footer')
    return statement, lines


def camt(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = xml_root(payload)
    # Namespace-independent local names, without dropping source values.
    for element in root.iter():
        element.tag = element.tag.rsplit('}', 1)[-1]
    statements = root.findall('.//Stmt')
    if len(statements) != 1:
        raise ValueError('Expected exactly one camt statement per source file')
    stmt = statements[0]
    balances = {}
    for balance in stmt.findall('Bal'):
        code = balance.findtext('Tp/CdOrPrtry/Cd')
        indicator = balance.findtext('CdtDbtInd')
        if indicator not in {'DBIT', 'CRDT'}:
            raise ValueError('Unknown camt balance debit/credit indicator')
        balances[code] = cents(balance.findtext('Amt', '')) * (-1 if indicator == 'DBIT' else 1)
    statement = {'account_id_raw': stmt.findtext('Acct/Id/IBAN'),
                 'currency': stmt.findtext('Acct/Ccy'),
                 'date_from': (stmt.findtext('FrToDt/FrDtTm') or '')[:10] or None,
                 'date_to': (stmt.findtext('FrToDt/ToDtTm') or '')[:10] or None,
                 'opening_cents': balances['OPBD'], 'closing_cents': balances['CLBD']}
    lines = []
    for number, entry in enumerate(stmt.findall('Ntry'), 1):
        indicator = entry.findtext('CdtDbtInd')
        if indicator not in {'DBIT', 'CRDT'}:
            raise ValueError('Unknown camt debit/credit indicator')
        amount = entry.find('Amt')
        if amount is None:
            raise ValueError('Missing camt amount')
        lines.append({'bank_line': entry.findtext('NtryRef'),
                      'booking_date': entry.findtext('BookgDt/Dt'),
                      'value_date': entry.findtext('ValDt/Dt'),
                      'amount_cents': cents(amount.text or '') * (-1 if indicator == 'DBIT' else 1),
                      'currency': amount.attrib['Ccy'],
                      'text_full': ' / '.join(el.text or '' for el in entry.findall('.//Ustrd')),
                      'counterparty': entry.findtext('.//RltdPties/Dbtr/Nm') or entry.findtext('.//RltdPties/Cdtr/Nm'),
                      'reference': entry.findtext('.//EndToEndId'),
                      'extra': {'transaction_code': entry.findtext('BkTxCd/Prtry/Cd'), 'status': entry.findtext('Sts/Cd')},
                      'locator': f'Ntry:{number}'})
    return statement, lines


def bank_csv(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reader = csv.reader(io.StringIO(payload.decode('utf-8-sig')))
    header = next(reader)
    columns = next(reader)
    if header[0] != 'Cuenta' or columns[:2] != ['Fecha', 'Concepto']:
        raise ValueError('Unknown bank CSV header')
    start, end = header[5].split(' al ')
    statement = {'account_id_raw': header[1], 'currency': header[3],
                 'date_from': _date(start, '%d/%m/%Y'), 'date_to': _date(end, '%d/%m/%Y'),
                 'opening_cents': cents(header[7])}
    lines = []
    balance = statement['opening_cents']
    chain_ok = True
    for number, values in enumerate(reader, 3):
        if not values:
            continue
        row = dict(zip(columns, values, strict=True))
        amount = cents(row['Abono']) - cents(row['Cargo'])
        running = cents(row['Saldo'])
        chain_ok = chain_ok and balance + amount == running
        balance = running
        lines.append({'booking_date': _date(row['Fecha'], '%d/%m/%Y'), 'value_date': None,
                      'amount_cents': amount, 'currency': statement['currency'],
                      'text_full': row['Concepto'], 'reference': row['Referencia'],
                      'extra': {'tracking_key': row['Clave de rastreo'], 'balance_cents': running},
                      'locator': f'row:{number}'})
    statement['closing_cents'] = balance
    statement['chain_ok'] = chain_ok
    return statement, lines
