# Playbook de diseño e implementación

Procedimiento para que un agente convierta una tarea del reto en una solución de software mantenible y compatible con su evaluador.

## 1. Descubrimiento antes del diseño

Antes de proponer arquitectura:

- Inspecciona el árbol real del repositorio, instrucciones locales y herramientas disponibles.
- Identifica si la petición es análisis, generación de entrega, construcción de un motor de reglas, parser, interfaz o mejora del evaluador.
- Sigue una operación de punta a punta: tarea → documentos/maestros → regla → decisión → asiento → JSONL → evaluación.
- Lee el formato exacto y el código de scoring antes de definir contratos.
- Usa `phase_dev` para ejemplos y calibración; separa esas convenciones del contenido variable por fase.

El estado observado al inspeccionar este repo es principalmente datos del reto, documentación y `participant/score.py`; no presupongas que hay una aplicación, dependencias, CLI o arquitectura de producción. Reconfirma este estado cada vez que empieces una tarea.

## 2. Modelo de dominio y límites

Define explícitamente:

- **Entrada:** fase, fecha de cierre, tarea, documentos fuente, maestros e histórico necesario.
- **Salida:** un objeto de decisión por clave de tarea, con motivos, clasificación, aplicaciones y/o asiento según el contrato.
- **Invariantes:** importes enteros en céntimos; asiento balanceado; moneda local; claves y fechas válidas; socio y objeto de coste coherentes.
- **Evidencia:** cada decisión debe poder trazarse a documentos, campos ERP, política o cálculo reproducible.
- **Desconocido:** ausencia de evidencia no se convierte en aprobación, rechazo o ajuste inventado; representa incertidumbre según el contrato.

Mantén separados los conceptos de ingestión, extracción, normalización, decisión de política, construcción de asiento, serialización y evaluación cuando el alcance requiera un sistema de software. No impongas esos módulos si la tarea es un script pequeño; preserva los límites que evitan mezclar parsing con contabilidad.

## 3. Diseña primero el flujo vertical

Para una tarea nueva, define un caso de extremo a extremo con:

1. Una clave de entrada y su documento fuente.
2. Las entidades y relaciones requeridas (sociedad, proveedor/cliente, pedido, recepción, partida abierta, extracto).
3. El orden de reglas y la primera condición que detiene o cambia la decisión.
4. El asiento esperado, incluidos impuestos, retenciones, diferencias y objetos auxiliares.
5. La estructura de salida y cómo el evaluador compara el resultado.
6. Un caso normal y los casos límite derivados de las políticas.

Prioriza pureza y determinismo en cálculos de importes y reglas. Aísla OCR/parsing, acceso a ficheros y heurísticas para poder revisar su efecto sin alterar reglas contables.

## 4. Implementación y datos

- Conserva los datos fuente; no sobrescribas ERP, inbox, tareas ni `golden`.
- Usa enteros en céntimos; no uses coma flotante para importes contables. Redondea según política por línea.
- Conserva moneda, sociedad y fecha durante conversiones; no combines monedas sin tipo aplicable.
- Valida referencias a cuentas, socios, centros de coste, WBS, documentos y líneas bancarias contra los maestros/entradas de la fase.
- Emite JSONL con una línea independiente por objeto, UTF-8 y claves según `FORMATO_ENTREGA.md`.
- Mantén reglas del escenario en configuración/datos cuando varíen por sociedad, contrato o fase; no hardcodees conclusiones aprendidas de un único fixture.
- Registra procedencia y motivos con códigos válidos; no escondas fallos de parsing como decisiones contables.

## 5. Evaluación del diseño

Evalúa la solución frente a:

- Corrección contable y precedencia de reglas.
- Cobertura de las claves de tarea y casos de borde.
- Idempotencia: volver a generar la entrega no duplica efectos.
- Trazabilidad de cada resultado a evidencia.
- Compatibilidad exacta con el esquema y scorer.
- Manejo explícito de errores, datos ausentes, duplicados y límites de fase.

`phase_dev/golden/` sirve para entender ejemplos y score en fase dev; evita ajustar heurísticas a un solo conjunto de soluciones. `phase_test/` es evaluación ciega. No añadas ni ejecutes tests salvo petición expresa del usuario; si pide verificación, usa las herramientas disponibles y comunica qué cubren.

## 6. Entrega de trabajo de ingeniería

Resume:

- Qué flujo se diseñó o implementó y qué archivos toca.
- Qué contratos, políticas y datos se consultaron.
- Decisiones de diseño relevantes y supuestos explícitos.
- Qué verificaciones se hicieron, sus resultados y lo que queda fuera.

No describas como implementado lo que solo es un plan, ni como verificado lo que no se ejecutó.
