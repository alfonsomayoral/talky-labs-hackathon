# AP source preparation — #140

`prepare_ap_sources(phase_path, destination, mode=..., extractor=..., transform=...)`
reads the exact AP task inventory and returns one source packet per task. Every
actual attachment is retained, including files absent from the message list;
missing declared attachments are reported. Message IDs must agree with task IDs.
Destinations, captures and run reports remain outside the source phase and Golden.
Messages without any document source remain incomplete and the command returns
a nonzero status; metadata alone does not establish a document's content.

Message JSON fields and supported Facturae 3.2.2 / CFDI 4.0 leaves are extracted
directly, without a provider. XML source fields, raw facts, normalized facts and
independent attachment classifications are saved with source SHA-256, locators,
parser/normalizer/extractor versions and page content/images. Unsupported XML,
PDF/text/image interpretation uses the shared `RecordedExtractor` boundary when
configured. In deterministic mode it remains explicitly UNKNOWN.

Facturae class codes are interpreted according to the official
[format field table](https://www.facturae.gob.es/content/dam/facturae/formato/versiones/Esquema_castellano_v3_2_x_06_06_2017_unificado.pdf):
OO/OC/CO/CC establish INVOICE; OR/CR establish CREDIT_NOTE. Copy classes do not
establish a duplicate accounting decision. Conflicting source hints/classes
remain CONFLICT; literals and their proof are retained without rewriting facts.

Source transforms may add native PDF images and unverified OCR aids, preserving
original source identity and every original page/block. Facts from another
attachment are rejected. Equal bytes at different paths retain separate origins.
Task, clock, source content and folder inventory are checked again before the
atomic `phase-sources.json` publication. Artifacts written before a failed
publication are tentative; they do not constitute a committed phase manifest.

Run metrics are separate from stable source identity. Matching record/replay
configurations use identical source packets, while provider calls/costs come from
recording provenance. Missing real recordings are not replaced with synthetic
fixtures. Fixtures are explicit and rejected by real replay mode.

The CLI entry point is source preparation, not an accounting solver:

```sh
kalmora prepare-ap PATH_TO_PHASE --state-dir OUTPUT_SOURCES
kalmora prepare-ap PATH_TO_PHASE --state-dir OUTPUT_REPLAY \
  --mode replay --captures CAPTURE_DIRECTORY --config residual-identity.json
```

Record mode additionally requires `--mode record --captures ... --config ...
--budget-usd ...`. The record settings file supplies the model, exact per-token
input/output rates, pricing provenance and optional `LLMConfig` parameters.
Budget comes exclusively from the explicitly authorized command argument.
`include_processing_aids` is an optional boolean. There are no default model or
price guesses. The resulting recording identity is saved outside the phase for
compatible replay; credentials stay in the environment. `--pdf-vision` applies
the existing bounded native-render/OCR processor and preserves source pages.

The command returns a nonzero status for uninterpreted sources or incomplete
task inventories. Its manifest has `accounting_run=false`. It produces no AP
decisions or journal entries and cannot by itself close M1, prove document quality,
claim July accounting comparison or validate September.
