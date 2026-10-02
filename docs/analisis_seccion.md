# Análisis mesa por mesa (presidencial 2018 y 2022)

Equivalente brasileño del análisis por mesa y circuito de CABA. Decisión del
2026-10-01: elección presidencial, todo el país, 2018 y 2022, sobre el que se
cargará 2026 cuando el TSE publique los resultados por sección.

```bash
python -m src.etl.extract.tse_extractor --dataset votacion_seccion_presidente locales_votacion --ano 2018 2022
python -m src.etl.extract.censo_extractor            # Censo 2022 por setor + malla (1,5 GB)
python -m src.etl.transform.votacion_seccion          # votos por sección (ancho)
python -m src.etl.transform.locales_votacion          # padrón y coordenadas por sección
python -m src.etl.transform.base_locales              # base por local de votación
python -m src.geo.censo_locales                       # Censo por área de influencia de cada local
python -m src.models.analisis_seccion                 # análisis -> datos.json + figs/
python -m src.viz.informe_seccion_pdf                 # informe PDF
```

## Unidades

- **Sección (seção eleitoral):** la urna. Son unas 470.000, con ~330
  electores cada una. Es la unidad mínima del escrutinio y el TSE publica su
  resultado. Las secciones agregadas el día de la elección se suman a su
  sección principal, porque el TSE publica sus votos bajo ese número.
- **Local de votación:** la escuela. Son unas 92.000, con ~5 secciones cada
  una. Es la **unidad del análisis**, como el circuito en CABA: tiene
  ubicación (latitud/longitud del TSE) y es lo bastante grande para que los
  porcentajes no sean ruido. Quedan fuera los locales con menos de 100
  electores y el exterior.
- **Município:** se usa para comparar 2018 con 2022, porque los números de
  local cambian entre elecciones.

## Controles

- Votos por sección contra el resultado oficial: coinciden al centésimo en
  las dos vueltas de ambos años (2018: Bolsonaro 46,03 / Haddad 29,28 en 1ª
  vuelta y 55,13 / 44,87 en 2ª; 2022: Lula 48,43 / Bolsonaro 43,20 en 1ª y
  50,90 / 49,10 en 2ª).
- Padrón: 100% de las secciones con votos encuentran su padrón. La
  abstención reconstruida en 1ª vuelta es 20,33% en 2018 y 20,87% en 2022, en
  línea con la oficial.
- Alrededor del 1% de las secciones tiene más votantes que padrón (voto en
  tránsito): en esas secciones la abstención se recorta en 0.

## Métodos

- **Descomposición de la varianza** del % de Lula por local, ponderada por
  votos válidos: entre UF, entre municípios de una UF y dentro del município.
- **Transferencias entre vueltas:** regresión ecológica con restricciones.
  Cada proporción está entre 0 y 1 y cada fila suma 100%. Se estima UF por UF
  sobre los locales, con los votos como proporción del padrón, ponderando por
  electores. La matriz nacional promedia las de cada UF según el peso de cada
  origen. Validación: aplicada a la 1ª vuelta de 2022 reproduce la 2ª (Lula
  50,91% estimado contra 50,89% real), con un error mediano de 1,3 puntos por
  local.
- **Censo por local:** cada setor censitário se asigna al local de votación
  más cercano de su município (punto interior del setor contra las
  coordenadas del local). Es el área de influencia de la escuela y es una
  aproximación: la gente no siempre vota en la escuela más cercana. El Censo
  2022 no publica ingreso por setor, así que el nivel socioeconómico se
  aproxima con los hogares con 2 baños o más y con cloaca conectada a red.
- **Qué explica el voto:** mínimos cuadrados ponderados del % de Lula sobre
  las variables del Censo, con y sin efectos fijos de UF. **Tipología:**
  k-medias (k = 4) sobre las variables estandarizadas.
- **Implicancias 2026:** la matriz de 2022 aplicada al agregado de encuestas
  de 1ª vuelta. A qué votante de 2022 se parece el de cada tercero es un
  supuesto: `seccion.analogia_2026` en `config/modelo.yaml`.

## Limitaciones

- Inferencia ecológica: compara territorios, no personas.
- Coordenadas faltantes: 7% de los locales en 2022 y 20% en 2018. Los locales
  sin coordenadas no entran al mapa ni al cruce con el Censo.
- La comparación 2018–2022 es por município, no por local.
