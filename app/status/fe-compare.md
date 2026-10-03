# fe/compare — 4.B Comparar con golden

## Hecho
- `/comparar` (`src/features/compare/ComparePage.tsx`, `ComparePage.module.css`):
  - Cabecera con `Page fill` y `PageHeader`. Interruptor «Solo diferencias / Todo» (`SegmentedControl`) guardado en `?vista=` (`todo`; por defecto, solo diferencias).
  - Sin golden (`score` null): `EmptyState` que explica que la comparación necesita `golden/`, que solo trae julio, y enlaza a Ejecuciones.
  - Lista (`DataTable`) de las partidas que difieren, ordenadas por la nota que pierden: resultado (Difiere, No entregada, No está en golden, Exacta), tarea, partida (`Mono`), qué difiere (etiquetas de `diffLabel`), nota de la partida, número de diferencias y puntos que pierde.
  - Al abrir una fila, si la partida existe en la ejecución, se abre el peek con `useOpenItem()`. Con j/k y el peek abierto, el peek sigue al cursor. Las partidas que no están en la ejecución (no entregadas, o la entrada de cuenta de bancos) cierran el peek y se ven solo en el panel de la derecha.
  - Panel de la derecha: `GoldenDiff` de la partida del cursor, con «Abrir partida» si existe.
  - Por debajo de 1100 px, el panel de diferencias pasa debajo de la lista.
- `src/features/compare/TaskScores.tsx` (+ `.module.css`): nota total y subnotas en el orden de `PIPELINE`, más el balance. Cada tarjeta muestra peso, nota, lo que aporta (de su máximo) y cuántas partidas difieren. Al pulsar una tarea, la lista se filtra (`?tarea=`); se quita con la píldora o pulsándola otra vez. El balance se puntúa entero y no filtra.
- `src/features/compare/model.ts`: lógica pura.
  - `diffRows(perItem, { all, task })`: filas con su tipo de diferencia, ordenadas por pérdida. Pérdida = peso de la tarea × (1 − nota de la partida) ÷ partidas de la tarea en golden × 100. En bancos, cuentas y líneas se cuentan por separado. Es exacta en las tareas que promedian por partida y aproximada en las que puntúan con F1. Las partidas que sobran no tienen nota: van al final.
  - `taskSummaries(score)`: subnotas por tarea.
  - `parseCompareParams` / `applyCompareParams`: estado en la URL.
- `src/features/compare/model.test.ts`: 9 tests. Incluye la puerta: con la fixture del kit alterada en 3 filas, pasada por `deriveRun` con golden, la lista contiene exactamente esas 3 partidas, y golden contra sí misma no lista nada. También corre sobre julio real (se salta si no está `phase_dev`): con 3 filas alteradas de golden lista exactamente esas 3.

## Verificación
Desde `app/`, con `KALMORA_DEV_PHASE=/Users/alfonsomayoral/Talky/participant/phase_dev`:
- `npm run typecheck`: exit 0.
- `npm run lint` (oxlint src dev): exit 0, sin avisos.
- `npm run test`: `Test Files 38 passed (38)`, `Tests 244 passed (244)`. El test de julio corre, no se salta.
- `npm run build`: exit 0 (`✓ built in 375ms`).

En el navegador (dev server del worktree, puerto 5174), con julio y su golden cargados desde `/dev/data`:
- Golden contra sí misma: 100,00 y «Sin diferencias con la referencia».
- Ejecución alterada creada en el navegador desde golden (no está en el repo; ya borrada): una decisión AP, una línea de asiento AP, el cliente de un cobro, una casación quitada en BIN-1000 y el importe de un anticipado. Comparar lista exactamente esas 5 partidas, con nota 99,77.
- Filtro por tarea (Bancos), «Todo» (las exactas también salen), peek al pulsar una partida AP, `k` hasta la línea bancaria (el peek se cierra y se ve el `GoldenDiff`) y el diseño a 1024 px.
- Consola sin errores. Al terminar quedó activa la ejecución golden de julio.

## Sin verificar
- El estado vacío sin golden no se ha visto en el navegador: habría que cargar `phase_test` y dejarlo en la sesión. Es una rama simple del render.
- En el navegador solo se probaron las alteraciones de AP, cobros, bancos y cierre. Facturación e intragrupo están cubiertos por los tests del motor (`itemDiff.test.ts`) y por la puerta sobre la fixture (facturación).

## Peticiones a la coordinadora
- **ItemPanel:** permitir abrir el peek directamente en la pestaña Golden, por ejemplo con `?pestana=golden` junto a `?item=`. Así, desde Comparar, «Abrir partida» llevaría a las diferencias y no al razonamiento. Es de activity (2.C).
- **Kit `GoldenDiff` (activity):** en las diferencias de importe (`amount` en cierre), los valores se muestran como céntimos en bruto (`-596573`), no con `<Amount>`.
- **Motor:** la entrada de cuenta de bancos (`bank_rec:<cuenta>`) sale `exact` aunque su nota sea < 1, porque sus `diffs` solo recogen los ajustes. En «Todo» aparece como «Exacta» con nota del 99 %. Si se quiere otra semántica, se cambia en `engine/score/itemDiff.ts`.

## Commits
- `3d162fe feat: add golden comparison model`
- `21bf092 feat: add golden comparison page`
- (este fichero) `docs: add compare status`
