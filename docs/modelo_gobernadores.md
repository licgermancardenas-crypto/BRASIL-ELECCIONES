# Modelo de gobernadores 2026

Código: `src/models/montecarlo/proyeccion_gobernadores.py`. Parámetros:
`config/modelo.yaml` (sección `gobernadores`). Cada corrida queda en
`data/processed/electoral/gobernadores_sim/<fecha_utc>/` con `meta.json`,
`probabilidad_uf.csv`, `calibracion.csv` y `validacion.csv`.

## Qué es

27 elecciones **independientes**, cada una con su propio balotaje si nadie
supera el 50% de los votos válidos. Lo único común entre UFs es el shock
nacional de cada família (mismo ruido que Câmara y Senado). Sin encuestas
(decisión del 2026-10-01).

Reporta, por UF, la probabilidad de que gane cada família —separando al
candidato incumbente del resto— y la probabilidad de balotaje; y a nivel
nacional, cuántas gobernaciones toma cada família. **No distingue entre sí a
candidatos no incumbentes de una misma família.**

## Modelo por UF

- Fuerza de família = % de voto a Câmara 2022 en la UF (famílias 2026) + shocks de família.
- Puntaje de cada candidato = fuerza de su família × (1 si es el primero de
  su família, β si no) × exp(σ·z + δ·incumbente).
- 1ª vuelta: % de votos = puntaje / suma. Más de 50% gana.
- 2ª vuelta entre los dos primeros: % × exp(σ_bal·z); gana el mayor.

**Incumbente** (decisión del 2026-10-01): electo gobernador **o vice** en el
ciclo anterior, por CPF y misma UF, con **un solo parámetro δ**. Incluye
elecciones suplementarias que figuran en `consulta_cand` (2018: AM 2017 y TO
2018). En 2026 hay incumbente en 20 de 27 UF (9 gobernadores y 11 vices; varios
vices probablemente asumieron cuando el gobernador renunció en abril, cosa que
los datos del TSE no muestran).

**RR:** la suplementaria de gobernador de junio de 2026 figura en el TSE sin
electo (votos del primero, Arthur Henrique, anulados sub judice). No se marca
incumbente en RR.

## Calibración: 2018 + 2022 (54 elecciones)

Máxima verosimilitud de (família ganadora, si el ganador era incumbente, si
hubo balotaje), con la fuerza de Câmara del **mismo** año. Números aleatorios
comunes en toda la grilla. Falla si un óptimo queda en el borde superior.

| Parámetro | Valor | Lectura |
|---|---:|---|
| β | 0,5 | el 2º candidato de una família compite con la mitad de su fuerza |
| σ candidato | 1,25 | un candidato puede multiplicar o dividir por ~3,5 la fuerza de su família |
| **δ incumbente** | **1,5** | **multiplica la fuerza por ~4,5: el factor más grande** |
| σ balotaje | 0,1 | el que lidera la 1ª vuelta casi siempre gana la 2ª |

Datos crudos: en 2018 el incumbente compitió en 20 UF y ganó en 10 (año de
renovación); en 2022 compitió en 20 y ganó en 17.

## Validación

Acierto de la família ganadora (la más probable según el modelo):

| | Modelo | "Gana el incumbente; si no, la família más fuerte" | "Gana la família más fuerte" |
|---|---:|---:|---:|
| Dentro de muestra (2018+2022) | 35/54 | 33 | 26 |
| Calibrado en 2018 → probado en 2022 | 20/27 | 19 | 14 |
| Calibrado en 2022 → probado en 2018 | 15/27 | 14 | 12 |

- Fuera de muestra rinde igual que dentro: no está sobreajustado.
- Le gana a la regla del incumbente por una elección por año: casi toda la
  señal es la incumbencia.
- δ (1,25 en cada año por separado) y σ (1,0–1,25) son estables. **β y σ_bal
  no**: con 2018 solo, el ruido de balotaje queda en 1,5 (balotajes casi al
  azar ese año); con 2022 solo, en 0,2. La corrida usa los valores conjuntos.

## Resultado (corrida 2026-10-01, 10.000 simulaciones, semilla 42)

| Família | Media | p10 | Mediana | p90 |
|---|---:|---:|---:|---:|
| centrao | 19,0 | 16 | 19 | 22 |
| gobierno_lula | 5,4 | 3 | 5 | 8 |
| direita_bolsonarista | 1,7 | 0 | 1 | 3 |
| centro_liberal | 0,9 | 0 | 1 | 2 |

El centrão domina porque tiene 15 de los 20 incumbentes. Detalle por UF en
`probabilidad_uf.csv`.

## Limitaciones

- Sin encuestas: el voto personal entra como ruido calibrado.
- No se sabe por datos TSE quién ejerce hoy cada gobernación (vices que asumieron).
- β y el ruido de balotaje no son estables entre 2018 y 2022.
- consulta_cand 2026 no publica situación de candidatura: incluye impugnadas.
