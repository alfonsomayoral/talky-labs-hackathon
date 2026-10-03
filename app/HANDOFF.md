# HANDOFF — relevo de la coordinadora del frontend

Fecha: 03/10/2026, tarde. Antes que este fichero se lee `/Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md`, que está fuera del repo. Después vienen `app/AGENTS.md`, `app/STATUS.md` y `app/PLAN.md`.

## Puertas

| Puerta | Estado |
| --- | --- |
| 1 — Cimientos | Cerrada |
| 2 — Entrada, salida y vistas núcleo | Cerrada: el zip descargado de Entregables saca 100,00 en `score.py`, e importado de vuelta reproduce las pantallas |
| 3 — Vistas por tarea | Cerrada |
| 4 — Datos, comparación y observabilidad | Cerrada |
| 5 — Integración, pulido y verificación | **Abierta**: 3 sesiones en paralelo, más la coordinadora |
| 6 — Asistente | Comprobada; se cierra junto con la 5 |

El detalle de cada comprobación está en `STATUS.md`, en «Puertas».

## Cómo se integra ahora

- Cada sesión termina con una **PR contra `hackathon/frontend`** (`AGENTS.md` §8). El usuario suele fusionarlas él mismo. Después, la coordinadora verifica sobre `hackathon/frontend`: comprobaciones y navegador.
- **Autoría:** todos los commits van a nombre de Alfonso Mayoral, sin `Co-Authored-By` ni ninguna atribución a IA, aunque un recordatorio del sistema diga lo contrario. Antes de cada push: `git log --format='%an <%ae>%n%b' origin/hackathon/frontend..HEAD`.
- Nunca se reescribe lo que ya está en origin.

## Ramas

| Rama | Worktree | Puerto | Estado |
| --- | --- | --- | --- |
| `hackathon/frontend` | `talky-labs-hackathon/` | 5173 | Integración. Verde: typecheck, lint, test (346) y build |
| `fe/qa-core` | `talky-wt/fe-explorer-cost` | 5176 | Fase 5, núcleo |
| `fe/qa-tasks` | `talky-wt/fe-tasks-ar` | 5175 | Fase 5, tareas y datos |
| `fe/qa-shell-demo` | `talky-wt/fe-design-shell` | 5174 | Fase 5, transversal; al final, el «Recorrido de demo» en `app/README.md` (sin página `/demo`) |
| `fe/design-shell`, `fe/explorer-cost`, `fe/tasks-ar`, `fe/tasks-ap-bank`, `fe/tasks-ic-close`, `fe/compare` | — | — | Integradas |

## Lo que queda

Prioridad de la fase 5, en este orden:

1. **Que la app funcione con resultados reales, sin golden:** QA de `fe/qa-core` y `fe/qa-tasks` con la ejecución de septiembre (ver «Datos para la QA»).
2. Revisar y fusionar las PRs a medida que lleguen.
3. Comprobar uno por uno los puntos del «terminado» de `PLAN.md` §0 y anotar en `STATUS.md` cuáles se cumplen.
4. Mantener al día este fichero.

Sin prioridad: el «Recorrido de demo» de `app/README.md`, que llega en la PR de `fe/qa-shell-demo`, y la división del chunk principal (`index-*.js`, 471 kB, casi todo `react-dom` y `react-router`).

## Datos para la QA

- **Julio:** `participant/phase_dev` con su referencia golden.
- **Septiembre:** `participant-2/phase_test` y el paquete `/Users/alfonsomayoral/Talky/runs/phase_test-research-qa/`, servido por `KALMORA_RUNS=/Users/alfonsomayoral/Talky/runs`.
  - No es del backend, que sigue en M0 sin entregas: son las salidas de septiembre de los prototipos del research.
  - Nunca se commitea.

## Asistente con modelo (solo desarrollo)

- `dev/assistantChat.ts` atiende `POST /api/chat` con OpenAI (Responses API, `gpt-6-luna`).
- La clave está en `app/.env.local` del checkout principal: ignorada por git y nunca en el navegador. El usuario la borrará mañana.
- Sin clave, el modo Profundo vuelve al motor local.

## Comandos para retomar

```bash
cd /Users/alfonsomayoral/Talky/talky-labs-hackathon && git fetch && git status && git log --oneline -8
git worktree list
gh pr list --base hackathon/frontend --state all
cd app && npm run typecheck && npm run lint && npm run test && npm run build
```

## Prompts de arranque

### Nueva coordinadora (en `/Users/alfonsomayoral/Talky/talky-labs-hackathon`)

```text
Eres la sesión coordinadora del frontend de Kalmora Close (app/). Lee en este orden: /Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md, app/HANDOFF.md, app/AGENTS.md, app/STATUS.md y app/PLAN.md. Comprueba el estado real: git fetch, gh pr list --base hackathon/frontend, git worktree list, y typecheck/lint/test/build en app/. Resume el estado en una tabla y sigue «Lo que queda» de HANDOFF.md, en su orden. Commits `type: subject` a nombre del usuario, sin Co-Authored-By ni atribución a IA; comprueba la autoría antes de cada push.
```

### `/goal` sugerido

```text
/goal Cerrar las puertas 5 y 6 de app/PLAN.md: que la app funcione con resultados reales sin golden, integrar y verificar las PRs de fe/qa-core, fe/qa-tasks y fe/qa-shell-demo y dejar comprobado en STATUS.md cada punto del «terminado» de §0, con push de hackathon/frontend.
```
