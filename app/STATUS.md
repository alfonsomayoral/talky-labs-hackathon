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
