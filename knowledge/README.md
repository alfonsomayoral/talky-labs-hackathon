# Contexto para agentes de ingeniería

Usa esta base como mapa de contexto para diseñar e implementar automatización contable del reto. Empieza por la tarea concreta; no cargues toda la documentación si basta una fuente específica.

## Navegación por necesidad

| Si vas a… | Lee primero |
|---|---|
| Entender términos y límites del dominio | [CONTEXT.md](../CONTEXT.md) |
| Diseñar o implementar una solución | [Playbook de ingeniería](engineering/implementation-playbook.md) |
| Entender principios del curso y modelos mentales | [Ocho módulos](reference/curso-ocho-modulos.md) |
| Resolver las seis tareas de Kalmora | [Flujos de cierre Kalmora](workflows/cierre-kalmora.md) y la sección correspondiente de las políticas |
| Generar ficheros de entrega | [Formato de entrega](../participant/FORMATO_ENTREGA.md) |
| Conocer sociedades, fases o estructura de datos | [README del participante](../participant/README.md) |
| Validar compatibilidad de puntuación | `participant/score.py` y `participant/phase_dev/golden/` |

## Autoridad de fuentes

1. Petición del usuario para el objetivo del cambio.
2. Esquemas/tareas y contratos de `participant/score.py` para interfaces y evaluación.
3. `participant/POLITICAS_CONTABLES.md` para reglas contables del escenario.
4. Datos fuente de la fase para hechos y evidencia concreta.
5. `knowledge/reference/curso-ocho-modulos.md` para conceptos generales, solo como apoyo.

Si se contradicen, no mezcles reglas ni promedies los resultados: conserva la fuente de mayor autoridad, explica la discrepancia y evita inferir datos no presentes.

## Conocimiento curado

- [Referencia del curso](reference/curso-ocho-modulos.md) resume los ocho módulos leídos en el sitio.
- [Flujos de Kalmora](workflows/cierre-kalmora.md) condensa tareas, dependencias y controles del reto.
- `CONTEXT.md` contiene el vocabulario del dominio; mantenlo corto y sin decisiones de implementación.

No dupliques aquí el manual, el esquema JSONL, los maestros ERP ni los datos de fase. Enlázalos como fuente de verdad.
