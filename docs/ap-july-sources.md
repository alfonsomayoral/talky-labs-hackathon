# AP inbox sources: record and replay

`kalmora.documents.ap_sources` covers every `inbox/ap/<doc_id>/` listed in
`tasks/ap_documents.json`. `DocumentRouter` parses each source. PDFs go through
`LLMDocumentExtractor` → `RecordedExtractor` → `StageRunner` (record mode).
XML uses the provider-free `XMLDocumentExtractor`, and `message.json` is read as
metadata. The state directory (outside git) holds `extraction-config.json`,
`recordings/`, `stages/`, and `runs/<uuid>.json`, which is the cost audit. One
configuration per state directory.

```sh
set -a; source /path/to/openai.env; set +a
.venv/bin/python -m kalmora.documents.ap_sources record <phase> <state> [--doc-id ID ...]
.venv/bin/python -m kalmora.documents.ap_sources replay <phase> <state>
```

Record defaults: `gpt-6-luna`, reasoning `low`, `image_detail=high`, USD 40
budget, concurrency 16, timeout 180 s and the conservative rates of
`tools/capture_document_sample.py`. Accepted captures are reused. A rerun retries
every recorded failure in the selection, so use `--doc-id` to retry only
transient ones.

`load_ap_sources(phase, state) -> dict[doc_id, APTaskSources]` is replay-only and
never constructs a client. `APTaskSources.message` (`APMessage`) carries
`received_at`, `channel`, `sender` (`from`), `to`, `subject`, `body`,
`attachments` and the full `raw` message. Each `APAttachment` carries `path`,
`document`, `facts`, `unknowns`, `normalized`, `classification` and `error`.
A missing or failed capture, or an XML/parse error, leaves `facts=None` with its
category in `error`.
