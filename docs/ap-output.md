# Validated AP rows and export — partial #55

`APHeader` contains resolved invoice scope and integer **document** cents.
`build_ap_row` consumes that header, explicit coded `ApLine` portions, a complete
M0 journal, and the final decision metadata. It never extracts, selects a PO,
calculates tax, invents a cost object or turns an internal unknown into a public
decision. Evidence and diagnostics stay in the separate run audit.

Posting rows require all header fields, a scoped supplier line, conserved net
amounts and a journal that passes `validate_entry`. Optional master/date context
checks both journal dimensions and coded lines. The supplier document payable
must match gross less withholdings, guarantee and explicit 407 applications;
foreign-currency headers are never replaced by local journal amounts. Unsigned
credit-note amounts retain their inverse debit/credit sides. Explicit MULTI_PO
portions remain supplied lines; export cannot invent their split.
The active `TaxCatalog` is required for posted rows, to validate AP codes and
distinguish capitalized VAT from deductible/import quotas. Document base, charged
VAT, withholding and guarantee totals must each conserve the header. This uses
catalogue classifications and supplied journal amounts, not a second tax/FX
calculation. Local-currency `amount_doc` must equal its debit/credit magnitude;
foreign base/fiscal components must explicitly preserve document cents. An
approved advance request must retain the exact Dr407/Cr400 policy entry.
Cost dimensions conserve their own document amounts; an unrelated PO or CC/PEP
cannot absorb a direct portion. GR/IR may exceed invoiced net when the explicit
price difference credits the same cost dimension. Capitalized VAT stays in
non-deductible dimensions. Self-assessed VAT uses reverse-charge AP codes and
balanced document/local pairs with the proper sides.
Positive document cents with both local sides zero are rejected explicitly:
the current M0 contract cannot retain their accounting direction. The caller
must preserve this diagnostic and abstain rather than drop the component.

Non-posting decisions carry no journal or coded lines. REJECT/HOLD need the
single winning policy reason; DUPLICATE needs another original `doc_id`.
NOT_INVOICE requires the policy's exact type/action pair. Payment block metadata
is valid only for POST_PAYMENT_BLOCK. Non-invoice types cannot become posting
rows merely because monetary fields are present.

`validate_ap_row` checks the same constraints for externally constructed rows.
`write_ap_jsonl(path, rows, expected_doc_ids=...)` requires exact task coverage,
without missing, extra or duplicate IDs, and validates every row before writing.
Sorted IDs and JSON keys make repeated exports stable. Exclusive atomic creation
is the default; `overwrite=True` uses atomic replacement. Failed validation
preserves an existing destination, and temporary files are always cleaned up.
Serialization performs no projected-ledger insertion or consumption-state commit.

The existing M0 comparator owns structural, accounting and optional golden
evaluation. Keep golden access in that evaluator boundary, never in this builder
or the engines. This core does not close #55: #41/#140 must supply all documents,
preserve factual evidence through decisions/coding and demonstrate full July
coverage and accounting comparison. A fixture export proves the deterministic
contract, not document-understanding accuracy.

```python
row = build_ap_row(
    doc_id=task_id, document_type="INVOICE", decision=payment.decision,
    header=resolved_header, lines=resolved_coded_lines,
    journal_entry=journal_result.journal_entry,
    payment_block=payment.payment_block,
    payee={"type": payment.payee} if payment.payee else None,
    context=master_context, tax_catalog=active_tax_catalog,
)
write_ap_jsonl(output_dir / "ap.jsonl", rows, expected_doc_ids=task_ids,
               context=master_context, tax_catalog=active_tax_catalog)
```

Focused checks: `.venv/bin/python -m unittest tests.test_ap_output
tests.test_ap_output_integration -v`. The integration fixtures exercise the real
allocation, valuation, fiscal, journal and payment factories through JSONL and M0
validation: ES/PT/MX treatments, original-imputation credits, foreign requests and
historical advance applications, explicit MULTI_PO with favorable price
differences, all notices and non-posting decisions. Additional regressions cover
document/local currency separation, per-dimension conservation, malformed scope,
coverage and atomic file behavior.
