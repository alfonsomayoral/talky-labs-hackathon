# Issue #54: independent module acceptance

The issue's accounting scope is original imputation for credits, an approved PO
for a foreign advance request, application at the advance's historical carrying
amount, and the applicable cost or exchange difference. Those capabilities are
implemented and independently validated. Acceptance of this module does not
claim a complete monthly transaction runner or require linking every historical
KG in the package.

The authoritative rules are `POLITICAS_CONTABLES.md` §1–2: invoice-date conversion
and per-line rounding, supplier partners on the AP auxiliary accounts, inverse
credit imputation to the original account/cost object, Dr407/Cr400 for the approved
foreign request, and application of advances at historical exchange rates. The
accepted documentary base and existing v0 implementation may provide resolved
inputs; the monetary module does not reclassify their extraction as a missing
implementation dependency.

## Criterion matrix

| Criterion | Code | Source and reproducible validation | Result |
| --- | --- | --- | --- |
| Original account, partner, CC/WBS and amount for a credit | `ap_credit_sources.CreditOriginalCatalog`, `ap_credit_bindings.resolve_credit_line_bindings`, `ap_journal.build_ap_journal`, `ap_credit_delivery.build_ap_credit_delivery`; existing `v0.proto.original_coding` also accepts originals published in the same phase | Exact July XML references and original ERP journals; `test_ap_credit_sources`, `test_ap_credit_bindings`, credit journal and delivery tests. The separate owned-row evaluator records two real rows with exact account/partner/CC/WBS, currency, document cents and assignment, with no scored/unscored differences | Implemented. Two owned original-source rows match exactly. The preserved v0 reference comparison also records all nine July credits as exact, with zero scored/unscored differences |
| Approved PO and resolved foreign supplier for a request | `ap_advance_sources.resolve_advance_sources`, `AdvanceApproval`, `ap_journal.build_down_payment_request` | Exact documentary PO, active PO/vendor/company masters; `test_ap_advance_sources` checks approval/scope/identity contradictions, absent approval and unknowns. `test_foreign_request_needs_approved_order_and_partner_on_407` verifies Dr407/Cr400 and the supplier on both legs | Implemented and validated for resolved approved inputs. No nonexistent ERP approval field is claimed; the new request's approval remains a source-binding condition, described below |
| Apply advances at historical carrying amounts | `ap_advance_history.resolve_historical_advances`, `ap_advance_bindings.resolve_advance_applications`, `ap_journal.build_ap_journal` | Original deposit/application journals, PO positions and AP headers. `test_three_original_imports_preserve_historical_non_monetary_cost` reproduces all three original import applications by account/partner/CC/WBS/local cents. History and journal tests cover partial exhaustion and cumulative rounding | Implemented. All three original carrying/application reproductions match; exhausted balances remain exhausted without reposting or repairing ERP |
| Cost or exchange difference when appropriate | `ap_journal.build_ap_journal`, explicit `AdvanceApplication` classification and `CreditAdvanceRestoration` | `test_non_monetary_historical_carrying_adjusts_cost_without_fx`, `test_monetary_settlement_records_gain_or_loss_only_when_evidenced`, partial-carry and restoration tests; original import applications corroborate the non-monetary cost treatment | Implemented. Explicit non-monetary treatment adjusts the bound cost object; monetary treatment records the applicable FX gain/loss. Zero delta does not invent classification |
| Preserve Debe/Haber, document/local cents, scope and rollback | `ap_credit_state`, `ap_restoration.prepare_ap_credit_restoration`, `ap_credit_delivery.build_ap_credit_delivery` | Partial/full credits, tax/withholding/guarantee limits, foreign locally booked 407, same-deposit/different-PO associations, quantity-backed receipt restoration, fully prepaid originals and failed output validation | Implemented. New consumption/restoration remains tentative until real row validation succeeds; failure does not mutate any input snapshot |
| Reproducible evidence, Golden confined to evaluation | Source-bound module tests; separate captured-row and v0 evaluator artifacts | 89 focused tests pass with the original July ERP. `owned-credit-evaluation/production-proof.json` records 64 unchanged original sources and no producer Golden access; its separate evaluation reports 2/2 exact. The preserved v0 evaluator reports 9/9 credits exact without serving reference data to the solver | Satisfied for independent module acceptance. Neither subset comparison nor v0's AP metric is a full monthly acceptance claim |

The matrix describes module functionality and its evidence. The separate v0
evaluation still preserves its missing open-item partner in the foreign advance
request and the corresponding `ENTRY_RULE` and `REFERENCE_ENTRY_RULE`; an exact
scorer result does not erase those diagnostics. Our request builder resolves the
supplier generally and puts it on both 407 and 400; originals remain unchanged.

## Original references in the same phase

The July documents include six credit references that match ordinary invoices in
the same task phase by literal number and company/vendor/currency. Existing v0
uses those published invoices before falling back to the initial ERP journal.
Therefore a reference absent from the initial historical catalog is not globally
missing: in particular, the third Corrective XML reference has a same-phase
original. The historical-catalog test's `NOT_FOUND` describes only that catalog.

No new publication adapter is required to accept this existing route. Converting
an arbitrary v0 row into a recorded ERP journal would require publication
identity/clock and original allocation metadata that its minimal journal does
not carry; those values must not be fabricated. Adoption of resolved sources and
our journal/state snapshots by the monthly runner belongs to #140.

## Approval evidence and boundaries

The July canonical PO inventory contains 655 rows with company, creation date,
currency, identity, items, project, purchasing group, requester, text, type and
vendor. It has no `approved`, release or status field. The new request PDF and
body do not add an explicit approval statement. This is not a requirement to add
an approval column to the package, and this module does not claim to have read
one. Nor does an old posted application prove approval of a different new PO.

Approval can be supplied under the accepted source contract as an evidenced
authorization for the exact PO. The API verifies that binding and rejects false,
unknown or contradictory approval. Establishing the authorization represented by
the accepted documentary base is an upstream source/integration responsibility;
it is not an unimplemented journal calculation. PO existence alone is not
rewritten as an observed boolean approval.

Historical consumption/restoration APIs remain available when their inputs are
needed. Missing original links, restored quantities or classifications correctly
remain unknown for the affected operation. The 56 historical KG without original
links do not make the independent accounting capabilities unimplemented, and
linking all of them is not a literal issue #54 acceptance criterion. Likewise,
global restoration and a complete monthly state runner are not added conditions
for accepting this module. #140 owns atomic adoption of advance, receipt and
restoration snapshots and the production of its resolved transaction requests.

## Focused reproduction and evaluation artifacts

The focused module run completed **89 tests, all passing**. A subsequent
original-source interoperability regression also passed: it routes the two XML
credits through the real typed transaction factories twice from each original
opening snapshot, compares their full rows to the credit finalizer, and rejects
both repeated publications. The command below now includes this additional case:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp \
.venv/bin/python -m unittest test_ap_credit_sources test_ap_credit_bindings \
  test_ap_advance_sources test_ap_advance_bindings test_ap_credit_history \
  test_ap_restoration test_ap_credit_delivery test_ap_advance_history \
  test_ap_journal -q
```

Evaluation evidence is preserved separately from the module's inputs:

- [Owned two-credit evaluation](../outputs/m1-owned-validation/owned-credit-evaluation/evaluation.json)
  and [producer proof](../outputs/m1-owned-validation/owned-credit-evaluation/production-proof.json):
  `PARTIAL_OWNED_2_CREDITS`, 2/2 exact, `monthly_score=null`, no monthly coverage
  or issue-closure claim in the artifact.
- [Preserved v0 July evaluation](../outputs/m1-owned-validation/integrated-producer/july-final-evaluation.json):
  its nine credit-note entities are exact, with zero scored/unscored differences.
  This is existing evaluator evidence, not a newly executed full-phase run.
- [Original-source transaction replay](../outputs/m1-owned-validation/owned-credit-replay/proof.json):
  two actual credit requests, identical repeated transaction outcomes, two
  rejected repeated publications, 82 unchanged original source files, no network
  or Golden access attempts, and zero provider calls. Reproduce the regression
  with `test_ap_credit_bindings.CreditBindingSourceTests.test_original_credit_deliveries_match_provider_free_transaction_replay`
  under the same ERP environment shown above. This proves replay for these two
  resolved transactions, not monthly policy decisions or receipt/407 integration.

Recommended disposition: accept and close issue #54's independent module scope
with this matrix and the existing implementation/evaluation evidence. Keep the
stated source conditions and #140 integration work explicit; do not represent
this recommendation as monthly accounting acceptance.
