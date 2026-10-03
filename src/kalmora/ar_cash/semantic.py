"""Optional evidence-backed review of unresolved receipts using shared M1 contracts.

Semantic selection is an association proposal, never authority to post a payment.
The deterministic run remains unchanged; consumers persist the returned audit.
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..data import PhaseData
from ..documents.contracts import (Candidate, ParsedBlock, ParsedDocument,
                                   ResolutionRequest, SemanticResolver, digest)
from ..documents.replay import validate_resolution
from ..money import integer
from .engine import (AR_ACCOUNTS, ArCashRun, _Candidate, _ReceivableTimeline,
                     _bank_line_index, _invoice_index, build_ar_cash)


@dataclass(frozen=True)
class ReviewedCash:
    run: ArCashRun
    reviews: tuple[dict, ...]


async def review_ar_cash(data: PhaseData, *, resolver: SemanticResolver | None = None,
                         max_candidates: int = 20, use_preparsed: bool = False,
                         normalized_dir: Path | None = None) -> ReviewedCash:
    """Build cash decisions then review unresolved, date-filtered candidates.

    No provider is instantiated or called unless the caller supplies a resolver.
    A bounded audit records source/request hashes, candidates, selection evidence
    or explicit abstention. The source is the original bank JSONL row, not a
    generated summary. Neither scores nor golden are inputs to this interface.
    """
    if integer(max_candidates, 'candidate limit') < 1:
        raise ValueError('positive candidate limit required')
    run = build_ar_cash(data, use_preparsed=use_preparsed, normalized_dir=normalized_dir)
    bank, accounts = _bank_line_index(data)
    invoices = _invoice_index(data)
    customers = {str(row['id']): row for row in data.table('customers')}
    timeline = _ReceivableTimeline(data.iter_journal())
    reviews = []
    ordered = sorted(run.results, key=lambda r: (bank[r.row['bank_line']][0]['value_date'],
                     bank[r.row['bank_line']][0]['booking_date'], r.row['bank_line']))
    for result in ordered:
        row = result.row
        receipt_id = row['bank_line']
        line, account_id = bank[receipt_id]
        company = str(accounts[account_id]['company'])
        day, currency = str(line['value_date']), str(line['currency'])
        timeline.advance(day)
        if not row['adjustment']:
            pool = [candidate for customer in customers
                    if row['customer'] is None or customer == row['customer']
                    for candidate in timeline.candidates(invoices, company, customer, day)
                    if candidate.invoice.currency == currency and candidate.balance > 0
                    and candidate.invoice.due_date <= day]
            pool.sort(key=lambda c: c.invoice.id)
            audit = {'bank_line': receipt_id, 'accounting_applied': False,
                     'candidates': [dict(asdict(c.invoice), account=c.account, balance=c.balance)
                                    for c in pool]}
            if not pool or len(pool) > max_candidates or resolver is None:
                audit['status'] = ('NO_CANDIDATES' if not pool else 'CANDIDATE_LIMIT'
                                   if len(pool) > max_candidates else 'RESOLVER_UNAVAILABLE')
            else:
                relative = f'bank/{account_id}/{data.month}.lines.jsonl'
                raw = (data.phase_dir / relative).read_bytes()
                blocks = [text for text in raw.decode('utf-8').splitlines()
                          if text.strip() and json.loads(text).get('bank_line') == receipt_id]
                if len(blocks) != 1:
                    raise ValueError('semantic review requires one original bank source row')
                document = ParsedDocument(relative, digest(raw), 'application/x-ndjson',
                    'ar-cash-bank-row-v1', (ParsedBlock(receipt_id, blocks[0]),))
                candidates = tuple(Candidate(c.invoice.id, dict(asdict(c.invoice),
                    name=customers[c.invoice.customer].get('name', ''),
                    account=c.account, balance=c.balance)) for c in pool)
                request = ResolutionRequest(document, candidates, context={
                    'bridge_version': 'ar-cash-review-v1', 'bank_line': receipt_id,
                    'receipt_date': day, 'amount': line['amount'],
                    'hard_constraints': dict(company=company, currency=currency,
                        **({'customer': row['customer']} if row['customer'] else {})),
                    'accounting_rule': 'A ranking does not prove invoice payment; association review only.'})
                before = request.sha256
                resolution = await resolver.resolve(request)
                if request.sha256 != before:
                    raise ValueError('semantic resolver changed its bounded request')
                validate_resolution(request, resolution)
                audit.update(status=resolution.status, source=document.to_dict(),
                             request_sha256=before, request_context=request.context,
                             request_candidates=[asdict(c) for c in request.candidates],
                             resolution=resolution.to_dict())
            reviews.append(audit)
        # Earlier deterministic applications reduce availability for later reviews.
        for adjustment in row['adjustment']:
            if adjustment['account'] not in AR_ACCOUNTS:
                continue
            assignment = str(adjustment.get('assignment', ''))
            amount = adjustment['credit'] - adjustment['debit']
            if assignment in invoices:
                timeline.apply(_Candidate(invoices[assignment], adjustment['account'], 0), amount)
            else:
                timeline.apply_open_item(company, adjustment['account'],
                    str(adjustment.get('partner', '')), assignment, amount)
    return ReviewedCash(run, tuple(reviews))
