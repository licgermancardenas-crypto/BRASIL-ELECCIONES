# Balotaje presidencial 2026: transferencias y pronóstico

`src/models/balotaje_2026.py` · parámetros en `config/modelo.yaml` (`balotaje`) ·
salida en `data/processed/electoral/balotaje_2026/<fecha_utc>/`.

Decisión del 2026-10-07: pronosticar el balotaje (25/10) desde el resultado de
la 1ª vuelta del TSE por município, no desde encuestas (no había encuestas de
2ª vuelta todavía; Datafolha sale el 8/10, AtlasIntel el 9/10).

## Datos

- 1ª vuelta 2026 final por município (5.571, 100% de secciones):
  `python -m src.models.conteo_2026 --final` →
  `resultado_presidencial_2026_1v_municipios.parquet` (padrón, comparecencia,
  abstención, blancos, nulos y cada candidato). El exterior entra con sus
  votos válidos por UF (`conteo_presidencial_2026_1v.json`).
- 2018 y 2022 por local de votación (`locales_<año>.parquet`), sumados a
  município por código IBGE.

## Método

Lula y Flávio no se reparten por igual: a cada grupo de la 1ª vuelta se le
aplica una fila de la matriz 1ª → 2ª vuelta de la elección anterior
(regresión ecológica con restricciones por UF sobre locales, la de
`analisis_seccion`).

| Grupo 1ª vuelta 2026 | Regla |
|---|---|
| Lula, Flávio | fila PT / Bolsonaro 2022 (retención) |
| Blanco-nulo, abstención | su fila 2022 (movilización) |
| Terceros | fila de su análogo 2022 dice cuántos votan válido; el reparto Lula/Flávio depende del método |

- **A · analogía**: el tercero reparte como su análogo 2022 (Cury → Ciro,
  Caiado → Tebet, Renan Santos, Zema y otros → "otros").
- **R · origen**: regresión ecológica 2ª vuelta 2022 → 1ª vuelta 2026 por
  município (por UF si tiene ≥ 80 municípios, si no por región). Los votantes de
  terceros que venían de Lula vuelven a Lula, los de Bolsonaro a Flávio, y los
  de blanco/abstención se reparten como el análogo. Los votos de cada município
  se ajustan proporcionalmente para que sumen lo observado.

## Backtest (base 2018 → 2ª vuelta 2022)

| Método | Lula predicho | Real | Error nacional | MAE por UF |
|---|---|---|---|---|
| A · analogía | 52,8 | 50,9 | +1,9 pp | 1,95 pp |
| R · origen | 50,7 | 50,9 | −0,2 pp | 1,08 pp |

R es el principal. El error de A viene de que en 2018 Ciro era centroizquierda
(~89% a Haddad) y en 2022 no: la analogía no viaja entre elecciones, el origen sí.
Es UNA elección de backtest: el error nacional chico de R puede ser suerte.

## Montecarlo

% Lula por UF = predicción R + shock nacional + shock UF.

- Shock nacional: t de Student (4 gl), desvío
  √(error backtest² + (A−R)²/4 + 1,5²) ≈ 1,5 pp. El 1,5 pp es un piso por lo
  que el backtest no ve: participación diferencial, campaña, apoyos.
- Shock UF: desvío de los errores por UF del backtest sin el nacional (1,27 pp).

## Escenarios

Fijan la proporción a Lula de algunos terceros (entre los que votan válido):
apoyos de Caiado y Zema a Flávio (20% a Lula), Renan también, Cury con Lula
(65%); movilización como en 2018 (blanco y abstención volvieron más al PT);
y sin movilización (solo votos válidos, retención total).

## Límites

- Regresión ecológica: estima el comportamiento de grupos por su peso en el
  territorio, no de individuos. Los terceros chicos (Zema, otros) son los más
  ruidosos.
- La movilización 2022 (blanco y abstención hacia Bolsonaro) se supone que se
  repite; el escenario 2018 mide cuánto pesa ese supuesto.
- No usa encuestas de 2ª vuelta. Cuando salgan, sirven de contraste.

## Movilización (`src/models/movilizacion_2026.py`)

Salida en `data/processed/electoral/movilizacion_2026/<fecha_utc>/`. Sin encuestas
(decisión del 2026-10-07).

- Reserva: votantes de la 2ª vuelta 2022 que no votaron el 4/10, con la misma
  matriz de origen por UF ajustada a la abstención de cada município.
  Resultado 2026-10-07: 5,7 M de Lula 2022 y 3,0 M de Bolsonaro 2022 (neta
  Lula 2,6 M), contra una brecha de 6,4 M en el pronóstico: no alcanza ni con
  el 100 % de la reserva de Lula.
- Historia entre vueltas (2018 y 2022, por quintil de voto PT): la 2ª vuelta
  movilizó relativamente más a las zonas bolsonaristas en los dos ciclos.
- Para empatar, la abstención tendría que bajar ~29 pp en los municípios donde
  ganó Lula en 2022 (nuevos votantes repartidos como el voto 2022 del município);
  el mayor movimiento entre vueltas observado es 0,7 pp.
