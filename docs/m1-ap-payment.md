# Payment metadata and simulated notices (#50)

`ap_payment.resolve_payment` takes duplicate/rejection/hold stage statuses,
explicit construction-subcontractor eligibility and the invoice event snapshot
from #46. Status arguments accept `DuplicateResult.status` and `RuleStage.status`
without importing or modifying #47/#48/#49 models. Duplicates precede rejection,
rejection precedes hold and all precede payment metadata. An earlier UNKNOWN
blocks a later conclusion. Preceding modules retain their own reasons/evidence.

After stages clear, a construction subcontractor with a confirmed expired or
absent article 43 certificate gets `POST_PAYMENT_BLOCK` and
`CONTRACTOR_CERTIFICATE_EXPIRED`. A valid certificate releases that block at the
inclusive invoice-date boundary. Other vendors do not need that certificate.
Missing eligibility/certificate evidence remains UNKNOWN when it can change
the result. Unknown event inventories cannot justify a default null payee.

A confirmed active assignment produces FACTOR. A confirmed embargo received
strictly before the invoice produces AEAT_EMBARGO. Neither condition produces
null when both are explicitly false. The manual does not define their
simultaneous precedence: both true gives internal UNKNOWN/PAYEE_CONFLICT, so no
legal priority is invented. This limitation has no known package example and
needs explicit policy clarification before outputting an overlapping case.

`apply_notice(document_type, event, state)` returns NOT_INVOICE with the action
from policy §2.1 and a new immutable simulated state. PROFORMA and VENDOR_STATEMENT
have action NONE. Other notices require explicit matching event kind and receipt;
certificates require both validity dates, assignments require validity start,
and bank changes require verified evidence and the exact replacement IBAN.
Incomplete/unverified notices give internal UNKNOWN, no action, and the original
state. Repeating the identical notice is idempotent; conflicting identities fail.
ERP and masters are never modified.

No journal entry or AP JSONL contract is produced here. These are internal
decision objects to integrate with extraction/identity (#41/#42), output contracts
(#32) and posting. NOT_INVOICE/HOLD/REJECT/DUPLICATE cannot cause entries in this
module. Full July decision/reason comparison is outstanding; golden is never
read by this module or its synthetic tests.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests -p
'test_ap_payment.py' -v` covers 10 policy tests for stage ordering, expired/valid
certificates, factor and embargo, overlap/unknowns, all notice actions,
idempotence, no mutation and scope isolation. This draft depends on #46/#49.
