# Billing taxes and deductions core — partial #63

`kalmora.billing_deductions.calculate_billing_amounts` receives resolved billable
`BillingBaseLine` cents and explicit `BillingTerms`: tax code, guarantee basis
points, Mexican 5-per-mille flag and advance rate (zero or policy 3000 bp).
No missing contract condition becomes an inferred default. Each input and advance
state carries company, currency, contract and customer in `BillingScope`.

Policy authority: `POLITICAS_CONTABLES.md` §§1 and 3.1, with Portuguese rates and
jurisdictions confirmed against `phase_dev/erp/tax_codes.json`. Supported rates:
R21 21%, R10 10%, RISP 0%, PR06 6%, PR23 23%, PRAUT 0%, MR16 16%. RISP includes
the policy-required article reference; PRAUT charges no output VAT to the customer.
Tax applicability is already resolved upstream; this module verifies jurisdiction,
not whether the underlying activity qualifies for its selected code.

## Calculation and invariants

VAT rounds HALF_UP independently per billable base line, using M0 `round_cents`.
Guarantee uses the contract rate on total base (500 bp gives the policy 5%). Each
invoice-level deduction rounds independently. Mexican inspection levy is 50 bp
(0.5%) on total base, debit 63100000. Mexican advance amortization is 3000 bp
(30%) on total **including VAT**, capped at the explicit available advance.

The typed result includes base, VAT, gross, guarantee, levy, advance, payable,
deduction accounts/partners and a tentative new advance state. It conserves:
`payable + guarantee + levy + advance == base + VAT`. Guarantees use 43000900
with customer; advances use 43800000 with customer. Impossible deductions causing
negative payable, negative bases and noninteger cents are rejected. No credit-note
or advance replenishment/reversal behavior is inferred.

`AdvanceState.available_cents` is the remaining balance **after** its history.
`advance_from_history` can build it from explicit original receipts and prior
applications. History is not subtracted again on billing. Applications are immutable,
chronological and keyed by invoice; repeats and older invoices fail. Exhaustion
records a zero application to retain replay protection. State is tentative: persist
only after complete posting, with serialized updates to prevent stale-state reuse.

## Connections still pending

- #58: eligibility, period/approval and general refacturation checks.
- #59–#62: actual certified/service/revision/energy base lines. Synthetic tests
  substitute explicit bases, without building or interpreting those workflows.
- Contract/customer adapters: correct tax applicability, contractual conditions
  and master validation; explicit advance receipt/application history or balance.
- #64/#32: dates, invoice legend rendering, revenue CC/PEP, full journal, FACe,
  output contracts and FX where applicable. Amounts in this core stay in the
  supplied currency; foreign advances must be resolved into that same currency
  before invocation, and are never mixed with other balances implicitly.

Synthetic tests independently calculate all seven rates, guarantee and levy
rounding boundaries, gross-based amortization and capped exhaustion. Net/tax and
deduction fixtures balance through M0 validation. No solver/test reads golden.
