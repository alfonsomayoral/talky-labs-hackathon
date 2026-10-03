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
| 5.A–5.B QA y pulido: núcleo | «QA y pulido: núcleo» | `fe/qa-core` | `talky-wt/fe-explorer-cost` | 5176 | En curso | Fases 2–4 | Resumen, Atención, Actividad, panel y kit, Ejecuciones, Entregables, Comparar, Coste y Asistente |
| 5.A–5.B QA y pulido: tareas y datos | «QA y pulido: tareas y datos» | `fe/qa-tasks` | `talky-wt/fe-tasks-ar` | 5175 | En curso | Fase 3 | `/tareas/*`, Balance y Datos |
| 5.B–5.C Pulido transversal y demo | «Pulido transversal y demo Kalmora» | `fe/qa-shell-demo` | `talky-wt/fe-design-shell` | 5174 | En curso | Fases 2–4 | Diseño, componentes, shell y accesibilidad. La demo es solo el «Recorrido de demo» de `app/README.md`, al final y sin prioridad |
| 5 — PRs de QA y «terminado» de §0 | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | En curso | 5.A–5.C | Revisa y fusiona las PRs |
| 6.A–6.B Asistente | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 2.C, 2.D | `/asistente` y panel ⌘J; proveedor local y SSE |

## «Terminado» de `PLAN.md` §0

Comprobado por la coordinadora el 03/10/2026 sobre `hackathon/frontend`.

| # | Punto | Estado | Evidencia |
| --- | --- | --- | --- |
| 1 | Julio carga, crea la referencia y su nota en la app es 100,00, igual que `score.py` | Cumple | `/dev/data` con `phase_dev`: nota 100. Paridad con `score.py` en `src/engine/score/parity.test.ts` |
| 2 | El zip de Entregables, pasado por `score.py`, saca la misma nota que la app | Cumple | Zip descargado del navegador → `score.py`: 100,00, todas las subnotas a 1,0. Con entregas alteradas, la paridad del motor la cubre `parity.test.ts` |
| 3 | Importar unas 6 JSONL cualesquiera (septiembre) llena todas las pantallas sin tocar código | Cumple, con la QA de fase 5 en curso | `phase_test-research-qa`: 6/6 entregas, 719 partidas, «Lista», cero errores de consola en todas las rutas. Sin fichero, la vista de tarea lo dice (`MissingTaskFile`). Aún no hay ninguna entrega del backend, que sigue en M0 |
| 4 | Cada partida de las 6 tareas abre con asiento cuadrado, regla, evidencia enlazada y comparación con golden | Cumple | `src/engine/derive/doneCheck.test.ts`, sobre las 726 partidas de julio. Destapó 4 partidas de cierre sin evidencia, corregidas en `df39c16` |
| 5 | `typecheck`, `lint`, `test` y `build` en verde | Cumple | 354 tests en `3c980fe` |
| 6 | El Asistente responde las 4 preguntas con cifras iguales a Resumen y Atención, y las partidas citadas abren el panel | Cumple | Navegador con julio: 56 pendientes, 11,6 M€, hueco de 69,8 M€ a 0 €. Tests en `src/features/assistant/engine/local.test.ts` |
| 7 | El recorrido de demo se hace sin errores en consola | Cumple | Los 7 pasos del «Recorrido de demo» de `app/README.md` sobre julio, sin errores ni avisos |

Repetido sobre `5caa8e8`, que ya lleva las PRs #153, #154, #157, #158, #161 y #162:
- **3:** septiembre sin golden, 21 rutas y paneles, cero errores y cero avisos de consola;
- **5:** 360 tests y build en verde;
- **7:** el recorrido de demo de julio, sin errores.

Pendiente para cerrar las puertas 5 y 6: la segunda PR de `fe/qa-core` (contraste y fecha en `MasterCompare`) y una última pasada de 3, 5 y 7.

## Datos para la QA

- Julio: `participant/phase_dev` con su referencia golden.
- Septiembre: `participant-2/phase_test` y el paquete `/Users/alfonsomayoral/Talky/runs/phase_test-research-qa/`, fuera del repo, en `KALMORA_RUNS=/Users/alfonsomayoral/Talky/runs`. **No es del backend**, que sigue en M0 sin entregas: son las salidas de septiembre de los prototipos del research (`ap_decision` + asientos de `ap_coding`, `ar_billing`, `ar_cash/sub_test`, `bank/out_test`, `ic_diff/test_ic_prior` y `close_tb/sub_test`). Nunca se commitea.

## Seguimiento de sesiones

| Sesión | Última instrucción | Próximo hito |
| --- | --- | --- |
| QA y pulido: núcleo | Fase 5 en `fe/qa-core` | PR contra `hackathon/frontend` |
| QA y pulido: tareas y datos | Fase 5 en `fe/qa-tasks` | PR contra `hackathon/frontend` |
| Pulido transversal y demo Kalmora | Fase 5 en `fe/qa-shell-demo`; el guion de demo va en `app/README.md` | PR contra `hackathon/frontend` |
| Explorador, Facturación y Cobros, AP + Bancos | Paquetes cerrados e integrados | — |

## Puertas

| Puerta | Estado | Comprobación |
| --- | --- | --- |
| 1 — Cimientos | Cerrada | Comprobaciones en verde, nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | Cerrada | Comprobaciones en verde (218 tests). Julio y golden cargados: `API004128` con su asiento de 7 líneas cuadrado y la cascada §2.2 en verde. El zip descargado de Entregables saca 100,00 en `score.py`; importado de vuelta reproduce Resumen y Entregables (726 partidas, 56 en atención, nota 100). Cero errores en consola |
| 3 — Vistas por tarea | Cerrada | Las 7 vistas abren julio sin errores de consola. AP: duplicado `API005209`, fraude `API005229`, abono `API005587`. Bancos: N:1 `BIN-1200/BL0004009`, comisiones sin contabilizar con ajuste y 12/12 conciliadas. Cobros: factura cedida `BL0000085`. Intragrupo: base de días 25.833,33 € frente a 25.000 €. Cierre: periodificación `ACCRUAL/1200/V100039` y valoración de 3100 (−5.993.500 MXN). Diario de 36.743 asientos en páginas de 500 |
| 4 — Datos, comparación y observabilidad | Cerrada | ⌘K encuentra `API004128`, `BL0000085`, `V100045`, `40090000` y un asiento (sesión 4.D). Comparar lista exactamente las partidas alteradas (test con julio y navegador). Calibración dibujada con un paquete sintético con confianza (sesión 4.C) |
| 5 — Integración, pulido y verificación | Abierta | La app funciona con resultados reales sin golden (septiembre), PRs de QA integradas y «terminado» de §0 comprobado punto por punto |
| 6 — Asistente | Comprobada, se cierra con la 5 | Las 4 preguntas con las cifras de Resumen y Atención; partidas citadas abren el panel; «Explica API004128» da su razonamiento; proveedor API probado contra SSE simulado |
