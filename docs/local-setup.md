# Levantar el entorno local: backend, MCP, agente y front

Cuatro piezas, tres procesos. El MCP no es un proceso aparte: lo sirve el backend con `--mcp`.

```
navegador ──► front (Vite, :5173) ──► backend /v1 (:8001)
    │
    └─► POST /api/chat ──► agente `kalmora chat` (:8110) ──► MCP en el backend (:8001/mcp/) ──► modelo (Ollama u OpenAI)
```

| Pieza | Comando | Puerto |
| --- | --- | --- |
| Backend + MCP | `kalmora serve --mcp` | 8001 |
| Agente de chat | `kalmora chat` | 8110 |
| Front | `npm run dev` en `app/` | 5173 |

Los puertos son los que usa esta guía. Son elecciones, no valores fijos: `kalmora serve` usa 8000 y `kalmora chat` 8100 por defecto, y se cambian con `--port`. Si cambias uno, cambia también la variable que lo referencia (ver [Variables](#variables)).

## Requisitos

- Python 3.12 o superior.
- Node 20.19+ o 22.12+ (Vite 8 lo exige; con 20.17 arranca con un aviso).
- Para el agente con Ollama: Ollama en marcha (`ollama serve`) y los modelos descargados (`ollama pull qwen3:14b`, `ollama pull qwen3:8b`).
- Para el agente con OpenAI: una clave con permiso de peticiones a modelos (ver [Problemas frecuentes](#problemas-frecuentes)).

## 1. Instalar

Desde la raíz del repo:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[api,mcp,assistant]'
```

`api` da FastAPI y uvicorn para `serve`, `mcp` el servidor MCP y `assistant` lo que necesita `chat`. Los comandos de abajo usan `python3 -m kalmora` con `PYTHONPATH=src`; si instalaste el paquete en el venv, puedes usar `.venv/bin/kalmora` en su lugar y quitar `PYTHONPATH=src`.

Para el front:

```bash
cd app
npm install
```

## 2. Configurar

### `.env` de la raíz (backend y agente)

`kalmora chat` lee este archivo por sí mismo. `kalmora serve` no: hay que cargarlo en la shell (paso 3). El archivo está en `.gitignore`.

Agente con Ollama:

```
KALMORA_AI_PROVIDER=ollama
KALMORA_AI_MODEL=qwen3:14b
KALMORA_AI_FAST_MODEL=qwen3:8b
KALMORA_MCP_URL=http://127.0.0.1:8001/mcp/
```

Agente con OpenAI:

```
KALMORA_AI_PROVIDER=openai
KALMORA_AI_MODEL=gpt-6-luna
OPENAI_API_KEY=...
KALMORA_MCP_URL=http://127.0.0.1:8001/mcp/
```

La clave solo se lee del entorno o del `.env`, nunca de un flag. El puerto del agente no tiene variable: se pasa con `--port`.

### `app/.env.local` (front)

Se crea con `cp .env.example .env.local`. También está ignorado por git. Lo mínimo para usar el backend y el agente:

```
VITE_API_URL=http://127.0.0.1:8001
VITE_CHAT_URL=http://127.0.0.1:8110
```

- Usa `127.0.0.1` y no `localhost` en estas URLs. Si otro servicio escucha en el mismo puerto por IPv6 (por ejemplo un contenedor de Docker), el navegador resuelve `localhost` a `::1` y la petición no llega a tu backend.
- Vite lee este archivo solo al arrancar; si lo cambias, se reinicia solo el servidor de desarrollo, pero hay que recargar la página.
- Sin `VITE_CHAT_URL` el Asistente usa el motor local. Con `VITE_CHAT_URL` va siempre al agente y las variables `OPENAI_*` de este archivo ya no se usan.

## 3. Backend y MCP

Una terminal, desde la raíz:

```bash
set -a; source .env; set +a
PYTHONPATH=src python3 -m kalmora serve --port 8001 --mcp
```

- API en `http://127.0.0.1:8001/v1`, MCP en `http://127.0.0.1:8001/mcp/`.
- Al arrancar recarga los paquetes que haya en `outputs/data` (`--no-restore` para saltarlo).
- Sin `--close-command`, el botón «Cerrar el mes» responde `409 run.unavailable`: los cierres se cargan por la API. Para lanzarlos desde el front añade `--close-command 'python3 -m kalmora close {phase_dir} --out {out}'`.
- Con `--evaluator <carpeta>` (donde `<carpeta>/<fase>/golden` existe) se activa la evaluación; con `--serve-golden` el front puede puntuar ejecuciones. Solo para fases de desarrollo.

Comprobar:

```bash
curl -s http://127.0.0.1:8001/v1/phases
```

Devuelve las fases cargadas. Un `GET` a `/mcp/` responde 406: es lo esperado, habla Streamable HTTP.

## 4. Agente de chat

Otra terminal, desde la raíz. Con la configuración del `.env` basta:

```bash
PYTHONPATH=src python3 -m kalmora chat --port 8110
```

Al arrancar imprime la configuración efectiva (proveedor, modelos, endpoint, MCP). Comprobar:

```bash
curl -s http://127.0.0.1:8110/api/chat/health    # {"ok":true,"tools":28}
curl -s http://127.0.0.1:8110/api/chat/status    # proveedor, modelos, estado de calentamiento
```

- `health` con `tools: 28` confirma que el agente llega al MCP del backend.
- Los flags (`--provider`, `--model`, `--fast-model`, `--mcp-url`, `--ollama-url`, `--num-ctx`…) pisan al `.env`. Mira `python3 -m kalmora chat --help`.
- Con Ollama, el modelo rápido se carga primero; el profundo (`qwen3:14b`) se carga la primera vez que se usa el modo Profundo y esa respuesta tarda más.
- El agente solo lee: no modifica fases ni ejecuciones.

## 5. Front

Otra terminal:

```bash
cd app
npm run dev
```

Abre `http://localhost:5173`. Vite escucha en IPv6, por eso aquí sí hay que usar `localhost`. El Asistente está en `/asistente` o con `⌘J`; la barra del chat muestra el modelo que responde, por ejemplo «Responde el agente del backend (ollama:qwen3:14b)».

Si el 5173 está ocupado: `npm run dev -- --port 5174 --strictPort`.

## 6. Cargar datos

El agente solo ve las fases cargadas en el backend. Ábrelas desde el backend en **Ejecuciones → Nuevo cierre**:

- «Subir .zip al backend» con el zip de la fase, o
- una fase ya restaurada de `outputs/data`, que aparece sola.

La fase se identifica por el nombre de su carpeta (`phase_dev`). Los datasets que sirve el middleware de Vite (`KALMORA_DATASETS`, ids `dev` y `test`) no existen para el agente: el front envía `dataset_id: "dev"` y el agente responde que no está cargado. Una ejecución local que el backend no conoce solo permite preguntas sobre la fase.

## Parar todo

`Ctrl+C` en cada terminal. Si quedaron procesos sueltos:

```bash
pkill -f "kalmora serve"
pkill -f "kalmora chat"
pkill -f "app/node_modules/.bin/vite"
```

## Variables

| Variable | Dónde | Para qué |
| --- | --- | --- |
| `KALMORA_AI_PROVIDER` | `.env` | `ollama` (por defecto) u `openai` |
| `KALMORA_AI_MODEL` | `.env` | Modelo del modo Profundo. Obligatorio con `openai`; `qwen3:14b` por defecto con Ollama |
| `KALMORA_AI_FAST_MODEL` | `.env` | Modelo del modo Rápido (por defecto, el mismo que el profundo) |
| `KALMORA_MCP_URL` | `.env` | Endpoint MCP del backend (`…/mcp/`) |
| `OPENAI_API_KEY` | `.env` | Clave de OpenAI; solo con `openai` |
| `KALMORA_OPENAI_API` | `.env` | `chat` (por defecto, `/chat/completions`) o `responses` (`/responses`) |
| `OLLAMA_HOST` / `KALMORA_OLLAMA_URL` | `.env` | Dirección de Ollama (por defecto `http://127.0.0.1:11434`) |
| `KALMORA_OLLAMA_NUM_CTX` | `.env` | Ventana de contexto pedida a Ollama (32768) |
| `VITE_API_URL` | `app/.env.local` | Backend `/v1` |
| `VITE_CHAT_URL` | `app/.env.local` | Agente de chat |

La lista completa del agente está en `src/kalmora/assistant/config.py`; el diseño, en [chat-agent-harness.md](design/chat-agent-harness.md).

## Problemas frecuentes

- **El backend responde 404 a una subida desde el front.** Casi siempre la petición llegó a otro servicio en el mismo puerto (Docker en IPv6). Usa `127.0.0.1` en `VITE_API_URL`, o cambia de puerto. Comprueba quién escucha con `lsof -nP -iTCP:8001 -sTCP:LISTEN`.
- **`Cannot find native binding` al arrancar Vite (o oxlint).** Bug de npm con dependencias opcionales ([npm/cli#4828](https://github.com/npm/cli/issues/4828)): falta el paquete nativo de tu plataforma. Instálalo sin guardarlo, con la misma versión que `rolldown`: `npm install --no-save --no-package-lock @rolldown/binding-darwin-arm64@$(node -p "require('./node_modules/rolldown/package.json').version")`. Cambia `darwin-arm64` por tu plataforma.
- **El agente con OpenAI responde 401 `Missing scopes: model.request`.** La clave es restringida. Dale el permiso *Model capabilities → Request* en OpenAI, usa una clave con acceso completo o, si la clave solo tiene permiso para la Responses API, pon `KALMORA_OPENAI_API=responses` en el `.env`. Después reinicia solo el agente (lee el `.env` al arrancar).
- **El agente dice que el dataset no está cargado.** Ver [Cargar datos](#6-cargar-datos).
- **La primera pregunta con Ollama tarda.** El modelo se está cargando en memoria; `ollama ps` muestra qué hay cargado. Mientras `llama-server` use CPU o GPU, está generando.
- **`kalmora chat` dice que falta `OPENAI_API_KEY` o el modelo.** Con `openai` ambos son obligatorios; revisa el `.env` de la raíz.
