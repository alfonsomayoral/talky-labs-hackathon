# Deterministic AP coding recovery (#45)

Policy §1 assigns supplier defaults unless the document or purchase order says
otherwise; omitted policy detail comes from recorded ERP history. `ap_coding`
implements that boundary with account/fiscal precedence **document → confirmed PO
→ vendor master → contextual history when the master field is missing**. A known
current master treatment prevails over older historical treatment, unless explicit
document/PO facts override it. Cost objects use **document → PO → contextual history
→ an explicitly supplied vendor object**, with no inferred vendor object. It creates no entry,
eligibility decision or output row and reads no golden data.

`CodingRecord` is frozen and carries company/vendor/document currency, optional
account/tax code/reconciliation account, CC/WBS and immutable source evidence.
`withholding_codes=None` means unknown; `()` means explicitly no withholding.
Historical records additionally carry `recorded_on` and `context`.
`CodingQuery(company, vendor, currency, invoice_date, project=None, context=None)`
identifies the exact scope and optional independently resolved context/project.

`CodingCatalog.resolve(query, document=records, order=records)` returns a
`CodingResult` and five `FieldResolution` objects: account, tax code, supplier
account, cost object and withholding codes. A field's first populated tier wins.
Equal candidates retain all proof; distinct candidates at that tier remain
`AMBIGUOUS`. Invalid supplied values produce `INVALID`, never a lower-tier
fallback. A source missing a field permits fallback for that field only. A CC
and WBS are **one indivisible cost-object choice**, so the resolver never combines
a document CC with a PO WBS. Overall status is `RESOLVED`, `AMBIGUOUS`, `INVALID`
or `INCOMPLETE`. A complete `record` exists only when all five fields resolve.
Partial field results preserve usable facts and diagnostics for review.

The catalogue validates expense/asset accounts (2/6) and supplier accounts
(40000000/41000000/40300000) against the supplied chart, AP tax codes against the
company's country, and withholding codes against the supplied catalogue/policy
country. Vendor null withholding explicitly clears retention; an absent master
field remains missing. Known document or PO withholding treatment can override
the master, including an explicitly exempt line. The core does not calculate
quotas or decide whether an actual invoice omitted required withholding.

Cost centers must belong to the company. WBS identity is obtained from the
project master's nested WBS list, never guessed from a textual prefix. WBS must
belong to the company and, when the query provides a project, to that exact
project. A query with explicit construction project requires WBS. Missing cost
objects remain incomplete; company/vendor scope alone cannot justify copying a
past CC/PEP. Duplicate identities in supplied masters fail early.

History is considered only with a caller-provided exact concept context and
company/vendor/currency match. Matching normalizes case and whitespace only;
it does not infer an expanded concept from a shortened journal description.
Historical dates must be **strictly before** the target invoice date. Multiple
compatible candidates remain ambiguous whenever history is the winning tier,
regardless of frequency or recency. Historical context alone cannot override a
known current vendor account, tax code, supplier account or withholding treatment.
A current document can override one field while other fields still retain
historical uncertainty. No arbitrary latest-record or mode preference
is authorized by the policy.

`CodingCatalog.from_phase(PhaseData)` snapshots companies, vendors, chart,
cost centers, projects, tax codes and PO positions. It joins recorded
`ap_invoices` with journal entries by **company and journal id**, only for source
POST/POST_PAYMENT_BLOCK invoices. It reads expense/asset lines whose document
currency matches the invoice, retaining source line and AP document evidence.
The historical visibility date is the latest issue/receipt/posting date. Supplier
accounts come from the matching vendor's supplier lines; multiple supplier
accounts remain candidates. Invoice-wide withholding amounts are not invented
as per-line withholding codes. The vendor treatment remains an explicit fallback.

```python
catalog = CodingCatalog.from_phase(data)
# selected.order and selected.evidence come from a RESOLVED #43 result.
po_record = catalog.order_record(selected.order, evidence=selected.evidence)
result = catalog.resolve(
    CodingQuery(company, vendor, currency, invoice_date, project=project),
    document=normalized_document_coding_records,
    order=(po_record,),
)
```

`order_record` reads one explicitly confirmed PO position; it does not retrieve
candidates or split a MULTI_PO aggregate. Call the resolver per normalized
invoice line/PO portion, preserving the quantity allocation's original line
identity in the caller. Final quantity conservation and posting belong to #44,
#51 and #54. The caller must also complete identity and eligibility checks.

Known vendor company restrictions are validated before returning coding; a
1100-only vendor cannot supply relabelled defaults or overrides for 1910.
Legacy master inputs without affiliations require the caller's #42 identity
validation; this function does not infer company authorization from their absence.

Eleven synthetic tests cover current-master precedence over conflicting history,
explicit document/PO overrides, missing-master historical fallback, conflicts, compatible historical
ambiguity, strict dates, source joins, currency/company/vendor isolation,
account/tax/withholding validation, CC/WBS ownership, project mismatch,
immutable masters and missing context/object/withholding. Source-only smoke
validation loaded 6,343 expense/asset historical records from original July ERP
and resolved its explicit notarized-fee cost object without golden access. Account
and treatment in that case remain those of the current vendor master.

Normalized document facts/extraction (#41) and end-to-end phase adaptation remain
pending. This core supplies deterministic recovery but does not claim full July
AP output validation or issue closure.
