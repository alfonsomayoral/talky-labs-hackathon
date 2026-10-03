# Estado del frontend

Solo lo edita la sesión coordinadora. Cada sesión escribe su estado y sus peticiones en `app/status/<rama>.md`, con `/` cambiada por `-` (ver `AGENTS.md` §8).

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
| 2.C Actividad y panel de partida | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | En curso | 1.C | `ItemPanel` y kit (`ProcessMap`, `ReasoningView`, `JournalEntryView`…). **Desbloquea la fase 3** |
| 2.D Atención | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.C | Commit `21fc1c3` |
| Refinado de diseño + 4.D Búsqueda y teclado | «Kalmora Close frontend: diseño y shell» | `fe/design-shell` | `talky-wt/fe-design-shell` | 5174 | Asignado | 1.A | Cambios de componentes solo compatibles (las demás sesiones los usan) |
| 4.A Explorador de datos + 4.C Coste y calibración | «Resumen y Atención Kalmora Close» | `fe/explorer-cost` | `talky-wt/fe-explorer-cost` | 5176 | Asignado | 1.B, 1.C | Resumen y Atención ya los cubre la coordinadora |
| 3.B Facturación + 3.C Cobros | «Actividad y panel de partida» | `fe/tasks-ar` | `talky-wt/fe-tasks-ar` | 5175 | Esperando el kit | 2.C (kit) | 2.C lo termina la coordinadora |
| 3.A AP + 3.D Bancos | «Kalmora Close frontend: AP y Bancos» | `fe/tasks-ap-bank` | `talky-wt/fe-tasks-ap-bank` | 5177 | Asignado; el kit llega después | 2.C (kit) | Puede empezar por lo que no usa el kit |
| 3.E Intragrupo + 3.F Cierre y balance | — | — | — | — | Pendiente | 2.C (kit) | Siguiente oleada |
| 4.B Comparar con golden | — | — | — | — | Pendiente | 2.C | Siguiente oleada |
| 5.A–5.C QA, pulido y demo | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Pendiente | Fases 2–4 | |
| 6.A–6.B Asistente | — | — | — | — | Pendiente | 2.C, 2.D | Ruta `/asistente` ya registrada |

## Seguimiento de sesiones

| Sesión | Última instrucción | Próximo hito |
| --- | --- | --- |
| Diseño y shell | Instrucciones enviadas: refinado, peticiones de diseño y ⌘K | Informe en `app/status/fe-design-shell.md` |
| Resumen y Atención | Instrucciones enviadas: 4.A + 4.C, empieza ya | Informe en `app/status/fe-explorer-cost.md` |
| Actividad y panel de partida | Instrucciones enviadas: parar 2.C; 3.B + 3.C tras el kit | Aviso de la coordinadora cuando el kit esté en `hackathon/frontend` |
| AP y Bancos | Instrucciones enviadas: avanzar sin el kit | Aviso de la coordinadora cuando el kit esté en `hackathon/frontend` |

## Puertas

| Puerta | Estado | Comprobación |
| --- | --- | --- |
| 1 — Cimientos | Cerrada | Comprobaciones en verde, nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | Abierta | Recorrido completo sobre julio, `API004128` con su asiento de 7 líneas, zip de entrega con nota 100 |
| 3 a 6 | Pendientes | Ver `PLAN.md` §6 |
