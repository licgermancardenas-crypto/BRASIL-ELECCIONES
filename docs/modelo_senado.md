# Modelo de bancas — Senado Federal post-2026

Código: `src/models/montecarlo/proyeccion_senado.py`. Parámetros:
`config/modelo.yaml` (sección `senado`). Cada corrida queda en
`data/processed/legislativo/senado/<fecha_utc>/` con `meta.json`.

## Leer antes de usar

**El Senado se decide por candidato y este modelo no ve candidatos, solo
famílias.** Sin encuestas (decisión del 2026-10-01) estima cuántas bancas
tiene chance cada família por UF; **no nombra ganadores**. Su error medido en
2018 es grande (ver Validación) y los rangos p10–p90 **no lo incluyen**:
reflejan solo el ruido de famílias, no el error del modelo.

## Composición

- **27 bancas que no se eligen** (electos en 2022, mandato hasta 2031):
  partido **actual** según la API del Senado (decisión del 2026-10-01),
  clasificado con la tabla 2026. Romário (RJ) figura sin partido →
  `sin_alineamiento` (registrado en `familias_partidarias.yaml`).
  Resultado: centrão 13, direita bolsonarista 9, gobierno Lula 4, sin alineamiento 1.
- **54 bancas en juego** (2 por UF), simuladas.

## Regla por UF

1. Fuerza de cada família = % de voto a Câmara 2022 en la UF (famílias 2026),
   más el mismo ruido que el modelo de Câmara (shock nacional + shock por UF).
2. Una família sin candidatos en la UF no puede ganar. Con 1 candidato
   compite con su fuerza; con 2 o más, su segundo candidato compite con
   β × fuerza (cada elector vota dos veces).
3. Ganan las 2 entradas más fuertes.

Candidatos 2026: `consulta_cand` del TSE, sin duplicados por UF y número.
El TSE no publica todavía la situación de candidatura: incluye impugnadas.

## Calibración y validación con 2018

2018 también renovó 2 bancas por UF. Se reprodujo con la fuerza de Câmara
**del mismo 2018** y la clasificación 2018. Criterio: menor error en el total
nacional por família (es lo que el modelo reporta).

| Regla | Error total por família (de 53) | Aciertos UF×família |
|---|---:|---:|
| β = 0,0 – 0,2 (elegido: 0,1) | **13** | 30 |
| β = 0,5 | 27 | 35 |
| Ingenua (2 famílias más fuertes) | 19 | 28 |

β ≤ 0,2 equivale a "una banca por família por UF". Con β = 0,5 se acertaban
más UF, pero le daba 43 bancas al centrão contra 29 reales: por eso el
criterio es el error en el total.

**Sesgo observado:** en 2018 el modelo le dio 14 bancas al campo PT contra 7
reales (ola anti-PT de ese año). Y eso con el voto a Câmara del mismo año;
para 2026 se usa el de 2022, así que el error esperado es mayor.

53 bancas y no 54: en MT la segunda electa (Selma Arruda, PSL) fue casada y
sus votos anulados.

## Resultado (corrida 2026-10-01, 10.000 simulaciones, semilla 42, β = 0,1)

| Família | Siguen | En juego (media) | Total p10 | Mediana | p90 | Prob. mayoría propia (≥41) |
|---|---:|---:|---:|---:|---:|---:|
| centrao | 13 | 27,1 | 38 | 40 | 41 | 40% |
| gobierno_lula | 4 | 16,7 | 15 | 21 | 26 | 0% |
| direita_bolsonarista | 9 | 6,2 | 10 | 14 | 22 | 0% |
| centro_liberal | 0 | 4,0 | 1 | 3 | 8 | 0% |
| sin_alineamiento | 1 | 0 | 1 | 1 | 1 | 0% |

## Limitaciones

- Sin voto personal de candidatos: el factor decisivo del Senado no está.
- Error de validación 2018 de 13/53 bancas por família, no incluido en los rangos.
- Ruido de Câmara aplicado a la fuerza de família en el Senado.
- Candidaturas impugnadas incluidas (el TSE no publica la situación 2026).
