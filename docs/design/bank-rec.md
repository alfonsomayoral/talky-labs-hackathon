# Bank reconciliation (M3): design record

Working record for milestone M3 ("Bancos / `bank_rec.jsonl`", issues #66–#77, epics #12–#14). Questions are written before they are researched; decisions are appended under each question. Status: **design in progress, no product code touched.**

Goal (from the brief): analyse the whole problem and its edge cases, and propose an implementation plan for the bank reconciliation of the 12 bank accounts, ending in typed in-memory results before any JSONL serialization.

## Known facts (observed, not decided)

Sources: `participant/POLITICAS_CONTABLES.md` §4, `FORMATO_ENTREGA.md` (Bank Rec), `score.py`, `phase_dev/{tasks,bank,erp}`, `knowledge/reference/bank-rec-data-model.html`, the issue bodies #12–#14 and #66–#77, `src/kalmora/`. No golden file was read; counts quoted from the issues and the tracked reference are labelled as such.

- **Deliverable:** one row per bank account of `tasks/bank_accounts.json` (12): `account`, `company`, `matches[{bank_lines, book_lines}]`, `unmatched_bank[{bank_line, category}]`, `unmatched_book[{book_line, category}]`, `adjustments[{category, lines}]`. `book_line` is `<entry id>#<line number>`.
- **Scoring per account** (`score.py`): 0.45 × F1 of (bank_line, book_line) pairs, 0.20 × F1 of unmatched keys, 0.15 × category accuracy over the reference unmatched keys, 0.20 × journal-line match of all adjustment lines (company explicit, ±2 cents). Weight of the module in the total: 0.20. The `category` of a match, the adjustment `category`/`ref` and the amounts of matches are not scored directly.
- **Milestone reference** (issue text): 224 matched groups (216 1:1, 8 grouped), 61 unmatched bank lines, 9 unmatched book lines, 56 adjustment groups; five FX differences and one loan interest explain six matches with different amounts; one adjustment group can serve several unmatched lines.
- **Data:** 12 accounts with statements for April–July 2026 (N43, CAMT.053, Mexican CSV) plus a twin `.lines.jsonl` carrying the `bank_line` ids (July: 286 lines; April 287, May 238, June 251). The recorded journal has hundreds to a thousand lines per 572 account since 2025; **no journal line carries a `bank_line` id**. The same `gl_account` repeats across companies (57200001 in 1000, 1100, 1200); a 572 account is identified by (company, gl_account) and has its own currency (EUR, MXN, USD).
- **Naive probe, July** (exact amount, booking date ±6 days, same account): 203 bank lines with one candidate, 6 with several, 77 with none; April 250/11/26, May 200/11/27, June 215/10/26.
- **Code today:** `PhaseData.bank_lines`, `model.BankLine`, `output_models.bank_rec` (row types), `ledger` (open items, balances), `validation`, `money.RateTable`. No reconciliation code exists on any branch.
- **Coordination points named by the issues:** receipt `BL0000706` (AR cash), cash-pooling sweep (intercompany), `SWIFT-API004253`, `BOOK_AMOUNT_ERROR` (absent in July), dependencies on M0-03/05/07/08/09/12 and M1-17.

## Questions

### Q1. What is the result model, and how does it relate to `ArBankRecRow`?

*Why it matters:* the stated end state is typed in-memory instances per account.
*Acceptance:* one root instance per account; every field of the delivery row reachable; invariants checked at construction; serialization is a separate mechanical step.

### Q2. Which book lines are candidates for the July reconciliation?

*Why it matters:* the journal holds years of 572 lines; the reconciliation of the month must decide whether earlier open items (outstanding payments from June, items the bank executed in June) take part.
*Acceptance:* a rule for the candidate window and for items carried from earlier months, justified by the history and by categories such as `OUTSTANDING_PAYMENT` and `PRIOR_PERIOD_BANK_ITEM`.

### Q3. How are statements normalized and bank accounts tied to GL accounts?

*Why it matters:* identity is (company, gl_account) and currency; formats differ; the delivered ids come only from the twin files.
*Acceptance:* a single typed statement line; opening/closing balance chain verified per account; currency and account identity explicit; no format reimplemented unless a detail is needed.

### Q4. How is 1:1 matching done without choosing arbitrarily among repeated amounts?

*Why it matters:* pairs carry 45 % of the account score.
*Acceptance:* a deterministic, evidence-ordered procedure (reference, date, text) with a stated tie-break and a "refuse to guess" outcome; each line used once.

### Q5. How are grouped matches (1:N remittances, N:1 split lots) found?

*Why it matters:* groups of 36, 19 and 9 lines were observed; subset-sum searches are explicitly discouraged.
*Acceptance:* groups come from references and history (SEPA remittances, payment runs, payroll lots), with totals checked, never from exhaustive search.

### Q6. How are matches with justified differences recognised (FX, loan interest, factoring)?

*Why it matters:* an adjustment must not turn the match into an unmatched line.
*Acceptance:* a rule per difference type reproducing the amount and the adjustment account side.

### Q7. How are unmatched bank lines classified and their entries built?

*Why it matters:* categories and adjustments are 55 % of the score; some need vendor, invoice, customer, receipt or retention data.
*Acceptance:* per category a text/amount/context rule, the entry template with partner, assignment, cost object and currency, and the evidence it needs.

### Q8. How are unmatched book lines and book-side errors classified?

*Why it matters:* `BOOK_DUPLICATE`, `BOOK_AMOUNT_ERROR`, `WRONG_BANK_ACCOUNT`, `OUTSTANDING_PAYMENT`, `TRANSFER_IN_TRANSIT`, `PRIOR_PERIOD_BANK_ITEM`, `FX_REVALUATION` look alike.
*Acceptance:* a decision order separating timing items from errors, with the evidence each requires.

### Q9. How are adjustment entries grouped, dated and made explicit?

*Why it matters:* one adjustment can serve several lines; foreign-currency accounts adjust in functional currency; every line needs an explicit company.
*Acceptance:* one entry per cause with a single owner, balanced, with company, partner, assignment and cost object rules, and provenance.

### Q10. How does M3 coordinate with AR cash, intercompany, AP and factoring?

*Why it matters:* the same bank movement (receipt `BL0000706`, pooling sweep, direct debits, returned debits) can be booked by more than one module.
*Acceptance:* a single owner per movement, a declared interface, and no double posting.

### Q11. What is the catalogue of edge cases and the policy for each?

*Why it matters:* the brief asks to analyse all edge cases; July contains planted ones and September will contain others.
*Acceptance:* a table of edge cases (repeated amounts, same-day pairs, split lots, foreign currency, sign errors, unknown text, missing statement day, duplicates, bank error vs duplicate) each with a rule or an explicit unresolved result.

### Q12. How is the implementation validated without the golden?

*Why it matters:* the golden is evaluation-only and the test phase has none.
*Acceptance:* oracles from the history, balance and policy invariants, synthetic fixtures for variants absent in July, and the comparator only in evaluation.

### Q13. What generalises to the September phase, and what is the fallback when a rule does not apply?

*Why it matters:* bank texts, remittance shapes and error cases can differ.
*Acceptance:* rules keyed on structure and evidence rather than on July literals; an explicit unresolved outcome instead of a guess.

### Q14. Module boundaries, order of work and the proposed implementation scope.

*Why it matters:* the issue dependencies (#66→#77) and the other branches must fit together.
*Acceptance:* module list, dependency direction, milestones, and what is merged from other branches.

## Findings from research (facts; each reproducible from `phase_dev` without the golden)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | Statements are internally consistent: for all 12 accounts and 4 months, opening + movements = closing and closing(M) = opening(M+1). | Parsed N43 (records 11/33), CAMT.053 (`OPBD`/`CLBD`), CSV; 48/48. | Normalization can be verified mechanically. |
| F2 | The `.lines.jsonl` twin is aligned **by position** with the original file (36/36 N43 files; same count and signed amount per row). | Position check. | Ids come from the twin; details come from the original. |
| F3 | The original N43 carries what the twin drops: mandate `REF. MANDATO V100028-1100` (vendor id), `FRA <invoice no.>` (the direct debit's invoice), returned-receipt id (`RC26-00280`), return motive (`MD06`/`AM04`), remittance references. | N43 records 22/23 of CMA-1100, CMA-1200, CMA-1000. | Direct debits, returned debits and duplicates are resolved from the statement itself; no AP data is needed to name vendor and invoice. |
| F4 | **Month-end identity:** `statement closing − book balance at month end = Σ unmatched bank − Σ unmatched book (posted in the month)`; exact on all 11 non-USD accounts for July. April and May month-ends are 0 except small carried items. | Computed with the prototype classification. | Gives a golden-free invariant per account (Q12). |
| F5 | A deterministic prototype (tiers below) reproduces the milestone reference **structure** for July: 216 one-to-one (incl. 6 with differences), 7 one-to-many (N = 36, 19, 9, 4, 4, 2, 2) + 1 many-to-one (payroll in two lots), 67 unmatched bank lines = 61 + 5 FX + 1 loan, 9 unmatched book lines (5 + 4 prior-period). | Prototype counts. | The approach covers the whole July problem; counts are not row-level proof. |
| F6 | Naive greedy matching by smallest date gap steals across months: July fees (−3,200/−950 on 07-10) pair with June month-end BANKFEE entries (06-30). | Prototype run. | Fee, card and interest entries are month-end postings: match only within the same month, book date ≥ bank date. |
| F7 | Direct-debit book entries (`source=DD`) carry the invoice number as `reference`; direct debits post in the book **after** the bank in 4 July cases (bank 06-29/06-30, book 07-02…07-15). | Book/bank comparison. | Direct debits match on invoice number + amount, with a book date that may follow the bank by up to ~35 days; these four are the July `PRIOR_PERIOD_BANK_ITEM`. |
| F8 | Recurring identical amounts (rent −4,951,799 ×6, cash pooling −30,000,000 ×2) are ambiguous by amount and date. | CMA-1200, BIN-1000. | Disambiguate by reference tokens (invoice number, company suffix) and, for equal-evidence ties, chronological order. |
| F9 | The only duplicate **bank** charge is the second statement line with the same mandate, invoice number and amount (`GM26/21893`, −526,544, 07-13 and 07-14). | N43 `FRA` of CMA-1000. | Rule: first occurrence is a not-booked debit, later occurrences are `BANK_ERROR`. |
| F10 | USD account: books are in MXN with `amount_doc` in USD; bank-fee adjustments convert at the SYN-BCE rate of the **bank line's booking date** (USD 18.00 on 07-10 → 27,713 MXN; the June fee was booked at the 06-10 rate, 26,480). | `fx_rates.jsonl`, June BANKFEE entries. | Compare on `amount_doc` for the USD account; convert adjustments at the booking-date rate. |
| F11 | Factoring: the bank advance equals the book `Dr 572 / Cr 553` line, but two July remittances were booked without the interest and fee line that June's entry includes (`66500000`). The charges equal `advance − cash` and `interest + fee` in `factoring_assignments`. | JEs of FAC26061053 vs FAC26070673/FAC26070662. | Match is exact on the 572; the adjustment is `Dr 66500000 / Cr 55300000 FACTOR-BAE`, assignment = ceded invoice. |
| F12 | History gives an entry template for every bank-originated category (fee, interest with 19 % retention, card `62910000`+`CC-1000-DIR`, direct debit `Dr 41000000` partner + invoice, returned debit + commission, loan with `66200000`, treasury transfer, FX difference with `66800000`/`76800000`). | Journal entries by `source`. | Adjustments follow historical templates, not invented ones. |
| F13 | The tracked reference (`bank-rec-data-model.html`) states the scoring granularity: lines are compared flattened by (account, partner, cost object, amount ±2 cents) and **line granularity counts**; adjustment grouping does not. Its worked conventions: fees with the same account+date+concept+amount are one adjustment with aggregated `Dr 626 / Cr 572`; a returned receipt is one entry (`Dr 430 + Dr 626 / Cr 572`, 572 aggregated); interest is one entry (`Dr 572 net`, `Dr 473`, `Cr 762 gross`); a duplicate payment is cancelled with `Dr 572 / Cr 400 per vendor`. | HTML reference, `score.py`. | Emit adjustment lines in those shapes. Provenance note: the reference was written from the golden; we use its conventions, not its values. |
| F14 | A wrong-bank item is a payroll paid from BIN-1100 and booked in CMA-1100 (same company, same amount, same date); a duplicate book entry is a confirming maturity posted twice (07-30 and 07-31) in BAE-1100. | Prototype leftovers. | Cross-account pairing inside one company, and duplicate detection by (reference, amount, vendor lines). |

## Decisions

### Q1. Result model: typed immutable instances per account in `kalmora.bankrec`, converted to `ArBankRecRow`. **Decided.**

Frozen, slotted dataclasses validated at construction (same decision as ADR 0003). One `AccountReconciliation` per bank account (12), in `tasks/bank_accounts.json` order:

- `StatementLine(id, account, booking_date, value_date, amount, currency, text, detail)` where `detail` is the original-format record (references, mandate, invoice, motive) or `None`.
- `Match(bank_lines, book_lines, shape: ONE_TO_ONE | ONE_TO_MANY | MANY_TO_ONE, difference: Difference | None, evidence)`.
- `Unmatched(line_id, side: BANK | BOOK, category, amount)`.
- `Adjustment(category, lines: tuple[AdjustmentLine, ...], causes: tuple[str, ...])`, where `AdjustmentLine` carries company, account, debit, credit, partner, assignment, cost object.
- `AccountReconciliation(account, company, gl_account, currency, statement_opening, statement_closing, book_balance, matches, unmatched_bank, unmatched_book, adjustments, diagnostics)`.
- `BankRecRun(results, unresolved)`; `to_row` produces the existing `ArBankRecRow`.

### Q2. Candidate window: match globally over all statement months, project the target month. **Decided.**

Alternatives: (a) reconcile July alone (July statement vs July-posted book lines); (b) carry state month by month; (c) match over April–July in chronological order and project the July view. (a) cannot tell a prior-period item from an error (the four July direct debits whose bank line is in June); (b) needs per-month adjustment state we do not have. Decision (c): bank lines are all statement lines of the four months, book lines are 572 lines posted from the first statement month; months are processed in chronological order. The July view is: bank lines = July statement; book lines = July-posted lines plus earlier lines matched to a July bank line; a July-posted book line matched to an earlier-month bank line is reported as unmatched book `PRIOR_PERIOD_BANK_ITEM`. The first-month opening balance equals the book balance one day earlier on every account except one whose gap is explained by April-posted prior-period direct debits (F4), so nothing before April is needed. This is the only choice that reproduces the milestone counts (F5).

### Q3. Normalization: stdlib parsers for the original formats, twin for ids. **Decided.**

N43 (records 11, 22, 23, 33), CAMT.053 (`xml.etree`) and the Mexican CSV are parsed with the standard library; each line takes its id from the twin by position (F2); the opening/closing chain and `opening + movements = closing` are checked per file and any failure blocks the account. Identity is (company, gl_account) from `bank_accounts`, currency from the account (EUR, MXN, USD). For a foreign-currency account the comparison uses `amount_doc` of the book line (F10).

### Q4. One-to-one matching: evidence tiers, month order, FIFO tie-break, never arbitrary. **Decided.**

Applied per account, months in chronological order, each line used once:

1. **Reference match:** direct debit by invoice number + amount (F3, F7); remittance, payroll and confirming tokens belong to Q5; pooling by company suffix in the text (`BIN-1100` ↔ `CP…1100`).
2. **Beneficiary match for foreign transfers:** name tokens + currency + date (leads to Q6 when amounts differ).
3. **Exact amount** with source-specific temporal rules: `BANKFEE`/`CARD`/`BANKINT` same month and book date ≥ bank date (F6); `DD` book date within +35 days of the bank date; everything else within ±6 days.
4. **Ties** (equal evidence): chronological pairing; if still ambiguous, no pair and a diagnostic.

### Q5. Grouped matches from references, with totals checked. **Decided.**

`REMESA yyyymmdd-nnn` ↔ `F110` references ending in the same token (observed 36, 19, 9, 4, 4, 2, 2 lines); `ORDEN NOMINAS mm/yyyy [LOTE n]` ↔ `NOMyyyymm` (N:1 when the payroll is paid in lots); `REMESA CF…` ↔ confirming. A group is accepted only if the sums are equal; otherwise it is left unmatched. No subset-sum search.

### Q6. Justified differences stay matches. **Decided.**

- **FX:** transfer abroad matched by beneficiary and date; difference = bank − book amount; the adjustment uses the FX account the payment entry itself used (`66800000` loss, `76800000` gain; a loss that reduces a booked gain is `Dr 76800000`).
- **Loan:** `CUOTA PRESTAMO` against the loan entry that has principal only; difference = interest (original `CAP`/`INT` reference); `Dr 66200000 / Cr 572`.
- **Factoring:** exact 572 match; missing charges per F11; `Dr 66500000 / Cr 55300000 FACTOR-BAE`, assignment = ceded invoice; no 572 effect.

### Q7. Bank-side classification and entries. **Decided.** Table-driven by statement text and original-format data; entries follow F12/F13.

| Category | Rule | Adjustment (functional currency) |
|---|---|---|
| `BANK_FEE_NOT_BOOKED` | text `COMISION …`, `GASTOS SWIFT` with no month-end entry | `Dr 62600000 / Cr 572`, aggregated per account+date+concept+amount; guarantee fee `66900000` |
| `DIRECT_DEBIT_NOT_BOOKED` | `RECIBO …` with mandate and `FRA`, first occurrence | `Dr 41000000` partner = mandate vendor, assignment = invoice / `Cr 572` |
| `RETURNED_DIRECT_DEBIT` | `DEVOLUCION RECIBO` + `COMISION DEVOLUCION`, receipt id from the original record | `Dr 43000000` partner = receipt customer, assignment = receipt; `Dr 62600000` commission; `Cr 572` total |
| `INTEREST_NOT_BOOKED` | `ABONO LIQUIDACION INTERESES` + `RETENCION 19%` (19 % check) | `Dr 572` net, `Dr 47300000`, `Cr 76200000` gross |
| `CARD_SETTLEMENT_NOT_BOOKED` | `LIQUIDACION TARJETA` | `Dr 62910000` cost center `CC-1000-DIR` / `Cr 572` |
| `POOLING_NOT_BOOKED` | `TRASPASO CASH POOLING` with no `POOL` entry | `Dr 55200000` partner 1000 / `Cr 572` (outflow) |
| `UNRECORDED_RECEIPT` | credit with no book line | `Dr 572 / Cr 55500000` |
| `BANK_ERROR` | later occurrence of the same mandate+invoice+amount (F9) | none |
| `LOAN_INTEREST_NOT_BOOKED`, `FACTORING_CHARGES_NOT_BOOKED`, `FX_RATE_DIFFERENCE` | Q6 | Q6 |

### Q8. Book-side classification. **Decided.** In this order:

1. Matched to an earlier-month bank line → `PRIOR_PERIOD_BANK_ITEM` (no adjustment).
2. Same-company pair with an unmatched bank line in another account, equal amount and date → `WRONG_BANK_ACCOUNT` (both sides); one entry `Dr correct 572 / Cr wrong 572`.
3. Second posting of the same reference, amount and vendor lines → `BOOK_DUPLICATE`; cancel with `Dr 572 / Cr 400` per vendor line of the duplicate entry.
4. Source `CLOSE_FX*` → `FX_REVALUATION` (no adjustment).
5. Treasury transfer whose other leg is absent → `TRANSFER_IN_TRANSIT`.
6. Payment posted in the last days of the month with no bank line → `OUTSTANDING_PAYMENT`.
7. Reference or beneficiary equal but amount different and not Q6 → `BOOK_AMOUNT_ERROR` (correct against the vendor account); absent in July, covered by fixtures.
8. Otherwise unresolved with a diagnostic.

### Q9. Adjustment entries. **Decided.** One entry per cause (F13), company on every line, partner and assignment per policy §1, cost object per policy, amounts in the company's functional currency (USD fees converted at the booking-date rate, F10), debits equal credits. Each entry carries provenance `(event_id = cause key, stage = "bank_rec")` so replays are idempotent and `Ledger.add_entry` accepts it. Line granularity is kept as in the reference (aggregated fees, one entry per returned receipt, one per interest settlement).

### Q10. Coordination. **Decided.**

- **`BL0000706`:** bank_rec owns the first leg (`Dr 572 / Cr 555`); AR cash owns the application (`Dr 555 / Cr 430`); the 555 account must net to zero across both.
- **Pooling:** bank_rec posts the participant side (`Dr 55200000` partner 1000); intercompany reads the entry rather than posting a second one (workflow guide: adjusted through bank reconciliation).
- **Direct debits:** vendor and invoice come from the statement (F3), so no AP result is required to compute; when AP's July postings exist, the entry clears the vendor item with the same assignment.
- **Factoring:** shares `55300000 FACTOR-BAE` with AR cash `FACTORED_MISDIRECTED`.
- Interface: `BankRecRun` exposes the adjustment entries so close and AR cash can add them to a ledger projection.

### Q11. Edge-case catalogue. **Decided.**

| Edge case | Where seen | Rule |
|---|---|---|
| Repeated amounts, same day | pooling −30,000,000 ×2 (BIN-1000, 06-26) | Reference token, then chronological; else diagnostic |
| Recurring same-amount debits | rent −4,951,799 (CMA-1200) | Invoice number; FIFO |
| Month-end postings vs mid-month bank dates | fees, card, interest | Same month, book date ≥ bank date |
| Book posted after bank | 4 July direct debits | `PRIOR_PERIOD_BANK_ITEM` |
| Duplicate bank charge | GM26/21893 | First booked, later `BANK_ERROR` |
| Duplicate book entry | CF110026062529 | `BOOK_DUPLICATE`, cancel per vendor |
| Payment in lots | payroll 2 lots (BIN-1200) | N:1 with equal sums |
| Large remittance | 36 lines | Token + sum |
| Foreign currency transfer | USD/GBP | Beneficiary match; FX difference account from payment entry; gain reduction is a debit on `76800000` |
| Foreign-currency account | `BANH-3100-USD` | `amount_doc`; adjust at booking-date rate |
| Interest with retention | CMA-1000, BAE-1300 | One entry, 19 % check |
| Wrong bank account | payroll BIN-1100/CMA-1100 | Cross-account pair |
| Unrecorded statement day | BL0000706 | `UNRECORDED_RECEIPT` |
| Factoring advance without charges | FAC26070673, FAC26070662 | Charges from `factoring_assignments` |
| FX revaluation reversal | CLOSE_FX 07-01 | `FX_REVALUATION` |
| Treasury transfer pending | TRF07IT | `TRANSFER_IN_TRANSIT` |
| Absent in July | `BOOK_AMOUNT_ERROR`, guarantee fee `66900000`, `LOAN_INTEREST` as bank-side unmatched | Rules + fixtures |
| Unknown text or missing evidence | September | Unresolved with diagnostic, never a guessed category |
| `SWIFT-API004253` (known exception in `docs/discrepancies.md`) | GBP payment to the vendor of invoice 26026284 (AP document `API004253`): bank −5,743,000 vs book −5,718,981; the payment entry credited `76800000` 35,174 | The adjustment is a **debit** on `76800000` (24,019) because it reduces the booked gain; the sign is decided from the direction of the difference relative to the FX line of the payment entry, never from the account |

### Q12. Validation without the golden. **Decided.**

1. **Month-end identity** per account (F4), before and after adjustments (after: `closing − (book + Σ adjustments on 572) = −Σ unmatched book that stays`).
2. **Milestone reference structure** (F5): 216/8/61/9 and the line counts per category.
3. **Regression on April–June:** matching yields the month-end differences observed there.
4. **Templates from history** (F12): each adjustment equals the structure of an existing entry of the same source.
5. **Fixtures** for what July lacks (Q11 last rows) in a synthetic scenario set.
6. The comparator and golden only in evaluation. Row-level correctness of July pairs is **not** provable without the golden.

### Q13. Generalisation and fallback. **Decided.** Rules key on structure (original-format references, source, month order, identity) and a text-pattern table; only that table is July-specific. An item that matches no rule is unresolved; nothing is guessed. September risks: new texts, remittance shapes and a case for `BOOK_AMOUNT_ERROR`.

### Q14. Modules, order and scope. **Decided.**

`src/kalmora/bankrec/`: `model.py`, `statements.py` (parsers, twin alignment, chain checks), `book.py` (candidates per account and currency), `match.py` (Q4–Q6), `classify.py` (Q7–Q8), `adjust.py` (templates, FX conversion), `validate.py` (identity, invariants), `run.py` (`build_bank_rec`), `rows.py` (`to_row`). Dependencies: `data`, `ledger`, `validation`, `money`, `facts`-independent. Order by issue: P1 #66–#67; P2 #68–#69; P3 #70; P4 #71–#74; P5 #75; P6 #76–#77. Each phase ends with the identity and counts check.

## Open risks and blockers

- **No blocker.** No non-inferable product, legal or financial decision is needed.
- R1: line granularity of adjustments (aggregated fees, merged credit lines) rests on the tracked reference; a different golden convention costs points in the 20 % adjustment component.
- R2: book-side categories `OUTSTANDING_PAYMENT` and `TRANSFER_IN_TRANSIT` are inferred from source and timing (one case each in July).
- R3: the `SWIFT-API004253` exception is explained (Q11) but its sign rule is only confirmed by this one case; issue #77 still asks to investigate the historical rates.
- R4: September text patterns and remittance forms are unseen.
- R5: pooling ownership with intercompany and the `55500000` netting with AR cash need an agreed interface.
- R6: the identity and counts are strong evidence but not row-level proof of the July pairs.

## Proposed implementation scope (awaiting approval)

1. Statement layer (#66–#67): parsers, twin alignment, chain checks, account identity, currency.
2. Matching (#68–#70): tiers, groups, differences, with the identity check.
3. Classification (#71–#74): bank-side and book-side rules and the text table.
4. Adjustments (#75): templates, FX conversion, provenance.
5. Validation and comparison (#76–#77): identity, counts, fixtures, exception investigation, comparator hook.
6. Reproducible check script outside the repository unless tests are requested.

## Implementation and evidence

Status: implemented in `src/kalmora/bankrec/` (`model`, `statements`, `book`, `match`, `classify`, `adjust`, `validate`, `run`, `rows`) with tests in `tests/test_bankrec_*.py`. Entry point `build_bank_rec(data, month=None) -> BankRecRun`; `to_row` produces the existing `BankRecRow`.

Adjustments to the plan above, found while implementing:

- **Equal candidates** are paired in id order and reported as an `ambiguous` diagnostic instead of being refused (refusing would score zero for both lines; the data has only interchangeable same-day fees).
- **Direct-debit adjustments** are one entry per statement line (the historical `DD` template). July gives 59 adjustments against the 56 in the milestone reference; the three extra come from direct debits, whose grouping rule the reference does not state. Risk R1 stands.
- **Wrong-bank adjustment** sits in the bank-side account's row (the reference does not say which row holds it).
- **Factoring charges** apply only to advance lines (`ANTICIPO` in the statement); a final liquidation is a plain match.
- **A book-amount error** is modelled as a match with a `BOOK_AMOUNT_ERROR` difference (same invoice, different amount), corrected against the vendor; it is covered by synthetic tests only.
- **Revaluation lines** (`CLOSE_FX*`) carry no amount in a foreign account's own currency, so they are excluded from its comparison.
- **As-of rule:** reconciling month M uses only book lines posted up to its end, so earlier months can be rerun.
- A statement line no rule recognises is reported in `diagnostics` and left out of the result; nothing is guessed.
- Reconciliation checks (golden-free): the month-end **carry** (statement closing minus book balance must equal the month's unmatched statement lines plus differences minus the unmatched book lines posted in it) and the **after-adjustments** residual (only bank errors and book items that need no entry may remain). Failures are `identity:` diagnostics.

Evidence (reproducible, no golden):

- **Development phase, July:** 12 accounts, 0 unresolved, 0 `identity`/`no rule` diagnostics; 224 matches (216 one-to-one, 7 one-to-many, 1 many-to-one; 8 with a difference: 5 FX, 1 loan, 2 factoring), 61 unmatched bank lines and 9 unmatched book lines with the category counts of the milestone reference (31 fees, 17 direct debits, 4 returned-debit lines, 4 interest lines, 1 card, 1 pooling, 1 unrecorded receipt, 1 bank error, 1 wrong bank; book: 4 prior-period, 1 duplicate, 1 outstanding, 1 transfer in transit, 1 revaluation, 1 wrong bank).
- **Reference examples reproduced exactly:** USD fee 18.00 → 27,713 MXN; interest entry `Dr 572 326,430 / Dr 473 76,570 / Cr 762 403,000`; duplicate confirming cancelled with `Dr 572 17,775,503 / Cr 400` per vendor (12,504,802, 3,004,872, 2,265,829); returned receipt `RC26-00280` → `Cr 572 50,319`.
- **As-of regression April–July:** every month passes both checks, and the direct debits not booked at the end of April, May and June (3, 7, 4) are exactly the prior-period items of the following month.
- **Tests:** 59 new tests (statements, matching tiers, classification, every adjustment template, a synthetic phase end to end, and the development phase when `participant/phase_dev` or `KALMORA_PHASE_DEV` is available, otherwise skipped). `mypy` is clean on the package. The full suite still has 13 failures in the LLM client tests that exist without this change.

Known limits: row-level correctness of the July pairs is not provable without the golden; September texts and remittance shapes are unseen; `OUTSTANDING_PAYMENT` and `TRANSFER_IN_TRANSIT` rest on one case each; the coordination with AR cash (`BL0000706`) and intercompany (pooling) is by convention, not yet integrated.
