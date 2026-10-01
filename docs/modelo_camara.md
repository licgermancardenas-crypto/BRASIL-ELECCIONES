# Modelo de bancas — Câmara dos Deputados 2026

Código: `src/models/montecarlo/proyeccion_bancas.py` (+ `reparto.py`).
Parámetros: `config/modelo.yaml`. Cada corrida queda en
`data/processed/legislativo/camara/<fecha_utc>/` con `meta.json` (semilla,
parámetros, sha256 de insumos, validación).

## Qué es y qué no es

**Sin encuestas** (decisión del 2026-10-01). La base es el **resultado 2022**
de Câmara por UF y partido, llevado a los partidos, listas (federaciones) y
famílias de **2026**. El resultado responde: *¿qué composición sale si 2026
se parece a 2022, con el nivel de movimiento que mostraron las famílias entre
2018 y 2022?* No es una proyección de intención de voto 2026.

## Pasos

1. **Base.** Votos válidos 2022 (nominales + legenda) por UF y partido →
   sigla sucesora 2026 (linaje) → lista 2026 (federaciones: FE BRASIL,
   PSOL REDE, PSDB CIDADANIA, UNIÃO+PP, PRD+SOLIDARIEDADE) → família 2026.
2. **Ruido** (en puntos del % de la família en cada UF), por simulación:
   - shock nacional por família, común a todas las UF: desvío = |cambio medio 2018→2022|;
   - shock por UF y família: desvío = volatilidad medida (`docs/volatilidad_familias.md`).
   El total de la família se mueve y se reparte entre sus listas según su peso en la base.
3. **Reparto por lista**, no por família: cociente electoral, solo compiten
   listas con ≥ 80% del cociente (Lei 14.211/2021), mayores promedios.
4. **Bancas por UF 2026** desde `consulta_vagas` del TSE: 513, misma
   distribución que 2022.

## Validación del reparto (2022)

Repartiendo los votos reales 2022 con las listas reales 2022: 22 de 513
bancas caen en otra lista, pero **el error por família es de 6 bancas**
(3 de `gobierno_lula` a `esquerda_independente`, casi todo en AP, donde
decide el piso individual del 20% del cociente que no se modela).

## Resultado (corrida 2026-10-01, 10.000 simulaciones, semilla 42)

| Família | Base sin ruido | Media | p10 | Mediana | p90 |
|---|---:|---:|---:|---:|---:|
| centrao | 247 | 240,7 | 205 | 240 | 277 |
| gobierno_lula | 125 | 128,5 | 99 | 127 | 160 |
| direita_bolsonarista | 92 | 91,2 | 43 | 90 | 141 |
| centro_liberal | 49 | 51,1 | 24 | 49 | 80 |
| sin_alineamiento | 0 | 1,4 | 0 | 1 | 4 |
| esquerda_independente | 0 | 0 | 0 | 0 | 0 |

La base sin ruido no coincide con las bancas reales 2022 reclasificadas
(ej. derecha bolsonarista 92 vs 98): con los mismos votos, las listas 2026
más grandes (federación UNIÃO+PP, PRD+SOLIDARIEDADE, PODE con PSC) se quedan
con más sobras.

### Por qué el shock nacional

Sin él, los shocks de las 27 UF se compensan y el total nacional casi no se
mueve: los intervalos p10–p90 se achican a la mitad o menos (ej. derecha
bolsonarista 77–105 en vez de 43–141). Eso sería sobreconfianza.

## Limitaciones

- Partidos nuevos (MISSÃO) no tienen votos en la base.
- Listas que no compiten en 2026 en una UF conservan ahí su voto 2022.
- Volatilidad y shock nacional estimados con una sola diferencia entre elecciones.
- No se modela el piso individual del 20% del cociente por candidato.
