# fe/admin-live — nuevo cierre en blanco, administración y eventos en vivo

Base: `origin/main` (d32f6fc), que lleva el frontend de `/v1` aún no integrado en `hackathon/frontend`.

## Hecho
- **Eventos en vivo con `/v1`** (`src/data/providers/api.ts`). Antes, mientras corría el cierre, la página se quedaba en «Conectando», sin eventos y con todas las tareas pendientes, porque `subscribeRun` solo emitía `done` o `error`. Ahora:
  - mientras la ejecución está `running`, emite un lote (aunque vaya vacío) para que pase a «En curso»;
  - lee las líneas nuevas de `trace/events.jsonl` con `Range: bytes=<offset>-` (admite 206 y 200);
  - una línea sin terminar espera, salvo cuando la ejecución ya ha acabado.
- **Nuevo cierre en blanco** (`src/features/runs/NewRunPage.tsx`):
  - cada visita empieza en el paso 1 con el cargador abierto;
  - el dataset ya abierto se ofrece con «Usar», sin recargarlo;
  - el paso 2 y la tarjeta «Ejecución activa» solo reflejan lo elegido o creado en ese flujo;
  - «Olvidar» pide confirmación (`ConfirmRemove.tsx`).
- **Store** (`src/data/stores.ts`, ampliación compatible):
  - `useRunStore.runsOf(datasetId)`;
  - `remove(id, datasetId?)` borra ejecuciones de un dataset que no está abierto.
- **Administración** (`/administracion`, `src/features/runs/AdminPage.tsx`, entrada «Administración» en Entrega, atajo `g m`, icono `Settings`):
  - todos los datasets y todas las ejecuciones guardados en el navegador, con la columna «Datos» (nombre y mes);
  - borrado con diálogo de confirmación;
  - borrar un dataset borra también sus ejecuciones.
- **Dataset en la cabecera** de cada ejecución, guardada y en vivo (`RunLivePage.tsx`).
- `CONTRACT.md` §2 describe la lectura incremental de `trace/events.jsonl`.

## Verificación
- `npm run typecheck`, `lint` y `build`: verdes y sin avisos. `npm run test`: 57 ficheros y 369 tests en verde.
- Tests nuevos:
  - `api.test.ts`: cierre en curso, líneas nuevas y última línea sin `\n`;
  - `stores.runs.test.ts`: listar y borrar ejecuciones de un dataset no abierto.
- Navegador, con julio y la referencia golden más septiembre servidos en desarrollo:
  - Nuevo cierre arranca en blanco con julio activo; «Usar» y luego «Abrir referencia» muestran la tarjeta;
  - en Administración, Cancelar no borra; se borró la referencia de julio con septiembre activo, y después septiembre siendo el activo;
  - la cabecera de la ejecución muestra el dataset;
  - cero errores en consola.
- Punta a punta con el backend de `origin/main` (`kalmora serve` en el puerto 8010) y un comando de cierre de prueba que añade un evento cada 1,5 s. Se vio «En curso · 3 eventos» con AP en 3/297 y, al terminar, los 8 eventos. Las peticiones fueron 206.

## Sin verificar
- El comando de cierre real todavía no escribe `trace/events.jsonl`, así que con él la página muestra «En curso» sin eventos.
- La cabecera de una ejecución en vivo usa el dataset abierto. Si alguien abre la URL de una ejecución en curso con otro dataset activo, la etiqueta no corresponde.

## Peticiones a la coordinadora
- Se han tocado `src/app/routes.tsx` y `src/app/nav.ts` para añadir `/administracion`, por indicación directa del usuario.

## Commits
- ver `git log origin/main..fe/admin-live`
