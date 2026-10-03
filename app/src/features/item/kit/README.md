# Kit de partida (`@/features/item/kit`)

Componentes de dominio que comparten el panel de partida (`ItemPanel`), Actividad y las vistas por tarea (fase 3). Todo se importa desde `@/features/item/kit`; no importes ficheros sueltos.

Las reglas de `src/components/README.md` siguen aplicando: tokens, `Amount` para importes, `Mono` para ids y artículos de la política.

## Razonamiento por proceso

Cada vista de tarea abre con su mapa de decisión, antes de la lista.

```tsx
const flow = useProcessFlow('ap')            // null hasta que la ejecución está lista
const filter = findFlowFilter(flow, nodeId)  // restaura la selección desde la URL
<ProcessMap flow={flow} selectedId={nodeId} onSelect={(f) => setNodeId(f?.id ?? null)} />
// filtra la lista con filter?.items (Set de ItemId)
```

- `processFlow(task, derived, core, run)`: versión pura de `useProcessFlow`, para tests o para otra ejecución.
- `ProcessFlow`: columnas por etapa de la política, nodos con recuento e importe en EUR (`total.amount`), enlaces y desglose por motivo. Cada nodo y cada entrada del desglose llevan un `FlowFilter` `{ id, label, items }`.
- `flowIssues(flow)`: problemas de conservación (lo que entra y sale de cada nodo y su desglose suman su recuento); vacío si el mapa es coherente.

## Razonamiento de una partida

| Componente | Props | Qué muestra |
| --- | --- | --- |
| `ReasoningView` | `itemId`, `onEvidence?` | Titular, hechos, pasos y la decisión con su artículo. Si la ejecución no trae `trace/events.jsonl`, lo dice y reconstruye los pasos desde la entrega |
| `PolicyCascade` | `checks` de `apCascade(row, events)` | Las 14 comprobaciones de la §2.2 en orden: ✓, ✗ y la que corta |
| `TraceTimeline` | `steps` de `reasoningSteps(events, cascade)` o `events` | Los eventos en orden, con chips de evidencia (`onEvidence`) |
| `BankMatchFacts` | `item` | Forma de la casación bancaria (1:1, N:1, 1:N), fechas e importes |

Funciones puras en `reasoning.ts`: `reasoningSummary` (titular y hechos por tarea), `reasoningSteps`, `apCascade`, `bankMatchDetail`, `matchShape` y `loanInterest` (act/360 de intragrupo).

## Asientos, evidencia, maestros y golden

| Componente | Props | Qué muestra |
| --- | --- | --- |
| `JournalEntryView` | `entry` o `lines`, `company?`, `currency?`, `title?`, `highlight?` | Debe y haber con nombre de cuenta, socio y objeto de coste; totales y ✓ de cuadre. Con varias sociedades, cuadre por sociedad |
| `EvidenceList` | `entries`, `focusKey?`, `defaultOpen?` | Evidencia agrupada y desplegable. Las entradas se construyen con `evidenceKey(ref)` para que los chips de la traza la enfoquen |
| `DocumentViewer` | `path` (dentro del dataset), `height?` | PDF en `iframe` con blob, XML indentado (`prettyXml`), correo y JSON |
| `MasterCompare` | `rows: CompareRow[]`, `title?`, `note?` | Documento frente a la ficha, con la fila que difiere marcada. `ApMasterCompare({ row })` la rellena para AP (IBAN, dominio, NIF…) |
| `RawBankRecord` | `bankLine` | Registros N43 22 y 23, nodo CAMT o fila CSV de la línea |
| `GoldenDiff` | `score: ItemScore`, `currency?` | Diferencias campo a campo y línea a línea con la referencia |
| `JsonView` | `value` | JSON plegable |

Ayudas: `journalTotals`, `findErpRecord`, `findStatementLine`, `parseBookLine`, `uniqueRefs`, `itemEurCents` (importe de una partida en céntimos de EUR, 3100 al tipo de cierre).

## Contexto y etiquetas

- `useItemContext(itemId)` → `{ status, error, ctx }`. `ctx` trae la partida, las filas entregadas, sus asientos, eventos, atención, `score` y `accountScore` (bancos) contra golden, y el dataset.
- `TASK_META[task]`: `label`, `title`, `route` e `icon` de cada tarea. `itemTaskHref(itemId)` lleva a la vista de su tarea con `?item=`.
- `EVENT_KIND_META`, `BILLING_TYPE_LABELS`, `evidenceLabel`, `erpFileLabel`.

## Pruebas

`processFlow.test.ts` y `reasoning.test.ts` usan el dataset mínimo de `testing/fixture.ts`, que cubre las 6 tareas. Úsalo también en los tests de las vistas por tarea.
