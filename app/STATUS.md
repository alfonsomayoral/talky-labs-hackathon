# Estado del frontend

Solo lo edita la sesión coordinadora. Cada sesión escribe su estado y sus peticiones en `app/status/<rama>.md`, con `/` cambiada por `-`, y al terminar abre una PR contra `hackathon/frontend` (ver `AGENTS.md` §8).

Ruta de datos: **lista**. Julio se carga desde el middleware, la referencia golden se crea, y `useDerivedRun()` devuelve partidas, atención, traza sintetizada, validación y nota 100. La puerta 1 está cerrada.

## Paquetes

| Paquete | Sesión | Rama | Worktree | Puerto | Estado | Depende de | Notas |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.0 Andamiaje | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | — | Tipos de dominio, rutas y navegación |
| 1.A Diseño y shell | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.0 | Tokens Talky, 25 componentes, shell con hoja flotante, logo de Talky |
| 1.B Datos (adaptador v1) | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.0 | Balance registrado igual al golden; 96 extractos cuadran |
| 1.C Motor | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.0 | Paridad exacta con `score.py` en 8 casos; totales en EUR |
| 2.A Ejecuciones y entregables | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.B, 1.C | El zip de entrega saca 100 en `score.py` |
| 2.B Resumen | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.C | Commit `ac57d87` |
| 2.C Actividad y panel de partida | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.C | `ItemPanel` y kit (`ProcessMap`, `ReasoningView`, `JournalEntryView`…), con su `README.md`. Desbloquea la fase 3 |
| 2.D Atención | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.C | Commit `21fc1c3` |
| Refinado de diseño + 4.D Búsqueda y teclado | «Kalmora Close frontend: diseño y shell» | `fe/design-shell` | `talky-wt/fe-design-shell` | 5174 | Hecho e integrado (`2e27dea`) | 1.A | Cambios de componentes solo compatibles (las demás sesiones los usan) |
| 4.A Explorador de datos + 4.C Coste y calibración | «Explorador de datos y coste» | `fe/explorer-cost` | `talky-wt/fe-explorer-cost` | 5176 | Hecho e integrado (`f5420cc`) | 1.B, 1.C | |
| 3.B Facturación + 3.C Cobros | «Facturación y Cobros Kalmora Close» | `fe/tasks-ar` | `talky-wt/fe-tasks-ar` | 5175 | Hecho e integrado (PR #129) | 2.C (kit) | |
| 3.A AP + 3.D Bancos | «AP + Bancos tasks frontend» | `fe/tasks-ap-bank` | `talky-wt/fe-tasks-ap-bank` | 5177 | Hecho e integrado | 2.C (kit) | Más `37b4774`: estado de cuenta con la regla del control del Resumen |
| 3.E Intragrupo + 3.F Cierre y balance | «Explorador de datos y coste» | `fe/tasks-ic-close` | `talky-wt/fe-explorer-cost` | 5176 | Hecho e integrado (PR #132) | 2.C (kit) | |
| 4.B Comparar con golden | Coordinadora (subagente) | `fe/compare` | `talky-wt/fe-design-shell` | 5174 | Hecho e integrado (`0d5bdda`) | 2.C | Peticiones resueltas: `?pestana=golden`, importes con `Amount`, etiqueta «Pierde por sus partidas» |
| 5.A–5.B QA y pulido: núcleo | «QA y pulido: núcleo» | `fe/qa-core` | `talky-wt/fe-explorer-cost` | 5176 | Hecho e integrado (#158, #165) | Fases 2–4 | Resumen, Atención, Actividad, panel y kit, Ejecuciones, Entregables, Comparar, Coste y Asistente |
| 5.A–5.B QA y pulido: tareas y datos | «QA y pulido: tareas y datos» | `fe/qa-tasks` | `talky-wt/fe-tasks-ar` | 5175 | Hecho e integrado (#154, #161, #166) | Fase 3 | `/tareas/*`, Balance y Datos |
| 5.B–5.C Pulido transversal y demo | «Pulido transversal y demo Kalmora» | `fe/qa-shell-demo`, `fe/qa-shell-format` | `talky-wt/fe-design-shell` | 5174 | Hecho e integrado (#153, #157, #162) | Fases 2–4 | Diseño, componentes, shell, accesibilidad y el «Recorrido de demo» de `app/README.md` |
| 5 — PRs de QA, chunk principal y «terminado» de §0 | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 5.A–5.C | Framework en su propio chunk (`53ae7b6`): `index` pasa de 471 a 168 kB |
| 6.A–6.B Asistente | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 2.C, 2.D | `/asistente` y panel ⌘J; proveedor local y SSE |

## «Terminado» de `PLAN.md` §0

Comprobado por la coordinadora el 03/10/2026 sobre `hackathon/frontend`.

| # | Punto | Estado | Evidencia |
| --- | --- | --- | --- |
| 1 | Julio carga, crea la referencia y su nota en la app es 100,00, igual que `score.py` | Cumple | `/dev/data` con `phase_dev`: nota 100. Paridad con `score.py` en `src/engine/score/parity.test.ts` |
| 2 | El zip de Entregables, pasado por `score.py`, saca la misma nota que la app | Cumple | Zip descargado del navegador → `score.py`: 100,00, todas las subnotas a 1,0. Con entregas alteradas, la paridad del motor la cubre `parity.test.ts` |
| 3 | Importar unas 6 JSONL cualesquiera (septiembre) llena todas las pantallas sin tocar código | Cumple, con la QA de fase 5 en curso | `phase_test-research-qa`: 6/6 entregas, 719 partidas, «Lista», cero errores de consola en todas las rutas. Sin fichero, la vista de tarea lo dice (`MissingTaskFile`). Aún no hay ninguna entrega del backend, que sigue en M0 |
| 4 | Cada partida de las 6 tareas abre con asiento cuadrado, regla, evidencia enlazada y comparación con golden | Cumple | `src/engine/derive/doneCheck.test.ts`, sobre las 726 partidas de julio. Destapó 4 partidas de cierre sin evidencia, corregidas en `df39c16` |
| 5 | `typecheck`, `lint`, `test` y `build` en verde | Cumple | 360 tests y build sin avisos en `c1a37d9` |
| 6 | El Asistente responde las 4 preguntas con cifras iguales a Resumen y Atención, y las partidas citadas abren el panel | Cumple | Navegador con julio: 56 pendientes, 11,6 M€, hueco de 69,8 M€ a 0 €. Tests en `src/features/assistant/engine/local.test.ts` |
| 7 | El recorrido de demo se hace sin errores en consola | Cumple | Los 7 pasos del «Recorrido de demo» de `app/README.md` sobre julio, sin errores ni avisos |

Última pasada sobre `c1a37d9` (todas las PRs de la fase 5 integradas):
- **3:** septiembre sin golden, todas las rutas y una partida por tarea con todas sus pestañas, sin errores de consola;
- **5:** 360 tests y build sin avisos;
- **6:** las cifras cuadran en julio (las 4 preguntas) y en septiembre (resumen y revisión);
- **7:** el recorrido de demo de julio, sin errores.

**Los 7 puntos se cumplen. Plan cerrado.**

## Pendiente tras el cierre

Nada de esto rompe la app.

- **Límite de la prueba con resultados reales.** Septiembre se probó con las salidas de los prototipos del research (`/Users/alfonsomayoral/Talky/runs/phase_test-research-qa/`), no con el backend: este sigue en M0 y aún no produce entregas. Cuando el backend entregue las 6 JSONL hay que repetir el punto 3 con ellas. Su API (`/api/runs` con SSE) tampoco se ha probado contra un servidor real.
- **Asistente.** El modo Profundo con modelo (`dev/assistantChat.ts`) solo existe en desarrollo, con la clave en `app/.env.local`. En producción, la redacción tendrá que hacerla el backend (`POST /api/chat`).
- **Núcleo (qa-core):**
  - Comparar enseña el selector «Solo diferencias / Todo» en el estado vacío sin golden.
  - `ProcessMap` se corta en el panel ⌘J.
  - `JournalEntryView` muy estrecho oculta el nombre de la cuenta.
  - Quedan textos auxiliares en `--ink-4`.
- **Tareas (qa-tasks):**
  - La ficha AP de documentos que no son factura enseña el apartado «Pago».
  - El dominio parecido no resalta el carácter que cambia.
  - La descripción de cuenta del Balance se corta a 1440 px.
  - En Bancos de septiembre, los intereses de préstamo salen con 2 líneas sin casar y 3 ajustes. Es de la entrega del prototipo: que el backend lo cuadre.
- **Sin verificar:** teclado y lector de pantalla en cada vista, y anchos menores de 1440 px.

## Datos para la QA

- Julio: `participant/phase_dev` con su referencia golden.
- Septiembre: `participant-2/phase_test` y el paquete `/Users/alfonsomayoral/Talky/runs/phase_test-research-qa/`, fuera del repo, en `KALMORA_RUNS=/Users/alfonsomayoral/Talky/runs`. **No es del backend**, que sigue en M0 sin entregas: son las salidas de septiembre de los prototipos del research (`ap_decision` + asientos de `ap_coding`, `ar_billing`, `ar_cash/sub_test`, `bank/out_test`, `ic_diff/test_ic_prior` y `close_tb/sub_test`). Nunca se commitea.

## Seguimiento de sesiones

Todas las sesiones de trabajo han cerrado su paquete y no hay PRs abiertas contra `hackathon/frontend`.

## Puertas

| Puerta | Estado | Comprobación |
| --- | --- | --- |
| 1 — Cimientos | Cerrada | Comprobaciones en verde, nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | Cerrada | Comprobaciones en verde (218 tests). Julio y golden cargados: `API004128` con su asiento de 7 líneas cuadrado y la cascada §2.2 en verde. El zip descargado de Entregables saca 100,00 en `score.py`; importado de vuelta reproduce Resumen y Entregables (726 partidas, 56 en atención, nota 100). Cero errores en consola |
| 3 — Vistas por tarea | Cerrada | Las 7 vistas abren julio sin errores de consola. AP: duplicado `API005209`, fraude `API005229`, abono `API005587`. Bancos: N:1 `BIN-1200/BL0004009`, comisiones sin contabilizar con ajuste y 12/12 conciliadas. Cobros: factura cedida `BL0000085`. Intragrupo: base de días 25.833,33 € frente a 25.000 €. Cierre: periodificación `ACCRUAL/1200/V100039` y valoración de 3100 (−5.993.500 MXN). Diario de 36.743 asientos en páginas de 500 |
| 4 — Datos, comparación y observabilidad | Cerrada | ⌘K encuentra `API004128`, `BL0000085`, `V100045`, `40090000` y un asiento (sesión 4.D). Comparar lista exactamente las partidas alteradas (test con julio y navegador). Calibración dibujada con un paquete sintético con confianza (sesión 4.C) |
| 5 — Integración, pulido y verificación | Cerrada | Las 3 sesiones de QA integradas. Comprobaciones en verde (360 tests). Septiembre sin golden: todas las rutas, una partida por tarea con todas sus pestañas, y Resumen, Atención y Asistente con las mismas cifras (645 de 719, 60 pendientes, 9,4 M€). Julio: recorrido de demo sin errores. Cero errores de consola |
| 6 — Asistente | Cerrada | Las 4 preguntas con las cifras de Resumen y Atención en julio, y las de resumen y revisión también en septiembre; las partidas citadas abren el panel; «Explica API004128» da su razonamiento; proveedor API probado contra SSE simulado; modo Profundo con modelo solo en desarrollo |
