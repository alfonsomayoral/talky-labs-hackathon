# Kalmora Close — frontend

Puesto de mando del cierre mensual de Grupo Kalmora. Recibe las entradas de una fase, carga los resultados del agente, explica cada decisión con su regla y su evidencia, y genera la entrega de los 6 ficheros oficiales validada. El problema está en [`../PROBLEM.md`](../PROBLEM.md) y el plan en [`PLAN.md`](PLAN.md).

## Arranque

Requiere Node 22 o superior.

```bash
cd app
npm install
cp .env.example .env.local   # y ajusta las rutas de datos (ver abajo)
npm run dev                  # http://localhost:5173
```

| Comando | Para qué |
| --- | --- |
| `npm run dev` | Servidor de desarrollo con los datos locales |
| `npm run typecheck` | `tsc -b` |
| `npm run lint` | oxlint |
| `npm run test` | vitest. Los tests de paridad con `score.py` leen julio de `KALMORA_DEV_PHASE`, del dataset `dev` de `.env.local` o de `../../participant/phase_dev`; sin datos, se saltan |
| `npm run build` | Build de producción en `dist/` |

## Datos

Los datos **nunca** se commitean: el repo es público.

- **En desarrollo**, `.env.local` dice qué carpetas sirve el middleware de Vite (`dev/kalmoraData.ts`):
  - `KALMORA_DATASETS=dev:/ruta/a/participant/phase_dev,test:/ruta/a/participant-2/phase_test`, con rutas absolutas o relativas a `app/`;
  - `KALMORA_RUNS=/ruta/a/runs` (opcional): paquetes de ejecución del backend, por ejemplo su carpeta `outputs/`.
- **Sin middleware** (o en producción), en **Ejecuciones → Nuevo cierre** se arrastra la carpeta de una fase tal como la dan los organizadores, o su `.zip`.

Después, en el mismo Nuevo cierre, se eligen los resultados:

| Origen | Cómo |
| --- | --- |
| Referencia | «Abrir referencia» lee `golden/` (solo julio). Su nota es 100 |
| Importados | Las 6 JSONL sueltas, la carpeta de un paquete o su `.zip` |
| Backend | «Cerrar el mes», con `VITE_API_URL` definida. La app sigue el progreso por SSE |

El **Asistente** (`/asistente` o `⌘J`) responde con el motor local. En desarrollo, si `.env.local` define `OPENAI_API_KEY`, el modo Profundo hace que un modelo de OpenAI (`OPENAI_MODEL`, por defecto `gpt-6-luna`) redacte el texto sobre las mismas cifras. La clave se queda en el servidor de Vite.

`/dev/data` es una página de depuración para cargar todo con un clic.

## Recorrido

1. **Resumen** (`/`): frase con la cifra clave, autonomía, atención, hueco del balance cerrado, nota, el proceso en orden y «Te necesitan».
2. **Atención** (`/atencion`): lo que el agente no puede cerrar solo, por prioridad. Las correcciones (`a` aceptar, `p` posponer, `n` nota) se exportan aparte en `overrides.jsonl` y no cambian la entrega.
3. **Actividad** (`/actividad`): cada partida, con el mapa de decisión de su tarea. Cualquier partida se abre en el panel lateral (`?item=`) con sus pestañas Razonamiento, Resumen, Asiento, Evidencia y Golden.
4. **Tareas** (`/tareas/*`), **Balance** y **Datos**: el espacio de trabajo de cada tarea, que abre con su mapa de decisión, y las entradas enlazadas.
5. **Entregables** (`/entregables`): validación por fichero, nota igual que `score.py` y descarga del zip con las 6 JSONL, `manifest.json` y `overrides.jsonl`.

`⌘K` busca cualquier id (documento, línea bancaria, asiento, proveedor, cliente o cuenta) y `?` muestra los atajos.

## Contrato con el backend

[`CONTRACT.md`](CONTRACT.md): el paquete de ejecución (`deliverables/` obligatorio; `manifest.json` y `trace/` opcionales) y la API (`/api/datasets`, `/api/runs` con SSE). Con solo las 6 JSONL, la app deriva partidas, atención, balance, validaciones y nota.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `src/app/` | Rutas y navegación |
| `src/design/`, `src/components/` | Tokens de la marca Talky y componentes base ([README](src/components/README.md)) |
| `src/shell/` | Barra lateral, cabecera, panel lateral, ⌘K y atajos |
| `src/domain/` | Tipos de entradas y salidas; catálogos de la política y de las tareas |
| `src/data/` | Adaptador de datos v1: fuentes, parsers, worker, stores. La frontera para las vistas es `src/data/stores.ts` |
| `src/engine/` | Puerto de `score.py`, balance, validación, partidas, atención y traza mínima |
| `src/features/` | Una carpeta por pantalla. `item/kit/` es el kit de razonamiento que comparten ([README](src/features/item/kit/README.md)) |

Cómo trabajan en paralelo las sesiones que construyen la app: [`AGENTS.md`](AGENTS.md) y [`STATUS.md`](STATUS.md).
