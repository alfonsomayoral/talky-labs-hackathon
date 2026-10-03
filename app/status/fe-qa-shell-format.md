# fe/qa-shell-format — 5.B pulido: signo de los importes a cero

Rama aparte de `fe/qa-shell-demo` para no cambiar la PR #157, que ya estaba revisada.

## Hecho

- `formatMoney` (`src/lib/format.ts`) usa `signDisplay: 'negative'` en vez de `'auto'` cuando no se pide `signed`. Ya no pinta «-0 €» ni con un cero negativo ni con un negativo que redondea a cero, como `-40` céntimos con 0 decimales: la vista compacta lo hacía por debajo de 1.000 €. Era el caso de Cash pooling en septiembre, que encontró qa-core.
- Nada más cambia de signo:
  - los negativos conservan el «-»;
  - los positivos siguen sin «+»;
  - con `signed` (la prop `signed` de `Amount`) sigue `'exceptZero'`, que ya dejaba el cero sin signo.
- `formatCompactMoney` por encima de 1.000 € no puede redondear a cero, así que no cambia.

## Verificación

- Tests nuevos en `src/lib/format.test.ts`:
  - cero negativo, negativo que redondea a cero (con 0 decimales y en compacto), con y sin `signed`, y sin símbolo;
  - los negativos conservan el «-» y los positivos no llevan «+».
  - Antes del cambio fallaban («-0,00 €»).
- `npm run typecheck` y `npm run lint` (oxlint) con salida 0. `npm run test`: 55 ficheros y 356 tests en verde. `npm run build` correcto.
- Navegador, puerto 5174, julio con la referencia golden. El módulo cargado desde Vite da:
  - `formatMoney(-0)` → «0,00 €» y `formatMoney(-40, 'EUR', { compact: true })` → «0 €»;
  - `-150311` en MXN → «-1.503,11 MXN» y `150311` → «1.503,11 €»;
  - con `signed`: «+1.503,11 €».
  - En Intragrupo no aparece ningún «-0» y la consola está limpia.

## Sin verificar

- No he visto el caso de Cash pooling en septiembre: esa ejecución no está en este worktree. El test reproduce los dos casos posibles: cero negativo y negativo redondeado.

## Peticiones a la coordinadora

- Ninguna.

## Commits

- `4b32ba5 fix: never print a minus sign on zero amounts`
