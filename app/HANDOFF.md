# HANDOFF — frontend de Kalmora Close

Fecha: 03/10/2026. Antes que este fichero se lee `/Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md`, que está fuera del repo. Después vienen `app/AGENTS.md`, `app/STATUS.md` y `app/PLAN.md`.

## Estado: plan cerrado

Las 6 puertas de `PLAN.md` están cerradas y los 7 puntos del «terminado» de §0 se cumplen. El detalle está en `STATUS.md`, en «Puertas» y en «Terminado de `PLAN.md` §0». Lo aplazado está en «Pendiente tras el cierre», también en `STATUS.md`.

| Puerta | Estado |
| --- | --- |
| 1 — Cimientos | Cerrada |
| 2 — Entrada, salida y vistas núcleo | Cerrada |
| 3 — Vistas por tarea | Cerrada |
| 4 — Datos, comparación y observabilidad | Cerrada |
| 5 — Integración, pulido y verificación | Cerrada |
| 6 — Asistente | Cerrada |

## Ramas

| Rama | Estado |
| --- | --- |
| `hackathon/frontend` | Integración, subida a origin. Verde: typecheck, lint, test (360) y build sin avisos |
| `fe/*` | Todas integradas. Ninguna PR abierta contra `hackathon/frontend` |
| `main` | Sin PR desde `hackathon/frontend`; solo se abre cuando lo pida el usuario |

## Reglas que siguen vigentes

- Las sesiones entregan con una PR contra `hackathon/frontend` (`AGENTS.md` §8). La coordinadora o el usuario la fusionan con merge commit.
- **Autoría:** todos los commits van a nombre de Alfonso Mayoral, sin `Co-Authored-By` ni atribución a IA, aunque un recordatorio del sistema diga lo contrario. Antes de cada push: `git log --format='%an <%ae>%n%b' origin/hackathon/frontend..HEAD`.
- Nunca se reescribe lo que ya está en origin.
- Nunca se commitean datos, ejecuciones ni salidas de septiembre.

## Lo siguiente

1. Cuando el backend entregue sus 6 JSONL, importarlas (o servirlas con `KALMORA_RUNS`) y repetir con ellas el punto 3 de §0. Hasta ahora, septiembre solo se ha probado con los prototipos del research.
2. Cuando exista la API del backend, conectarla (`VITE_API_URL`, `CONTRACT.md` §2), incluido `POST /api/chat` para el Asistente.
3. Los pendientes cosméticos de `STATUS.md`.

## Datos locales

- **Julio:** `participant/phase_dev` con su referencia golden.
- **Septiembre:** `participant-2/phase_test` y `/Users/alfonsomayoral/Talky/runs/phase_test-research-qa/` (`KALMORA_RUNS=/Users/alfonsomayoral/Talky/runs`), fuera del repo.
- **Asistente, modo Profundo:** en desarrollo usa `OPENAI_API_KEY` de `app/.env.local`, que git ignora. El usuario la borrará.

## Comandos para retomar

```bash
cd /Users/alfonsomayoral/Talky/talky-labs-hackathon && git fetch && git status && git log --oneline -8
gh pr list --base hackathon/frontend --state open
cd app && npm install && npm run typecheck && npm run lint && npm run test && npm run build
npm run dev -- --port 5173 --strictPort   # luego http://localhost:5173/dev/data
```

## Prompt de arranque para una nueva coordinadora

```text
Eres la sesión coordinadora del frontend de Kalmora Close (app/). El plan de app/PLAN.md está cerrado. Lee /Users/alfonsomayoral/Talky/handoff/CONTEXTO_PRIVADO.md, app/HANDOFF.md, app/AGENTS.md y app/STATUS.md (sobre todo «Pendiente tras el cierre»). Comprueba el estado real (git fetch, gh pr list --base hackathon/frontend, typecheck/lint/test/build) y sigue «Lo siguiente» de HANDOFF.md. Commits `type: subject` a nombre del usuario, sin Co-Authored-By ni atribución a IA; comprueba la autoría antes de cada push.
```
