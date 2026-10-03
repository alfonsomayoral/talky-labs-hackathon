# Chat agent (assistant): design record

Working record, `/autogrill-with-docs`. Questions are written before they are researched; decisions are appended under each question with their evidence. Companion documents: [harness](chat-agent-harness.md) (what the agent is told and which tools it uses) and [evals](chat-agent-evals.md) (how it is tested).

Status: **implemented (see "Revision 1" at the end); first evals run against local Ollama on the competition data**.

Goal (from the request): define the implementation and design plan for the chat agent, its harness so that it understands the accounting concepts of the project and knows which MCP tools to use, and the list of evals to test it.

## Known facts (observed, not decided)

**Front end (`origin/main`, `app/`)**
- The Assistant has two modes. **Fast** is a local rules engine: `detectIntent` recognises `summary`, `review`, `balance`, `cost`, `process`, `explain` (an item id), `bank` and `unknown` with regexes, and answers with typed cards computed in the browser. **Deep** is, in development only, a Vite middleware (`app/dev/assistantChat.ts`) that calls an OpenAI Responses model: the model writes 2 to 5 plain Spanish sentences **over the local answer sent as `context`**, so figures, cards and citations stay the browser's and cannot drift.
- `app/CONTRACT.md` section 2 keeps one backend route as valid: `POST /api/chat` with `{run_id, dataset_id, messages: [{role, content}], mode: "fast"|"deep"}`, answered by SSE: `event: delta` `{text}`, `event: card` (types `metric`, `table`, `items`, `reasoning`, `process`), `event: citation` `{item}` or `{policy_ref}`, `event: done`. It uses its own variable, `VITE_CHAT_URL`. Unknown card types are dropped by the app.
- Item ids are `<task>:<key>` (`ap:API004151`, `bank_rec:BIN-1100/BL0000650`, `ic:1000-1100/INTEREST_DAY_COUNT`, ...). Human corrections are exported as `overrides.jsonl`.

**Back end (`backend`, worktree `talky-labs-hackathon-api`, uncommitted)**
- 28 read-only MCP tools over the same use cases as the HTTP API (stdio and Streamable HTTP), returning `{data, meta}` with `meta.sources` (file path + sha256). Lists default to 25 and cap at 100 rows. Errors carry a stable `code`. No tool writes.
- Run bundles (`deliverables/`, `trace/events.jsonl`, `trace/attention.jsonl`, `manifest.json`, `overrides.jsonl`) are readable through the API, but **no module in `src/` writes `trace/` yet** and there is no orchestrator (M7-01, #105). Today a run's explanation is limited to its delivered row, the policies and the data.
- `kalmora.llm.client` makes **one structured request, with no tools and no agent loop** (`retries=0`, `store=False`), with explicit budget, rates and provenance of prices, recorded in `RunRecorder`. The model is chosen by the caller. A conversational agent needs a tool loop, which this client does not provide.
- Knowledge available as text: `participant/POLITICAS_CONTABLES.md` (184 lines, Spanish, sections 1 to 6; evidence cites `policy_ref` such as `§2.2.3`), `CONTEXT.md` (164 lines, English glossary), `knowledge/` (workflows, course reference, playbook).
- ADR 0001: the golden is evaluator-side only. `phase_test` has no golden. Source data (vendor invoices, bank narratives, inbox files) is untrusted text.
- Scoring comes only from the six delivery files; the assistant earns no points, so it must not compete with M1 to M7 for time.
- `AGENTS.md`: no tests unless asked. Here the evals are explicitly requested, as a **list** (this document defines them; it does not implement them).

## Questions

### Q1. What must the agent do, for whom, and what must it refuse?
*Why it matters:* every later choice (tools, harness, evals) hangs from the scope. The front already answers eight intents locally; the agent must add value beyond them.
*Owner:* product (the user). *Acceptance:* a list of jobs, each traceable to MCP tools or to the policies, and a list of explicit refusals.

### Q2. How does the agent relate to the front's existing fast and deep modes?
*Why it matters:* the app already guarantees that figures cannot drift from the screens; replacing it carelessly would lose that guarantee.
*Acceptance:* which mode the agent replaces or extends, and the rule that keeps numbers equal to the app's.

### Q3. What is the deployment topology?
*Why it matters:* earlier discussion leaned to "same repository, separate process, MCP as the boundary"; it must be confirmed with its costs (second copy of the data, secrets, CORS, SSE).
*Acceptance:* processes, the transport to the tools, where the model key lives, and the route the front calls.

### Q4. Which model provider and which agent runtime?
*Why it matters:* the repository's client is OpenAI-only and tool-less; the platform guidance is to use the newest capable models; a runtime choice (own loop, a framework, a vendor SDK) decides lock-in and testability.
*Acceptance:* a provider-neutral port, a default model per mode, and the loop implementation with its dependency cost.

### Q5. How does the agent learn the accounting concepts (harness knowledge)?
*Why it matters:* the policies and the glossary are the authority; the model's own accounting knowledge is a risk, not a source. Context size, freshness, language (policies are Spanish, glossary English) and citations all depend on it.
*Acceptance:* what is placed in the prompt, what is retrieved by a tool, how it is versioned, and how an answer cites it.

### Q6. What are the behavioural rules of the harness?
*Why it matters:* grounding, arithmetic, uncertainty, language, tone, length and response format are what separate a useful reviewer from a confident fabricator.
*Acceptance:* a system prompt skeleton whose every rule is testable by an eval.

### Q7. Which MCP tools does the agent use, for which question, and what must change in the tool surface?
*Why it matters:* 28 tools is a large menu; tool descriptions, result size and composite tools decide accuracy and cost.
*Acceptance:* a playbook mapping question types to tool sequences, the tools to expose or hide, and the new tools justified by a failing case.

### Q8. How is the answer produced in the app's typed format (text, cards, citations)?
*Why it matters:* the app only renders the five card types and cites `item` or `policy_ref`; who builds the cards decides whether numbers can be trusted.
*Acceptance:* the production path from tool results to SSE events, with the invariant that every figure shown comes from a tool result.

### Q9. How is the agent protected from hostile or accidental inputs?
*Why it matters:* documents, bank narratives and notes are untrusted text that a model will read; a tool-using agent can be steered by them. The golden and `phase_test` boundaries must hold.
*Acceptance:* a threat list, the controls for each, and the evals that prove them.

### Q10. How is conversation state, scope and context managed?
*Why it matters:* the app sends the messages; which dataset and run the question is about, long histories and tool-result bulk all consume context.
*Acceptance:* what the request carries, what the server keeps, and the limits.

### Q11. How are cost, latency and behaviour observed?
*Why it matters:* the project already audits model spend per run; an agent loop can multiply calls.
*Acceptance:* budgets per turn, a turn trace, and what is recorded without leaking data.

### Q12. What evals prove the agent, and how are they built without leaking the golden?
*Why it matters:* an agent without evals cannot be changed safely. Cases must come from the real data, the golden may only be used as an offline reference, and `phase_test` has no answers.
*Acceptance:* a taxonomy, a catalogue of cases with graders and thresholds, the data each uses, and how they run (offline, CI, before release).

### Q13. What depends on work that does not exist yet?
*Why it matters:* the "why did the engine decide this?" answers need `trace/`, which nothing writes.
*Acceptance:* what ships now, what ships with the orchestrator, and how the agent degrades honestly meanwhile.

### Q14. Can the agent change anything (propose or record overrides)?
*Why it matters:* the MCP server is read-only on purpose; a human override is a decision with consequences.
*Acceptance:* a stated write policy and, if any, the human confirmation step.

### Q15. Where does it live in the repository and in the milestones, and what is the implementation scope?
*Why it matters:* M8 covers the HTTP API; the agent is a separate deliverable that must not slow the scored work.
*Acceptance:* module boundaries, a milestone and issue breakdown, ordered slices, and an approval gate.

## Evidence

Sources are primary (vendor and standards documentation) unless marked.

- **Tool design.** Anthropic, [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents): consolidate to a few high-impact tools instead of one per endpoint; namespace related tools; return concise high-signal data with an optional detailed format (a concise Slack result used 72 tokens against 206); cap responses (Claude Code caps tool responses at 25,000 tokens); return actionable error messages; write descriptions "as for a new team member"; evaluate tools with realistic multi-call tasks and a held-out set.
- **Context.** Anthropic, "Effective context engineering for AI agents" (read through secondary summaries in the search results, not fetched): keep identifiers light and load data just in time through tools; the system prompt should sit at the right altitude, neither brittle rules nor vague guidance; unpruned history degrades retrieval accuracy.
- **Evals.** Anthropic, [Demystifying evals for AI agents](https://anthropic.com/engineering/demystifying-evals-for-ai-agents): task, trial, grader, transcript, outcome; code-based graders for objective checks, model-based for nuance (non-deterministic, needs human calibration), human as gold standard; capability evals (low pass rate) versus regression evals (about 100%); `pass@k` versus `pass^k` (all trials succeed); start with 20 to 50 tasks drawn from real failures; clean isolated state per trial; grade outcomes, not paths; give LLM judges an "Unknown" escape; conversational agents are judged on completion, interaction quality and efficiency and need a simulated user for multi-turn tests.
- **Judges.** Search results on LLM-as-judge ([deepeval citation faithfulness](https://deepeval.com/docs/metrics-citation-faithfulness) and recent ACL/arXiv work): judges are biased by length and self-style and inconsistent; decompose into rubric criteria and treat any single verdict as uncertain.
- **Prompt injection.** Anthropic, [Mitigate jailbreaks and prompt injections](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks): deliver untrusted content only inside `tool_result` blocks; say in the tool description or result where it came from; state in the system prompt that tool content is data; JSON-encode third-party strings; do not put your own instructions in tool results; least privilege; optionally screen tool output with a small model; red-team before release. [OWASP LLM01 and LLM06 (2025)](https://genai.owasp.org/llmrisk/llm06/): minimise extensions and their functionality, enforce authorization downstream not in the model, require human approval for high-impact actions, segregate external content. Simon Willison, [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/): private data + untrusted content + external communication is the dangerous combination; remove one.
- **MCP into the model API.** [Claude MCP connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector): beta, the MCP server must be publicly reachable over HTTP (local stdio servers cannot be used), only tool calls are supported, and it is not eligible for zero data retention. Our MCP server is local and private, so the connector does not apply: the assistant must be an MCP **client** that hands the tool list to the model itself.
- **Loop.** [Tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner): automates the loop (beta), supports `max_iterations` and streaming, and recommends the manual loop when you need human-in-the-loop, custom logging or conditional execution. [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming): `content_block_delta` with `text_delta` and `input_json_delta` events.
- **Models and cost.** [Models overview](https://platform.claude.com/docs/en/models/overview): Sonnet 5.5 (`claude-sonnet-5-5`) $2 / $10 per million input / output tokens, 1M context, adaptive thinking, default effort `high`; Opus 5.5 (`claude-opus-5-5`) $4 / $20, default effort `medium`; Haiku 4.5 (`claude-haiku-4-5-20251001`) $1 / $5, 200K context; one million tokens is about 555k words, so 1.8 tokens per word. [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching): up to 4 breakpoints; minimum 512 tokens on Sonnet 5.5 and Opus 5.5; 5-minute TTL (write 1.25x) or 1-hour (write 2x); reads cost 0.1x (0.05x on Opus 5.5); order `tools` then `system` then `messages`, so a change to tool definitions invalidates everything; automatic caching moves the breakpoint forward in multi-turn use.
- **Measured here.**
  - `POLITICAS_CONTABLES.md` 2,352 words and `CONTEXT.md` 1,113 words and the close workflows 602 words: about 4,100 + 2,000 + 1,100 tokens at 1.8 tokens per word, so the whole knowledge is **about 7,000 tokens**.
  - The 28 MCP tool definitions: 15,998 characters, about **4,000 tokens**.
  - The front ignores SSE events it does not know (`else continue` in `streamChat`), treats `event: error` as a failure, and accepts `message` as a delta. Cards of unknown type are dropped.
  - The front's backend path (`VITE_CHAT_URL` set) has **no local fallback** when the request fails; its dev path does.

## Decisions

### Q1. Scope
**Decision.** The assistant is a **read-only reviewer's aide** for one loaded phase and, optionally, one run on the server. Jobs:

| Job | Example | Main sources |
|---|---|---|
| J1 Close status | "¿Cómo ha ido el cierre?" | run summary, deliverables, attention |
| J2 Review queue | "¿Qué reviso primero?" | attention by priority and impact |
| J3 Explain an item | "¿Por qué se retuvo `ap:API004151`?" | item row, trace if any, policy |
| J4 Book lookups | balances, open items, entries, bank lines, FX | ledger tools |
| J5 Consistency | "¿Cuadra el balance?" | balance summary, load report |
| J6 Bank view | unmatched items by category | bank tools, `bank_rec` rows |
| J7 Concepts | "¿Qué es una partida abierta?" | knowledge pack, with citation |
| J8 What if | "¿Qué pasa si registro este asiento?" | `validate_entry`, `simulate_entry` |
| J9 Cost and runs | "¿Cuánto costó este cierre?" | run manifest |

**Refuses** (and says why in one sentence): approving, overriding, posting or launching anything; showing or inferring the golden, or a score for a phase without one; data of phases that are not loaded; legal or tax advice beyond the policies; out-of-domain requests; dumping the whole journal. Acceptance met: each job maps to tools in the [harness](chat-agent-harness.md) and to eval cases in the [evals](chat-agent-evals.md).

### Q2. Relation to the front's modes
**Decision.** Keep **fast** exactly as it is (local, rules, no tokens, instant). **Deep** becomes the backend agent. The agent never receives the app's local answer as authority: figures come from tool results (Q8). When the front asks `mode: "fast"` of the backend, the service runs the same agent with the small model and a 4-call cap.
**Why.** The local engine already gives zero-cost, zero-drift answers to the eight intents it knows; the agent is for what rules cannot do (concepts, explanations, free-form lookups).
**Front change needed (not done here):** fall back to the local engine when the backend request fails, as the dev path already does.
**Known divergence.** When a run has no `attention.jsonl`, the app derives attention with heuristics while the agent can only report what the engine produced; the agent says so instead of deriving it.

### Q3. Topology
**Decision.** Same repository, **separate process**, MCP as the boundary.
- `kalmora serve --mcp` mounts the existing MCP server at `/mcp` (Streamable HTTP) **inside the API process**, so the agent reads the data already loaded in memory (today `kalmora mcp` loads a second copy: 2.5 s, about 330 MB).
- `kalmora chat` is the assistant: it serves `POST /api/chat` (SSE) and `GET /api/chat/status` on its own port, exactly the route the app builds from `VITE_CHAT_URL` (no `/v1` prefix). It connects to `--mcp-url`, reads the model key from the environment and never from a file or from the browser.
- No login, localhost CORS by default, as for the API.
**Rejected.** (a) A router inside the API process: puts the model key beside the data and a write-capable surface next to the agent. (b) Calling `Services` directly with no MCP: loses the single tool surface that Claude Desktop, Claude Code and the in-product agent share, which is the thing we evaluate. (c) The vendor MCP connector: needs a public HTTP endpoint and is not zero-retention eligible (Evidence).

### Q4. Provider and runtime
**Decision.**
- A provider-neutral port `AgentModel` (stream a turn given system blocks, messages and tools; yield text deltas, tool calls, usage, stop reason). First adapter: **Anthropic Messages API**. The OpenAI Responses adapter is a second implementation of the same port when wanted; the repository's existing `kalmora.llm` client stays for document extraction.
- **Own minimal manual loop** (about 200 lines), not the SDK tool runner and not a framework. The loop must cap calls and budget, JSON-encode tool results, intercept the local `present` tool, run the guards, and trace each step, which is exactly the case where the vendor recommends the manual loop. `pydantic-ai` is pinned in the repo but `kalmora.llm` deliberately disables its tools and loop; adding it back for chat would reopen that decision. The Claude Agent SDK targets agents with file and shell tools, which this assistant must not have (inference, not measured).
- Models: deep = `claude-sonnet-5-5` (effort `medium`, tuned by evals K04); fast = `claude-haiku-4-5-20251001`; `claude-opus-5-5` selectable by flag for comparison and for hard explanation cases. Pins and prices are configuration, with price provenance, as `kalmora.llm` already requires.
- Cost estimate for planning (to be measured in eval K02): about 14,000 cached prefix tokens read at $0.20 per million is $0.003 per model call; a deep turn of about four calls with a few thousand fresh tokens and about 2,000 output tokens is **roughly $0.05 to $0.08 on Sonnet 5.5**, about double on Opus 5.5.
**Assumption flagged.** The team may prefer OpenAI because the repository uses it today. The port makes that a one-adapter change and the evals are provider-agnostic. Not a blocker.

### Q5. Harness knowledge
**Decision.** Put the authoritative text **in the prompt**, not behind retrieval.
- A **knowledge pack** is built from the loaded package: `POLITICAS_CONTABLES.md` verbatim (Spanish, so `§` citations stay exact), the project glossary (`CONTEXT.md`, English) with a Spanish-English term table, and the close workflows. About 7,000 tokens; it is the first cached block (1-hour TTL).
- The pack carries `policies_sha256` (the same value the run manifest records) and a **section index** (`§1`, `§2.2`, `§2.2.3`, ...). The MCP server exposes it as a resource and a small `get_policies` tool so the chat service builds it from the package actually loaded, not from a local copy.
- Precedence rule inside the prompt, copied from `AGENTS.md`: the policies govern accounting decisions; general course concepts never override them; when the policy is silent the agent says so.
- Worked examples (3 to 5) are written from the policies only. No example may come from the golden.
**Rejected.** Embedding retrieval: the corpus is 7,000 tokens, cheaper to cache whole and free of retrieval misses; revisit above about 40,000 tokens.

### Q6. Behavioural rules
**Decision.** The system prompt has fixed sections: role and scope; the knowledge pack; ten numbered rules R1 to R10 (grounding, no arithmetic, observed versus rule versus inference, untrusted data, read-only, refusals, language, length, item-id format, uncertainty); a tool policy; and an output policy. A dynamic **scope block** (phase, month, run and its status, available tools, today) comes after the cache breakpoint. The full skeleton and the rule-to-eval map are in the [harness](chat-agent-harness.md). Every rule has at least one eval, which is the acceptance criterion.

### Q7. Tool use
**Decision.** Expose **25 of the 28 existing** tools plus **three new ones** (`get_policies`, `summarize_run`, `calculate`): 28 tools, about 4,500 tokens, and a playbook per question type.
- **Hidden from the assistant:** `landing_rows` (raw internal tables, heavy and untrusted), `list_packages` and `get_job` (ingestion operations), `get_run_evaluation` (a 29th tool that exists only when the server starts with `--evaluator`; golden-based; offered to the assistant only by an explicit development flag).
- **New, each justified by a predicted failure that an eval will confirm** (`get_policies` is needed by the harness itself, Q5):
  1. `summarize_run(run_id)`: counts by decision, reason, type and priority and totals in cents over the delivered files. Without it the agent pages 305+ rows to answer "how did it go" (evals H04, B01, B03).
  2. `calculate(op, values)`: exact integer arithmetic (sum, difference, percentage with a stated rounding) so the model never does money math (evals A13, G04).
- Existing tools to tune: concise result mode and trimmed `meta.sources` for the heavy ones; descriptions rewritten with the vocabulary of the glossary; error text that says what to change.
- Limits per turn: deep 12 tool calls, fast 4; 40,000 tokens of tool results; a truncated result says how to narrow the filter.
**Rejected.** Letting the model see all 28 tools: more descriptions, a larger prompt and three tools it should not use. Dynamic tool search: unnecessary at 28 tools.

### Q8. Producing text, cards and citations
**Decision.** **Figures reach the user only by copy from tool results.**
- The final message is plain Spanish text with item ids in the app's format (`ap:API004151`). No Markdown, links or images (sanitised).
- Cards are built by the **server** through a local function tool `present(type, source_call, select)` that the model calls to say what to show; the server copies the values out of the stored tool result and validates the card against the app's five types. The model never types an amount into a card.
- A **number guard** runs on the finished text: every monetary or counting number must appear in a tool result (normalised for `1.234,56`, cents and integers) or in a `calculate` result; otherwise the model gets one repair turn, and then a safe fallback answer.
- Citations: `{item}` for every item id present in both the text and a tool result; `{policy_ref}` for every `§` reference, validated against the section index; an unknown reference is stripped and counted as a failure in the trace.
- **Streaming:** progress events (`event: status` with the tool being used, ignored by the app) during tool rounds; the verified text is then emitted as `delta` chunks. This gives up token-by-token streaming on purpose, because a retracted number cannot be un-sent and the app can only append. Answers are short, so the delay is small.

### Q9. Threats and controls
**Decision.**

| Threat | Control | Eval |
|---|---|---|
| Indirect injection in data the model reads (bank `text`, inbox messages, vendor names, entry `header_text`, attachment names, override notes, engine event summaries) | Only tool results carry data, JSON-encoded, each tool says where the content came from; the prompt states tool content is data; read-only tools only; per-turn caps | F01 to F09 |
| Direct jailbreak or prompt extraction | Prompt rules; nothing secret in the prompt; refusal templates | F10, E04 |
| Exfiltration through rendered output | No tool reaches the network; the output sanitiser removes links, images and HTML; the app renders plain text | F08, G07 |
| Excessive agency | No write tools; the human decides in the app (Q14) | E01, D06 |
| Golden or other-phase leakage | Evaluator tools hidden; scope block lists the only phase; no cross-conversation memory | E02, E03, E05 |
| Hallucinated numbers or citations | Number guard, section index | G03 to G06 |
| Runaway cost or loops | Call, token and USD caps; rate limit per client | H07, K02 |
Trifecta check: private data yes, untrusted content yes, **external communication no** (the only outlet is the user's own browser, sanitised), so the combination is broken. A small-model screen on tool results is **not built first**; it is added only if the red-team suite F fails, to avoid cost and latency without evidence.

### Q10. State and context
**Decision.** Stateless server. The request is the app's: `run_id`, `dataset_id` (the phase name), `messages`, `mode`. The service keeps the last 10 turns (text only) within a 4,000-token budget, re-queries tools each turn (they are in-memory and cheap) and keeps no memory between conversations. `run_id` may be local to the browser (an imported bundle); if the server does not know it (`run.not_found`), the agent says the run is not on the server and answers only about the phase. One MCP session per request.

### Q11. Observability
**Decision.** One **turn trace** per request, `outputs/chat/<date>/<turn_id>.json`: scope, mode, model and pins, per-step usage (input, output, cache read and write), cost with explicit rates and provenance, each tool call (name, arguments, duration, result size, error code), guard outcomes, final text, latency to first status and total. Budgets: hard stop at USD 0.25 per turn (proposal), 20 requests per minute per client. `--no-store-text` for runs that must not keep conversations. Evals read these traces.

### Q12. Evals
**Decision.** Three tiers, full catalogue in the [evals](chat-agent-evals.md): T0 deterministic component tests with no model; T1 loop tests with a scripted fake model; T2 live-model evals, `pass^3` on deterministic-oracle cases, on demand under a spend cap. Oracles are computed from the source files by code that does not use the MCP tools; the golden is allowed as an **offline reference** only. Real-data cases are generated locally into a git-ignored folder, because the repository is public; only synthetic-fixture cases are committed.

### Q13. Dependencies on unfinished work
**Decision.** Ship in phases. **P1 (now):** J1 to J9 on books, deliverables, attention if present, policies; explanations are labelled "derived from the delivered row and the policy". **P2 (after M7-01 writes `trace/`):** explanations from events with evidence, `reasoning` cards, confidence. **P3:** comparing runs. Meanwhile the agent states plainly when a run has no trace.

### Q14. Writes
**Decision.** None in v1, enforced by the tool list, not by the prompt. Overrides stay a human action in the app. A later "draft an override" helper would return a payload the UI pre-fills and the person confirms; it needs its own ADR and front support.

### Q15. Placement and scope
**Decision.** New package `kalmora.assistant` (`knowledge`, `prompt`, `loop`, `model` port, `anthropic_model`, `mcp_tools`, `guard`, `present`, `sse`, `service`, `trace`), command `kalmora chat`, extra `assistant`. Evals in `evals/assistant/`. New milestone **M9 — Asistente de chat**, separate from M8 and outside the scored path. Slices and issues below.

## Gaps found while deciding (new questions, resolved)

- **G1. Is the run the app names known to the server?** Not always (local bundles). Handled in Q10.
- **G2. Money display.** Tools return cents; people read `1.234,56 EUR`. The prompt fixes the format (Spanish separators, currency of the company) and the guard normalises both forms.
- **G3. Public repository.** Real-data eval cases cannot be committed. Handled in Q12.
- **G4. Policies come from the package, not the repo** (`participant/` is git-ignored). Handled in Q5 by serving them through MCP.
- **G5. Thinking blocks across tool turns.** With adaptive thinking the loop must return the model's thinking blocks with each tool result. This is vendor behaviour I did not verify in this session; the first loop slice confirms it with a test before anything else.
- **G6. Divergence between the app's local derivations and backend answers.** Documented in Q2; an eval (J-series) pins the agent's honesty about it.
- **G7. Rate limiting without login.** Per-client token bucket; weak by design, acceptable for a local deployment.
- **G8. Provider choice** is an assumption (Q4), not a blocker.

## Implementation plan (for approval)

Milestone **M9 — Asistente de chat**, ordered slices, each shippable alone. Sizes: S under a day, M one to two days, L three or more.

| # | Slice | Contents | Size | Depends on |
|---|---|---|---|---|
| S0 | Tool surface | `serve --mcp` mounts `/mcp`; `get_policies` resource and tool; `summarize_run`; `calculate`; tool descriptions pass; concise modes; `--assistant-tools` allowlist | M | M8 MCP (done, uncommitted) |
| S1 | Harness and loop | knowledge pack and section index; system prompt; scope block; `AgentModel` port; Anthropic adapter; manual loop with caps, JSON-encoded results, thinking-block round trip; budget; turn trace | L | S0 |
| S2 | Output contract | `present` tool and card builder; number guard; citation validator; sanitiser; SSE with `status`, buffered `delta`, `error`; `POST /api/chat`, `GET /api/chat/status`; `kalmora chat` | L | S1 |
| S3 | Evals | harness, oracles, graders, T0 and T1 suites, synthetic fixtures; then T2 live suites and the red-team set; baseline report and thresholds | L | S2 (T0 starts with S1) |
| S4 | Front integration | `VITE_CHAT_URL` wiring, fallback to local on failure, status badge, `status` events (front team) | S | S2 |
| S5 | Trace-aware answers | explanations from events, `reasoning` cards, confidence | M | M7-01 |
| S6 | Model choice | run K04 across Haiku, Sonnet, Opus; pick defaults; tune effort and caps | S | S3 |

Epics for the milestone: E1 tool surface (S0), E2 harness and loop (S1), E3 output contract and guards (S2), E4 evals (S3, S6), E5 front integration (S4), E6 trace-aware (S5).

**Open risks.** Provider and model availability and cost in the real environment (G8); the thinking-block behaviour (G5); eval thresholds are proposals until a baseline exists; the assistant earns no score, so it must follow M1 to M7.

**Blockers.** None.

**Approval gate.** No product code, configuration or infrastructure has been changed. Implementation starts only after explicit approval.

## Revision 1: provider decision and what was built (after approval)

**Decision change (Q4).** The user chose **OpenAI in production and Ollama for local development**, instead of the Claude default
proposed above. The port made it a small change. Consequences:

- Two adapters, both in `kalmora.assistant`: `OllamaModel` over the **native `/api/chat`** (not the OpenAI-compatible route), because
  only it lets the request set `num_ctx` (Ollama's default context of 2,048 to 4,096 tokens is smaller than the prompt), and
  `OpenAICompatModel` over **Chat Completions with tools and streaming** (`store=false`, `max_completion_tokens`), which also serves any
  OpenAI-compatible server. Chat Completions was chosen over the Responses API because reasoning is not carried in the messages, so the
  thinking-block round trip of gap G5 disappears. The OpenAI adapter is tested against recorded stream shapes only; **no call was made to
  OpenAI** (no key was provided), so its behaviour with a live model is unverified.
- The Anthropic-specific parts of the harness (cache breakpoints) are gone. What matters on both providers is the same rule: **keep the
  system prompt and the tool list identical between requests**. To get that, the per-request `<scope>` block now travels at the head of
  the user's turn, not in the system prompt (a test proves the system prompt and tool names do not change between requests).
- Tool results carry a `*_display` string next to every integer amount in cents (`-153.685,27`), and R8 tells the model to copy it. Reason:
  in the first live question the 14B model wrote `15.368,53` for `-15368527` cents (off by a factor of 10); the number guard caught it and
  forced a repair, but the better fix is to never ask the model to divide.
- The prompt examples carry **no figures**: they had the real policy's tolerances, which contradicted any other policy and let those
  numbers count as grounded.
- Costs: no USD estimate is made without explicit prices (`--input-usd-per-mtok`, `--output-usd-per-mtok`, `--price-source`), as
  `kalmora.llm` requires; a local model costs nothing and its traces say `cost_usd: null`.

**Measured on the user's machine (Apple M4, 24 GB), `qwen3` family, `num_ctx` 32,768, thinking off.**

| | qwen3:8b | qwen3:14b |
|---|---|---|
| Cold load, tiny prompt | 9.7 s | 11.3 s |
| Prefill of the 9,700-token stable prefix, first time | 67 s | 121 s |
| Same prefix again (Ollama's prompt cache) | 0.3 s | 0.3 s |
| Warm-up at service start (prefix + 28 tool definitions, about 14,000 tokens) | n/a | 164 s, once |
| First real question after warm-up (balance of one account) | n/a | 26 s |

So the service **warms the model at start** (`/api/chat/status` reports `warm`), local timeouts default to 600 s (deep) and 240 s (fast),
and a local model is a development tool: a 14B model on this hardware answers in tens of seconds, not seconds.

**What exists now.**

| Piece | Where |
|---|---|
| Tool surface: `get_policies`, `summarize_run`, `calculate`; `serve --mcp` mounts `/mcp/` in the API process | `kalmora/app/usecases`, `kalmora/mcp`, `kalmora/api` |
| Assistant: model port, adapters, MCP client, loop, `present` cards, guards, traces, SSE service, `kalmora chat` | `kalmora/assistant/` |
| T0 and T1 suites (35 tests, ids G01 to G14, J03 to J05, J07, H05, H08, F13, D09-equivalent) | `tests/test_assistant.py` |
| T2 catalogue: 101 synthetic cases with reference answers, 78 generated real-data cases, runner and report | `evals/assistant/` |

Not implemented: H09 (tool-description A/B needs two description sets), K05 (concurrency; a single local model serves one turn at a
time), the rubric judge (graded by reference-fact keywords instead; a judge model can be plugged into `Ctx.judge`), and the OpenAI live
run. The ordering rule "no `delta` before the guards pass" is enforced and tested.
