# Source contract alignment (#222)

The production contracts are `APLineFacts.uom`, `APHeaderFacts`' separate
gross/payable fields, and the explicit date aliases in `ap_notice_bridge`.
Normalizer v3 and XML extractor v3 align source observations with those
contracts; these changes do not reinterpret archived v2 artifacts.

- Only a direct invoice row's `unit` aliases to `uom`. Header `unit`, raw
  labels and nested references retain their meaning. Differing `unit`/`uom`
  candidates become a conflict with both original proofs.
- `certificate_issued_on` aliases to `certificate_issue_date`; `issued_on`
  is normalized as a date under its own name. Existing `*_date`,
  `*valid_from` and `*valid_until` fields retain date normalization. These
  are observed dates accepted by the notice bridge, never dates inferred
  from reception, a title or a validity period. Mixed numeric date separators
  and ambiguous day/month order are rejected.
- An observed `taxable_base` uses cents, as other monetary source fields do.
  Decimal scaling and parenthesized negatives preserve exact source digits
  even when a caller's Decimal precision is low. Existing integer normalized
  units are retained without another scale conversion.
- Raw namespaces, including every `raw.xml.<exact leaf path>`, retain literal
  values and evidence without whitespace stripping or business conversion.
  Normalizing v3 facts again leaves their fields and version identity unchanged.
  Float candidates remain invalid, with the original retained in `raw`.

Facturae's header `ReceiverTransactionReference` explicitly denotes an order
reference and retains `po_reference`. Its line counterpart can identify an
operation, order or contract and remains `receiver_transaction_reference`.
Facturae `UnitOfMeasure` is a catalogue code and becomes `uom_code`, without
an ERP unit translation. `InvoiceTotal` remains the literal `raw.invoice_total`;
only the explicitly observed `TotalOutstandingAmount` supplies `payable`.
The [official Facturae field definitions](https://www.facturae.gob.es/content/dam/facturae/formato/versiones/Esquema_castellano_v3_2_x_06_06_2017_unificado.pdf)
define these distinct meanings (sections 3.1.2.10, 3.1.5.9, 3.1.5.14,
3.1.6.1.7 and 3.1.6.1.15).

CFDI's optional literal `Unidad` supplies `uom`; catalogue `ClaveUnidad`
supplies only `uom_code`. This distinction follows the
[SAT CFDI 4.0 definitions](https://wwwmat.sat.gob.mx/cs/Satellite?blobcol=urldata&blobkey=id&blobtable=MungoBlobs&blobwhere=1461176340698&ssbinary=true).
CFDI `Total` remains `payable`. Type codes remain literal raw hints interpreted
by the existing classifier; extraction adds no derived document type.

Gross is not copied from payable or calculated from other amounts. Missing
units, totals and source dates remain unknown. XML line counts remain outside
this change because accepted XML facts must equal original literal leaves;
a derived count requires a separate proof contract. An evaluation interface
that expects `unit`, gross from payable, or a derived XML count needs an
explicit, versioned boundary decision rather than altered source facts.

Previously prepared AP bundles explicitly pin XML/normalization versions and
will reject these new versions. Regenerate a bundle from the original sources
and retained accepted model recordings before using v3; XML remains local and
needs no paid extraction call. Preserve the old bundle and its frozen code for
historical replay. Do not replace its configuration/hash to bypass the version
check or silently call old normalized facts new observations.
