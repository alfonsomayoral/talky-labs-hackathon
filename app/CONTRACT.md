# Contrato backend → frontend

El backend (Python) cierra el mes. El frontend (`app/`) lo enseña y genera la entrega. Este documento fija lo que el backend tiene que producir para que el frontend funcione.

**Propiedad:** la capa de datos es del equipo de backend. `app/src/data/` es un **adaptador v1** provisional que se adaptará a la API y al almacenamiento que monte ese equipo. La frontera estable para las pantallas es `app/src/data/stores.ts` más los tipos de `app/src/domain/types/`: ninguna vista importa nada de dentro de `src/data/`. Si el backend cambia la forma de la API, se cambia el adaptador, no las pantallas.

**Mínimo:** las 6 JSONL oficiales. Con solo eso, la app deriva partidas, atención, balance, validaciones y nota (si el dataset trae `golden/`). Lo demás es opcional y enriquece la trazabilidad.

## 1. Paquete de ejecución (carpeta)

```
runs/<run_id>/
├── manifest.json            opcional — metadatos de la ejecución
├── deliverables/            OBLIGATORIO — formato exacto de FORMATO_ENTREGA.md
│   ├── ap.jsonl  ar_billing.jsonl  ar_cash.jsonl  bank_rec.jsonl  ic.jsonl  close.jsonl
└── trace/                   opcional
    ├── events.jsonl         pasos del agente por partida (solo se añaden)
    └── attention.jsonl      lo que el agente manda a una persona (sustituye las heurísticas de la app)
```

- Importes en céntimos enteros y en la moneda local de la sociedad. Fechas `YYYY-MM-DD`. Marcas de tiempo en ISO-8601 UTC.
- La app importa el paquete arrastrando la carpeta o su zip. En desarrollo también lo lee de `KALMORA_RUNS` (ver `PLAN.md` §3.5).
- **No se commitea** ningún paquete: `runs/` está en `.gitignore`, porque el repo es público.

### 1.1 `manifest.json`

El backend ya escribe un informe por ejecución en `outputs/runs/<uuid>.json` (`kalmora.runlog`, `schema_version: 1`). Incluye las llamadas a modelos con tokens y coste estimado, la duración y el estado. **La app acepta ese informe tal cual** si va en el paquete como `manifest.json` o `run.json`, y lo traduce a este formato. Si el backend añade a su informe los tiempos por tarea y las correcciones humanas, se muestran sin cambios en la app.


```json
{"run_id": "dev-2026-07-r003", "dataset": "phase_dev", "month": "2026-07",
 "started_at": "2026-10-03T10:00:00Z", "finished_at": "2026-10-03T10:21:40Z", "runtime_s": 1300,
 "models": [{"provider": "typesafe", "name": "jev-1.13.0", "calls": 2140, "input_tokens": 3900000, "output_tokens": 40000, "cost_usd": 0.16},
            {"provider": "anthropic", "name": "claude-opus-5", "calls": 61, "input_tokens": 410000, "output_tokens": 52000, "cost_usd": 3.35}],
 "cost_usd_total": 3.51, "agent_version": "<git sha>", "policies_sha256": "<sha256 de POLITICAS_CONTABLES.md>",
 "tasks": {"ap": {"started_at": "…", "finished_at": "…"}, "ar_billing": {"…": "…"}},
 "human_overrides": 0}
```

### 1.2 `trace/events.jsonl`: un evento por línea

```json
{"event_id": "e-000812", "item": "ap:API004151", "seq": 4, "ts": "2026-10-03T10:03:12Z",
 "kind": "CHECK", "step": "bank_details", "result": "FAIL", "policy_ref": "§2.2.3",
 "summary": "IBAN de la factura ES12… ≠ ficha ES93…; sin carta de cambio ni cesión registrada",
 "evidence": [{"kind": "doc", "path": "inbox/ap/API004151/factura.pdf", "locator": "IBAN"},
              {"kind": "erp", "file": "erp/vendors.jsonl", "key": "V100045", "field": "bank.iban"}],
 "model": null, "confidence": null, "duration_ms": 3}
```

- **`item`:** `<tarea>:<clave>`. Las claves son estas:
  - `ap:<doc_id>`
  - `ar_billing:<billing_item>`
  - `ar_cash:<bank_line>`
  - `bank_rec:<cuenta>/<bank_line o book_line>`
  - `ic:<soc1>-<soc2>/<causa>`
  - `close:<tipo>/<sociedad>/<clave>`
- **`kind`:** `EXTRACT | CHECK | MATCH | CLASSIFY | ESTIMATE | DECIDE | POST | MODEL_CALL`.
- **`result`:** `PASS | FAIL | INFO`.
- **`evidence[].kind`:** `doc` (ruta dentro del dataset + `locator`), `erp` (fichero + `key` + `field`), `bank` (`account` + `bank_line`), `journal` (`<id asiento>#<línea>`), `precedent` (texto del precedente histórico).
- **`model`** cuando se usó un modelo:

  ```json
  {"provider": "typesafe", "name": "jev-1.13.0", "question": "document_type",
   "answer": "INVOICE", "probabilities": {"INVOICE": 0.93, "PROFORMA": 0.05},
   "input_tokens": 1800, "output_tokens": 20, "cost_usd": 0.00008}
  ```

- **`confidence`:** probabilidad de que la decisión final de la partida sea correcta (0–1), en el evento `DECIDE`. Alimenta las bandas, el orden de Atención y la curva de calibración.

### 1.3 `trace/attention.jsonl`

```json
{"attention_id": "att-0007", "item": "ap:API004151", "kind": "FRAUD_SIGNAL", "priority": "P0",
 "title": "IBAN distinto al de la ficha sin carta de cambio", "impact": 4202872, "affects_tb": false,
 "policy_ref": "§2.2.3", "recommendation": {"decision": "HOLD", "reasons": ["BANK_DETAILS_CHANGED"]},
 "alternatives": [{"decision": "POST", "p": 0.06}],
 "suggested_action": "Confirmar el cambio por teléfono con el número de la ficha antes de pagar"}
```

- **`kind`:** `FRAUD_SIGNAL | MATERIAL_UNEXPLAINED | AGENT_DOUBT | ESTIMATE | CROSS_TASK | POLICY_EXCEPTION | MASTER_DATA | DATA_QUALITY`.
- **`priority`:** `P0 | P1 | P2 | P3`.

## 2. API HTTP

**Sustituida por la API `/v1` del backend** (`kalmora serve`, `docs/api-contracts.md` §9 en la rama del backend). Con `VITE_API_URL` definida, la app (`src/data/providers/api.ts`):

- lista las fases cargadas (`GET /v1/phases`) y las abre leyendo sus ficheros (`GET /v1/phases/{fase}/files/{ruta}`, sin `golden/`);
- sube el zip de los organizadores («Subir .zip al backend», `POST /v1/packages`) y espera a que cargue (`GET /v1/jobs/{id}`);
- lanza el cierre con «Cerrar el mes» (`POST /v1/phases/{fase}/runs`, que ejecuta el comando de `kalmora serve --close-command`) y lo sigue consultando `GET /v1/runs/{id}` cada 2 s hasta `completed` o `failed`; no hay eventos en vivo;
- lista las ejecuciones del mismo mes con carpeta de paquete (`GET /v1/runs`, `has_files`, `month`) y las carga (`GET /v1/runs/{id}/files/{ruta}`), con el informe de ejecución como `manifest.json` si el paquete no trae uno.

La nota solo aparece si la fase trae `golden/` y el backend se arranca con `--serve-golden`. El chat del Asistente usa su propia variable, `VITE_CHAT_URL`. La tabla siguiente es la propuesta original; solo `POST /api/chat` sigue vigente.

| Método y ruta | Qué hace | Respuesta |
| --- | --- | --- |
| `POST /api/datasets` | Sube una fase (zip con `erp/`, `inbox/`, `bank/`, `tasks/`, `golden/` opcional) | `{"dataset_id": "…"}` |
| `GET /api/datasets` | Lista los datasets disponibles (incluidos los locales del servidor) | `[{"dataset_id", "name", "month", "has_golden"}]` |
| `POST /api/runs` | Lanza el cierre: `{"dataset_id": "…", "options": {…}}` | `{"run_id": "…"}` |
| `GET /api/runs?dataset_id=…` | Lista ejecuciones | `[manifest]` |
| `GET /api/runs/{id}` | Estado: `{"state": "queued|running|done|failed", "tasks": {"ap": {"state", "done", "total"}, …}, "manifest": {…}, "files": ["deliverables/ap.jsonl", …]}`. `files` es opcional: si viene, la app solo pide esos ficheros y no deja 404 en consola por `trace/` ausente | JSON |
| `GET /api/runs/{id}/events` | Eventos en vivo por **SSE**: cada mensaje es un evento de §1.2; al final, `event: done` | `text/event-stream` |
| `GET /api/runs/{id}/files/{ruta}` | Cualquier fichero del paquete (`deliverables/ap.jsonl`, `trace/events.jsonl`…) | El fichero |
| `POST /api/chat` | Pregunta al Asistente: `{"run_id", "dataset_id", "messages": [{"role", "content"}], "mode": "fast|deep"}` | SSE: `event: delta` con texto, `event: card` con una tarjeta (`{"type": "items|table|reasoning|metric", …}`), `event: citation` con `{"item"}` o `{"policy_ref"}`, y `event: done` |


### 2.1 Tarjetas del Asistente (`event: card`)

Mismo formato que `src/features/assistant/engine/types.ts` (`AssistantCard`). Importes en céntimos enteros con su moneda.

| `type` | Campos |
| --- | --- |
| `metric` | `title?`, `metrics: [{label, value, delta?, comparison?, hint?}]`; `value` es `{kind: "number", value}`, `{kind: "percent", value}`, `{kind: "money", cents, currency}` o `{kind: "text", text}` |
| `table` | `title?`, `columns: [{label, align?}]`, `rows`: lista de filas de celdas `{kind: "text"\|"mono", text}`, `{kind: "number"\|"percent", value}`, `{kind: "money", amounts: [{cents, currency}]}` o `{kind: "item", item, label}` |
| `items` | `title?`, `items: [{item, title?, amount?, currency?, priority?, status?}]` (cada `item` es un id de partida `<tarea>:<clave>`), `total?` |
| `reasoning` | `item`, `headline`, `facts`, `steps` |
| `process` | `task`: la app dibuja el mapa de decisión de esa tarea |

`event: delta` lleva `{"text": "…"}`. La app también acepta una cadena JSON o texto plano, y descarta las tarjetas de tipo desconocido.

En desarrollo, sin backend, el modo Profundo usa `dev/assistantChat.ts`: el servidor de Vite atiende `POST /api/chat` con un modelo de OpenAI (`OPENAI_API_KEY` y `OPENAI_MODEL` en `.env.local`, solo en el servidor). La petición lleva además `context`, la respuesta local de la app. El modelo solo redacta el texto, y las cifras, tarjetas y citas siguen siendo las locales.

CORS abierto a `http://localhost:5173` en desarrollo.

## 3. Lo que hace la app con lo recibido

- **Valida cada JSONL:**
  - una fila por elemento de `tasks/`;
  - campos y valores permitidos;
  - asientos cuadrados;
  - céntimos enteros;
  - cuentas del plan.
- **Deriva:** partidas, atención (si no viene `attention.jsonl`), balance registrado, después y correcto, y la nota con el mismo algoritmo que `score.py` (si hay `golden/`).
- **Descarga** el zip de entrega con las 6 JSONL tal como llegaron y `manifest.json`.
- **Correcciones humanas:** se exportan aparte como `overrides.jsonl`, con una línea por corrección: `{"attention_id" | "item", "decision", "note", "user", "ts"}`.
