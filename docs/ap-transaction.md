# Atomic AP posting (#140)

`commit_ap_transaction(request, state, tax_catalog=..., withholding_catalog=...,
rates=..., context=...)` connects the real allocation, valuation, tax, withholding,
journal and AP output engines. It accepts resolved inputs and structured
`Evidence`; it does not extract documents, decide eligibility, infer facts or
access Golden/provider/files.

`APTransactionRequest` carries an explicit `APComponentScope`, document type,
evidence and `APPostingInputs`. The posting inputs contain the observed header,
country, posting date, resolved monetary and quantity lines, complete receipt/order
catalogues, PO prices, advance applications and optional payment metadata.
The active tax/withholding catalogues are explicit function arguments. `CodedAPLine`
links every output portion to its valued/fiscal line; its amount, cost imputation
and fiscal treatment must conserve those inputs. Accounting amounts remain
integer document cents; journal debits/credits remain local cents.
For quantity-matched lines, every coded PO/position must belong to that same
allocated invoice line, and all allocated positions must be represented. Equal
cost dimensions cannot permit one line's PO to be substituted for another's.

For quantity allocation, supply the complete order/receipt catalogue needed to
validate historical usage, and explicit eligible receipt IDs on every
`OrderPortion`. Supply an explicit observed `receipt_as_of`; there is no default
date. Selected receipts after that date are refused. The caller selects and
bounds the cutoff using phase/source evidence; the transaction keeps invoice date
unchanged for FX and fiscal calculations.

The transaction builds tentative receipt and advance states, constructs a real
validated journal, and passes the resulting journal and observed header to
`build_ap_row`. Only after that validation succeeds does it return `COMMITTED`
with one new `APTransactionState`. The caller replaces its prior snapshot with
the returned state. Factory/header/output errors propagate without mutating the
old snapshot; allocation failure returns `BLOCKED` with that exact old state and
allocation diagnostics. `HOLD`, `REJECT`, `DUPLICATE` and `NOT_INVOICE` return
`NOT_POSTING` with the same state before any factory runs. Their separate delivery
rows/actions remain the runner's responsibility. `UNKNOWN` is refused.

The state contains `ConsumptionState`, `AdvanceState`, published keys, evidence
and canonical JSON snapshots of validated rows. `state.rows` and `result.row`
return fresh copies, so later caller edits cannot alter a confirmed journal or
delivery row. A previously committed key, historical posted event, historical
allocation key, or published task ID raises before factories. Historical events
protect the company/document identity even if incoming supplier or currency
fields change. Replaying AP starts
from the original baseline and cached facts; it does not append to a posted state.

This is an in-memory commit boundary. Persisting the complete resulting snapshot
or atomically exporting the complete task inventory belongs to the phase runner;
there is no external-ledger or filesystem transaction here. Source evidence must
cover the resolved facts and eligibility, and the caller supplies active master
validation context. This component validates ordinary invoices and resolved
credit-note reversals without new receipt consumption. `APDownPaymentInputs`
connects the separate foreign-advance factory with the same atomic publication
boundary: resolved approved order, vendor master, position and exempt treatment
are mandatory. A failed header/output validation does not create an advance
balance, and both 407 and 400 retain the supplier dimension. No receipts are used
by this request. Credit-note receipt/advance restoration still requires a
separate source-backed workflow.
Import VAT requires an explicit zero-base DUA fiscal line, quota and reference;
include its zero-valued coded/valuation portion to preserve the output's tax-code
correspondence. It cannot be inferred from a freight charge or become expense.
It does not establish complete M1 task coverage.

Integration tests exercise real factories: a historical 1000-unit-milli use of a
2000-unit-milli receipt; failed I1 journal/header; successful I2; I1 retry without
supply; advance rollback after a later AP-row failure; non-posting, scope and
repeat protections; immutable publications; positive VAT, withholding and
guarantee with a payment block; a direct original-backed credit-note reversal;
and synthetic dates/IDs with distinct invoice/arrival FX rates. No reference
deliverables or provider calls are needed.
