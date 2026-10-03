"""Observed M6 facts from originals/history/masters, never closing targets.

A development fixture extractor, not a production document engine or an LLM.
Observed periods retain shared Evidence and DocumentFacts; unknowns stay explicit.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
import csv
import re

from kalmora.close.contracts import digest, file_hash
from kalmora.close.rules import month_bounds, shift_month
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.money import RateTable, company_local_currency, round_cents

CONTINUOUS = {'ELEC', 'WATER', 'TELECOM', 'FUEL', 'TRAVEL', 'COURIER', 'OFFICE', 'LANDFILL',
              'PT_UTIL', 'MX_UTIL'}
EPISODIC = {'PROF_IND', 'PROF_CORP', 'PT_PROF', 'MX_PROF'}
PREPAID = {'INSURANCE', 'RENT_RUSTIC', 'RATING_GB'}


def ev(document, field, quote=None, page=None):
    return asdict(Evidence(document, field, page, quote))


def day(text):
    return date.fromisoformat(text) if '-' in text else date(*map(int, text.split('/')[::-1]))


def period(text):
    """Explicit full ranges and the history's dd/mm–dd/mm/yyyy convention."""
    match = re.search(r'(\d{2}/\d{2}/\d{4})\s*[–—-]\s*(\d{2}/\d{2}/\d{4})', text)
    if match:
        return day(match[1]), day(match[2]), match.group()
    match = re.search(r'(\d{2})/(\d{2})\s*[–—-]\s*(\d{2})/(\d{2})/(\d{4})', text)
    if match:
        d1, m1, d2, m2, year = map(int, match.groups())
        return date(year - (m1 > m2), m1, d1), date(year, m2, d2), match.group()
    return None


def cents_europe(text):
    return round_cents(Decimal(text.replace('.', '').replace(',', '.')) * 100)


def component_groups(journal):
    result = defaultdict(lambda: defaultdict(int))
    for row in journal.get('lines', []):
        if row['account'].startswith('6') and row['account'] not in {'66800000', '66210000'}:
            result[row.get('cost_center'), row.get('wbs')][row['account']] += row['debit'] - row['credit']
    return result


def daily_samples(histories, observations, account):
    """Sum separate invoices within a period; replace its estimate with actuals.

    The adapter supplies one observation per invoice business identity. Separate
    invoices for the same cost object and coverage period are additive, rather
    than competing samples from which the last invoice would overwrite the rest.
    Reissued historical estimates retain only the latest closing per reference.
    A posted invoice replaces a close estimate for the same coverage period.
    Retain the last three periods for the mean daily-rate estimator.
    """
    def group(records, basis):
        result = {}
        for sample in records:
            amount = sample['amounts'].get(account, 0)
            if amount <= 0:
                continue
            key = sample['start'], sample['end']
            item = result.setdefault(key, {'amount': 0, 'start': key[0], 'end': key[1],
                'evidence': sample['evidence'], 'source_evidence': [], 'sample_basis': basis})
            item['amount'] += amount
            item['source_evidence'].append(sample['evidence'])
        return result
    latest_estimates = {}
    for sample in sorted(histories, key=lambda s: s.get('closing', '')):
        identity = (sample.get('reference') or digest(sample['evidence']), sample['start'], sample['end'])
        latest_estimates[identity] = sample
    grouped = group(latest_estimates.values(), 'historical_close_estimate')
    grouped.update(group(observations, 'posted_invoice'))
    samples = sorted(grouped.values(), key=lambda s: (s['end'], s['start']), reverse=True)[:3]
    bases = {s['sample_basis'] for s in samples}
    return samples, next(iter(bases)) if len(bases) == 1 else 'mixed_observed_periods'


def monthly_coverage_observed(histories):
    """Monthly exposure needs repeated month-long service, not isolated events."""
    months = set()
    for observation in histories:
        start, end = day(observation['start']), day(observation['end'])
        first, last = month_bounds(start.strftime('%Y-%m'))
        if start == first and end == last:
            months.add(start.strftime('%Y-%m'))
    return len(months) >= 2


def build_facts(data, upstream, ledger, sources, diagnostics):
    phase = data.phase_dir
    first, closing = month_bounds(data.month)
    earliest = shift_month(first, -12)
    rates = RateTable(data.table('fx_rates'))
    vendors = {v['id']: v for v in data.table('vendors')}
    history = list(data.iter_journal())
    original = {e['id']: e for e in history}
    projected = list(ledger.iter_entries())
    ap_history = {a['doc_id']: a for a in data.table('ap_invoices')}
    received = {r['doc_id']: r for r in upstream['ap']}
    document_facts, cache = [], {}
    router = DocumentRouter(phase)

    def parse(relative):
        if relative not in cache:
            parsed = router.parse(relative)
            sources[relative] = parsed.source_sha256
            cache[relative] = parsed
        return cache[relative]

    def observed_period(document_id):
        candidates = []
        for path in sorted((phase / 'inbox/ap' / document_id).iterdir()):
            if path.suffix.lower() not in {'.pdf', '.xml'}:
                continue
            relative = path.relative_to(phase).as_posix()
            parsed = parse(relative)
            starts, ends = [], []
            for block in parsed.blocks:
                source_field = block.source_field or ''
                if 'InvoicingPeriod' in source_field and 'StartDate' in source_field:
                    starts.append((day(block.text), block))
                if 'InvoicingPeriod' in source_field and 'EndDate' in source_field:
                    ends.append((day(block.text), block))
                span = period(block.text)
                if span:
                    start, end, quote = span
                    evidence = ev(relative, source_field or block.id, quote, block.page)
                    candidates.append((start, end, evidence, parsed.source_sha256))
            for (start, b), (end, c) in zip(starts, ends):
                candidates.append((start, end, ev(relative, b.source_field + ' / ' + c.source_field,
                                                b.text + ' / ' + c.text), parsed.source_sha256))
        distinct = {(start, end) for start, end, _, _ in candidates}
        if len(distinct) != 1:
            diagnostics.append({'kind': 'unresolved_document_period', 'document': document_id,
                                'candidates': [(a.isoformat(), b.isoformat()) for a, b in distinct]})
            return None
        start, end, evidence, hashed = candidates[0]
        fact = DocumentFacts(hashed, 'm6_observed_period/v1', {
            'service_period': [Fact({'start': start.isoformat(), 'end': end.isoformat()}, Evidence(**evidence))]})
        document_facts.append(fact.to_dict())
        return start, end, evidence

    series = {}

    def get_series(company, vendor, cc, wbs):
        key = company, vendor, cc, wbs
        if key not in series:
            series[key] = {'series_id': 'service:' + digest(key)[:24], 'service_id': ':'.join(str(x) for x in key),
                'company': company, 'vendor': vendor, 'cost_center': cc, 'wbs': wbs,
                'po_required': vendors[vendor].get('po_required', False), 'history': [], 'observations': [],
                'received_coverage': [], 'evidence': []}
        return series[key]

    # Historical accruals are observations, never additional current postings.
    for e in history:
        if e.get('source') != 'CLOSE_ACCRUAL' or not earliest.isoformat() <= e['posting_date'] < first.isoformat():
            continue
        liability = [l for l in e['lines'] if l['account'] == '40090000']
        if len(liability) != 1 or liability[0].get('partner') not in vendors:
            continue
        vendor = liability[0]['partner']
        if vendors[vendor]['archetype'] not in CONTINUOUS | EPISODIC or vendors[vendor].get('po_required'):
            continue
        span = period(e.get('header_text', ''))
        if not span:
            diagnostics.append({'kind': 'history_period_missing', 'entry': e['id']})
            continue
        start, end, quote = span
        for (cc, wbs), amounts in component_groups(e).items():
            s = get_series(e['company'], vendor, cc, wbs)
            evidence = ev('erp/journal_entries.jsonl', e['id'] + '/header_text,lines', e['header_text'])
            s['history'].append({'start': start.isoformat(), 'end': end.isoformat(), 'amounts': dict(amounts),
                'reference': e['reference'], 'closing': e['posting_date'], 'evidence': evidence})
            s['evidence'].append(evidence)

    # Receipt coverage includes held/rejected/duplicate invoices, not just postings.
    prepaid_current, receipt_amounts, ap_receipts = [], set(), []
    for row in upstream['ap']:
        vendor = vendors.get(row.get('vendor_id'))
        if not vendor or row.get('document_type') != 'INVOICE':
            continue
        archetype = vendor['archetype']
        if archetype not in CONTINUOUS | EPISODIC | PREPAID or vendor.get('po_required'):
            continue
        observed = observed_period(row['doc_id'])
        if not observed:
            continue
        start, end, evidence = observed
        ap_receipts.append({"doc_id": row["doc_id"], "company": row["company"],
                            "vendor": row["vendor_id"], "decision": row["decision"],
                            "start": start.isoformat(), "end": end.isoformat(), "evidence": evidence,
                            "posted": bool(row.get("journal_entry"))})
        journal = row.get('journal_entry')
        if not journal:
            journal = {'lines': []}
            for l in row.get('lines', []):
                account = l.get('gl_account', l.get('account'))
                if account:
                    amount = rates.to_local(l['amount'], row['currency'], row['company'], row['invoice_date'])
                    journal['lines'].append(dict(l, account=account, debit=max(amount, 0), credit=max(-amount, 0)))
        groups = component_groups(journal)
        if not groups:
            candidates = [s for s in series.values()
                          if s["company"] == row["company"] and s["vendor"] == row["vendor_id"]]
            # A single source-backed historical cost object supports association;
            # several possible sites remain unknown rather than picking one.
            if len(candidates) == 1:
                groups[candidates[0]["cost_center"], candidates[0]["wbs"]] = {}
            else:
                diagnostics.append({"kind": "unresolved_received_service_allocation",
                                    "document": row["doc_id"], "blocking": bool(candidates),
                                    "company": row["company"], "vendor": row["vendor_id"],
                                    "evidence": evidence, "candidate_series": [s["series_id"] for s in candidates]})
                for s in candidates:
                    s["coverage_unknown"] = True
        business = row['company'], row['vendor_id'], re.sub(r'[^\w]', '', row.get('invoice_number') or '').upper()
        posted = row.get('decision') in {'POST', 'POST_PAYMENT_BLOCK'}
        first_arrival = posted and business not in receipt_amounts
        if posted:
            receipt_amounts.add(business)
        for (cc, wbs), amounts in groups.items():
            if archetype in CONTINUOUS | EPISODIC:
                s = get_series(row['company'], row['vendor_id'], cc, wbs)
                s['received_coverage'].append({'start': start.isoformat(), 'end': end.isoformat(),
                    'document': row['doc_id'], 'decision': row['decision'], 'evidence': evidence})
                if first_arrival:
                    s['observations'].append({'start': start.isoformat(), 'end': end.isoformat(),
                                              'amounts': dict(amounts), 'evidence': evidence})
                s['evidence'].append(evidence)
        if archetype in PREPAID and row.get('decision') in {'POST', 'POST_PAYMENT_BLOCK'} and journal and end > closing:
            components = [{'account': account, 'cost_center': cc, 'wbs': wbs, 'amount': amount}
                          for (cc, wbs), amounts in groups.items() for account, amount in amounts.items() if amount > 0]
            if components:
                prepaid_current.append({'company': row['company'], 'invoice': row['doc_id'],
                    'start': start.isoformat(), 'end': end.isoformat(), 'evidence': [evidence],
                    'components': components, 'total_local': sum(c['amount'] for c in components)})

    accruals = []
    previous_close = (first - timedelta(days=1)).isoformat()
    all_received_ids = set(ap_history) | set(received)
    projects = data.table('projects')
    for key, s in sorted(series.items(), key=lambda pair: repr(pair[0])):
        typ = vendors[s['vendor']]['archetype']
        histories = s.pop('history')
        observations = s.pop('observations')
        prior = [h for h in histories if h['closing'] == previous_close]
        active = bool(s['received_coverage'] or prior)
        for project in projects:
            if s['wbs'] and s['wbs'].startswith(project['id'] + '.') and project.get('planned_end', '9999') < first.isoformat():
                active = False
        if not active:
            diagnostics.append({'kind': 'inactive_service_not_extrapolated', 'series': s['series_id']})
            continue
        carry = [h['start'] for h in prior if h['reference'].removeprefix('ACCR-') not in all_received_ids]
        s['window_start'] = min([first.isoformat(), *carry])
        s['historical_references'] = sorted({h['reference'] for h in histories})
        accounts = sorted({a for h in histories + observations for a in h['amounts']})
        s['components'] = []
        if typ in EPISODIC:
            last_months = {h['closing'] for h in histories}
            current_points = [c for c in s['received_coverage'] if c['start'][:7] == data.month]
            if not monthly_coverage_observed(histories) or current_points:
                diagnostics.append({'kind': 'episodic_service_not_invented', 'series': s['series_id'],
                    'observed_closes': sorted(last_months), 'current_received': current_points,
                    'exposure': 'unknown additional service consumption',
                    'basis': 'monthly exposure requires repeated full-month service coverage; isolated event history does not prove current consumption'})
                continue
            s['method'] = 'recurring_unbilled_monthly_history'
            for account in accounts:
                grouped = defaultdict(int)
                for h in histories:
                    grouped[h['closing']] += h['amounts'].get(account, 0)
                samples = [{'amount': a, 'closing': c} for c, a in sorted(grouped.items()) if a > 0]
                if samples:
                    s['components'].append({'account': account, 'cost_center': s['cost_center'],
                                            'wbs': s['wbs'], 'samples': samples})
        else:
            s['method'] = 'mean_observed_daily_rate'
            for account in accounts:
                samples, sample_basis = daily_samples(histories, observations, account)
                if samples:
                    s['components'].append({'account': account, 'cost_center': s['cost_center'],
                                            'wbs': s['wbs'], 'samples': samples, 'sample_basis': sample_basis})
        if s['components']:
            accruals.append(s)

    prepaids = {(p['company'], p['invoice']): p for p in prepaid_current}
    by_prep = defaultdict(list)
    for e in history:
        if e.get('source') in {'PREPAID', 'CLOSE_PREPAID'} and e['posting_date'] <= closing.isoformat():
            by_prep[e['company'], e['reference']].append(e)
    for (company, reference), entries in sorted(by_prep.items()):
        balance = sum(l['debit'] - l['credit'] for e in entries for l in e['lines'] if l['account'] == '48000000')
        if not balance:
            continue
        invoice_id = reference.removeprefix('PREP-')
        invoice = ap_history.get(invoice_id)
        if not invoice:
            diagnostics.append({'kind': 'prepaid_invoice_missing', 'reference': reference, 'balance': balance})
            continue
        e = sorted(entries, key=lambda x: x['posting_date'])[0]
        match = re.search(r'\((\d+)/(\d+)\)', e['header_text'])
        if not match:
            raise ValueError('historical prepaid coverage is not observable')
        installment, count = map(int, match.groups())
        start = shift_month(day(e['posting_date']).replace(day=1), 1 - installment)
        end = shift_month(start, count) - timedelta(days=1)
        original_entry = original[invoice['journal_entry']]
        components = [{'account': account, 'cost_center': cc, 'wbs': wbs, 'amount': amount}
                      for (cc, wbs), amounts in component_groups(original_entry).items()
                      for account, amount in amounts.items() if amount > 0]
        prepaids[company, invoice_id] = {'company': company, 'invoice': invoice_id, 'start': start.isoformat(),
            'end': end.isoformat(), 'references': [reference], 'components': components,
            'total_local': sum(c['amount'] for c in components),
            'evidence': [ev('erp/journal_entries.jsonl', e['id'], e['header_text']),
                         ev('erp/ap_invoices.jsonl', invoice_id + '/journal_entry', invoice['journal_entry'])],
            'coverage_basis': 'historical installment number/term; not inferred from targets'}

    pending = []
    contracts = {c['id']: c for c in data.table('sales_contracts')}
    for row in upstream['ar_billing']:
        if row['expected'] != 'SKIP_PENDING_APPROVAL':
            continue
        if row['type'] != 'OBRA_CERTIFICATION':
            diagnostics.append({'kind': 'non_works_pending_item', 'billing_item': row['billing_item']})
            continue
        relative = 'inbox/ar/billing/' + row['billing_item'] + '/documento.pdf'
        parsed = parse(relative)
        text = '\n'.join(re.sub(r' +', ' ', b.text) for b in parsed.blocks)
        amounts = {}
        for key, label in [('cumulative', 'Certificado a origen'), ('previous', 'Certificado anterior'),
                           ('current', 'Importe de la presente certificación')]:
            match = re.search(re.escape(label) + r':\s*([\d.,]+)\s+([A-Z]{3})', text)
            if not match or match[2] != company_local_currency(row['company']):
                raise ValueError('unresolved certification amount/currency')
            amounts[key] = cents_europe(match[1])
        chapters = [{'number': int(m[1]), 'description': m[2], 'amount': cents_europe(m[3])}
                    for m in re.finditer(r'^(\d{2}) (.+?) ([\d.,]+) EUR\s*$', text, re.M)]
        month_match = re.search(r'Mes certificado:\s*(\d{4}-\d{2})', text)
        if not month_match or 'PENDIENTE DE APROBACIÓN' not in text or 'No facturar' not in text:
            raise ValueError('certification approval/month ambiguous')
        evidence = [ev(relative, 'certification', text.strip(), 1)]
        cert = dict(amounts, chapters=chapters, month=month_match[1], approved=False)
        document_facts.append(DocumentFacts(parsed.source_sha256, 'm6_certification_fixture/v1',
                             {'certification': [Fact(cert, Evidence(**evidence[0]))]}).to_dict())
        pending.append({'billing_item': row['billing_item'], 'company': row['company'], 'customer': row['customer'],
            'project': contracts[row['contract']]['project'], 'certification': cert,
            'billing_status': row['expected'], 'evidence': evidence})

    open_positions = ledger.open_items()
    doc_balances, local_only = defaultdict(int), defaultdict(list)
    for e in projected:
        for l in e['lines']:
            key = e['company'], l['account'], l.get('partner'), l.get('assignment')
            currency = l.get('currency', e.get('currency', company_local_currency(e['company'])))
            if currency != company_local_currency(e['company']):
                signed = (1 if l['debit'] else -1) * abs(l.get('amount_doc', 0))
                if 'FX' not in e.get('source', ''):
                    doc_balances[*key, currency] += signed
            elif l['account'].startswith(('400', '410', '403', '1633', '552')):
                local_only[key].append(e.get('id', e.get('reference')))
    foreign_ap = {}
    for a in list(ap_history.values()) + [dict(r, vendor=r.get('vendor_id'), number=r.get('invoice_number'))
                                          for r in upstream['ap'] if r.get('journal_entry')]:
        company = a['company']
        if a.get('currency') == company_local_currency(company) or not a.get('vendor'):
            continue
        if str(a.get('kind') or a.get('document_type') or 'invoice').lower() not in {'invoice', 'credit_note'}:
            continue
        journal = a.get('journal_entry')
        journal = original.get(journal, {}) if isinstance(journal, str) else journal or {}
        liabilities = [l for l in journal.get('lines', []) if l['account'] in {'40000000', '41000000', '40300000'}
                       and l.get('partner') == a['vendor']]
        for l in liabilities:
            key = company, l['account'], a['vendor'], l.get('assignment')
            foreign_ap.setdefault(key, (a['doc_id'], a['currency']))
    fx_positions = []
    for key, (doc_id, currency) in sorted(foreign_ap.items(), key=lambda pair: repr(pair[0])):
        local = open_positions.get(key, 0)
        if not local:
            continue
        principal = doc_balances[*key, currency]
        if not principal:
            diagnostics.append({'kind': 'foreign_local_residual', 'item': 'AP:' + doc_id, 'local': local,
                                'principal': 0, 'action': 'not fabricated as foreign principal'})
            continue
        fx_positions.append({'company': key[0], 'account': key[1], 'partner': key[2], 'assignment': key[3],
            'item': 'AP:' + doc_id, 'currency': currency, 'document_signed': principal,
            'evidence': [ev('erp/journal_entries.jsonl', f'position:{key}',
                            'signed document principal from foreign-currency postings after dependency adjustments')],
            'local_only_transactions': local_only[key]})
    loan = data.table('intercompany_agreements')['loan']
    borrower = loan['borrower']
    for account in ('16330000', '55200000'):
        key = borrower, account, loan['lender'], None if account == '16330000' else loan['id']
        currencies = {k[-1] for k, value in doc_balances.items() if k[:4] == key and value}
        if len(currencies) != 1:
            raise ValueError('loan/interests require a unique historical foreign principal')
        currency = currencies.pop()
        fx_positions.append({'company': borrower, 'account': account, 'partner': loan['lender'], 'assignment': loan['id'],
            'item': 'GL:' + account, 'currency': currency, 'document_signed': doc_balances[*key, currency],
            'filter_assignment': account != '16330000',
            'assignment_binding': 'principal originally unassigned; unique agreement from original history',
            'evidence': [ev('erp/intercompany_agreements.json', 'loan', loan['id']),
                         ev('erp/journal_entries.jsonl', f'position:{key}', 'document amount including owned IC corrections')]})
    for bank in data.table('bank_accounts'):
        if bank['currency'] == company_local_currency(bank['company']):
            continue
        relative = f"bank/{bank['id']}/{data.month}.csv"
        sources[relative] = file_hash(phase / relative)
        bank_rows = list(csv.reader((phase / relative).read_text(encoding='utf-8-sig').splitlines()))
        data_rows = [r for r in bank_rows[2:] if r and r[-1].strip()]
        if not data_rows:
            raise ValueError('foreign bank statement closing balance missing')
        final_value = data_rows[-1][-1]
        principal = round_cents(Decimal(final_value.replace(',', '')) * 100)
        fx_positions.append({'company': bank['company'], 'account': bank['gl_account'], 'partner': None,
            'assignment': None, 'filter_partner': False, 'filter_assignment': False,
            'item': 'BANK:' + bank['id'], 'currency': bank['currency'], 'document_signed': principal,
            'evidence': [ev(relative, 'last/Saldo', final_value)], 'principal_basis': 'original statement closing balance'})

    return {'accruals': accruals, 'ap_receipts': ap_receipts,
            'prepaids': list(prepaids.values()), 'pending_certifications': pending,
            'fx_positions': fx_positions, 'document_facts': document_facts,
            'billed_invoices': [dict(r['invoice'], company=r['company'], customer=r['customer'], id=r['journal_entry']['reference']) for r in upstream['ar_billing'] if r.get('invoice')],
            'ageing_evidence': [ev('erp/ar_invoices.jsonl', 'due_date'), ev('erp/customers.jsonl', 'kind,insolvency'),
                                ev('erp/journal_entries.jsonl', 'open items after cash applications')],
            'ic_owned_services': [], 'coverage_limitations': diagnostics,
            'impairment_rounding': 'truncate',
            'impairment_rounding_evidence': 'historical 50% provisions truncate half cents (e.g. compare open-invoice odd cents with original 490 balances); not a target tolerance',
            'estimation_policy': 'last three distinct periods; additive invoice costs within period replace same-period estimates; mean daily rate; no targets read'}
