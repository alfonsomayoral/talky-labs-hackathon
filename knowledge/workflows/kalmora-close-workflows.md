# Kalmora Close Workflows

This guide maps the course concepts to the hackathon tasks. The participant policy manual governs every scenario-specific decision.

## Project accounting rules

- Amounts are integer cents in each company's local currency; quantities use thousandths.
- Every journal entry must balance debit and credit.
- Open-item accounts carry the business partner required by the manual.
- Expense, revenue, and fixed-asset lines use either a cost center or a WBS element, never both.
- Check the chart of accounts and historical allocations against `phase_*/erp/` and the journal.
- The development phase is July 2026 and includes `golden`; the test phase is September 2026 and does not.

## AP — Vendors

Classify the document before building an entry: not every item in the inbox is an invoice. For invoices, apply the decision order: duplicate, reject, hold, payment block, then post. Do not confuse payment status with recognition of the invoice.

With a purchase order and receipt, debit GR/IR (`40090000` in the manual) for the received value and allocate permitted differences to the expense using the correct cost object. Check deductible/reverse-charge VAT, tax withholding, construction retention, advances, and payment beneficiary. See [POLITICAS_CONTABLES.md §2](../../participant/POLITICAS_CONTABLES.md) for the rules.

## AR — Customers and receipts

Invoice only services, certificates, or production supported by approval, measurement, or contract. Work pending approval is not invoiced; assess it for WIP revenue at close. Extraordinary services require customer approval, price revisions follow the approved effective date, and energy billing follows measurement and contract terms.

Imported credits initially sit in `55500000`: apply them to identified invoices or promissory notes and classify differences using the documented category. If the reason for an underpayment is unknown, leave the balance open instead of inventing a penalty or discount. See [POLITICAS_CONTABLES.md §3](../../participant/POLITICAS_CONTABLES.md).

## Bank and intercompany reconciliation

Match `bank_line` statement lines to account 572 journal lines; matches may be one-to-one or grouped. Classify unmatched bank and book items separately, and post adjustments only for categories the policy marks as adjustable. An unrecorded cash-pooling transfer also affects intercompany balances, but it is adjusted through bank reconciliation to avoid a duplicate entry.

For intercompany balances, reconcile invoices, pooling, loans, interest, and the joint venture across both companies. Determine whether a difference is an invoice in transit, day-count error, incorrect partner, duplicate, or unrecorded pooling before adjusting. Interest on KMI-2025-01 uses act/360 under the policy.

## Close entries

- **ACCRUAL:** estimate consumed, uninvoiced services without a purchase order from vendor history; do not accrue what is already recorded in GR/IR.
- **PREPAID:** defer future coverage and recognize each month's consumed portion.
- **WIP_REVENUE:** recognize completed work pending approved certification using the policy's revenue treatment.
- **FX_REVAL:** remeasure foreign-currency balances using the case's published closing rate.
- **BAD_DEBT:** calculate the required allowance net of the existing allowance for eligible balances; exclude public administrations and intercompany balances under the manual.
- **DOUBTFUL_RECLASS:** reclassify invoice by invoice in the month bankruptcy is declared.

Date close entries on the last day of the month; do not submit automatic reversals on day one. Refer to [POLITICAS_CONTABLES.md §§4–6](../../participant/POLITICAS_CONTABLES.md) for exact accounts, rates, tolerances, and signs.

## Final review

Before delivery, confirm that:

- no document is duplicated against the month's intake or history;
- decisions rely on documents and masters in the active phase;
- open items use the correct assignment and differences are not forced;
- each entry balances and uses the right company, partner, account, and cost object;
- bank movements are not posted twice;
- amounts are cents and dates are ISO (`YYYY-MM-DD`);
- each JSONL file has one valid JSON object per line and follows the delivery schema.
