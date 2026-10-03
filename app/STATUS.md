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
| Diseño (refinado) | Sesión «design» | `fe/design-shell` | `talky-wt/fe-design-shell` | 5174 | Pendiente de abrir | 1.A | Pulido del sistema de diseño y del shell; luego 4.D (⌘K y teclado) |
| 2.A Ejecuciones y entregables | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | En curso | 1.B, 1.C | Subida, fuentes de resultados y zip de entrega |
| 2.B Resumen | Coordinadora (subagente) | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Hecho | 1.C | Commit `ac57d87` |
| 2.C Actividad y panel de partida | Coordinadora (subagente) → sesión «activity» | `fe/activity` | `talky-wt/fe-activity` | 5175 | En curso (subagente) | 1.C | `ItemPanel`, kit de razonamiento y `ProcessMap` |
| 2.D Atención | Coordinadora (subagente) → sesión «overview-attention» | `fe/overview-attention` | `talky-wt/fe-overview-attention` | 5176 | En curso (subagente) | 1.C | Cola P0–P3 y `overrides.jsonl` |
| 3.A AP | Sesión «tasks-ap-bank» | `fe/tasks-ap-bank` | `talky-wt/fe-tasks-ap-bank` | 5177 | Pendiente | 2.C (kit) | |
| 3.D Bancos | Sesión «tasks-ap-bank» | `fe/tasks-ap-bank` | `talky-wt/fe-tasks-ap-bank` | 5177 | Pendiente | 2.C (kit) | |
| 3.B Facturación | — | — | — | — | Pendiente | 2.C (kit) | |
| 3.C Cobros | — | — | — | — | Pendiente | 2.C (kit) | |
| 3.E Intragrupo | — | — | — | — | Pendiente | 2.C (kit) | |
| 3.F Cierre y balance | — | — | — | — | Pendiente | 2.C (kit) | |
| 4.A Explorador de datos | — | — | — | — | Pendiente | 2.C | |
| 4.B Comparar con golden | — | — | — | — | Pendiente | 2.C | |
| 4.C Coste y calibración | — | — | — | — | Pendiente | 2.A | |
| 4.D Búsqueda y teclado | Sesión «design» | `fe/design-shell` | `talky-wt/fe-design-shell` | 5174 | Pendiente | 1.A | |
| 5.A–5.C QA, pulido y demo | Coordinadora | `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Pendiente | Fases 2–4 | |
| 6.A–6.B Asistente | — | — | — | — | Pendiente | 2.C, 2.D | Ruta `/asistente` ya registrada |

## Puertas

| Puerta | Estado | Comprobación |
| --- | --- | --- |
| 1 — Cimientos | Cerrada | Comprobaciones en verde, nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | Abierta | Recorrido completo sobre julio, `API004128` con su asiento de 7 líneas, zip de entrega con nota 100 |
| 3 a 6 | Pendientes | Ver `PLAN.md` §6 |
