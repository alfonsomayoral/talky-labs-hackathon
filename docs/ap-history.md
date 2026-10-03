# Historical receipt certainty — integration #140

`reconcile_receipt_history` accepts evidenced receipts with their confirmed PO
prices, and historical AP GR/IR demands already joined to those positions. The
caller supplies a grounded assertion that this historical inventory is complete.
An absent demand then means no recorded AP consumption; it is not a default for
an incomplete read. Accrual reversals are not receipt consumption.

Integer document cents give a range of integer milli quantities compatible with
half-up rounding. The adapter checks each receipt's supplied amount against its
quantity and PO price, then bounds consumption per receipt without selecting a
historical matching. A uniquely determined full or partial use creates a
`ReceiptUsage`. Otherwise the receipt stays UNKNOWN with bounds and evidence.
Equal monetary balances, a partial order total or a stable FIFO algorithm alone
do not demonstrate the receipt split.

An optional `HistoricalDemand.processed_on` is a `Fact` containing an observed
processing date. Temporal restrictions apply only when every demand of that
position carries that fact. Invoice issue and journal dates are not silently
substituted. Each historical demand prefix must fit the receipt capacity visible
then; incompatible observations retain `HISTORY_TEMPORAL_EVIDENCE_INSUFFICIENT`.
Where the clock is grounded, receipts after the last historical processing event
have no historical consumption. Without it, use only quantity conservation.

The returned snapshot distinguishes AVAILABLE, CONSUMED, PARTIAL and UNKNOWN.
`known_receipt_ids(order)` supplies only capacities established by these facts.
The AP caller still filters them by its current receipt cutoff and source
references, passes the complete catalogue to the allocator, and commits newly
allocated quantities only after journal and AP-row validation. If a relevant
receipt is UNKNOWN, a shortage of known capacity is an integration uncertainty;
it must not be exported as the accounting reason QTY_NOT_RECEIVED.

The source adapter remains responsible for the ERP join, supplier/currency/unit
scope, posted-document protection (including HOLD later resolved and posted),
source hashes, and processing-date semantics. This component does not prove full
July coverage or classify documents. Its synthetic integration checks require
neither Golden nor provider.
