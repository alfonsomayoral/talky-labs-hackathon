# M2 source workflow — #56, #57 and #9

Functional M2 closure was authorized by the user using the working v0 convention,
with M1 integration deferred to #140. The implementation connects original AR
documents, shared capture/replay, exact/bounded reference resolution and the typed
billing engine. It does not close M1 or claim September/provider acceptance.

## Results

- July: 26/26 tasks resolved, 25 invoices, one pending certification and one WIP
  input; no unresolved task and no reposting of historical transactions.
- All five support types are covered; 18 invoices retain FACe information.
- Both delivered JSONL files are byte-identical on native record/replay, with
  zero provider calls and zero actual cost. No callback or v0 fallback is allowed
  on replay.
- The isolated official `score_ar_billing` result is **1.0**, 26 items answered.
  Output hashes were frozen before opening golden in the evaluator. This is the
  AR billing module score, not a global close score or field-extraction metric.
- Seven pre-existing reviewed development annotations match every annotated
  typed fact and their original attachment hashes. Market MWh was unannotated;
  the native reader additionally retains the three observed optional columns.
  This is a development comparison, not a held-out model benchmark.
- All 25 invoice numbers match v0 over the same ERP inventory. Invoice numbers,
  journal references and 430 assignments agree, including `SU26-00107…00116`.
- `close --module ar_billing` succeeds and archives the source report/captures in
  `trace/ar_billing.zip`; the trace retains original evidence for every task.
- All 830 imported original files retain their manifest SHA-256 values.
- Focused billing regression suite: **84 tests, 83 passed, one skipped**. The
  existing annotated-engine golden test was skipped because that development
  source view has no golden; the new source delivery was evaluated separately.

Tests cover missing/conflicting sources, explicit zero extras and complete tables,
approval/pending behavior, exact units, source/master proof binding, semantic
selection and abstention with a fake response-aware adapter, capture corruption,
normalizer/master invalidation with no callbacks, publication rollback and guards
against source-contained outputs and symlinks. No live model was called.

## Reproduction

Use Python 3.12 and the optional document dependencies. The verification runtime
was Python 3.12.14 with pypdf 6.10.0; the repository's pinned optional dependency
set was not installed for this local run. Capture identity includes the actual
parser/transformation configuration, so other configurations require fresh capture.

```sh
PYTHONPATH=src python -m kalmora solve-ar-billing data/julio/participant/phase_dev \
  --output outputs/m2-final/record/ar_billing.jsonl --work-dir outputs/m2-final/state
PYTHONPATH=src python -m kalmora solve-ar-billing data/julio/participant/phase_dev \
  --output outputs/m2-final/replay/ar_billing.jsonl --work-dir outputs/m2-final/state --mode replay
PYTHONPATH=src python -m kalmora close data/julio/participant/phase_dev \
  --out outputs/m2-final/close --module ar_billing
PYTHONPATH=src KALMORA_PHASE_DEV=data/m2-julio/participant/phase_dev \
  python -m unittest discover -s tests -p 'test_billing*.py' -q
```

`data/julio` is the complete immutable imported package. `data/m2-julio` is a
development source view with original ERP/AR inputs and no golden. Existing reader
regressions also use source-hash-checked ParsedDocument snapshots generated from
those PDFs. Neither annotations nor snapshots feed the production source runner.
The evaluator separately loads the unchanged organizer scorer and
`phase_dev/golden/ar_billing.jsonl` after the deliveries are frozen.

## Reproduction fingerprints and limits

The exact fingerprints, coverage, annotation comparison and environment are in
[m2-source-workflow.json](m2-source-workflow.json). Source ZIP SHA-256:
`c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`.

Unknown/scanned layouts remain unresolved. The optional LLM DTO/prompt and bounded
semantic recording path have injected-client checks; live provider quality is
unevaluated. The existing M6 WIP handoff separately expects `documento.pdf` and
both pending phrases; the broader M2 attachment interface does not establish
general M6 attachment compatibility. M1/#140 remains open.
