# Assistant evals

Implements `docs/design/chat-agent-evals.md`. Everything here is invented data; real-data cases are generated locally.

```
python -m evals.assistant list [--suite A,B] [--star]        # the cases, as JSON lines
python -m evals.assistant selfcheck                          # every case against its reference answer (no model): graders accept a right answer
python -m evals.assistant negcheck                           # a content-free answer: lists graders that accept it (should be only E06)
python -m evals.assistant t0t1                               # the deterministic suites (tests/test_assistant*.py)
python -m evals.assistant run --provider ollama --model qwen3:14b --k 3 --star          # synthetic fixture, live model
python -m evals.assistant run --private <participant>/phase_dev --run-dir <api run dir> \
    --live-mcp http://127.0.0.1:8010/mcp/ --provider ollama --model qwen3:14b --star     # real data through a running API
```

* `fixtures.py` builds the synthetic phase, the run bundles (with and without trace, running, failed, missing a file, with a
  defect) and the injection variants. Injection payloads ask the model to *build* the canary word, so quoting the data is never
  a failure.
* `oracles.py` computes expected values from the raw files; it never calls the MCP tools.
* `graders.py` holds the code graders; `cases.py` the catalogue (parameterised by the data it asks about);
  `private.py` samples the entities from a real phase and writes stand-in run bundles (copies of the golden, which the
  assistant is never shown).
* `harness.py` builds a world (API services over the fixtures) and drives the assistant; `run.py` is the runner and report
  (pass^k, pass@k, latency, tool calls, tokens, cost, K06 secrets scan).

Output: `outputs/evals/assistant/<timestamp>/report.json` and `report.md`.
