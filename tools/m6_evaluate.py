#!/usr/bin/env python3
"""Evaluation-only: verify frozen hashes BEFORE opening any close/balance target.

The solver never imports this tool. Detail is deliberately stricter than the
shared aggregate comparator. Representation differences remain visible.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from kalmora.close.contracts import file_hash
from kalmora.data import PhaseData
from kalmora.evaluation.compare import compare_close
from kalmora.evaluation.scorer import load_scorer
from kalmora.evaluation.structure import check_structure
from kalmora.evaluation.boundary import check_boundary
from kalmora.money import company_local_currency
from kalmora.validation import validate_entry


def rows(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def verify_freeze(output):
    freeze = json.loads((output / 'freeze.json').read_text())
    if freeze.get('frozen_before_evaluation') is not True:
        raise ValueError('output was not frozen')
    for name, hashed in freeze['files'].items():
        if file_hash(output / name) != hashed:
            raise ValueError('frozen output changed: ' + name)
    return freeze


def line_totals(group, strict=False):
    totals = defaultdict(int)
    doc = defaultdict(int)
    for row in group:
        entry = row['journal_entry']
        for line in entry['lines']:
            dims = (row['company'], line['account'], line.get('partner'), line.get('cost_center'),
                    line.get('wbs'), line.get('tax_code'))
            if strict:
                dims += (line.get('assignment'), line.get('currency', entry.get('currency')))
            signed = line['debit'] - line['credit']
            totals[dims] += signed
            doc[dims] += (1 if signed > 0 else -1 if signed < 0 else 0) * line.get('amount_doc', abs(signed))
    return totals, doc


def differences(gold, actual):
    return [{'dimensions': list(key), 'expected': gold.get(key, 0), 'actual': actual.get(key, 0),
             'delta': actual.get(key, 0) - gold.get(key, 0)}
            for key in sorted(set(gold) | set(actual), key=repr) if gold.get(key, 0) != actual.get(key, 0)]


def trial_balance(path, jsonl=False):
    data = rows(path) if jsonl else json.loads(path.read_text())
    return {(r['company'], r['account']): r['balance'] for r in data}


def evaluate(phase, output, report_dir):
    output, phase, report_dir = output.resolve(), phase.resolve(), report_dir.resolve()
    if report_dir.is_relative_to(output) or report_dir.is_relative_to(phase):
        raise ValueError('evaluation must not alter the freeze or originals')
    freeze = verify_freeze(output)
    goldpath = phase / 'golden/close.jsonl'
    gold, actual = rows(goldpath), rows(output / 'close.jsonl')
    scorer, scorer_identity = load_scorer(phase.parent / 'score.py')
    shared = compare_close(scorer, gold, actual)
    G, A = defaultdict(list), defaultdict(list)
    for r in gold: G[scorer.close_key(r)].append(r)
    for r in actual: A[scorer.close_key(r)].append(r)
    detail = []
    sign_errors, date_errors, invariant_errors = [], [], []
    for key in sorted(set(G) | set(A), key=repr):
        g, a = G.get(key, []), A.get(key, [])
        expected, amount = sum(r.get('amount', 0) for r in g), sum(r.get('amount', 0) for r in a)
        gl, gd = line_totals(g, strict=True); al, ad = line_totals(a, strict=True)
        ge, _ = line_totals(g); ae, _ = line_totals(a)
        if expected and amount and (expected > 0) != (amount > 0):
            sign_errors.append(list(key))
        detail.append({'key': list(key), 'gold_rows': len(g), 'actual_rows': len(a),
            'expected_amount': expected, 'actual_amount': amount, 'delta': amount - expected,
            'strict_line_differences': differences(gl, al), 'document_amount_differences': differences(gd, ad),
            'economic_line_differences': differences(ge, ae),
            'gold_line_count': sum(len(r['journal_entry']['lines']) for r in g),
            'actual_line_count': sum(len(r['journal_entry']['lines']) for r in a),
            'gold_periods': [r.get('period') for r in g],
            'actual_references': [r['journal_entry'].get('reference') for r in a]})
    closing = freeze['month'] + '-' + str(__import__('calendar').monthrange(*map(int, freeze['month'].split('-')))[1])
    phase_data = PhaseData(phase)
    companies = {c['code'] for c in phase_data.table('companies')}
    context = {'companies': companies,
               'accounts': {a['account'] for a in phase_data.table('chart_of_accounts')},
               'partners': companies | {a['id'] for name in ('vendors', 'customers') for a in phase_data.table(name)},
               'cost_centers': {c['id']: c for c in phase_data.table('cost_centers')},
               'wbs': {w['id']: dict(w, company=p['company']) for p in phase_data.table('projects') for w in p['wbs']},
               'min_date': closing, 'max_date': closing}
    for i, r in enumerate(actual, 1):
        e = r['journal_entry']
        for err in validate_entry(e, context): invariant_errors.append({'row': i, 'error': err})
        if e.get('posting_date') != closing or e.get('document_date') != closing:
            date_errors.append(i)
        account = {'ACCRUAL': '40090000', 'PREPAID': '48000000', 'WIP_REVENUE': '43090000',
                   'BAD_DEBT': '49000000', 'DOUBTFUL_RECLASS': '43600000'}.get(r['type'])
        if account:
            balance = sum(l['debit'] - l['credit'] for l in e['lines'] if l['account'] == account)
            target = -r['amount'] if r['type'] in {'ACCRUAL', 'BAD_DEBT'} else r['amount']
            if balance != target: invariant_errors.append({'row': i, 'error': 'amount does not tie to control account'})
        if r['type'] == 'FX_REVAL':
            foreign = [l for l in e['lines'] if l.get('currency') != company_local_currency(r['company'])]
            if len(foreign) != 1 or foreign[0].get('amount_doc') != 0:
                invariant_errors.append({'row': i, 'error': 'FX changed document principal'})
    original = trial_balance(output / 'erp_original_balance.json')
    pre = trial_balance(output / 'pre_m6_balance.json')
    final = trial_balance(output / 'final_balance.json')
    truthpath, recordedpath = phase / 'golden/trial_balance_truth.jsonl', phase / 'golden/trial_balance_recorded.jsonl'
    truth, recorded = trial_balance(truthpath, True), trial_balance(recordedpath, True)
    gold_close = defaultdict(int)
    for r in gold:
        for l in r['journal_entry']['lines']:
            gold_close[r['company'], l['account']] += l['debit'] - l['credit']
    balance_detail = []
    company_totals = defaultdict(lambda: {'final_abs_difference': 0, 'upstream_abs_difference': 0,
                                         'm6_abs_difference': 0, 'original_abs_difference': 0,
                                         'different_final_accounts': 0})
    for key in sorted(set(original) | set(pre) | set(final) | set(truth) | set(recorded)):
        expected_pre = truth.get(key, 0) - gold_close[key]
        before_delta = pre.get(key, 0) - expected_pre
        m6_delta = final.get(key, 0) - pre.get(key, 0) - gold_close[key]
        delta = final.get(key, 0) - truth.get(key, 0)
        assert delta == before_delta + m6_delta
        original_delta = original.get(key, 0) - recorded.get(key, 0)
        t = company_totals[key[0]]
        for name, value in [('final', delta), ('upstream', before_delta), ('m6', m6_delta), ('original', original_delta)]:
            t[name + '_abs_difference'] += abs(value)
        t['different_final_accounts'] += bool(delta)
        if any((delta, before_delta, m6_delta, original_delta)):
            balance_detail.append({'company': key[0], 'account': key[1], 'currency': company_local_currency(key[0]),
                'original': original.get(key, 0), 'recorded_reference': recorded.get(key, 0),
                'pre_m6': pre.get(key, 0), 'expected_pre_m6': expected_pre,
                'm6_movement': final.get(key, 0) - pre.get(key, 0), 'reference_m6_movement': gold_close[key],
                'final': final.get(key, 0), 'truth': truth.get(key, 0),
                'upstream_delta': before_delta, 'm6_delta': m6_delta, 'final_delta': delta})
    decisions = rows(output / 'close_decisions.jsonl')
    sensitivity = []
    for d in decisions:
        if d.get('type') == 'ACCRUAL' and d.get('action') == 'post':
            sensitivity.append({'company': d['company'], 'vendor': d['vendor'], 'series_id': d['series_id'],
                 'amount': d['amount'], 'low': sum(e['low'] - e.get('existing_unreversed_accrual', 0) for e in d['estimates']),
                 'high': sum(e['high'] - e.get('existing_unreversed_accrual', 0) for e in d['estimates']),
                 'gaps': d['gaps'], 'cost_center': d.get('cost_center'), 'wbs': d.get('wbs'), 'estimates': d['estimates']})
    type_counts = {typ: {'gold_rows': sum(r['type'] == typ for r in gold),
                        'actual_rows': sum(r['type'] == typ for r in actual),
                        'gold_keys': sum(k[0] == typ for k in G), 'actual_keys': sum(k[0] == typ for k in A)}
                   for typ in sorted({r['type'] for r in gold + actual})}
    summary = {'integration': 'simulated', 'acceptance': 'NOT_ACCEPTED_REAL_FLOW', 'gate_171': 'OPEN',
        'evaluated_at': datetime.now(timezone.utc).isoformat(), 'frozen_at': freeze['frozen_at'],
        'freeze_sha256': file_hash(output / 'freeze.json'), 'close_sha256': freeze['files']['close.jsonl'],
        'reference_hashes': {p.name: file_hash(p) for p in (goldpath, truthpath, recordedpath)},
        'scorer': scorer_identity, 'official_close_score': scorer.score_close(gold, actual),
        'counts': type_counts, 'aggregate_keys': {'gold': len(G), 'actual': len(A)},
        'exact_financial_amount_keys': sum(bool(d['delta'] == 0 and d['gold_rows'] and d['actual_rows']) for d in detail),
        'economic_exact_keys': sum(not d['economic_line_differences'] for d in detail),
        'strict_exact_keys': sum(not d['strict_line_differences'] and not d['document_amount_differences'] for d in detail),
        'structural_errors': check_structure({'close': actual}), 'journal_invariant_errors': invariant_errors,
        'amount_sign_errors': sign_errors, 'date_errors': date_errors, 'boundary': check_boundary(),
        'balances_by_company': {c: dict(t, currency=company_local_currency(c)) for c, t in sorted(company_totals.items())},
        'limitations': freeze['estimation_limitations'],
        'interpretation': ['Aggregate tolerance is not exact accounting acceptance.',
            'Strict comparison includes assignment and document-currency representation differences.',
            'FX local-only movement is intentionally document_currency with amount_doc=0, unlike local-currency reference serialization.',
            'Accruals use stable service identities when the missing invoice identity is unobserved.',
            'Sensitivity is historical-rate dispersion, not confidence bounds; missing service evidence is separate.',
            'Absolute balance differences are two-sided L1 norms, not one-sided P&L or cash losses. Do not add currencies.']}
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [('summary', summary), ('shared_compare_close', shared), ('detail', detail),
                         ('balance_differences', balance_detail), ('accrual_sensitivity', sensitivity)]:
        (report_dir / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    verify_freeze(output)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('phase', 'output', 'report-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    s = evaluate(a.phase, a.output, a.report_dir)
    print(json.dumps({k: s[k] for k in ('official_close_score', 'counts', 'aggregate_keys', 'structural_errors',
                                      'journal_invariant_errors', 'date_errors', 'balances_by_company')}, indent=2))
