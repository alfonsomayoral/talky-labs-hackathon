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

## Recorrido de demo

Sobre julio con la referencia: en `/dev/data`, carga `phase_dev` y crea la referencia, o en **Ejecuciones → Nuevo cierre** elige la carpeta de julio y pulsa «Abrir referencia». Cada URL se puede pegar tal cual; entre pantallas, `g` + letra (`g a` Atención, `g 4` Bancos, `g c` Comparar, `g e` Entregables, `g i` Asistente).

| Paso | URL | Qué enseñar |
| --- | --- | --- |
| 1. Resumen | `/` | La frase de apertura: el agente resuelve 663 de 726 partidas sin intervención (91,3 %). Los indicadores, el proceso en orden de AP a Cierre y «Te necesitan» |
| 2. Atención | `/atencion` | Primera tarjeta, en «Posible fraude»: `API005229`, IBAN distinto al de la ficha, 353.571,27 €. Está retenida (`HOLD`, `BANK_DETAILS_CHANGED`): el agente no paga y propone confirmar el cambio por teléfono. `a`, `p` y `n` registran la decisión sin tocar la entrega |
| 3. Panel de partida | `/tareas/ap?item=ap:API004128` | Factura 2026-001968 de Desmontes y Obras Pro, 30.232,16 €. En Razonamiento, la cascada §2.2 con sus 14 comprobaciones superadas. En Asiento, las 7 líneas cuadradas, con el IVA autorrepercutido y la retención de garantía del 5 %. También se abre con `⌘K` y el id |
| 4. Bancos N:1 | `/tareas/bancos/BIN-1200?item=bank_rec:BIN-1200/BL0004009` | La nómina en dos lotes, `BL0004009` y `BL0004010`, casada con un solo apunte de la 572: −683.761,68 €. A la izquierda, el puente de saldo del extracto al libro y la vista enfrentada banco/libro |
| 5. Comparar | `/comparar` | Subnotas por tarea al 100 % y ninguna diferencia, porque es la referencia. Con una ejecución del agente, aquí aparece cada partida que difiere y en qué campo |
| 6. Entregables | `/entregables` | Entrega «Lista»: 6/6 ficheros validados, 0 asientos descuadrados y nota 100,00, calculada igual que `score.py`. «Descargar entrega (.zip)» baja el zip con las 6 JSONL, `manifest.json` y `overrides.jsonl` |
| 7. Asistente | `/asistente` | Pulsa «¿Qué partidas tengo que revisar?»: 56 pendientes, 11,6 M€ y 2 de posible fraude, con las partidas enlazadas al panel. Se abre desde cualquier pantalla con `⌘J` |

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
