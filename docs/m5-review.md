# M5 v2 review and evidence

Refs #18, #19, #88–#94, #159. Local self-review, not an independent PR approval.

## Preservation and current source

The prior 20-file implementation was published unchanged in fork commit
`4ef3d576f1ba2323107dd863d645994069cbce97`, based on upstream backend
`8c38554f658d011d3250aebfa5fb4291c6495585`. Every file was byte-compared with
the previous delivery. Historical ZIP, patch and local commit log are retained.
The previous local commit `df0631...` was logged in that delivery, but its Git
objects were not included; the recovery does not falsely reuse its identity.

Commit `168c523529dee5c9f1aa0b6622d7caf3774f863e` adds read-only M5 CI for
Python 3.12/3.13. Its first run (37123410408) passed 220 discovered tests with
5 data-opt-in skips. The resulting source Git bundle was downloaded and verified,
so current-backend tests do not rely on a reconstructed or stale snapshot.
Subsequent M5 changes leave shared AP, bank, LLM and evaluation modules untouched.

## Fixed acceptance defects

The wrong-partner amount now follows the signed intended-pair residual. It is
-14,415,889 EUR cents for the supplied case, with independently constructed tests
for both signs, company orientations and local MXN. The financial reclassification
was already correct and is retained.

The AP/bank fixture adapter supplies explicit contracts outside the solver. It
certifies all 305 task/result/message IDs and dates, retaining held, rejected,
duplicate and unposted receipts. Unknown issuer is not confused with an external
supplier. Earlier received-but-unposted invoices are covered by the AP log.
Missing dates, IDs, partial inventories and conflicts are rejected.

The source-backed transit at 1000→1200 now reports 18,058,040 EUR cents and
posts net expense 14,924,000 cents against 40090000 with issuer 1000. The allocation
comes from the receiver's supported history, not the emitter's gross or CC.

Pooling links statement BL0005652 to its unique ERP mirror
1000-2026-3000000155 / CP2607221200 and the mock bank correction. Original pair
residual -27,053,177 cents becomes zero in the before-IC projection. The bank
owner is applied once; IC never emits a pooling journal.

## Newly exposed source/reference disagreement

After freezing source and output, the original scorer and current shared #35
comparator agree: **0.8615, all 5 expected rows detected**. All required fields and
all additional reference line fields of those 5 rows match exactly. However,
there are **3 unexpected INVOICE_IN_TRANSIT rows**, so whole-output acceptance
fails. This is separate from the real-engine gate.

| Source invoice | Issuer → receiver | Net EUR cents | Source emitter entry |
| --- | --- | ---: | --- |
| IC1000-26-0034 | 1000 → 2100 | 3411200 | 1000-2026-1800000034 |
| IC1000-26-0035 | 1000 → 3100 | 4316000 | 1000-2026-1800000035 |
| IC1100-26-0007 | 1100 → 1910 | 5693200 | 1100-2026-1800000007 |

All three are posted as issued invoices on July 31. The complete current receipt
inventory, historical AP log, AP register, original receiver journal and supplied
IC-relevant AP entries contain no matching receipt/posting/accrual by the close.
Policy §6 requires accrual of issued nonreceived invoices; it supplies no grace
period or exception for these pairs. The module therefore retains these findings.
The source/policy/reference disagreement needs owner resolution; it is not hidden
by filtering to reference keys or forcing a five-row output. The evidence bundle
contains source-transit-discrepancies.json with the exact positive/negative joins.

The resulting delta has 6 AP-owned entries, 56 bank-owned entries and 7 IC entries
(4 expected corrections plus 3 additional transits). It is not claimed to match
the complete benchmark or to complete the AP/bank engines.

## Validation scope

The development environment is Python 3.13.5. The standard current-backend suite
passes 243 tests discovered, with 5 opt-in data checks skipped by default. Those
5 checks were also run against the actual package separately: recorded accounting,
shared comparison, AP tax, AP withholding and M5 original/replayed ERP. All pass.
An attempted combined opt-in run hit the execution time limit; its partial log
is retained and is not presented as a completed all-in-one run.

The separate isolated fixture runs use the actual source ERP and mock dependency
outputs. Their open-audit guard denies reference, scorer and ZIP access. Two
fresh runs produce identical IC bytes; replay on the corrected projection emits
no new IC adjustments, retains a single bank pooling owner and preserves both
original and corrected ledger hashes. These are simulated integration checks,
not a golden-free run of real AP/bank engines.

Original package SHA-256:
`c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`

IC submission SHA-256:
`599cd3f5759b16113b8808690a135b3447c710ecfc270b189eee30913f98b71b`

Declared AP projection scope is intercompany: all 6 relevant entries of 242
posted fixture entries. Receipt coverage still covers all 305 documents. The
other 236 entries are inventoried, not represented as projected. Full AP mode
rejects the non-IC reference advance line with missing partner instead of silently
repairing it or weakening the shared validator. All 56 bank corrections are used.

## Delivery and open gates

Fork publication works after installation 167510256 was authorized. Creating a
PR in upstream returned 403 on POST /repos/alfonsomayoral/talky-labs-hackathon/pulls;
the effective connector installation is limited to the fork. No upstream PR,
independent approval or squash integration is claimed without further evidence.

M5 and epics #18/#19 remain open. #159 requires actual AP #55 receipt/export
outputs, bank #73/#75 corrections, unchanged source/ownership, repeatability and
full evaluation. #94 additionally retains the three source/reference differences.
The sign defect in #92 is fixed locally/remotely as recorded by the final commit;
fixture validation alone does not automatically close that issue or any other.
