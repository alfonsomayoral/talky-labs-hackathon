"""Accounting entry validation independent of output serialization contracts.

Optional context is a mapping of companies/accounts/partners/cost_centers/wbs
to sets or master-record mappings, plus min_date/max_date (ISO dates).
Master cost records may contain company; dates are checked when supplied.
Financial fees, FX, tax, impairment and cash residuals follow the organizer's
golden journals, which intentionally carry no cost object on these accounts.
"""
from datetime import date
import re
from .ledger import is_open_item_account
NO_COST_REQUIRED = {
    '62600000', '63100000', '66200000', '66210000', '66500000',
    '66800000', '66900000', '69400000', '70590000', '75900000',
    '76200000', '76800000', '79400000',
}

def validate_entry(entry, context=None):
    context = context or {}
    errors = []
    if not isinstance(entry, dict):
        return ['entry: expected object']
    company = entry.get('company')
    if not isinstance(company, str) or not re.fullmatch('\\d{4}', company):
        errors.append('company: expected four-digit company')
    if 'companies' in context and isinstance(company, str) and (company not in context['companies']):
        errors.append('company: unknown company')
    if 'currency' in entry and (not isinstance(entry['currency'], str) or not re.fullmatch('[A-Z]{3}', entry['currency'])):
        errors.append('currency: expected ISO currency')
    for field in ('posting_date', 'document_date'):
        if field in entry:
            try:
                value = entry[field]
                if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
                if field == 'posting_date' and (value < context.get('min_date', value) or value > context.get('max_date', value)):
                    errors.append(field + ': outside allowed period')
            except (ValueError, TypeError):
                errors.append(field + ': invalid YYYY-MM-DD date')
    lines = entry.get('lines')
    if not isinstance(lines, list) or not lines:
        return errors + ['lines: nonempty array required']
    total = 0
    seen_line_numbers = set()
    for index, line in enumerate(lines, 1):
        path = f'lines[{index}]'
        if not isinstance(line, dict):
            errors.append(path + ': expected object')
            continue
        if line.get('company', company) != company:
            errors.append(path + '.company: differs from entry company')
        number = line.get('line', index)
        if type(number) is not int or number < 1:
            errors.append(path + '.line: positive integer required')
        elif number in seen_line_numbers:
            errors.append(path + '.line: duplicate line number')
        else:
            seen_line_numbers.add(number)
        debit = line.get('debit')
        credit = line.get('credit')
        if type(debit) is not int or type(credit) is not int or debit < 0 or (credit < 0):
            errors.append(path + ': debit/credit must be nonnegative integer cents')
        else:
            total += debit - credit
            if debit and credit:
                errors.append(path + ': debit and credit both positive')
        if 'amount_doc' in line and type(line['amount_doc']) is not int:
            errors.append(path + '.amount_doc: integer cents required')
        account = line.get('account')
        if not isinstance(account, str) or not re.fullmatch('\\d{8}', account):
            errors.append(path + '.account: expected eight-digit account')
            continue
        if 'accounts' in context and account not in context['accounts']:
            errors.append(path + '.account: unknown account')
        partner = line.get('partner')
        if partner is not None and (not isinstance(partner, str) or not partner):
            errors.append(path + '.partner: nonempty string or null required')
        if line.get('assignment') is not None and (not isinstance(line['assignment'], str) or not line['assignment']):
            errors.append(path + '.assignment: nonempty string or null required')
        if is_open_item_account(account) and (not partner):
            errors.append(path + '.partner: required for open-item account')
        if account == '55300000' and partner != 'FACTOR-BAE':
            errors.append(path + '.partner: expected FACTOR-BAE')
        if account.startswith(('552', '2423', '1633')) and (not isinstance(partner, str) or not re.fullmatch('\\d{4}', partner) or partner == company):
            errors.append(path + '.partner: other group company required')
        if isinstance(partner, str) and partner and ('partners' in context) and (partner not in context['partners']):
            errors.append(path + '.partner: unknown partner')
        cost_center = line.get('cost_center')
        wbs = line.get('wbs')
        if cost_center and wbs:
            errors.append(path + ': cost_center and wbs are mutually exclusive')
        requires_cost_object = (account[0] in '267'
                                and not account.startswith('2423')
                                and account not in NO_COST_REQUIRED)
        if requires_cost_object and not cost_center and not wbs:
            errors.append(path + ': cost object required')
        for field, registry in (('cost_center', 'cost_centers'), ('wbs', 'wbs')):
            value = line.get(field)
            if value is not None and (not isinstance(value, str) or not value):
                errors.append(path + '.' + field + ': nonempty string or null required')
            if isinstance(value, str) and value and (registry in context):
                records = context[registry]
                if value not in records:
                    errors.append(path + '.' + field + ': unknown reference')
                elif isinstance(records, dict) and isinstance(records[value], dict) and (records[value].get('company', company) != company):
                    errors.append(path + '.' + field + ': belongs to another company')
        for field in ('currency',):
            if field in line and (not isinstance(line[field], str) or not re.fullmatch('[A-Z]{3}', line[field])):
                errors.append(path + '.currency: expected ISO currency')
    if total:
        errors.append(f'entry: unbalanced by {total} cents')
    return errors
