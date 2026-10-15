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
- No usa encuestas de 2ª vuelta, por decisión de método (2026-10-07).

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

## Gobernadores (`src/models/balotaje_gobernadores_2026.py`)

Siete UF van a 2ª vuelta el 25/10: AC, AM, DF, ES, RJ, RN, TO (TSE, elección
estadual 6259, cargo 0003). Unidad: município × zona (divulgación por zona del
TSE; el DF tiene 19 zonas). Salida en
`data/processed/electoral/balotaje_gobernadores_2026/<fecha_utc>/`.

Tres pronósticos, probados con los 26 balotajes de gobernador de 2018 y 2022:

| Método | RMSE | Ganador correcto |
|---|---|---|
| Ingenuo (cada finalista conserva su proporción) | 9,4 pp | 20/26 |
| Promedio | 10,3 pp | 18/26 |
| Origen (eliminados según su voto presidencial) | 12,9 pp | 14/26 |

Principal: ingenuo (`balotaje.gobernador_metodo`). El de origen falló en 2018
(Zema, Witzel, Moisés crecieron por fuera de la lógica presidencial) y sus
matrices por UF caen en esquinas (0 o 1) con pocas unidades: queda solo como
"señal" de hacia dónde empujan los eliminados. Montecarlo: t de Student (4 gl)
con desvío = RMSE del ingenuo. Remontadas en 2018-2022: 6 de 26, todas con el
líder por debajo del 60 % de los votos de los finalistas.

## Pronóstico municipal y tablero de la noche (`src/models/tablero_2v_2026.py`)

- `balotaje_2026` guarda `municipios.parquet` (método R por município; suma
  exactamente lo mismo que por UF) y `backtest_municipios.parquet` (2022 desde
  2018 con el resultado real; error medio por município 1,1 pts). El brief tiene
  la página "municipio por municipio" con los dos mapas.
- Tablero: cada município contado se compara con su pronóstico; el desvío se
  promedia por UF y se encoge hacia la región y el país (`tablero.k_votos`), y
  se proyecta sobre lo que falta contar. Incertidumbre = sd del Montecarlo ×
  fracción de votos sin contar (piso 0,15 pts).
- TSE 2ª vuelta: presidente elección 6258, gobernador 6260 (no existen antes
  del 25/10; el script avisa y sigue). Lista de municípios: config de 6258 o,
  si no está, la de 6257.
- Prueba (`--simular-2022`): Nordeste contando tarde, lo contado de cada
  município con desvío N(0, 4 pts) y pronóstico corrido 3 pts. Con 2 % contado
  la proyección erra −1,6 pts (dentro de su rango); con 30 %, −0,3; lo contado
  mostraba a Lula 5 pts abajo. Un pronóstico corrido parejo se cancela.
- Ensayo con el conteo REAL del 4/10 (`--ensayo-4-10`): el avance y el desvío
  dentro de cada município de las fotos del 4/10 aplicados a la 2ª vuelta de
  2022. Con 85 % contado lo contado daba Lula 49,3 % (perdiendo) y el tablero
  50,7 ± 0,4; con 91 %, 50,8 ± 0,3; real 50,9 %. Desvío real dentro de los
  municípios a medio contar: −0,25 pts para Lula en promedio (−0,6 en el
  Nordeste, donde las secciones del interior entran tarde), así que la
  proyección tiende a quedar ~0,15 pts corta para Lula a esa altura. Las fotos
  arrancan a las 19:26 de Brasília con ~85 % contado: las dos primeras horas
  de la noche no tienen ensayo con datos reales.
- Limitación: si lo contado dentro de los municípios está sesgado de forma
  correlacionada (todas las capitales primero), el desvío medio arrastra ese
  sesgo hasta que entran los interiores.

Noche del 25/10:

    python -m src.models.tablero_2v_2026 --loop 180

y abrir `reports/tablero/tablero_2v.html` (se recarga cada 60 s).

## Perfil de la reserva con el Censo (`src/models/perfil_reserva_2026.py`)

Cruza la reserva por município (movilizacion_2026) con el Censo 2022 por local
de votación sumado a município (5.367 municípios). Perfil de territorios, no de
personas. Salida en `data/processed/electoral/perfil_reserva_2026/<fecha_utc>/`.

- Abandono (votantes de la 2ª vuelta 2022 que no votaron el 4/10): Lula 9,4 %,
  Bolsonaro 5,2 %. Crece con el tamaño del município para Lula (8,9 % en los de
  menos de 20 mil electores a 10,1 % en los de más de 500 mil) y baja para
  Bolsonaro (5,7 % a 4,7 %). Por región, Lula pierde más en el Sudeste (10,9 %).
- Regresiones con efectos fijos de UF: dentro de cada estado ninguna variable
  del Censo mueve el abandono de Lula más de 0,5 pts por desvío estándar; los
  municípios con más abandono son más urbanos y con más cloaca a red.
- En el Norte la estimación da lo contrario (Lula 2,6 %, Bolsonaro 10,9 %):
  pocos municípios grandes y matriz de región, leerlo con cautela.

## Noche del 25/10: guion

1. Desde el inicio de la divulgación (17 h de Brasília):
   `python -m src.models.tablero_2v_2026 --loop 180` y abrir
   `reports/tablero/tablero_2v.html`.
2. Piezas con la última foto del tablero:
   `python -m src.viz.redes_noche_balotaje` → `reports/figures/redes/noche_25-10/`
   (presidente, estados, gobernadores y sus textos). Antes del 99,5 % contado
   dicen "proyección" y no proclaman ganador.
3. Probar el diseño sin datos reales: `--demo` (final) o `--demo --parcial`;
   salen con marca DEMO y no se versionan.

## Robustez (`src/models/robustez_balotaje_2026.py`)

`--n-boot 200` (~9 min). Corrida del 2026-10-07:

- Bootstrap (municípios y locales remuestreados dentro de cada UF, matrices
  reestimadas): sd 0,11 pts; 90 % entre 47,2 y 47,6 %.
- Métodos: origen 1ª vuelta 2022 encadenado con T22 (R1) 47,4 %; analogía
  47,1 %; matriz propia en todas las UF 47,3 %; matriz regional en todas 47,4 %.
- Supuestos: retorno de los terceros a su lado de 2022 del 80 % / 60 % → 47,4 /
  47,5 %; movilización como en 2018 48,3 % (P 9 %); sin movilización 48,5 %
  (P 12 %). Piso de incertidumbre 1 / 2 pts → P(Lula) 1 % / 6 %.
- Conclusión: el método casi no mueve el número; lo que pesa es qué pasa con la
  participación entre vueltas. Página "¿Cuánto aguanta el número?" en el brief.

## Control externo: encuestas de 2ª vuelta (`src/models/encuestas_balotaje_2026.py`)

Actualización del 2026-10-15. Las encuestas NO entran al pronóstico (decisión
del 2026-10-07): se contrastan aparte. Fuente: Wikipedia, revisión del 15/10
(`config/encuestas_wikipedia.yaml`, tabla 9 = Lula vs Flávio después del 4/10).
Salida en `data/processed/electoral/encuestas_balotaje_2026/<fecha_utc>/`.

- 10 encuestas de 9 casas (5 al 13/10); 9 con Flávio adelante. Promedio con
  efectos de casa, calidad 2018/2022 y vida media de 3 días: Lula 47,9 %
  (promedio simple 48,0). Sin tendencia: −0,03 pts/día (t −0,14).
- Track record por horizonte (solo encuestas posteriores a la 1ª vuelta): a 10
  días, el promedio subestimó a Haddad 4,8 pts en 2018 (giro tardío: +3,1 en
  los últimos 10 días) y sobreestimó a Lula 1,4 en 2022. Signo distinto: no se
  corrige la media (la regla de corrección exige el mismo sesgo en todas las
  elecciones); el error entra como desvío (3,4 pts con piso de 1,5).
- Contraste: encuestas 47,9 ± 3,4 vs modelo 47,3 ± 1,5 → z 0,16 (p 0,87).
  Síntesis por precisión (modelo pesa 83 %): 47,4 %, P(Lula) 3 %. Encuestas
  solas: P(Lula) 22 %; con el error de 2018 52,7 %, con el de 2022 46,6 %.
- Proporción uniforme de terceros a Lula que reproduce las encuestas: 53 %
  (el modelo da 43 %).

## Transferencias declaradas (`src/models/transferencias_balotaje_2026.py`)

BTG/Nexus 10–12/10 (n 2.002, telefónica): 2ª vuelta por voto de la 1ª. El
pronóstico se descompone en bloques de votos válidos por grupo (lineal en cada
proporción) y se recombina. Bayes Beta-binomial por subgrupo: a priori = modelo
R con 20 casos de peso; datos = subgrupo con n estimado (padrón × 2.002 /
efecto de diseño 1,5; abstencionistas con declaración del 50 %).

| Paso | Lula |
|---|---|
| Modelo R | 47,35 |
| + terceros como Nexus (Caiado 33 % a Lula, Cury 49, Renan 45, Zema 0) | 47,31 |
| + abstencionistas como Nexus (46 % a Lula vs 26 % en 2022) | 47,54 |
| + retención igual 98/98 (2022: Lula 97,3 %, Bolsonaro 99,9 %) | 48,13 |

Con shock nacional: 48,1 %, P(Lula) 8 %. La retención sola vale +0,59 pts,
más que todos los terceros. Brecha: 6,36 M de válidos (3,18 M de conversión).
Con 43 % de terceros, Lula necesita ~6,1 M de votos netos extra (reserva neta
2,6 M, bruta 5,7 M). Grilla de caminos en `grilla.csv`.

## Dónde se decide (`src/models/territorio_balotaje_2026.py`)

Pronóstico municipal R + reserva de movilización + cambio 1ª vuelta 2022→2026.

- Votos en juego (terceros + reservas): 18,0 M. SP 25 %; SP+MG+BA+RJ+PR 54 %.
  SP da a Flávio 4,4 M de margen (70 % del nacional).
- Lula perdió 1,8 M de votos de 1ª vuelta en el Sudeste y 1,0 M en el Sur
  desde 2022; el bolsonarismo creció 1,6 M en el Nordeste.
- Municípios de 100–500 mil electores (192): Lula 41,8 %, Flávio +4,8 M (76 %
  del margen). Menos de 20 mil: Lula 52,5 %. Capitales 47,6 % (≈ nacional).
- Termómetro: MG, desvío medio 1,8 pts del nacional en 2018, 2022 y 1ª 2026
  (−1,7 en la 1ª de 2026). Siguen AM, AP, TO. PA en 49,9 %.
- 84 municípios de más de 50 mil electores entre 45 y 55 % (31,8 M de
  electores); São Paulo capital 50,3 %.
- Participación (nuevos votantes como su município en 2022): +5 pts en el
  Nordeste → +0,4; en los municípios de Lula 2022 → +0,5; Sur y CO → −0,1.

Brief del 15/10: `reports/briefs/ATLAS_Brasil_Brief_Balotaje_2026-10-15.pdf`
(21 páginas; nuevas: encuestas, lo que dicen los votantes, dónde se decide ×2,
caminos al 50 %).

## Anexo: los 5.571 municípios (`src/viz/anexo_municipios_pdf.py`)

Lista completa de quién ganó cada município el 4/10, con el ganador de la 2ª
vuelta de 2022 y la proyección del modelo para el 25/10, agrupada por estado.
Salidas: `reports/briefs/ATLAS_Brasil_Municipios_<fecha>.pdf` (73 páginas) y
`.xlsx` (todos los candidatos, filtrable, con resumen por UF). Al 4/10: Flávio
ganó 2.908 municípios y Lula 2.663; 462 cambiaron de ganador respecto de 2022
(461 de Lula a Flávio). Nombres de la correspondencia TSE–IBGE; Boa Esperança
do Norte (MT, creado en 2023) se completa a mano.

    python -m src.viz.anexo_municipios_pdf --fecha 2026-10-15

## Hallazgos: redes e informe formal (15/10)

- `src/viz/redes_hallazgos_balotaje.py`: post de Instagram "5 datos" y carrusel
  de LinkedIn de 9 láminas (`reports/figures/redes/post_hallazgos_<fecha>.jpg`,
  `ATLAS_carrusel_hallazgos_<fecha>.pdf` + JPG), con los textos en `.txt`.
- `src/viz/informe_hallazgos_pdf.py`: informe formal de 9 páginas
  (`reports/briefs/ATLAS_Brasil_Hallazgos_Balotaje_<fecha>.pdf`). Reusa
  figuras del brief: correr antes `src.viz.brief_balotaje_pdf` con la misma fecha.

    python -m src.viz.redes_hallazgos_balotaje --fecha 2026-10-15
    python -m src.viz.informe_hallazgos_pdf --fecha 2026-10-15

## Ensayo del 15/10

El TSE ya publica los archivos de la elección 6258 en cero (generados el
13/10): la lectura en vivo del tablero corre de punta a punta contra el
endpoint real de la noche.
Resultado (15/10, 08:01): lectura completa en 6 min 36 s (5.570 municípios, 6
hilos), 0,0 % contado, proyección = pronóstico (47,35 ± 2,49, P 4 %), HTML
regenerado. Consecuencia para la noche: cada vuelta del loop tarda ~6–7 min
mientras haya municípios incompletos (lo completo no se vuelve a pedir), así
que `--loop 180` en la práctica actualiza cada ~10 min al principio. Lanzarlo
a las 16:45 de Brasília para tener la primera foto cuando arranca la
divulgación.
