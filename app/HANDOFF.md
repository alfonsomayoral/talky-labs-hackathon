# HANDOFF — relevo de la coordinadora del frontend

Fecha: 03/10/2026. Antes que este fichero se lee `/Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md`, que está fuera del repo. Después vienen `app/AGENTS.md`, `app/STATUS.md` y `app/PLAN.md`.

## Puertas

| Puerta | Estado |
| --- | --- |
| 1 — Cimientos | Cerrada: nota 100, paridad con `score.py`, balance registrado igual al golden |
| 2 — Entrada, salida y vistas núcleo | **Abierta**. Hechos 2.A, 2.B y 2.D; 2.C en `wip` (`3cb7318`) |
| 3 a 6 | Pendientes |

## Ramas

| Rama | Último sha | Estado |
| --- | --- | --- |
| `hackathon/frontend` | ver `git log -1` (incluye `3cb7318` y este fichero) | Integración. Pasa typecheck. Antes del wip pasaban también lint, test (212) y build |
| `fe/design-shell` | `70ee9ef` | Terminada e integrada (merge `2e27dea`) |
| `fe/explorer-cost` | ver `origin/fe/explorer-cost` tras su RELEVO | 4.C commiteado (`3db7f65`), 4.A a medias. Ver `app/status/fe-explorer-cost.md` en esa rama |
| `fe/tasks-ap-bank` | ver `origin/fe/tasks-ap-bank` tras su RELEVO | 3.A + 3.D en curso, sin kit. Ver `app/status/fe-tasks-ap-bank.md` en esa rama |
| `fe/tasks-ar` | `1c6cadd` | Sin empezar: espera el kit |
| `hackathon/fe-2c-activity` | `40f54e4` | Abandonada; worktree `/Users/alfonsomayoral/Talky/wt-fe-2c-activity` por retirar |

## Trabajo a medias

**2.C, Actividad y panel de partida** (`src/features/activity/`, `src/features/item/`), commit `3cb7318`:

- Escrito: el kit en `item/kit/` (`ProcessMap`, `processFlow`, `ReasoningView`, `PolicyCascade`, `TraceTimeline`, `JournalEntryView`, `EvidenceList`, `DocumentViewer`, `MasterCompare`, `RawBankRecord`, `GoldenDiff`, `index.ts`), las pestañas en `item/tabs/` y `ItemPanel`. `activity/` tiene `activityModel.ts` y `EventFeed`. Typecheck en verde.
- Falta, en este orden:
  1. pasar lint y test;
  2. `item/kit/README.md`;
  3. terminar `ActivityPage` (tabla, filtros en la URL, `ProcessMap` por tarea, línea de tiempo);
  4. revisar en el navegador `ap:API004128` (asiento de 7 líneas cuadrado, cascada en verde), `ap:API005229` (fraude por IBAN y dominio), una casación N:1 de bancos, un cobro `FACTORED_MISDIRECTED`, una periodificación y la pareja intragrupo `INTEREST_DAY_COUNT`.
- Siguiente paso: `cd app && npm run lint && npm run test`. Arregla lo que falle y escribe el README del kit.

## Orden de lo que queda

1. Cerrar 2.C y la **puerta 2**:
   - recorrido sobre julio;
   - zip de entrega con nota 100;
   - aplicar las peticiones pendientes:
     - atajos a/p/n con `usePageShortcuts` en `AttentionPage`;
     - «Te necesitan» del Resumen con `pendingAttention` de `@/shell/attentionBadge`;
     - exponer `downloadDelivery(run)` en 2.A;
     - mover `TASK_META`, `PIPELINE`, `KIND_LABEL` y `TASK_LABEL` a `src/domain/catalog/`.
   - Después, push y aviso a `fe/tasks-ar` y `fe/tasks-ap-bank` de que el kit está listo.
2. Integrar `fe/explorer-cost` y `fe/tasks-ap-bank` cuando terminen, con `git merge --no-ff`, comprobaciones y navegador.
3. Fase 3:
   - 3.B + 3.C en `fe/tasks-ar`;
   - abrir 3.E Intragrupo + 3.F Cierre y balance.
4. Fase 4: abrir 4.B Comparar con golden.
5. Fase 5: QA en el navegador, pulido y demo (coordinadora).
6. Fase 6: Asistente (`src/features/assistant/`).

## Comprobaciones pendientes

- Puerta 2: `npm run typecheck && npm run lint && npm run test && npm run build`, más el recorrido en el navegador.
- Comprobaciones de las puertas 3 a 6: `PLAN.md` §6.

## Comandos para retomar

```bash
cd /Users/alfonsomayoral/Talky/talky-labs-hackathon && git fetch && git status && git log --oneline -8
git worktree list
cd app && npm install && npm run typecheck && npm run test
npm run dev -- --port 5173 --strictPort   # luego http://localhost:5173/dev/data → cargar julio + golden
```

## Prompts de arranque

### Nueva coordinadora (en `/Users/alfonsomayoral/Talky/talky-labs-hackathon`)

```text
Eres la sesión coordinadora del frontend de Kalmora Close (app/). Lee en este orden: /Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md, app/HANDOFF.md, app/AGENTS.md, app/STATUS.md y app/PLAN.md. Comprueba el estado real: git fetch, git log de hackathon/frontend y de cada rama fe/*, git worktree list, y typecheck/lint/test/build en app/. Resume el estado en una tabla y sigue «Orden de lo que queda» de HANDOFF.md, empezando por cerrar 2.C y la puerta 2. Commits `type: subject` sin atribución, uno por paquete; integra ramas con git merge --no-ff y haz push de hackathon/frontend al cerrar cada puerta. Las sesiones te escriben en app/status/<rama>.md.
```

### Sesión `fe/explorer-cost` (4.A + 4.C)

```text
Eres la sesión del paquete «4.A Explorador de datos + 4.C Coste y calibración» de Kalmora Close. Worktree /Users/alfonsomayoral/Talky/talky-wt/fe-explorer-cost, rama fe/explorer-cost, puerto 5176. Lee app/AGENTS.md, app/STATUS.md, app/PLAN.md (Fase 4) y tu estado app/status/fe-explorer-cost.md, sobre todo «A medias». Haz git fetch y comprueba que tu rama coincide con origin/fe/explorer-cost. 4.C ya está commiteado; termina 4.A (/datos/*: maestros, diario con queryJournal, bandeja con visor, extractos con rawBankDetails, enlaces cruzados) desde el siguiente paso anotado. Comprobaciones según AGENTS.md §6; commits type: subject sin push; actualiza tu fichero de estado y avisa a la coordinadora.
```

### Sesión `fe/tasks-ap-bank` (3.A + 3.D)

```text
Eres la sesión del paquete «3.A AP + 3.D Bancos» de Kalmora Close. Worktree /Users/alfonsomayoral/Talky/talky-wt/fe-tasks-ap-bank, rama fe/tasks-ap-bank, puerto 5177. Lee app/AGENTS.md, app/STATUS.md, app/PLAN.md (§3.6, §4 y Fase 3), PROBLEM.md §5.1 y §5.4, y tu estado app/status/fe-tasks-ap-bank.md, sobre todo «A medias». Haz git fetch y comprueba que tu rama coincide con origin/fe/tasks-ap-bank. Sigue desde el siguiente paso anotado. Cuando la coordinadora avise de que el kit (src/features/item/kit) está en hackathon/frontend, haz git merge hackathon/frontend y conecta ProcessMap, ReasoningView, JournalEntryView y EvidenceList. Casos reales: /Users/alfonsomayoral/Talky/handoff/research/01_ap_decision.md, 02_ap_coding.md y 05_bank_rec.md. Comprobaciones según AGENTS.md §6; commits sin push; estado en app/status/fe-tasks-ap-bank.md.
```

### Sesión `fe/tasks-ar` (3.B + 3.C, siguiente oleada, espera el kit)

```text
Eres la sesión del paquete «3.B Facturación + 3.C Cobros» de Kalmora Close. Worktree /Users/alfonsomayoral/Talky/talky-wt/fe-tasks-ar, rama fe/tasks-ar, puerto 5175 (dependencias y .env.local listos). Lee app/AGENTS.md, app/STATUS.md, app/PLAN.md (§3.6, §4 filas /tareas/facturacion y /tareas/cobros, Fase 3), PROBLEM.md §5.2 y §5.3, y /Users/alfonsomayoral/Talky/handoff/research/03_ar_billing.md y 04_ar_cash.md. Empieza cuando la coordinadora confirme que el kit está en hackathon/frontend: git merge hackathon/frontend. Cada vista abre con su ProcessMap; tus carpetas son src/features/tasks/ar-billing/ y src/features/tasks/ar-cash/. Comprobaciones según AGENTS.md §6; commits sin push; estado en app/status/fe-tasks-ar.md.
```

### Paquete por abrir: 3.E + 3.F (crear antes el worktree `talky-wt/fe-tasks-ic-close`, rama `fe/tasks-ic-close`, puerto 5178)

```text
Eres la sesión del paquete «3.E Intragrupo + 3.F Cierre y balance» de Kalmora Close. Worktree /Users/alfonsomayoral/Talky/talky-wt/fe-tasks-ic-close, rama fe/tasks-ic-close, puerto 5178. Lee app/AGENTS.md, app/STATUS.md, app/PLAN.md (§4 filas intragrupo, cierre y balance; Fase 3), PROBLEM.md §5.5–5.7 y /Users/alfonsomayoral/Talky/handoff/research/06_close_tb.md y 07_ic_and_diff.md. Tus carpetas: src/features/tasks/ic/, src/features/tasks/close/ y src/features/ledger/. Usa el kit de src/features/item/kit (ProcessMap primero en cada vista) y trialBalance.eur para totales en EUR. Comprobaciones según AGENTS.md §6; commits sin push; estado en app/status/fe-tasks-ic-close.md.
```

### Paquete por abrir: 4.B Comparar con golden (worktree `talky-wt/fe-compare`, rama `fe/compare`, puerto 5179)

```text
Eres la sesión del paquete «4.B Comparar con golden» de Kalmora Close. Worktree /Users/alfonsomayoral/Talky/talky-wt/fe-compare, rama fe/compare, puerto 5179. Lee app/AGENTS.md, app/STATUS.md y app/PLAN.md (§4 fila /comparar, Fase 4). Construye /comparar con useDerivedRun().data.score (subnotas por tarea, perItem con FieldDiff) y GoldenDiff del kit, más un interruptor global «comparar». Puerta: sobre una entrega alterada se ven exactamente las partidas alteradas. Tu carpeta es src/features/compare/. Comprobaciones según AGENTS.md §6; commits sin push; estado en app/status/fe-compare.md.
```

### `/goal` sugerido para la nueva coordinadora

```text
/goal Cerrar la puerta 2 (2.C terminado e integrado, recorrido sobre julio, zip con nota 100) y llevar el plan de app/PLAN.md hasta la fase 6, coordinando las sesiones fe/* según app/STATUS.md e integrando cada rama verificada en hackathon/frontend con push al cerrar cada puerta.
```
