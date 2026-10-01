# Volatilidad de famílias (Fase 0) — Câmara dos Deputados 2018 → 2022

Insumo del ruido por família de la simulación Montecarlo (Fase 5), en
reemplazo de los 2 pp fijos para todas las famílias.

## Método

**Composición fija (decisión del 2026-10-01).** Cada partido de 2018 y 2022 se
lleva a su sigla sucesora en 2026 siguiendo el linaje de `config/partidos.yaml`
(PSL→UNIÃO, PRP→PATRIOTA→PRD, PROS→SOLIDARIEDADE, PSC→PODE, …) y se clasifica
con la tabla de família **2026** (la que usa el Montecarlo). Así, un partido
que cambió de família entre elecciones no cuenta como movimiento de votos.

- Votos: válidos a Deputado Federal (nominales + legenda), por UF.
- Volatilidad de una família = desvío típico, entre las 27 UF, del cambio de
  su % de votos entre 2018 y 2022, en puntos porcentuales (pp).
- Código: `src/etl/load/serie_historica.py`. Salida:
  `data/processed/electoral/volatilidad_familias.parquet` (columna
  `composicion`: `fija_2026` es la del modelo; `del_ano` queda como comparación).

## Resultado (corrida del 2026-10-01)

| Família | Volatilidad (pp) | Cambio medio entre UF (pp) | Comparación: clasificación de cada año |
|---|---:|---:|---:|
| centrao | 11.20 | +1.87 | 10.03 |
| direita_bolsonarista | 8.22 | +7.43 | 6.68 |
| centro_liberal | 6.20 | −4.39 | 6.54 |
| gobierno_lula | 5.03 | −3.71 | 6.49 |
| sin_alineamiento | 1.77 | −1.18 | 1.77 |
| esquerda_independente | 0.12 | −0.01 | 2.56 |

**El Centrão es la família más volátil**, contra el supuesto de la Fase 0 de
`metodologia_analisis.md` ("históricamente menos volátil que la base de
gobierno"). Se mide, no se asume: queda para revisión de esa frase.

## Sensibilidad: destino del PSL 2018

PSL 2018 (11,6 % del voto, la ola Bolsonaro) sigue su linaje a UNIÃO →
`centrao`, pero en 2022 sus votantes fueron mayormente con Bolsonaro al PL.
Si en cambio se cuenta PSL 2018 como `direita_bolsonarista`:

| Família | Linaje (por defecto) | PSL → direita |
|---|---:|---:|
| centrao | 11.20 | 8.23 |
| direita_bolsonarista | 8.22 | 6.05 |
| resto | sin cambios | sin cambios |

El Centrão sigue siendo el más volátil en ambos casos. Se mantiene la regla
de linaje por ser la misma para todos los partidos.

## Limitaciones

- Dos elecciones = **una sola diferencia por UF**. Es una primera
  aproximación; con 2026 ya habrá dos diferencias.
- `esquerda_independente` 2026 son partidos muy chicos (PCB, PCO, PSTU, UP):
  su volatilidad casi nula refleja su tamaño, no estabilidad política.
- Mide movimiento entre famílias a nivel UF, no dentro de cada família.
