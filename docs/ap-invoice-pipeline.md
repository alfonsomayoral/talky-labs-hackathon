# Ordinary AP invoice integration — #140

`evaluate_ap_invoice(APInvoiceRequest, APTransactionState, baseline=...)` connects
the existing duplicate, rejection, HOLD, chronology/payment and transactional
engines. It accepts independently normalized financial attachments and explicit
source/master/policy facts. It performs no extraction, provider calls, Golden
access, ERP writes or task-specific matching.

The mandatory active-phase `APERPBaseline` supplies historical duplicate records,
posted-document guards, receipt consumption and complete PO/receipt/price catalogs.
The state cannot discard that history or manufacture an unknown receipt's capacity.
Receipt availability uses an observed cutoff Fact within the active phase and no
earlier than invoice receipt. Invoice dates retain their own FX/fiscal role.

The execution order is duplicate → rejection → vendor/bank HOLD → quantity HOLD →
price HOLD → payment → atomic posting. Duplicate/REJECT/HOLD return validated rows
without journal entries or state consumption. Unknown earlier checks prevent a
later conclusion. A demonstrated quantity shortage precedes a missing price check;
unknown historical receipt capacity cannot establish `QTY_NOT_RECEIVED`.

Chronology is recomputed from the scoped timeline and invoice observations through
`strict_invoice_events`, rather than accepting a caller's resolved payment flags.
Bank support requires the original signed change and bank certificate; factoring
keeps invoice restrictions and expiry. Incomplete/uncertain event sources remove
inventory completeness, preserving UNKNOWN. Supplier dimensions and invoice
currency stay explicit throughout the journal factories.

Posting identity/date/currency and net/tax/gross must agree with independent
financial attachments. Any observed fiscal withholding, contractual retention or
guarantee amount must also agree. `guarantee_applicable` is an evidenced boolean,
not a default: missing contract applicability remains UNKNOWN. A true applicability
requires a resolved contract; a false applicability cannot carry a retention.
The transaction factories and exporter additionally check calculated deductions.

`line_source_bindings` explicitly connects each posting line to attachment path
and row index. Independent PDF/XML rows are compared, never concatenated. The
quantity gate checks observed quantity/unit before allocation; the price gate
checks the source unit price only after quantity clears. Final posting additionally
requires each source row's net and complete row coverage. Neither the coordinator
nor the bridge derives a unit price by dividing a net amount by quantity.

When a source prints `payable_cents`, `source_payable_basis` must explicitly specify
`BEFORE_APPLIED_ADVANCES` or `AFTER_APPLIED_ADVANCES`. Only actual transaction
advance applications bridge the former to final payable. The source amount is
never silently changed to accommodate an application. Missing/contradictory printed
amounts or unknown basis remain operational UNKNOWN, outside the AP JSONL contract.

Only a fully validated journal and AP row publish a new immutable state. The
publication includes the exact source duplicate observation, so a second monthly
channel cannot post the same invoice again. A failed final validator publishes no
receipt, advance, credit balance or observation. Standalone older transactions can
omit an observation; the coordinator abstains if the caller later supplies such
uncovered publications. Every result also returns its observation for the phase
runner's separate received/HOLD/REJECT/duplicate history.

This boundary currently handles ordinary invoices. Credits and approved foreign
advance requests have existing transactional factories but require their own
source/policy adapters. Source preparation, invoice request construction, complete
phase processing, export, recorded replay and evaluator comparison remain distinct
steps. Synthetic integration tests or preparing all July source packets do not by
themselves establish the 305-task July or 297-task September accounting acceptance.
