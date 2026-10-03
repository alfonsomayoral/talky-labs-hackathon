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

For an active-phase delivery, use `ap_phase_export.write_phase_ap_jsonl` instead
of supplying an expected inventory manually. It reads exactly
`tasks/ap_documents.json`, validates distinct opaque IDs without altering them,
and passes that snapshot to the same row/coverage serializer. Attachment names,
folder contents, month and expected distributions do not determine task keys.
The output destination is separate from the read-only phase. Its returned
`APExportReceipt` records the phase, task-source hash, published output hash and row
count. No missing task receives a fabricated decision. An incomplete result set
fails before output creation/replacement. The inventory has no fixed 305/297
size and can be loaded independently with `load_ap_task_inventory`.

Rows are copied, validated and encoded once into immutable UTF-8 bytes. The
receipt hashes those exact publication bytes before writing; it never rereads
the destination after publication. A later concurrent overwrite cannot change
which publication the receipt describes. The task inventory is loaded again
after row generation and staging, immediately before atomic publication. A
changed inventory, even with identical IDs but different source bytes, aborts
without replacing the previous delivery. Source mutation after that check is
outside this snapshot; producers should use immutable phase inputs.

The output directory is opened before lazy row generation and held by file
descriptor. Directory components are opened without following symlinks, and
directory identity is checked again before publication. Temporary creation,
replacement/exclusive linking and cleanup use that pinned descriptor. A
redirection detected before publication aborts; a redirection at the atomic
operation cannot send writes into the source phase. The published file may then
live in the renamed destination directory, so its former pathname must not be
assumed current. Exclusive creation preserves another writer's winning file.

`verify_ap_export_receipt(receipt)` returns `True` only when the current canonical
task bytes and output bytes match the receipt and parsed output has exactly one
row per task. Changed hashes, counts, source names, coverage, missing files or
redirected output paths fail. Verification reads the output through its own
descriptor and rechecks task stability. It performs no provider calls, row
generation, journal posting or balance consumption. It verifies export identity
and coverage, not accounting provenance: the upstream run manifest must bind
facts, masters and rule versions to establish compatible replay. Concurrent
changes after verification remain possible; verification does not lock producers.

```python
from kalmora.ap_phase_export import verify_ap_export_receipt, write_phase_ap_jsonl

receipt = write_phase_ap_jsonl(
    output_dir / "ap.jsonl", resolved_rows, phase_path=active_phase,
    context=master_context, tax_catalog=active_tax_catalog,
)
verify_ap_export_receipt(receipt)
```

The phase-export regressions cover task-only inventory, independent phases,
multiple attachments per task, missing/extra/duplicate rows, action validation,
source preservation, hashes/repetition and real ES/PT/MX engine journals.
Controlled interleavings cover inventory changes during generation and staging,
concurrent output replacement/creation, directory redirection and publication
failures, plus receipt tampering. No threads or timing sleeps are required.
The source-only development check reads all 305 original task keys, without
generating pretend results for them or consulting golden. Full July evaluation
and the frozen September delivery remain separate acceptance requirements.

`kalmora.output_validation` provides the shared delivery-contract check used by
both export and the M0 comparator. The compatibility facade in
`evaluation.structure` preserves evaluator callers; export imports no evaluator.
The M0 comparator owns accounting diagnostics and optional golden evaluation.
Keep golden access in that evaluator boundary, never in this builder
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

Focused checks: `.venv/bin/python -m unittest discover -s tests -p 'test_ap_output*.py' -v`.
The integration fixtures exercise the real
allocation, valuation, fiscal, journal and payment factories through JSONL and M0
validation: ES/PT/MX treatments, original-imputation credits, foreign requests and
historical advance applications, explicit MULTI_PO with favorable price
differences, all notices and non-posting decisions. Additional regressions cover
document/local currency separation, per-dimension conservation, malformed scope,
coverage and atomic file behavior.
