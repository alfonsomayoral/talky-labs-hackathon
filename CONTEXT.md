# Kalmora Accounting Domain

Canonical vocabulary for the challenge domain, kept consistent across design, implementation, and deliverables. This file defines terms; detailed rules live in the participant policies.

## Entities and documents

**Company**:
A legal entity in the group that records its own transactions, local currency, balances, and journal entries.
_Avoid_: group, when referring to one legal entity.

**Business partner**:
The counterparty associated with an open item: vendor, customer, group company, or factor, depending on the account.
_Avoid_: partner without saying which kind of counterparty it is.

**AP document**:
A document received in the accounts payable workflow; it may be an invoice, credit note, down payment request, or a non-invoice notice.
_Avoid_: invoice for every file in the inbox.

**Invoice**:
A document requesting payment for a transaction; in AP it must be validated, and in AR it supports a receivable subject to performance, contract, and challenge rules.
_Avoid_: receipt, payment, or journal entry as synonyms for invoice.

**Purchase order**:
Prior purchase authorization with items, quantities, prices, and terms; by itself it is not receipt or a posted invoice.
_Avoid_: recorded liability.

**Receipt**:
Evidence that goods or services were received. It is matched against the purchase order and invoice to confirm quantity and acceptance.
_Avoid_: invoice or purchase order.

**Open item**:
An individual amount awaiting clearing in a customer, vendor, or other auxiliary account.
_Avoid_: aggregate balance when the invoice, due date, or assignment is needed.

**Assignment**:
A reference linking an item to its source document or to the receipt/payment that clears it.
_Avoid_: bank reconciliation; these are different relationships.

## Accounting and close

**Journal entry**:
An atomic record of a transaction made up of debit and credit lines whose totals must be equal.
_Avoid_: bank movement when it does not itself imply a journal entry.

**Accrual basis**:
Recognition of income or expense when the service is performed or consumed, regardless of collection or payment.
_Avoid_: cash basis.

**Monetary item**:
A right or obligation to receive or pay a fixed or determinable amount of currency; a foreign-currency item may require closing-date remeasurement.
_Avoid_: non-monetary asset carried at historical cost.

**Period adjustment**:
An adjustment that assigns income or expense to the correct period when performance/consumption and billing, collection, or payment occur at different times.
_Avoid_: maturity reclassification.

**Prepaid expense**:
A payment already made for a service not yet consumed; the future portion remains an asset.
_Avoid_: accrued unbilled expense.

**Accrued unbilled expense**:
A service already consumed by close for which the invoice has not yet arrived; recognize the expense and estimated liability.
_Avoid_: prepaid expense.

**WBS element**:
A construction-project work breakdown element used to allocate costs/revenue when required by policy.
_Avoid_: cost center when the allocation must use a WBS element.

**Cost center**:
An organizational allocation object for overhead or service costs/revenue when a WBS element does not apply.
_Avoid_: assigning both a cost center and WBS element to one line.

## Operations

**Three-way match**:
A control comparing the purchase order, receipt, and invoice before releasing an invoice for payment.
_Avoid_: matching a payment to a bank statement.

**GR/IR**:
A clearing account between goods/services received and invoices received; the challenge manual uses account `40090000`.
_Avoid_: final expense or bank.

**Bank reconciliation**:
Matching statement lines to accounting lines in account 572 and classifying differences by cause.
_Avoid_: forcing equality with unsupported journal entries.

**Receipt residual**:
The difference between a bank credit and the applications to documents, classified only when supported by evidence.
_Avoid_: an arbitrary adjustment to clear the account.

**Impairment allowance**:
A valuation correction for a recoverability risk; it does not automatically extinguish the receivable.
_Avoid_: write-off or debt forgiveness.

**Work performed pending certification (WIP revenue)**:
Construction work executed by close but not yet approved/certified, handled under the challenge's specific close rule.
_Avoid_: an approved AR invoice.

## AR billing

**Billing item**:
One billable concept of the month (a certification, a municipal service report, a price revision, a PPA or a market settlement) that must be resolved as invoice or skip.
_Avoid_: invoice, which is only one possible result of a billing item.

**Certification (work certificate)**:
The monthly valuation of executed construction work approved by the project's facultative direction; the invoice amount is the current amount (cumulative minus the last invoiced cumulative).
_Avoid_: an invoice, or work merely executed but not approved.

**Price revision**:
A decree that changes a contract's monthly fee with retroactive effect, billed as the difference for each month since the effective date.
_Avoid_: a new fee schedule, a credit note.

**PPA / market settlement**:
Energy sold under a fixed-price contract for a contracted share of production, or at market through a representative whose settlement is net of deviations.
_Avoid_: representative's fee, which is billed separately and is not deducted from the revenue.

**Billing result**:
The in-memory outcome for one billing item: the decision, and, when invoicing, the invoice and its journal entry with evidence and diagnostics.
_Avoid_: delivery row, which is its later serialization.

## Bank reconciliation

**Statement line**:
One movement of a bank account statement, identified by its `bank_line` id.
_Avoid_: book line, or the bank-side journal posting it may correspond to.

**Book line**:
One line of a journal entry on the 572 account of a bank account, identified as `<entry id>#<line>`.
_Avoid_: statement line.

**Match**:
A pairing of one or more statement lines with one or more book lines of the same account, one-to-one, one-to-many or many-to-one, whose totals agree or differ for a justified cause.
_Avoid_: reconciliation, which is the result for a whole account.

**Reconciling item**:
A statement line or a book line left unmatched in the month, explained by a category.
_Avoid_: error, since most are timing items that need no adjustment.

**Prior-period item**:
A book line posted in the month whose statement line belongs to an earlier month.
_Avoid_: outstanding payment, which runs the other way: booked first, executed by the bank later.

**Reconciliation identity**:
For a bank account and month end, statement closing minus book balance equals the sum of unmatched statement lines minus the sum of unmatched book lines.
_Avoid_: a balance check on the statement alone.

## Evaluation

**Golden**:
The organizer's reference deliverables and trial balances for the development phase; evaluation evidence only.
_Avoid_: expected output the solver may consult, training data.

**Submission**:
The set of delivery files produced for one phase and evaluated against the golden.
_Avoid_: golden, run report.

**Comparator**:
The evaluator-side tool that explains, per entity, how a submission differs from the golden without changing the official score.
_Avoid_: scorer, when referring to the organizer's scoring.

**Scoring key**:
The identity under which the scorer groups submission rows for one module, such as a close key or an intercompany pair and cause.
_Avoid_: row, when several rows share one key.

