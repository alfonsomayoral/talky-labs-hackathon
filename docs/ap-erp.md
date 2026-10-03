# Active-phase ERP baseline — #140

`load_ap_erp_baseline(phase_path, grir_account=...)` reads purchase orders,
GR/SES, AP invoices/logs, vendors and the complete journal through read-only
`PhaseData`. It returns master-scoped order/receipt/price catalogues, receipt
certainty, recorded posting identities and the existing duplicate observations.
Actual source paths and SHA-256 values accompany the snapshot; sources changed
during a read and paths escaping the phase are rejected. Golden is unavailable.

Every AP GR/IR line supplies its explicit PO/item, supplier, document currency
and integer document cents. Accrual reversals from other journal sources do not
count as AP consumption. A HOLD document with a real AP journal does count.
Invoice/log links must agree and point to an existing AP journal with the
registered supplier/currency. Unlinked AP journals are still scanned; a direct
expense entry does not consume receipts and does not receive an invented doc_id.
Invoice currency comes from linked invoices or evidenced supplier lines, while
the observed journal header currency is preserved separately. Local-currency
headers and historical 407 applications never replace document currency or cents.

The certainty engine uses quantity conservation and rounding bounds. Journal
posting dates are not silently converted into processing clocks, and no FIFO
matching is inferred. Reversals lacking receipt restoration proof and ambiguous
splits retain UNKNOWN. Consumers must restrict allocation to known receipt IDs;
an unknown historical capacity cannot become QTY_NOT_RECEIVED.

The immutable consumption baseline includes every registered already-posted
identity, including resolved HOLD. `posting_guard` protects company/doc_id even
if incoming supplier fields change. A supplier/currency/number match against an
unlinked AP journal returns UNKNOWN: it lacks a usable duplicate_of and must be
resolved before posting. Duplicate policy still uses its own amount, chronology
and corrected-reissue rules; the guard does not replace them.

Reloading another phase rebuilds all state from that phase's sources. This module
does not extract invoices, execute a monthly AP run or prove September acceptance.
