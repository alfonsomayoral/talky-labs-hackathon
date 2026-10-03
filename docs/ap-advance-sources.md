# Evidenced foreign-advance source resolution — #54

`resolve_advance_sources` obtains the vendor from an exact documentary PO, an
explicit approval statement and active-phase masters. It returns either a
resolved `ApprovedAdvanceOrder` plus a copied `vendor_master`, or a non-postable
status with evidence and diagnostics. No matching uses invoice ID, amount, month,
vendor-name similarity or the vendor's habitual currency.

The caller provides a resolved company/currency/date, a `Fact` carrying the PO
reference and `AdvanceApproval(po_reference, approved)`. These two approval facts
represent **one associated approval statement**, not independent facts found
somewhere in a document. They must identify the same source document and the
same requested PO; approval is accepted only for the literal boolean `True`.
The caller must establish that association from the source. The helper neither
extracts free text nor infers approval from a PO's existence or project budget.

The PO must exist, belong to the document company/currency and predate the
request. Its vendor must exist, be explicitly enabled for that company and be
foreign according to observed vendor/company country masters. Exact observed
supplier/recipient tax identifiers corroborate that relationship. Contradictory,
unknown-in-master or ambiguous observed identifiers prevent posting. An absent
tax identifier does not discard the independent approved-PO proof of a foreign
request's counterparty; invoice rejection policy remains in the invoice engines.

Both success and abstention retain supplied source facts and ERP field references.
Inputs are snapshots; no master is changed. Pass the resolved order and vendor
master to `build_down_payment_request`, which still requires posting eligibility,
resolved amount and invoice-date FX and puts the partner on **both 407 and 400**.
Its returned advance state remains tentative until ledger insertion succeeds.

Focused regression command:
`.venv/bin/python -m unittest discover -s tests -p 'test_ap_advance_sources.py' -v`.
Tests cover missing/false/nonboolean approval, approval/PO scope contradictions,
unknown/ambiguous identities, company affiliation, foreign country, vendor proof,
new/reused IDs, different dates/PO positions, immutable inputs and idempotence.

This completes the general counterpart-resolution interface and its policy
checks. #140 must bind actual documentary approval statements and original
advance classifications/balances to it. `ap_journal` now maintains cumulative
original-credit limits for resolved references in `AdvanceState.credits`; its
caller must evidence historical credit consumption before starting. Advance
restoration for a credit and final independent evaluation are not inferred here.
An original invoice containing an applied advance (a nonzero 407 posting) cannot
be credited through the ordinary invoice path: the builder abstains until advance
restoration evidence is supported. This prevents reversing expense/payable while
silently dropping the original advance and its historical carrying amount. The
regression covers monetary and non-monetary advances without changing their state.
The issue remains open until its outstanding integration/evaluation criteria have
evidence; this helper does not declare the 305-document M1 delivery complete.


[Application and restoration APIs](ap-credit-restoration.md) now accept associated
classification/application Facts and explicit restored 407/receipt usage.
The ordinary credit route still abstains for an applied-advance original without
those proofs. Restored state remains tentative until the real delivery validator
accepts the header and accounting contract; #140 integration adopts every returned
snapshot together. No classification is inferred from a zero FX difference.
