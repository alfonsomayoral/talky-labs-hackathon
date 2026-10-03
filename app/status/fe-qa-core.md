# fe/qa-core — 5.A–5.B QA y pulido: núcleo

## Hecho

Tanda 1: cifras que cuadran entre pantallas y arreglos encontrados con septiembre.

- **Atención en EUR, como Resumen y Asistente.** La cabecera decía «Quedan 60 · 6,9 M€ + 49,7 M MXN» mientras Resumen y Asistente decían «60 · 9,4 M€». Ahora suma en EUR con `attentionSummary` y `eurConverter` de `features/overview/model` (3100 al tipo de cierre). Las cabeceras por prioridad siguen separadas por moneda, igual que la tabla del Asistente. `src/features/attention/AttentionPage.tsx`.
- **Hueco del balance de Entregables en EUR.** La tarjeta de nota toma `trialBalance.eur` (69,8 M€ en julio, igual que Resumen y Balance) en vez de las unidades de `score.py` (303,7 M, con MXN sin convertir). En el desglose de la tarea Balance, las dos cifras de `score.py` se muestran sin símbolo de moneda y con la etiqueta «(score.py, MXN sin convertir)». `src/features/deliverables/ScoreCard.tsx`.
- **Asiento en el panel estrecho.** `JournalEntryView` cortaba Debe y Haber al estrechar el panel. Las columnas de texto ceden con elipsis y Cuenta pesa el 60 %; a ancho normal se ve igual. `src/features/item/kit/JournalEntryView.tsx` y `.module.css`.
- **Asistente sin ids de julio.** Con septiembre, «Explica API004128» respondía «no lo encuentro… por ejemplo, «Explica API004128»». Ahora sugiere un id que existe en la ejecución activa (la primera factura de AP, o el id completo de cualquier partida), también en la respuesta de «no sé responder». El placeholder ya no cita un id: «¿Qué tengo que revisar?», «¿Cómo está BIN-1100?». Test nuevo en `src/features/assistant/engine/local.test.ts`. `src/features/assistant/engine/local.ts`, `src/features/assistant/Chat.tsx`.

## Verificación

- `npm run typecheck` (salida 0), `npm run lint` (oxlint, salida 0), `npm run test` (55 ficheros, 355 tests en verde), `npm run build` correcto. Tras `git merge origin/hackathon/frontend`.
- Navegador, puerto 5176, **septiembre** (`phase_test` + `phase_test-research-qa`, 719 partidas, 60 en atención):
  - Resumen, Atención y Asistente dan las mismas cifras: 645 de 719 resueltas, 89,7 %, 60 en atención por 9,4 M€, P0 2 · P1 14 · P2 44. Aceptar una con `a` en Atención baja a 59 en Atención y en la barra lateral; deshecho después.
  - Asistente, preguntas 1 a 4 sin golden: resumen con «Sin golden no hay nota»; revisar con 60 y 9,4 M€; balance con «Sin golden no se conoce el balance correcto» y el movimiento por tarea (78,3 M€, igual que el indicador del Resumen); proceso AP con 297 partidas y el mapa.
  - Sin golden: Comparar muestra su estado vacío («Sin referencia con la que comparar»), el panel no tiene pestaña Golden y `?pestana=golden` cae en Razonamiento, Entregables da «Lista» y «sin golden/ no hay nota», Coste explica que el manifiesto no trae coste, tiempos ni confianza. Ejecuciones y su detalle (`/ejecuciones/:id`) cargan.
  - Teclado: `j`/`k` y `Enter` en Actividad abren el panel; con el panel abierto `j` lo mueve a la siguiente partida; `Esc` lo cierra; ⌘K encuentra y abre `API005263`; ⌘J abre el Asistente lateral con el historial.
  - Cero errores en consola en todas estas pantallas.
- Navegador, **julio** con golden: Entregables da 100,00 y «Hueco del balance: registrado 69,8 M€ → 0 €».

## Sin verificar

- Estado de carga y de error de cada pantalla: solo los he visto de paso (las páginas cargan en menos de un segundo con datos en IndexedDB).
- Modo Profundo del Asistente: en este worktree no hay clave y responde el motor local, como se espera.

## Peticiones a la coordinadora

- `src/lib/format.ts` (qa-shell-demo): `formatMoney` pinta el cero negativo. En el Resumen de septiembre, Intragrupo neto dice «Cash pooling -0 €» (−0,3 céntimos tras convertir MXN). Propuesta: `signDisplay: opts.signed ? 'exceptZero' : 'negative'` en `formatMoney` y `formatCompactMoney`.
- Shell (qa-shell-demo): con el panel del navegador muy estrecho (~400 px) la barra lateral no se pliega y el título de las páginas se parte letra a letra. Fuera del alcance de escritorio; lo anoto por si entra en el pulido.

## Commits

- `8ad3343 fix: keep debit and credit visible when the item panel is narrow`
- `07814c3 fix: show the pending attention total in EUR like the overview`
- `1ad2720 fix: suggest item ids that exist in the active run in the assistant`
- `4ee8d57 fix: show the deliverables balance gap in EUR and label the scorer units`
