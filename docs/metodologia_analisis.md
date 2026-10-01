# Metodología de análisis — ATLAS Brasil 2026

Esto complementa `README.md` y `docs/metodologia_geoespacial.md`: ahí está el
QUÉ (estructura, fuentes); acá está el CÓMO se corre el análisis y con qué
cadencia, de principio a fin.

El proceso tiene 7 fases. Las primeras 3 son de una sola vez (o por hito
electoral); las fases 4-6 son el ciclo que se repite cada vez que entra
información nueva (nueva encuesta, nuevo dato del TSE); la 7 es la
operativa de entrega.

---

## Fase 0 — Línea de base histórica (una sola vez)

Antes de proyectar 2026 hay que entender cómo se comportó el sistema en
2018 y 2022: volatilidad de bloques, migración partidaria, correlación
entre primera vuelta presidencial y resultado de Câmara/Senado por UF.

- Correr `src/etl/extract/tse_extractor.py` para 2018 y 2022.
- Clasificar cada resultado histórico contra `familias_partidarias.yaml`
  **tal como estaba vigente en esa legislatura** (no retro-aplicar la
  clasificación 2026 al pasado — ahí está el error más común de este tipo
  de modelo).
- Salida: `data/processed/electoral/serie_historica_familias.parquet`,
  con un indicador de volatilidad por família y por UF (cuánto se mueve
  entre elecciones).

**Por qué importa:** la volatilidad histórica de cada família es el input
que define cuánto ruido meterle a cada una en la simulación Montecarlo de
la Fase 5. El Centrão históricamente es menos volátil que la base de
gobierno; eso se mide acá, no se asume.

---

## Fase 1 — Ingesta y validación de datos vivos

Se corre cada vez que hay una fuente nueva (encuesta publicada, actualización
del TSE, sesión de votación nominal en el Congreso).

1. **Extracción** (`src/etl/extract/`) → `data/raw/`.
2. **Validación estructural** (antes de tocar el dato): chequeo de
   completitud (¿vino el dataset completo o truncado?), de esquema
   (¿cambiaron columnas respecto a la corrida anterior?), de rango
   (¿los porcentajes suman ~100? ¿hay UFs faltantes?).
3. Si falla la validación, el pipeline corta ahí y no contamina
   `processed/` — es preferible un dato faltante a un dato corrupto
   propagado al modelo.

---

## Fase 2 — Normalización y transform

- Resolver família política por partido+año contra
  `config/familias_partidarias.yaml` (nunca hardcodeado en el dataset).
- Unificar códigos de municipio (TSE usa su propio código, IBGE otro —
  hay tabla de correspondencia pública, `src/etl/transform/` debe tener
  ese mapeo versionado, no hecho a mano cada vez).
- Para encuestas: cada ficha técnica entra con metadata completa (casa
  encuestadora, fecha de campo, tamaño de muestra, margen de error,
  metodología de contacto). Esto es insumo directo de la Fase 4.

---

## Fase 3 — Análisis descriptivo / exploratorio

Esto es lo que se hace en `notebooks/`, nunca en producción:

- Series de tiempo de intención de voto por candidato/família.
- Cruce intención de voto × perfil socioeconómico (religión, ingreso,
  región — como mostraron las notas de Datafolha/Perfil que vimos: el
  corte evangélico/católico y de ingresos es significativo en 2026).
- Mapa de correlación histórica entre voto presidencial y voto legislativo
  por UF (para calibrar cuánto "arrastra" la boleta presidencial a
  Diputados/Senado — efecto de arrastre, clave en sistema brasileño).

Esta fase no produce un número para publicar; produce **hipótesis e inputs
de calibración** para el modelo.

---

## Fase 4 — Agregación de encuestas (poll aggregation)

Acá es donde más disciplina metodológica hace falta, porque no hay una sola
encuesta "verdadera" — hay ~8 casas encuestadoras con house effects propios.

1. **Ponderación por calidad**: peso = f(tamaño de muestra, recencia,
   track record histórico de esa casa en elecciones pasadas — sí, hay que
   medir el error histórico de Datafolha/Quaest/Nexus/AtlasIntel contra el
   resultado real de 2018 y 2022, no asumir que todas pesan igual).
2. **Corrección de house effect**: cada encuestadora tiene un sesgo
   sistemático conocido (ej. una tiende a sobreestimar al oficialismo en
   X puntos de forma consistente) — se corrige antes de promediar, no
   después.
3. **Decaimiento temporal**: una encuesta de hace 3 semanas pesa menos que
   una de ayer — función de decaimiento exponencial sobre `fecha_campo`.
4. Salida: `data/processed/electoral/intencion_voto_familia.parquet`,
   que es el input directo de `src/models/montecarlo/proyeccion_bancas.py`.

**Esto todavía no está implementado en el scaffold** — es el próximo módulo
a construir (`src/models/agregacion_encuestas.py`), porque sin esto el
Montecarlo de bancas está corriendo sobre un promedio simple, que es
metodológicamente débil.

---

## Fase 5 — Simulación Montecarlo

Ya scaffoldeado en `src/models/montecarlo/proyeccion_bancas.py`. El ciclo es:

1. Tomar la intención de voto agregada y corregida (Fase 4).
2. Perturbar cada família con ruido calibrado por su **volatilidad
   histórica real** (Fase 0), no un número arbitrario de 2pp para todas.
3. Correr 10.000 escenarios, aplicando D'Hondt por UF para Câmara y el
   sistema mayoritario para Senado.
4. Para el balotaje presidencial: simular directamente sobre la pregunta
   de segunda vuelta de cada encuestadora (no inferir del resultado de
   primera vuelta — ya vimos que Lula/Flávio en 1ra vuelta y en balotaje
   simulado dan números distintos).
5. Resumen probabilístico: no se publica "Lula gana", se publica la
   distribución (media, p10, p90) y la probabilidad de cada escenario
   (ej. "balotaje: 94% de probabilidad bajo las condiciones actuales").

---

## Fase 6 — Validación / backtesting

Antes de confiar en cualquier output del modelo para el ciclo 2026:

- Correr el pipeline completo sobre los datos de **cierre de campaña
  2022** y comparar la proyección del modelo contra el resultado real.
- Si el error del modelo en 2022 (backtesting) es mayor al error promedio
  de las encuestas individuales, el modelo no está agregando valor —
  hay que revisar la ponderación de la Fase 4 antes de publicar nada de 2026.

Esto es no-negociable si el output va a un cliente (recordá que
`atlas-analytics` trabaja con candidatos reales — un número mal calibrado
tiene costo reputacional).

---

## Fase 7 — Operativa de entrega

| Evento | Acción |
|---|---|
| Nueva encuesta publicada | Fases 1→5 se re-corren automáticamente, se actualiza `reports/briefs/` con fecha |
| Actualización TSE (resultados definitivos de 1ra vuelta, 4/10) | Se corre Fase 0 extendida (ya no es proyección, es resultado real) — el modelo pasa de "proyección" a "diagnóstico de lo que pasó" |
| Previo al balotaje (25/10, si corresponde) | Brief específico con el modelo de 2da vuelta recalibrado con encuestas de balotaje real, no inferido |
| Cierre del ciclo | Backtesting final (Fase 6) documentado en `docs/`, para que sirva de insumo a `atlas-congreso-2027` y futuros proyectos de ATLAS Analytics |

**Cadencia sugerida hasta el 4/10**: corrida diaria de Fases 1-5 (las
encuestadoras publican con esa frecuencia en la semana pre-electoral),
con un brief consolidado cada 2-3 días en `reports/briefs/`.

---

## Lo que falta construir para que esta metodología esté operativa

1. ~~`src/models/agregacion_encuestas.py` (Fase 4)~~ — hecho para presidencial
   nacional (2026-10-01), ver `docs/agregacion_encuestas.md`. Falta extenderlo a
   gobernadores (encuestas por UF) y a intención por família para Câmara.
2. ~~Tabla de correspondencia código TSE ↔ código IBGE (Fase 2).~~ Hecho.
3. ~~Backtesting (Fase 6) contra 2022~~ — hecho contra 2018 y 2022, dentro del agregador.
4. ~~Historial de house effects por encuestadora~~ — track record 2018/2022
   automático contra el resultado TSE. Pendiente: cruzar con PesqEle por n.º de registro.
