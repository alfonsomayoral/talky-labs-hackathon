---
status: proposed
---

# AR billing ends in immutable typed results, not delivery dictionaries

The billing pipeline returns a list of frozen dataclass instances (one `BillingResult` per billing item, holding the invoice, its lines and the journal entry), and the `ar_billing.jsonl` rows are produced from them in a separate serialization step. Document reading is the only impure stage; every later stage is a pure function of resolved facts, masters and history. We accepted a second modelling style next to the existing `TypedDict` ERP shapes, and an extra mapping step, in exchange for validating invariants at construction (sums, one cost object per line, balanced entry) and for being able to test and compare results before any file is written. Building dictionaries directly would be shorter but would spread those checks across the serializer and leave nothing typed to hand to the evaluator or the later AR cash module.
