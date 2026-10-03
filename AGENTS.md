# Instrucciones para agentes de ingeniería

## Propósito del repositorio

Este repositorio contiene el reto de cierre contable sintético de Grupo Kalmora: políticas, datos ERP por fase, documentos de entrada, tareas, una referencia (`golden`) para desarrollo y un evaluador. No asumas que ya existe una aplicación de producto: inspecciona el árbol actual antes de elegir lenguaje, arquitectura, librerías o puntos de integración.

## Contexto que debes leer

Lee solo lo necesario para la tarea, en este orden:

1. [Mapa de conocimiento](knowledge/README.md).
2. [Vocabulario del dominio](CONTEXT.md).
3. La fuente autoritativa vinculada desde el mapa: políticas, formato, tareas y maestros/fase.
4. El código que exista y sus contratos; para puntuación, revisa `participant/score.py`.
5. [Flujo de trabajo de ingeniería](knowledge/engineering/implementation-playbook.md) cuando vayas a diseñar o modificar software.

## Precedencia de fuentes

- La petición actual del usuario define el resultado de producto que hay que lograr.
- Las instrucciones del repositorio y los contratos del evaluador definen las restricciones de ingeniería.
- `participant/POLITICAS_CONTABLES.md` rige las decisiones contables del caso Kalmora.
- Los ficheros `tasks/`, maestros y documentos de la fase determinan los hechos disponibles.
- `participant/FORMATO_ENTREGA.md` y `participant/score.py` determinan la interfaz de salida y la evaluación.
- `knowledge/reference/curso-ocho-modulos.md` aporta fundamentos y modelos mentales generales. Nunca prevalece sobre una política explícita del reto.

No conviertas una regla didáctica general, una inferencia o un ejemplo del curso en un hecho de los datos. Cuando falta evidencia, conserva el estado como desconocido y documenta la decisión.

## Modo de trabajo

Para cada solicitud de diseño o implementación:

1. **Descubre:** identifica fase, tarea, entradas, salidas, contratos, restricciones, código existente y casos frontera relevantes.
2. **Modela:** expresa entidades, estados, invariantes y decisiones contables usando [CONTEXT.md](CONTEXT.md). Separa hechos observados, reglas explícitas e inferencias.
3. **Diseña:** presenta la solución más pequeña que cubra el flujo completo; define límites de módulos, datos y errores antes de codificar cuando el cambio los afecte.
4. **Implementa:** sigue convenciones del repo, conserva los contratos JSONL, importes en céntimos enteros y trazabilidad hasta la fuente.
5. **Revisa:** inspecciona cambios y coherencia con tarea, políticas y evaluación. No añadas ni ejecutes tests salvo que el usuario pida probar o verificar la implementación.
6. **Entrega:** resume archivos/cambios, decisiones importantes, verificaciones ejecutadas y limitaciones concretas.

Trabaja de extremo a extremo dentro del alcance autorizado. Resuelve decisiones rutinarias con la evidencia disponible; pregunta solo por ambigüedades que impidan elegir una conducta correcta o cuando una acción externa/destructiva requiera autorización.

## Datos y fases

- Usa `participant/phase_dev/` para desarrollar; su `golden/` sirve para entender y puntuar el caso de julio de 2026.
- Usa `participant/phase_test/` como evaluación de septiembre de 2026; no presupongas que contiene `golden/` ni uses datos ocultos.
- No modifiques entradas fuente para facilitar una solución. Genera las entregas o resultados en el destino pedido por el usuario.
- El diario ya contiene operaciones históricas. Evita volver a registrarlas; distingue tarea pendiente, registro existente y ajuste necesario.
