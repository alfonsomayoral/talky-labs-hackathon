# Instrucciones para sesiones que trabajan en `app/`

Varias sesiones de Claude construyen el frontend en paralelo, cada una en su worktree y su rama. Una **sesión coordinadora** integra. Este fichero manda dentro de `app/`. El `AGENTS.md` de la raíz sigue aplicando para el dominio contable.

## 1. Qué leer, en este orden

1. Este fichero.
2. [`STATUS.md`](STATUS.md): tu paquete, tu rama, tu puerto y de qué dependes.
3. [`PLAN.md`](PLAN.md): §0, §2 (diseño), §3 (arquitectura), §4 (pantallas) y la fase de tu paquete.
4. [`CONTRACT.md`](CONTRACT.md): qué produce el backend y cómo llega a la app.
5. [`../PROBLEM.md`](../PROBLEM.md): solo las secciones de tu tarea (§5.x y §6).
6. [`../CONTEXT.md`](../CONTEXT.md): vocabulario del dominio.
7. [`src/components/README.md`](src/components/README.md) antes de crear interfaz. Si vas a usar el kit de partida, también `src/features/item/kit/README.md`.

## 2. Stack y comandos

React 19, Vite 8, TypeScript 6 estricto (`erasableSyntaxOnly`: sin `enum`, `namespace` ni propiedades en parámetros), react-router v8, zustand 5, recharts 3, CSS Modules, iconos lucide-react. El alias `@/` apunta a `app/src`.

Todo se ejecuta desde `app/` de tu worktree:

| Comando | Para qué |
| --- | --- |
| `npm run dev -- --port <tu puerto> --strictPort` | Servidor de desarrollo. El puerto está en `STATUS.md` |
| `npm run typecheck` | `tsc -b` |
| `npm run lint` | oxlint |
| `npm run test` | vitest |
| `npm run build` | Build de producción |

Tu `app/.env.local` define `KALMORA_DATASETS` con rutas **absolutas** a `participant/phase_dev` y `participant-2/phase_test`. Con el servidor arrancado, `/dev/data` carga julio y crea la ejecución de referencia (golden).

## 3. Contratos congelados

Se pueden **ampliar** sin romper. Para **cambiarlos**, se pide a la coordinadora.

- `src/domain/types/*`.
- La API de `src/data/stores.ts`: `useDatasetStore`, `useRunStore`, `sessionRestored`, `filesFromDataTransfer`.
- `useDerivedRun()` y sus selectores en `@/engine`: `useActiveRun`, `useItem`, `useItemEvents`, `useAttention`.
- Las props de los componentes de `src/components/`.
- `ItemPanel` con props `{ itemId, onClose }`, y `useOpenItem()` / `useActiveItemId()` de `@/shell/useOpenItem`.

**Solo los toca la coordinadora:** `src/app/routes.tsx`, `src/app/nav.ts`, `src/domain/types/`, `package.json`, `package-lock.json`, `vite.config.ts`, `vitest.config.ts`, `tsconfig*.json`, `.env.example`, `AGENTS.md`, `STATUS.md`, `PLAN.md` y `CONTRACT.md`. Si necesitas una dependencia, una ruta o un tipo nuevo, lo pides en tu fichero de estado (§7).

## 4. Carpetas de cada paquete

Una sesión solo escribe en las carpetas de su paquete.

| Paquete | Carpetas |
| --- | --- |
| design-shell (1.A, 4.D) | `src/design/`, `src/components/`, `src/shell/`, `src/lib/format.ts`, `src/lib/keyboard.ts`, `public/` |
| data (1.B) | `src/data/`, `dev/`. Es un adaptador v1: la capa de datos es del equipo de backend |
| engine (1.C) | `src/engine/`, `src/domain/catalog/` |
| runs-io (2.A) | `src/features/runs/`, `src/features/deliverables/` |
| overview (2.B) | `src/features/overview/` |
| activity (2.C) | `src/features/activity/`, `src/features/item/` (incluido `item/kit/`) |
| attention (2.D) | `src/features/attention/` |
| tasks-* (3.A–3.F) | `src/features/tasks/<tarea>/`, y `src/features/ledger/` para 3.F |
| data-explorer (4.A) | `src/features/data-explorer/` |
| compare (4.B) | `src/features/compare/` |
| observability (4.C) | `src/features/observability/` |
| assistant (6.A, 6.B) | `src/features/assistant/` |

Data y engine son de la coordinadora desde que cerró la fase 1.

## 5. Convenciones

- **Estilos:** CSS Modules (`*.module.css`), un fichero por componente o página. Solo se usan los tokens de `src/design/tokens.css`: ningún color, sombra ni radio fuera de los tokens.
- **Marca:** naranja de Talky solo en la acción primaria, la selección y el foco. Los colores de estado solo indican estado. Sin banners, ilustraciones ni degradados. Cada página va dentro de la hoja blanca que pone el shell: no añadas fondos de página.
- **Textos:** interfaz en español; identificadores y nombres de código en inglés; comentarios escasos.
- **Importes:** siempre en céntimos enteros y mostrados con `<Amount>`, nunca formateados a mano. Para totales de grupo hay que convertir a EUR: usa `stats.attention.impactEur` y `trialBalance.eur`, porque 3100 está en MXN.
- **Ids, cuentas, códigos y artículos de la política:** con `<Mono>`. Fechas, porcentajes y duraciones con `@/lib/format`.
- **Datos:** las vistas solo importan de `@/data/stores` y `@/domain/types`, nunca de `data/sources`, `data/parsers` ni `data/worker`.

## 6. Pruebas y comprobaciones

En `app/` **el plan sí exige** pruebas con vitest y las comprobaciones de puerta. Esto prevalece aquí sobre la regla de tests del `AGENTS.md` raíz.

- Cada sesión prueba su lógica pura con vitest.
- Antes de su último commit, cada sesión ejecuta `typecheck`, `lint`, `test` y `build` en verde. Si un fallo viene claramente de otra carpeta, lo anota en su estado en lugar de arreglarlo.
- Las pantallas se revisan en el navegador con julio y la referencia golden cargados: cero errores en consola.

## 7. Repo público

- Nunca se commitean datos (`participant/`, `data/`), paquetes de ejecución (`runs/`) ni salidas o predicciones de septiembre.
- Nunca se copia código, CSS, tokens ni imágenes de Kapia. Es solo inspiración visual.

## 8. Git y estado

- Cada sesión trabaja en su rama `fe/<paquete>`, en su worktree. **Sin push.**
- Commits con asunto `type: subject` (por ejemplo, `feat: add bank reconciliation view`), sin ámbito entre paréntesis y sin atribución. Un commit por cambio lógico.
- Solo la coordinadora integra en `hackathon/frontend`, con `git merge --no-ff`, y hace push al cerrar cada puerta.
- Cada sesión escribe su estado y sus peticiones **solo** en `app/status/<rama>.md`, con `/` sustituida por `-` (por ejemplo, `app/status/fe-activity.md`). Nunca en ficheros compartidos.

## 9. Informe final de cada sesión

Al terminar, `app/status/<rama>.md` queda así y se commitea en tu rama:

```markdown
# <rama> — <paquete>

## Hecho
- Pantallas, componentes y funciones, con sus rutas de fichero.

## Verificación
- Comandos ejecutados y su resultado (typecheck, lint, test, build).
- Qué se revisó en el navegador y con qué datos.

## Sin verificar
- Lo que no se ha podido comprobar y por qué.

## Peticiones a la coordinadora
- Cambios en ficheros que no son tuyos: rutas, tipos, dependencias, contratos.

## Commits
- `<sha> <asunto>`
```
