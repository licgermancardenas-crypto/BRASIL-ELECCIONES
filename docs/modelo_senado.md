# Modelo de bancas — Senado Federal post-2026

Código: `src/models/montecarlo/proyeccion_senado.py`. Parámetros:
`config/modelo.yaml` (sección `senado`). Cada corrida queda en
`data/processed/legislativo/senado/<fecha_utc>/` con `meta.json`,
`calibracion.csv` y `calibracion_efecto_candidato.csv`.

## Leer antes de usar

**El Senado se decide por candidato y este modelo no ve candidatos, solo
famílias.** Sin encuestas (decisión del 2026-10-01) estima cuántas bancas
tiene chance cada família por UF; **no nombra ganadores**. El error que tuvo
en 2018 está incorporado a los rangos como "efecto candidato" (ver abajo),
pero queda un sesgo por família que el ruido no corrige.

## Composición

- **27 bancas que no se eligen** (electos en 2022, mandato hasta 2031):
  partido **actual** según la API del Senado (decisión del 2026-10-01),
  clasificado con la tabla 2026. Romário (RJ) figura sin partido →
  `sin_alineamiento` (registrado en `familias_partidarias.yaml`).
  Resultado: centrão 13, direita bolsonarista 9, gobierno Lula 4, sin alineamiento 1.
- **54 bancas en juego** (2 por UF), simuladas.

## Regla por UF

1. Fuerza de cada família = % de voto a Câmara 2022 en la UF (famílias 2026),
   más los shocks de família del modelo de Câmara (nacional + por UF): cuánto
   puede cambiar la fuerza de una família entre elecciones.
2. Una família sin candidatos en la UF no puede ganar. Con 1 candidato
   compite con su fuerza; con 2 o más, su segundo candidato compite con
   β × fuerza (cada elector vota dos veces).
3. **Efecto candidato:** la fuerza de cada candidatura se multiplica por
   exp(N(0, σ)). Es el error del modelo aun conociendo la fuerza de la família.
4. Ganan las 2 entradas más fuertes.

Candidatos 2026: `consulta_cand` del TSE, sin duplicados por UF y número.
El TSE no publica todavía la situación de candidatura: incluye impugnadas.

## Calibración con 2018

2018 también renovó 2 bancas por UF. Se reprodujo con la fuerza de Câmara
**del mismo 2018** y la clasificación 2018 (decisión del 2026-10-01).

### β (segundo candidato de una família)

Criterio: menor error en el total nacional por família (es lo que el modelo
reporta).

| Regla | Error total por família (de 53) | Aciertos UF×família |
|---|---:|---:|
| β = 0,0 – 0,2 (elegido: 0,1) | **13** | 30 |
| β = 0,5 | 27 | 35 |
| Ingenua (2 famílias más fuertes) | 19 | 28 |

β ≤ 0,2 equivale a "una banca por família por UF". Con β = 0,5 se acertaban
más UF, pero le daba 43 bancas al centrão contra 29 reales.

### σ (efecto candidato), decisión del 2026-10-01: "sumar el error de 2018 al ruido"

Máxima verosimilitud de los ganadores reales 2018 por UF y família (52 UF×bancas;
MT excluido). Óptimo interior: **σ = 2,0** (log-verosimilitud −57,1; con
σ = 3,0 empeora a −58,4).

- **Por qué multiplicativo:** con un shock aditivo igual para todos (primer
  intento), la verosimilitud crecía sin tope y partidos de 0,5% (PCB, PCO,
  PSTU, UP) ganaban 3,6 bancas en promedio. Multiplicativo, un candidato
  puede potenciar o hundir a su família, pero un partido marginal no salta
  a competitivo.
- **Qué significa σ = 2:** un candidato puede multiplicar o dividir por ~7 la
  fuerza de su família (±1 desvío). En 2018 la fuerza de família explicó poco
  de quién ganó el Senado: decidieron los candidatos.
- **Sesgo que queda:** aun con σ óptimo, el total real 2018 del centrão cae
  en el percentil 1,00 de lo simulado (el modelo lo subestima) y el del
  campo PT en el 0,09 (lo sobreestima). No se corrige: sería ajustar a una
  sola elección.

53 bancas y no 54: en MT la segunda electa (Selma Arruda, PSL) fue casada y
sus votos anulados.

## Resultado (corrida 2026-10-01, 10.000 simulaciones, semilla 42, β = 0,1, σ = 2,0)

| Família | Siguen | En juego (media) | Total p10 | Mediana | p90 | Prob. mayoría propia (≥41) |
|---|---:|---:|---:|---:|---:|---:|
| centrao | 13 | 22,4 | 32 | 35 | 39 | 5% |
| gobierno_lula | 4 | 15,0 | 15 | 19 | 23 | 0% |
| direita_bolsonarista | 9 | 8,3 | 13 | 17 | 22 | 0% |
| centro_liberal | 0 | 7,0 | 4 | 7 | 11 | 0% |
| sin_alineamiento | 1 | 1,0 | 1 | 2 | 4 | 0% |
| esquerda_independente | 0 | 0,2 | 0 | 0 | 1 | 0% |

Sin efecto candidato (versión anterior) el centrão tenía mediana 40 y 40% de
probabilidad de mayoría propia: esa confianza no estaba justificada.

## Limitaciones

- Sin datos de candidatos: el voto personal entra solo como ruido calibrado.
- Sesgo por família observado en 2018 (centrão subestimado, campo PT
  sobreestimado con ruido) no corregido.
- Shocks de família de Câmara aplicados a la fuerza en el Senado.
- Candidaturas impugnadas incluidas (el TSE no publica la situación 2026).
