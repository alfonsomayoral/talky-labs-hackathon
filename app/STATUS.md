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
| 3.E Intragrupo + 3.F Cierre y balance | «Explorador de datos y coste» | `fe/tasks-ic-close` | `talky-wt/fe-explorer-cost` | 5176 | En curso | 2.C (kit) | Rama nueva en el mismo worktree |
| 4.B Comparar con golden | Coordinadora (subagente) | `fe/compare` | `talky-wt/fe-design-shell` | 5174 | Hecho e integrado (`0d5bdda`) | 2.C | Peticiones resueltas: `?pestana=golden`, importes con `Amount`, etiqueta «Pierde por sus partidas» |
| 5.A–5.C QA, pulido y demo | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Pendiente | Fases 2–4 | |
| 6.A–6.B Asistente | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | En curso | 2.C, 2.D | Solo `src/features/assistant/`; commitea la coordinadora |

## Seguimiento de sesiones

| Sesión | Última instrucción | Próximo hito |
| --- | --- | --- |
| Explorador de datos y coste | 4.A + 4.C integrados; asignado 3.E + 3.F en `fe/tasks-ic-close` | Informe en `app/status/fe-tasks-ic-close.md` |
| Facturación y Cobros (3.B + 3.C) | Integrado; paquete cerrado | — |
| AP + Bancos (3.A + 3.D) | Integrado; paquete cerrado | — |

## Puertas

| Puerta | Estado | Comprobación |
| --- | --- | --- |
| 1 — Cimientos | Cerrada | Comprobaciones en verde, nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | Cerrada | Comprobaciones en verde (218 tests). Julio y golden cargados: `API004128` con su asiento de 7 líneas cuadrado y la cascada §2.2 en verde. El zip descargado de Entregables saca 100,00 en `score.py`; importado de vuelta reproduce Resumen y Entregables (726 partidas, 56 en atención, nota 100). Cero errores en consola |
| 3 a 6 | Pendientes | Ver `PLAN.md` §6 |
