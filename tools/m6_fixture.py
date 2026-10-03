#!/usr/bin/env python3
"""Build explicitly simulated M1-M5 handoffs. Never read close/balance targets."""
from __future__ import annotations
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
import re
import sys

from kalmora.close.contracts import SCHEMA, Handoff, encoded, file_hash, seal
from kalmora.close.projection import project
from kalmora.close.rules import month_bounds
from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.money import company_local_currency
from kalmora.validation import validate_entry

ALLOWED = frozenset({'ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic'})
TASKS = {'ap': 'ap_documents', 'ar_billing': 'ar_billing_items', 'bank_rec': 'bank_accounts',
         'ar_cash': 'ar_receipts', 'ic': 'intercompany'}
IDENTITIES = {'ap': 'doc_id', 'ar_billing': 'billing_item', 'bank_rec': 'account', 'ar_cash': 'bank_line'}


def load_upstream(phase: Path, producer: str) -> tuple[list[dict], str]:
    if producer not in ALLOWED:
        raise ValueError('only the five upstream dependency fixtures are permitted')
    path = phase / 'golden' / (producer + '.jsonl')
    if path.resolve() != phase.resolve() / 'golden' / (producer + '.jsonl'):
        raise ValueError('fixture may not redirect outside the permitted area')
    data = [json.loads(row, parse_float=Decimal) for row in path.read_text().splitlines() if row.strip()]
    return data, file_hash(path)


def evidence(document: str, field: str, quote: str | None = None) -> dict:
    return asdict(Evidence(document, field, quote=quote))


def ap_key(company, vendor, number):
    normalized = re.sub(r'[^\w]', '', str(number)).upper()
    return f'ap:{company}:{vendor}:{normalized}'


def wrapper(company, reference, lines, day, source):
    return {'company': company, 'doc_type': 'SA', 'posting_date': day, 'document_date': day,
            'reference': reference, 'source': source, 'currency': company_local_currency(company),
            'header_text': reference, 'lines': deepcopy(lines)}


def normalize(journal, context, diagnostics):
    """Enrich missing metadata explicitly. Never change a debit or credit."""
    result = deepcopy(journal)
    company = result['company']
    for i, row in enumerate(result['lines'], 1):
        row.setdefault('company', company)
        row.setdefault('line', i)
        row.setdefault('currency', company_local_currency(company))
        row.setdefault('amount_doc', row['debit'] or row['credit'])
        for key in ('partner', 'assignment', 'cost_center', 'wbs', 'tax_code'):
            row.setdefault(key, None)
        if row['account'] == '40700000' and not row['partner'] and context.get('vendor_id'):
            row['partner'] = context['vendor_id']
            diagnostics.append({'kind': 'metadata_enrichment', 'event': context.get('doc_id'),
                'line': i, 'field': 'partner', 'value': row['partner'],
                'basis': 'original AP resolved vendor; policy requires vendor on 407'})
    errors = validate_entry(result)
    if errors:
        raise ValueError(f"dependency {result.get('reference')} invalid: {errors}")
    return result


def build(phase: Path, *, loader=None, provenance="golden_fixture",
          coverage_overrides=None, owned_postings=None) -> dict:
    """Use the same builder for explicit fixtures and audited producer inputs."""
    if provenance not in {"golden_fixture", "real"}:
        raise ValueError("unknown dependency provenance")
    if provenance == "real" and (not coverage_overrides or "ic" not in coverage_overrides):
        raise ValueError("real IC requires positive reconciliation coverage")
    loader = loader or load_upstream
    data = PhaseData(phase)
    month = data.month
    _, closing = month_bounds(month)
    entries = list(data.iter_journal())
    original = {e['id']: e for e in entries}
    references = defaultdict(list)
    for e in entries:
        references[e['company'], e.get('reference')].append(e)
    sources = {p.relative_to(phase).as_posix(): file_hash(p) for folder in ('erp', 'tasks')
               for p in sorted((phase / folder).iterdir()) if p.is_file()}
    bundle = {'schema': SCHEMA, 'phase': phase.name, 'month': month, 'closing_date': closing.isoformat(),
        'sources': sources, 'dependencies': [], 'recorded_events': [],
        'facts': {'accruals': [], 'prepaids': [], 'pending_certifications': [], 'fx_positions': []},
        'adapter': {'version': 'm6_handoff/v2',
                    'integration': 'real_upstream' if provenance == 'real' else 'simulated', 'diagnostics': []}}
    diagnostics = bundle['adapter']['diagnostics']
    for a in data.table('ap_invoices'):
        if a.get('journal_entry') in original:
            bundle['recorded_events'].append({'business_key': ap_key(a['company'], a['vendor'], a['number']),
                                             'journal_ids': [a['journal_entry']]})
    upstream = {}
    for producer in ('ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic'):
        rows, hashed = loader(phase, producer)
        upstream[producer] = rows
        task = data.table('tasks/' + TASKS[producer])
        expected = ['/'.join(pair) for pair in task['pairs']] if producer == 'ic' else task
        # An IC fixture exception report is not real positive reconciliation evidence.
        observed = expected if producer == 'ic' else [r[IDENTITIES[producer]] for r in rows]
        dependency = {'producer': producer, 'phase': phase.name, 'month': month,
            'provenance': provenance, 'source_sha256': hashed, 'complete': set(expected) == set(observed),
            'coverage': {'expected': expected, 'observed': observed,
              'mode': 'complete_fixture_exception_report' if producer == 'ic' else 'one_result_per_task',
              'limitations': ['absence of an IC exception is a fixture assumption, not real reconciliation evidence'] if producer == 'ic' else []},
            'postings': [], 'results': rows}
        if coverage_overrides and producer in coverage_overrides:
            override = coverage_overrides[producer]
            dependency['coverage'] = override['coverage']
            dependency['complete'] = override['complete']
        if owned_postings is not None and producer in owned_postings:
            dependency['postings'] = deepcopy(owned_postings[producer])
            bundle['dependencies'].append(dependency)
            continue
        postings = dependency['postings']

        def add(journal, key, stage, source_index, context=None, recorded_ids=()):
            journal = normalize(journal, context or {}, diagnostics)
            postings.append({'event_id': key, 'business_key': key, 'stage': stage,
                'journal_entry': journal, 'recorded_ids': list(recorded_ids),
                'evidence': [evidence(f'{provenance}:{producer}.jsonl@{hashed}', str(source_index))]})

        for index, row in enumerate(rows):
            if producer == 'ap':
                journal = row.get('journal_entry')
                if journal:
                    key = ap_key(row['company'], row['vendor_id'], row['invoice_number'])
                    recorded_ids = [journal['id']] if journal.get('id') in original else []
                    add(journal, key, 'ap.post', index, row, recorded_ids)
            elif producer == 'ar_billing':
                journal = row.get('journal_entry')
                if journal:
                    key = f"billing:{row['company']}:{row['billing_item']}"
                    ids = [journal['id']] if journal.get('id') in original else []
                    add(journal, key, 'billing.post', index, row, ids)
            elif producer == 'bank_rec':
                for j, adjustment in enumerate(row.get('adjustments', [])):
                    ref = adjustment['ref']
                    match = re.search(r'\d{4}-\d{2}-\d{2}', ref)
                    candidates = references[row['company'], ref]
                    day = match.group() if match else (candidates[0]['posting_date'] if candidates else closing.isoformat())
                    if day[:7] != month:
                        day = closing.isoformat()
                    if not match and not candidates:
                        diagnostics.append({'kind': 'projection_date_assumption', 'event': ref,
                            'date': day, 'basis': 'fixture has local adjustment but no event date; within-phase projection at close'})
                    journal = wrapper(row['company'], ref, adjustment['lines'], day, 'M6_DEP_BANK')
                    add(journal, f"bank:{row['account']}:{ref}:{adjustment['category']}", 'bank.adjust', f'{index}/adjustments/{j}')
            elif producer == 'ar_cash':
                if row.get('adjustment'):
                    journal = wrapper(row['company'], row['bank_line'], row['adjustment'], row['date'], 'M6_DEP_CASH')
                    add(journal, f"receipt:{row['company']}:{row['bank_line']}", 'cash.apply', index)
            elif producer == 'ic':
                if not row.get('adjustment'):
                    diagnostics.append({'kind': 'upstream_owner', 'event': row.get('detail'),
                                        'owner': 'bank.adjust', 'reason': row['cause']})
                    continue
                lines = deepcopy(row['adjustment'])
                company = row.get('responsible_company', row.get('responsible', lines[0]['company']))
                if isinstance(company, list):
                    raise ValueError('multi-company IC adjustment requires separate balanced journals')
                if row['cause'] == 'INTEREST_DAY_COUNT':
                    loan = data.table('intercompany_agreements')['loan']
                    currencies = {l.get('currency') for e in entries if e['company'] == loan['borrower']
                                  for l in e['lines'] if l.get('assignment') == loan['id']
                                  and l.get('currency') != company_local_currency(e['company'])}
                    if len(currencies) != 1:
                        raise ValueError('IC agreement currency is not uniquely supported by historical postings')
                    loan_currency = currencies.pop()
                    for l in lines:
                        l['currency'] = loan_currency
                        l['amount_doc'] = abs(row['amount'])
                    diagnostics.append({'kind': 'document_amount_enrichment', 'event': loan['id'],
                        'amount': abs(row['amount']), 'currency': loan_currency,
                        'basis': 'IC correction amount is in agreement currency; lines are local'})
                reference = re.search(r'(?:IC\d+-\d+-\d+|CP\d+)', row.get('detail', ''))
                source_event = reference.group() if reference else row.get('account', '')
                key = f"ic:{month}:{'/'.join(row['pair'])}:{row['cause']}:{source_event}"
                journal = wrapper(company, key, lines, closing.isoformat(), 'M6_DEP_IC')
                add(journal, key, 'ic.' + row['cause'].lower(), index)
        bundle['dependencies'].append(dependency)
    from m6_sources import build_facts
    preliminary = Handoff.from_dict(seal(bundle))
    projection = project(entries, preliminary)
    bundle['facts'] = build_facts(data, upstream, projection.pre_close, bundle['sources'], diagnostics)
    result = seal(bundle)
    Handoff.from_dict(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    def guard(event, arguments):
        if event == 'open' and isinstance(arguments[0], (str, bytes)):
            name = Path(arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0])
            if 'golden' in name.parts and name.name not in {p + '.jsonl' for p in ALLOWED}:
                raise PermissionError('M6 fixture adapter cannot access close or balance targets')
            if name.name.startswith('trial_balance_'):
                raise PermissionError('M6 fixture adapter cannot access balance targets')
    sys.addaudithook(guard)
    value = build(args.phase.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded(value))
    print(json.dumps({'integration': 'simulated', 'payload_sha256': value['payload_sha256'],
                      'facts': {k: len(v) for k, v in value['facts'].items() if isinstance(v, list)},
                      'diagnostics': len(value['adapter']['diagnostics'])}))


if __name__ == '__main__':
    main()
