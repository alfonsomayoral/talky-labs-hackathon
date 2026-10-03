# Plan de implementación del frontend — Kalmora Close (`app/`)

Este documento es la referencia para todos los agentes que construyan `app/`. El problema está definido en [`../PROBLEM.md`](../PROBLEM.md). El contrato con el backend está en [`CONTRACT.md`](CONTRACT.md).

## 0. Objetivo y criterio de terminado

`app/` es el puesto de mando del cierre mensual de Kalmora. Hace tres cosas:

1. **Recibe las entradas** con la misma estructura que dan los organizadores (`erp/`, `inbox/`, `bank/`, `tasks/` y, si existe, `golden/`).
2. **Obtiene los resultados del agente.** Llegan de tres fuentes:
   - la API del backend;
   - importar las 6 JSONL o un paquete de ejecución;
   - la solución de referencia (`golden/`), solo en julio.
3. **Entrega los 6 ficheros oficiales** validados.

Además hace visible cada paso: qué decidió el agente, con qué regla, con qué evidencia y qué necesita a una persona. **Las vistas más importantes son la trazabilidad y el razonamiento por proceso:**

- cada tarea muestra su mapa de decisión (cuántas partidas tomaron cada camino de la política);
- cada partida muestra su razonamiento paso a paso.

Un asistente conversacional (fase 6) responde preguntas sobre el cierre con esas mismas evidencias.

Está terminado cuando se cumple todo esto:

- [ ] Sobre la carpeta de julio, la app carga los datos y crea la ejecución de referencia. Su nota calculada en la app es **100,00** y coincide con `score.py`.
- [ ] El zip descargado desde Entregables, descomprimido y pasado por `python score.py`, saca la misma nota que muestra la app.
- [ ] Importar unas 6 JSONL cualesquiera (por ejemplo, las de septiembre que produzca el backend) llena todas las pantallas sin tocar código.
- [ ] Cada partida de las 6 tareas se abre en el panel lateral con:
  - su asiento cuadrado;
  - su regla de la política;
  - su evidencia enlazada al documento, la línea bancaria o el maestro;
  - su comparación con golden cuando lo hay.
- [ ] `npm run typecheck`, `npm run lint`, `npm run test` y `npm run build` pasan en verde.
- [ ] El Asistente responde las 4 preguntas preestablecidas con cifras que cuadran con Resumen y Atención, citando partidas que se abren en el panel lateral.
- [ ] El recorrido de demo se hace sin errores en consola.

## 1. Flujos del producto

| Flujo | Qué hace el usuario | Qué hace la app |
| --- | --- | --- |
| Entrada | Arrastra la carpeta de una fase (o su `.zip`), o elige un dataset servido en desarrollo | Detecta el inventario: sociedades, documentos, extractos por formato, meses de diario y si hay `golden/`. Valida la estructura y la guarda en el navegador |
| Ejecución | Pulsa «Cerrar el mes» (API del backend), importa resultados, o abre la referencia (golden) | Sigue el progreso en vivo si hay API (SSE). Sin API, carga el paquete. Deriva partidas, atención, balance, validaciones y nota |
| Revisión | Recorre Resumen, Atención, Actividad y las vistas por tarea | Muestra el porqué de cada decisión y lo que necesita una persona. Guarda las correcciones como `overrides.jsonl` |
| Salida | Va a Entregables | Valida las 6 JSONL contra `tasks/` y las reglas de formato. Calcula la nota si hay golden. Descarga el zip con las 6 JSONL y `manifest.json` |

Las correcciones humanas **no modifican** las 6 JSONL entregadas: el reto valora que el trabajo lo haga el agente. Se exportan aparte y el backend decide si las reaplica.

## 2. Diseño

### 2.1 Estructura (inspiración, sin banners ni ilustraciones)

- **De Linear:**
  - barra lateral fija (232 px) con selector de ejecución arriba y secciones;
  - cabecera de página fina con migas, título, filtros y acciones;
  - listas densas (filas de 36 px) agrupables, con filtros en chips y «Opciones de vista»;
  - panel lateral de detalle (*peek*) que se abre sobre cualquier lista sin cambiar de página;
  - paleta de comandos ⌘K y navegación con teclado (`j`/`k`, `Enter`, `Esc`, `g` + letra);
  - estados vacíos sobrios.
- **De Kapia:**
  - Resumen que abre con una frase y la cifra clave;
  - tres o cuatro indicadores con su comparación;
  - el mosaico de partidas coloreado por estado;
  - los paneles «Trabajando ahora» y «Te necesitan»;
  - la Bandeja como lista de lo pendiente con filtros;
  - Actividad como tabla de ejecuciones con detalle lateral.
  
  De Kapia no se copia código, CSS, tokens ni imágenes: solo la idea de estructura.
- **Sin** cabeceras pictóricas, banners ni fotos. El color se reserva a la marca (acciones primarias, selección) y a los estados.

### 2.2 Marca Talky (tokens)

Valores tomados de `usetalky.com` (web de producto) el 03/10/2026.

| Token | Valor | Uso |
| --- | --- | --- |
| `--brand` | `#F97316` | Acción primaria, selección activa, foco, cifras destacadas |
| `--brand-hover` | `#EA580C` | Hover de la acción primaria |
| `--brand-soft` | `#FFF7ED` | Fondo de fila seleccionada, chips de marca |
| `--brand-border` | `#FED7AA` | Bordes de elementos de marca |
| `--ink` | `#09090B` | Texto principal |
| `--ink-strong` | `#111827` | Títulos |
| `--ink-2` | `#4B5563` | Texto secundario |
| `--ink-3` | `#6B7280` | Etiquetas |
| `--ink-4` | `#9CA3AF` | Texto deshabilitado, marcas de eje |
| `--line` | `#E4E4E7` | Bordes y separadores |
| `--line-soft` | `#F3F4F6` | Separadores de fila |
| `--bg` | `#FFFFFF` | Hoja de trabajo |
| `--bg-subtle` | `#FAFAFA` | Fondo de la app y barra lateral |
| `--bg-muted` | `#F4F4F5` | Hover de fila, campos |
| `--ok` | `#059669` (fondo `#ECFDF5`) | Resuelto por el agente, cuadrado |
| `--warn` | `#D97706` (fondo `#FFFBEB`) | Necesita persona, estimación |
| `--danger` | `#DC2626` (fondo `#FEF2F2`) | Bloqueado, fraude, descuadre |
| `--info` | `#2563EB` (fondo `#EFF6FF`) | Ejecución determinista (regla) |
| `--radius-sm/md/lg` | 6 / 8 / 12 px | Etiquetas / controles / tarjetas |
| `--radius-pill` | 9999 px | Botón primario (estilo Talky) |

- **Tipografía:**
  - **Inter** (variable) para la interfaz: 13 px base, 12 px en tablas, títulos de página de 20 a 24 px con peso 600.
  - **JetBrains Mono** para identificadores, cuentas, importes, códigos y atajos.
  - **Libre Baskerville**, peso 400 y tracking negativo, solo en la frase de apertura del Resumen, como el titular de Talky.
- **Importes:** cifras tabulares (`font-variant-numeric: tabular-nums`) alineadas a la derecha. Siempre en la moneda local de la sociedad: EUR, o MXN en 3100.
- **Iconos:** `lucide-react`, 16 px, trazo 1,5.
- **Tema:** solo claro. El modo oscuro queda fuera de alcance.

## 3. Arquitectura técnica

### 3.1 Stack

| Pieza | Elección | Por qué |
| --- | --- | --- |
| Base | React 19, Vite, TypeScript estricto | Decidido con el equipo |
| Estilos | CSS Modules + `src/design/tokens.css` | Sin dependencia de framework CSS; tokens únicos |
| Rutas | `react-router` (modo librería) | Rutas por sección; el *peek* va en `?item=` |
| Estado | `zustand` | Stores pequeños: dataset, ejecución, interfaz, correcciones |
| Tablas | `@tanstack/react-table` + `@tanstack/react-virtual` | Listas de miles de filas (36.743 asientos en julio) |
| Gráficos | `recharts` y SVG propio | Barras, líneas y cascadas con recharts; DAG, mosaico, sankey y conectores en SVG propio |
| Trabajo pesado | Web Worker + `comlink` | Parseo de JSONL de 40 MB sin bloquear la interfaz |
| Ficheros | `fflate` | Leer zips subidos y generar el zip de entrega |
| Persistencia | `idb-keyval` (IndexedDB) | Recordar datasets y ejecuciones entre recargas |
| Paleta de comandos | `cmdk` | ⌘K |
| Pruebas | `vitest` + Testing Library | Lógica del motor y componentes |

### 3.2 Estructura de carpetas (cada carpeta tiene un único agente responsable)

```
app/
├── PLAN.md  CONTRACT.md  README.md
├── index.html  package.json  vite.config.ts  vitest.config.ts  tsconfig*.json  .env.example
├── dev/kalmoraData.ts            middleware de Vite: sirve datasets y paquetes locales en /__data y /__runs
└── src/
    ├── main.tsx  App.tsx
    ├── app/                      router, registro de rutas (routes.ts), proveedores
    ├── design/                   tokens.css, global.css, fuentes
    ├── components/               primitivas de la interfaz (ver 3.6)
    ├── shell/                    barra lateral, cabecera, PeekHost, CommandPalette, selector de ejecución
    ├── domain/                   tipos (erp, inbox, bank, tasks, deliverables, golden, bundle) y catálogos (política, cuentas)
    ├── data/                     fuentes (carpeta, zip, http), parsers, worker, stores, persistencia
    ├── engine/                   nota (puerto de score.py), balance, validación, síntesis de traza, selectores
    ├── features/
    │   ├── overview/  attention/  activity/  item/  runs/  deliverables/
    │   ├── tasks/ap/  tasks/ar-billing/  tasks/ar-cash/  tasks/bank/  tasks/ic/  tasks/close/
    │   └── ledger/  data-explorer/  compare/  observability/
    └── lib/                      formato de importes y fechas, ids, teclado
```

### 3.3 Flujo de datos

1. **Dataset (entradas).** Lo cargan tres fuentes: `FileSystemSource` (carpeta arrastrada o elegida), `ZipSource` y `HttpSource` (middleware de desarrollo o backend).
   - Un Web Worker lee y parsea los ficheros y construye índices: por id de documento, proveedor, cliente, cuenta, línea bancaria y asiento.
   - El diario y las entradas de mercancía se cargan bajo demanda, con progreso.
   - El worker responde consultas vía `comlink`.
2. **Ejecución (salidas).** Las 6 JSONL son obligatorias. `manifest.json`, `trace/events.jsonl` y `trace/attention.jsonl` son opcionales.
   - Con golden, la referencia se crea leyendo `golden/*.jsonl` y quitando los campos internos (`cases`, `je`, etc.).
3. **Motor (`engine/`), funciones puras:**
   - **Partidas:** un `WorkItem` por fila entregada, o por línea o casación en bancos.
   - **Atención:** heurísticas de §4 si no viene `attention.jsonl`.
   - **Traza mínima** si no viene `events.jsonl`: la cascada de la política reconstruida desde la decisión y los motivos.
   - **Balance de sumas y saldos:** registrado (desde el diario), después (más todos los asientos entregados) y correcto (desde golden).
   - **Validaciones de formato y nota:** puerto exacto de `score.py`.
4. **Vistas:** leen el motor a través de selectores memoizados. Ninguna vista parsea ficheros.

### 3.4 Propiedad de la capa de datos

La capa de datos es del equipo de backend. Lo que construye el paquete 1.B es un **adaptador v1** provisional:

- **Frontera estable para las pantallas:** `src/data/stores.ts` y los tipos de `src/domain/types/`. Ninguna vista importa de `src/data/sources`, `src/data/parsers` ni `src/data/worker`.
- **Cambiar de origen** (carpeta local, middleware de desarrollo o API del backend) es añadir o cambiar un proveedor, sin tocar stores ni vistas.
- **Los parsers del navegador** (N43, CAMT.053, CSV, Facturae y CFDI) solo sirven para mostrar evidencias. Si el backend entrega los datos ya parseados, se retiran.

### 3.4.1 Alineación con los milestones del backend

El backend se construye en los milestones del repo, de M0 a M7, en el mismo orden de dependencias que el frontend.

| Milestone | Qué produce | Qué consume el frontend | Pantalla |
| --- | --- | --- | --- |
| M0 — Base, contratos y auditoría | Lectura reproducible, contratos de salida (M0-06), informe de ejecución con modelo, coste y tiempo (M0-11), comparador con golden (M0-09) | Informe de ejecución como `manifest.json`; los mismos contratos de salida | Ejecuciones, Coste, Comparar |
| M1 — AP | `ap.jsonl` | Decisiones, motivos, asientos | Bandeja AP, Actividad, Atención |
| M2 — Facturación | `ar_billing.jsonl` | Facturas y pendientes de aprobación | Facturación, Cierre (obra pendiente) |
| M3 — Bancos | `bank_rec.jsonl` | Casaciones, sin casar y ajustes | Bancos |
| M4 — Cobros | `ar_cash.jsonl` | Aplicaciones y diferencias | Cobros |
| M5 — Intragrupo | `ic.jsonl` | Diferencias por pareja y causa | Intragrupo |
| M6 — Cierre | `close.jsonl` | Periodificaciones, anticipados, divisa, deterioro | Cierre, Balance |
| M7 — Integración y entrega | Ejecución completa, paquete de 6 ficheros y memoria | Paquete de ejecución completo; eventos y atención si los emite | Todas; Entregables valida el mismo paquete |

Cada milestone que termina se ve en la app al importar su JSONL: lo que aún no existe aparece como fichero ausente, con nota 0 en esa tarea.

### 3.5 Datos en desarrollo

`dev/kalmoraData.ts` sirve las carpetas definidas en `.env.local`:

```
KALMORA_DATASETS=dev:../../participant/phase_dev,test:../../participant-2/phase_test
KALMORA_RUNS=../runs
```

`KALMORA_RUNS` puede apuntar a la carpeta `outputs/` del backend. El backend guarda los datos en `participant/` o `data/`, ambos fuera de git; `KALMORA_DATASETS` puede apuntar ahí.

- Los datos **nunca** se copian al repo.
- `runs/` está en `.gitignore`. En particular, no se publican resultados de septiembre en el repo público.

### 3.6 Componentes base (`src/components/`)

| Grupo | Componentes |
| --- | --- |
| Acción | `Button` (primario en píldora naranja, secundario, fantasma), `IconButton`, `Kbd` |
| Estado | `StatusDot`, `Badge`, `Pill`, `ProvenanceBadge` (Regla, Histórico, Modelo, Humano), `ConfidenceBand` |
| Datos | `Amount` (céntimos a importe con moneda), `Mono`, `DataTable` (virtualizada, agrupable, selección por teclado), `KeyValue`, `Metric`, `Sparkline`, `ProgressBar` |
| Estructura | `Card`, `Section`, `Tabs`, `SegmentedControl`, `FilterBar` + `FilterChip`, `ViewOptions`, `EmptyState`, `Skeleton`, `QueryState` |
| Capas | `SidePanel` (peek), `Dialog`, `Menu`, `Tooltip`, `Toast` |

Componentes de dominio compartidos (`src/features/item/kit/`):

- `JournalEntryView`: debe y haber con nombres de cuenta, socio, objeto de coste y comprobación de cuadre.
- `ProcessMap`: el **mapa de decisión de un proceso**. Muestra el flujo de la política de esa tarea con el número de partidas e importe en cada rama. En AP, por ejemplo: recibidos → no son factura → duplicados → rechazos por motivo → retenciones por motivo → bloqueo de pago → contabilizados. Al pulsar una rama se filtra la lista. Es la vista de «razonamiento por proceso».
- `ReasoningView`: el razonamiento de una partida en lenguaje claro. Combina la cascada, los eventos, el precedente histórico y la confianza, y termina en la decisión con su artículo de la política.
- `PolicyCascade`: comprobaciones en orden con ✓, ✗ y la que corta.
- `TraceTimeline`: los eventos de una partida en orden.
- `EvidenceList`, con su visor de documentos: PDF en `iframe` con blob, XML formateado y JSON.
- `RawBankRecord`: registros N43 22 y 23 y nodo CAMT.
- `GoldenDiff`: diferencias campo a campo y línea a línea.
- `MasterCompare`: por ejemplo, el IBAN de la factura frente al de la ficha.

## 4. Mapa de pantallas

| Ruta | Pantalla | Pregunta que responde | Visualizaciones clave |
| --- | --- | --- | --- |
| `/` | Resumen | ¿Cómo ha ido el cierre? | Frase de apertura con la cifra clave. Indicadores: autonomía, partidas en atención en número y €, hueco del balance cerrado, nota, coste y tiempo. DAG de las 6 tareas en orden con estado y recuentos. Mosaico de partidas por estado. Tarjetas por tarea con peso y nota. Controles de cierre: 555 a cero, 12/12 bancos, intragrupo neto, asientos cuadrados. «Te necesitan» con las primeras 5 de atención |
| `/atencion` | Atención | ¿Qué necesita a una persona? | Grupos P0–P3 ordenados por pérdida esperada. Tarjeta con importe, regla, evidencia, recomendación y alternativas. Aceptar, Elegir alternativa, Posponer y Nota. Aplicar a similares. Contador de pendientes en número y € |
| `/actividad` | Actividad | ¿Qué hizo el agente, partida a partida? | Lista de todas las partidas agrupable por tarea, sociedad o estado, con filtros. Línea temporal de eventos si hay `events.jsonl` |
| `?item=<tarea>:<clave>` | Panel de partida (sobre cualquier ruta) | ¿Por qué esta decisión? | Pestañas **Razonamiento** (la primera), Resumen, Asiento, Evidencia y Golden |
| `/tareas/ap` | Bandeja de proveedores | ¿Qué se hizo con cada documento? | Sankey de tipo de documento a decisión. Lista con facetas de decisión y motivo. Ficha con el documento al lado, campos extraídos frente al maestro, casación línea a línea con pedido y entrada, cascada §2.2, beneficiario y bloqueo, enlace al duplicado |
| `/tareas/facturacion` | Facturación AR | ¿Qué se factura y por cuánto? | Partidas por tipo de contrato. Cálculo «a origen − anterior». Vista previa de la factura (líneas, IVA, retención, deducciones, DIR3). Obra pendiente de certificar enlazada al cierre |
| `/tareas/cobros` | Aplicación de cobros | ¿Qué paga cada abono? | Reparto de cada abono en facturas, pagarés y diferencias (barra apilada). Partidas abiertas del cliente antes y después. Barra de vaciado de la 555 |
| `/tareas/bancos` y `/tareas/bancos/:cuenta` | Conciliación bancaria | ¿Cuadra cada cuenta? | Rejilla de las 12 cuentas con estado y saldos. Vista enfrentada banco/libro con conectores de casación (1:1, N:1, 1:N). Sin casar por categoría. Ajustes. Puente de saldo extracto → libro. Registro crudo N43/CAMT |
| `/tareas/intragrupo` | Intragrupo | ¿Qué pareja no cuadra y por qué? | Matriz sociedad × sociedad con diferencias. Ficha de pareja con ambos libros, causa y ajuste. Cálculo act/360 del préstamo |
| `/tareas/cierre` | Cierre | ¿Qué falta registrar a fin de mes? | Periodificaciones con la estimación frente al histórico del proveedor (sparkline). Calendario de anticipados. Valoración en divisa con tipos. Deterioro por tramos de antigüedad. Obra pendiente |
| `/balance` | Balance de sumas y saldos | ¿Cuánto falta para el balance correcto? | Cascada «hueco cerrado» por tarea. Mapa de calor sociedad × grupo de cuentas. Tabla registrado / después / correcto con diferencias |
| `/datos/...` | Datos | ¿Qué hay en las entradas? | Maestros, diario virtualizado con filtros, bandeja de documentos y extractos, todo enlazado desde las partidas |
| `/entregables` | Entregables | ¿Está lista la entrega? | Validación por fichero: filas frente a `tasks/`, esquema, cuadre y céntimos. Nota y subnotas si hay golden. Vista previa. Descarga del zip y de cada fichero |
| `/ejecuciones`, `/ejecuciones/nueva`, `/ejecuciones/:id` | Ejecuciones | ¿De dónde salen estos resultados? | Lista de ejecuciones por dataset. Nuevo cierre (subida e inventario). Vista en vivo: DAG con progreso y feed de eventos por SSE |
| `/comparar` | Comparar con golden | ¿En qué se equivoca el agente? | Subnotas por tarea con desglose hasta la partida. Lista de diferencias por campo |
| `/coste` | Coste y ejecución | ¿Qué ha costado? | Tokens y coste por modelo (Jev, Claude). Gantt de duración por tarea. Curva de fiabilidad y deslizador de umbral si los eventos traen confianza |
| `/asistente` (y panel ⌘J) | Asistente | ¿Qué quiero saber del cierre? | Titular «¿Por dónde empezamos?». Caja de pregunta. 4 preguntas preestablecidas. Conversación con respuestas en tarjetas (cifras, partidas enlazadas, pasos de razonamiento con artículo de la política y evidencia) |

Todas las vistas por tarea (`/tareas/*`) **abren con su `ProcessMap`**: el razonamiento por proceso va antes que la lista.

## 5. Reglas del motor para derivar partidas y atención

Se aplican cuando el paquete no trae `trace/` y documentan la interpretación por defecto.

| Tarea | Partida | Estado | Atención |
| --- | --- | --- | --- |
| AP | `doc_id` | POST y NOT_INVOICE → resuelto. POST_PAYMENT_BLOCK, HOLD y REJECT → bloqueado. DUPLICATE → resuelto | `BANK_DETAILS_CHANGED` → P0 fraude. Resto de HOLD y REJECT → P2 excepción de política. Acciones de datos maestros (`UPDATE_BANK_DETAILS`, `REGISTER_*`) → P2 maestro |
| Facturación | `billing_item` | INVOICE → resuelto. SKIP_PENDING_APPROVAL → bloqueado | SKIP → P2 seguimiento |
| Cobros | `bank_line` | Sin diferencias → resuelto; con diferencias → resuelto con nota | `NON_CUSTOMER` y `OVERPAYMENT_DUPLICATE` → P1. Aplicación parcial → P2 |
| Bancos | cada casación y cada línea sin casar | Casado → resuelto. Sin casar con ajuste → resuelto. Sin casar sin ajuste → abierto | `BANK_ERROR` → P2. `POOLING_NOT_BOOKED`, `UNRECORDED_RECEIPT` y `WRONG_BANK_ACCOUNT` → P1 vínculo entre tareas |
| Intragrupo | pareja + causa | Con ajuste → resuelto. Sin ajuste → abierto | `POOLING_NOT_BOOKED` → P1 vínculo entre tareas |
| Cierre | tipo + clave | Resuelto | `ACCRUAL`, `BAD_DEBT` y `FX_REVAL` por encima de 50.000 € → P1 estimación |

En todas las tareas, un asiento descuadrado → P0 diferencia material. El orden dentro de cada prioridad es por importe. Si el evento trae confianza, se ordena por pérdida esperada, (1 − p) × importe.

## 6. Fases

Cada fase termina en una **puerta**: comprobaciones que el coordinador ejecuta antes de abrir la siguiente. Dentro de cada fase, los agentes trabajan en paralelo y cada uno en su carpeta.

### Fase 1 — Cimientos

**Objetivo:** esqueleto navegable con la marca Talky, datos de julio cargados y el motor dando la misma nota que `score.py`.

| Paquete | Responsable | Carpetas | Entregable |
| --- | --- | --- | --- |
| 1.0 Andamiaje | Coordinador (antes de lanzar agentes) | raíz de `app/` | Vite, TypeScript, lint, vitest, dependencias, árbol de carpetas, `routes.ts` con todas las rutas como marcadores, tipos de dominio vacíos |
| 1.A Diseño y shell | Agente «design-system» | `design/`, `components/`, `shell/` | Tokens de §2.2. Componentes de §3.6 con galería en `/dev/ui`. Barra lateral, cabecera con migas, `PeekHost` controlado por `?item=`, esqueleto de la paleta ⌘K, atajos de teclado globales |
| 1.B Datos | Agente «data-layer» | `domain/types/`, `data/`, `dev/` | Tipos de todos los ficheros de entrada y salida. Fuentes carpeta, zip y http. Parsers JSONL (por streaming), N43, CAMT.053, CSV mexicano, Facturae y CFDI. Worker con índices y carga bajo demanda. Stores de dataset y ejecución. Persistencia en IndexedDB. Middleware de desarrollo |
| 1.C Motor | Agente «engine» | `engine/`, `domain/policy.ts` | Puerto de `score.py` con pruebas de paridad. Balance registrado desde el diario. Aplicación de asientos. Validadores de entrega. Síntesis de partidas, traza mínima y atención (§5). Catálogo de motivos y categorías → § de la política |

**Puerta 1:**

- `typecheck`, `lint`, `test` y `build` en verde.
- La app arranca y las rutas navegan.
- Carga julio por el middleware y por carpeta arrastrada.
- La referencia golden da **100** en el motor.
- Paridad: sobre 3 entregas alteradas (decisiones cambiadas, asientos quitados, ficheros ausentes), la nota del motor coincide con `python score.py` con un margen de ±0,01.
- El balance registrado calculado desde el diario coincide con `golden/trial_balance_recorded.jsonl`.

### Fase 2 — Entrada, salida y vistas núcleo

**Objetivo:** el flujo completo subir → resultados → revisar → descargar funciona con julio.

| Paquete | Responsable | Carpetas | Entregable |
| --- | --- | --- | --- |
| 2.A Ejecuciones y entregables | Agente «runs-io» | `features/runs/`, `features/deliverables/` | Nuevo cierre con subida (carpeta o zip), inventario detectado, avisos y persistencia. Tres fuentes de resultados (API con SSE, importar JSONL o paquete, referencia golden). Lista y selector de ejecuciones. Vista en vivo. Entregables con validación, nota, vista previa y descarga en zip con `manifest.json` |
| 2.B Resumen | Agente «overview» | `features/overview/` | Todo lo de la fila Resumen de §4 |
| 2.C Actividad y panel de partida | Agente «activity» | `features/activity/`, `features/item/` | Lista de partidas (agrupación, filtros, opciones de vista, teclado). Panel de partida con sus 5 pestañas, con Razonamiento como pestaña principal. Kit de dominio de §3.6, incluidos `ProcessMap` y `ReasoningView` |
| 2.D Atención | Agente «attention» | `features/attention/` | Cola P0–P3, tarjetas, acciones, aplicar a similares, store de correcciones y exportación de `overrides.jsonl` |

**Puerta 2:**

- Recorrido completo sobre julio: subir la carpeta, abrir la referencia, ver el Resumen con cifras que cuadran con `tasks/`.
- `API004128` (certificación con ISP y garantía del 5 %) muestra su asiento de 7 líneas cuadrado y la cascada §2.2 en verde.
- Descargar el zip y pasarlo por `python score.py` da 100.
- Importar el zip de vuelta reproduce las mismas pantallas.
- Cero errores en consola.

### Fase 3 — Vistas por tarea

**Objetivo:** cada tarea tiene su espacio de trabajo. Abre con su mapa de decisión (`ProcessMap`) y sigue con la visualización que mejor explica su resultado (§4).

| Paquete | Responsable | Carpeta |
| --- | --- | --- |
| 3.A AP | Agente «task-ap» | `features/tasks/ap/` |
| 3.B Facturación | Agente «task-ar-billing» | `features/tasks/ar-billing/` |
| 3.C Cobros | Agente «task-ar-cash» | `features/tasks/ar-cash/` |
| 3.D Bancos | Agente «task-bank» | `features/tasks/bank/` |
| 3.E Intragrupo | Agente «task-ic» | `features/tasks/ic/` |
| 3.F Cierre y balance | Agente «task-close-ledger» | `features/tasks/close/`, `features/ledger/` |

**Puerta 3:**

- Las 7 vistas abren todas las partidas de julio sin errores.
- Comprobaciones puntuales contra golden:
  - en AP, un duplicado, un fraude de IBAN y un abono;
  - en bancos, una remesa N:1 y una comisión sin contabilizar;
  - en cobros, una factura cedida cobrada por error;
  - en intragrupo, la diferencia de base de días;
  - en cierre, una periodificación y la valoración en divisa de 3100.
- La lista de AP con 305 filas y el diario con 36.743 asientos se desplazan con fluidez.

### Fase 4 — Datos, comparación y observabilidad

**Objetivo:** cualquier cifra se puede seguir hasta su origen, y el equipo de backend puede depurar contra golden desde la app.

| Paquete | Responsable | Carpeta | Entregable |
| --- | --- | --- | --- |
| 4.A Explorador de datos | Agente «data-explorer» | `features/data-explorer/` | Maestros, diario, bandeja y extractos, con enlaces cruzados (proveedor → sus facturas e histórico) |
| 4.B Comparar con golden | Agente «compare» | `features/compare/` | Subnotas por tarea hasta la partida. Diferencias por campo y por línea de asiento. Interruptor global «comparar» |
| 4.C Coste y calibración | Agente «observability» | `features/observability/` | Modelos, tokens y coste desde `manifest.json`. Gantt por tarea desde los eventos. Curva de fiabilidad y deslizador de umbral cuando hay confianza |
| 4.D Búsqueda y teclado | Agente «command» | `shell/CommandPalette*`, `lib/keyboard` | Búsqueda ⌘K de cualquier id (documento, línea bancaria, asiento, proveedor, cliente, cuenta), acciones y atajos en toda la app |

**Puerta 4:**

- ⌘K encuentra `API004128`, `BL0000085`, `V100045`, `40090000` y un id de asiento.
- Sobre una entrega alterada, Comparar muestra exactamente las partidas alteradas.
- La calibración se dibuja con un paquete de prueba que trae confianza.

### Fase 5 — Integración, pulido y verificación

**Objetivo:** demo estable y repo listo para el equipo.

| Paquete | Responsable | Entregable |
| --- | --- | --- |
| 5.A QA de punta a punta | Agente «qa» | Recorrido en el navegador de todas las rutas con julio (referencia) y septiembre (resultados importados), con capturas y lista de fallos corregidos |
| 5.B Pulido | Agente «polish» | Estados vacíos, carga y error. Accesibilidad (teclado, foco, contraste del naranja sobre blanco en texto pequeño). Rendimiento (división por rutas, worker). Consistencia visual |
| 5.C Documentación y demo | Agente «docs-demo» | `app/README.md` (arranque, datos, contrato) y modo demo con el guion del informe |

**Puerta 5:** se cumple todo el «terminado» de §0, salvo el Asistente, que se cierra en la fase 6.

### Fase 6 — Asistente conversacional

**Objetivo:** preguntar al cierre en lenguaje natural y obtener respuestas con la misma trazabilidad que el resto de la app.

| Paquete | Responsable | Carpeta | Entregable |
| --- | --- | --- | --- |
| 6.A Interfaz del Asistente | Agente «assistant-ui» | `features/assistant/` (salvo `engine/`) | Pantalla `/asistente` con marca Talky en tema claro: titular en serif «¿Por dónde empezamos?», caja de pregunta con envío por Enter y selector de modo (Rápido, Profundo), y 4 preguntas preestablecidas en chips con icono. Conversación con respuestas en tarjetas: cifras, tabla, partidas que abren el panel lateral, pasos de razonamiento con artículo de la política y evidencia. Historial por ejecución. El mismo chat como panel lateral desde cualquier pantalla con ⌘J |
| 6.B Motor de respuestas | Agente «assistant-engine» | `features/assistant/engine/` | Proveedor local determinista sobre `useDerivedRun`. Intenciones: resumen del mes, qué revisar, por qué no cuadra el balance, cómo decidió un proceso, explicar una partida por su id, estado de una cuenta bancaria, coste. Proveedor API (`POST /api/chat` por SSE, `CONTRACT.md` §2) para que el backend responda con Claude y herramientas sobre la ejecución. Las claves de API nunca están en el navegador |

**Preguntas preestablecidas:**

1. «Resumen del último mes contable».
2. «¿Qué partidas tengo que revisar?».
3. «¿Por qué no cuadra el balance?».
4. «¿Cómo ha decidido el agente la bandeja de proveedores?».

**Puerta 6:**

- Las 4 preguntas responden con cifras idénticas a las de Resumen y Atención.
- Cada partida citada abre el panel lateral.
- «Explica API004128» devuelve su razonamiento.
- El proveedor API funciona contra un servidor SSE de prueba.

## 7. Orquestación multiagente

- **Rama única** `hackathon/frontend`.
  - Un commit por paquete, con asunto `type: subject` (por ejemplo, `feat: add bank reconciliation view`), sin ámbito entre paréntesis ni atribución.
  - Push al cerrar cada puerta.
- **Propiedad de carpetas:** un agente solo escribe en las carpetas de su paquete.
  - Rutas, barra lateral y tipos de dominio son del coordinador después de la fase 1.
  - Un agente que necesite cambiarlos lo pide en su informe.
- **Contratos congelados al cerrar la fase 1:** tipos de `domain/`, API de los stores, firmas del motor y props de los componentes base. Ampliar se permite; romper, no.
- **Cada agente:**
  - lee este plan, `CONTRACT.md` y `PROBLEM.md`;
  - prueba su lógica con vitest;
  - ejecuta `typecheck` y `build` antes de entregar;
  - informa de lo hecho, lo pendiente y lo no verificado.
- **El coordinador**, en cada puerta:
  - integra;
  - ejecuta las comprobaciones;
  - recorre la app en el navegador integrado;
  - corrige los choques;
  - commitea.
- **Ejecución:**
  - fase 1: 1 andamiaje + 3 agentes en paralelo;
  - fase 2: 4 agentes;
  - fase 3: 6 agentes;
  - fase 4: 4 agentes;
  - fase 5: 3 agentes;
  - fase 6: 2 agentes.
  - Una fase no empieza hasta cerrar la puerta de la anterior.

## 8. Riesgos y decisiones

| Riesgo o decisión | Tratamiento |
| --- | --- |
| Memoria del navegador con el diario completo (36–40 MB por fase) | Carga bajo demanda en el worker. Índices por id. Nunca se mantiene el diario entero en React |
| Paridad exacta con `score.py` | Pruebas de paridad contra Python en la puerta 1. Cualquier diferencia bloquea la fase |
| Repo público | Ni datos, ni ejecuciones, ni resultados de septiembre en git. `runs/` y `.env.local` en `.gitignore` |
| Despliegue (Vercel) | Fuera de este plan. En producción no hay datos servidos: se sube la carpeta. Lo decide el equipo |
| Backend aún sin API | La app funciona importando las 6 JSONL. La API de `CONTRACT.md` se conecta cuando exista, sin tocar pantallas |
| Correcciones humanas | No alteran la entrega. Se exportan a `overrides.jsonl` y se cuentan en el manifiesto |
