# `src/data` — capa de datos (adaptador v1)

Este módulo es un **adaptador provisional**. La capa de datos es del **equipo de backend**: cuando su API exista, este código se adapta a ella. Mientras tanto, la app funciona sola, leyendo en el navegador las carpetas de cada fase y los paquetes de ejecución.

## Frontera

Las vistas y el motor solo importan esto:

- `@/data/stores`: `useDatasetStore`, `useRunStore`, `sessionRestored` y `filesFromDataTransfer`.
- `@/domain/types`: `DatasetApi`, `DatasetMeta`, `DatasetCore`, `RunBundle` y el resto de tipos.

Nada fuera de `src/data/` importa de `sources/`, `parsers/`, `worker/`, `bundles/` ni `providers/`.

## Proveedores

`stores.ts` no sabe de dónde vienen los datos: se los pide a un proveedor (`providers/`).

| Proveedor | Origen | Qué hace |
| --- | --- | --- |
| `local` | Carpeta o `.zip` elegidos por el usuario | Parsea los ficheros en un Web Worker e importa paquetes de ejecución desde ficheros |
| `dev` | Middleware de Vite: `/__data/<id>`, `/__runs/<id>` (`dev/kalmoraData.ts`) | Igual que `local`, pero leyendo los ficheros por HTTP |
| `api` | Backend `/v1` (`CONTRACT.md` §2), activo si existe `VITE_API_URL` | Sube y abre fases, lanza el cierre y lo sigue por consulta, y lista y carga las ejecuciones |

Abrir un dataset devuelve un `DatasetApi`: el `core` ya cargado y métodos asíncronos para lo pesado (diario, entradas de mercancía, detalle bruto del banco, ficheros). Los métodos `rawBankDetails`, `recordedTrialBalance` y el opcional `einvoice` son **evidencia derivada**. Un proveedor puede devolverla ya calculada por el backend en lugar de parsearla en el navegador.

## Conectar un proveedor nuevo

Por ejemplo, la API definitiva del backend:

1. Implementa `RemoteProvider` (`providers/types.ts`) en `providers/<nombre>.ts`. `openDataset` puede construir el `DatasetApi` con llamadas HTTP; no necesita el worker.
2. Regístralo en `remoteProviders` (`providers/index.ts`).

Ni `stores.ts` ni las vistas cambian.

## Qué es temporal

- **El parseo en el navegador:** `worker/`, `sources/` y `parsers/` (JSONL, Norma 43, CAMT.053, CSV mexicano, Facturae y CFDI). Solo hace falta mientras el backend no sirva los datos ya procesados.
- **La ruta de ficheros de un dataset en la API:** `GET /api/datasets/{id}/files/…` (en `providers/api.ts`) es una suposición. Todavía no está en `CONTRACT.md`.
- **La copia de las carpetas en IndexedDB:** `persist.ts` guarda los ficheros elegidos para poder reabrirlos al recargar. Con la API bastaría con guardar el id.

## Desarrollo

- `.env.local` define `KALMORA_DATASETS` y `KALMORA_RUNS`; el middleware los sirve.
- `/dev/data` sirve para depurar: cargar datasets por cada vía, ver el inventario y los avisos, comprobar el balance registrado contra golden, crear e importar ejecuciones y ver `useDerivedRun()`.
- Las pruebas con datos reales (`*.test.ts` con `@vitest-environment node`) se saltan si no existe `../../participant/phase_dev`.
