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

## Estado por estado (presidente + gobernador)

Decisión del 2026-10-02: presidente y gobernador 2018/2022, un solo PDF con
27 capítulos.

```bash
python -m src.etl.extract.tse_extractor --dataset votacion_seccion_uf --ano 2018 2022   # ~5 GB, todos los cargos por UF
python -m src.etl.transform.votacion_seccion --cargo gobernador --ano 2018 2022
python -m src.models.analisis_estados                  # -> estados/<fecha>/datos.json + figs/
python -m src.viz.informe_estados_pdf                  # -> reports/briefs/ATLAS_Brasil_Estado_por_Estado_<fecha>.pdf
```

- **Gobernador por escuela:** votos de los dos primeros de la 1ª vuelta,
  otros, blanco/nulo y abstención, en cada vuelta. Los resultados por UF
  coinciden con los oficiales.
- **Voto cruzado:** % de escuelas donde el bando que gana a presidente no es
  el que gana a gobernador. Se calcula solo si los dos primeros a gobernador
  se reparten los bandos presidenciales: correlaciones con el % de Lula por
  escuela de signo opuesto y las dos con |r| ≥ 0,2. Si no, no se calcula (AM,
  RO, RR, RS en 2022).
- **Mesas atípicas:** z = (% Lula en la sección − % en el resto de su escuela)
  / sqrt(azar binomial + tau²), donde tau² es la variación normal entre mesas
  de una misma escuela, estimada en todo el país (2,2 pp). Se marca atípica
  con |z| > 4: son 584 de 422.400 secciones en escuelas con 3 mesas o más.
  Atípica no quiere decir irregular: suelen ser secciones especiales
  (universidades, cárceles, hospitales) o urnas muy chicas.
- **Transferencias de terceros por UF:** cuando el tercero sacó menos del 3%
  en la UF, el informe avisa que la estimación es poco precisa.

## Capas geoespaciales por estado (GeoJSON)

```bash
python -m src.etl.extract.tse_extractor --dataset locales_votacion --ano 2024 2026
python -m src.etl.transform.coordenadas_locales --ano 2022 --respaldo 2024 2018   # completa coordenadas
python -m src.geo.divisiones            # capas por UF en data/processed/geo/<UF>/
python -m src.geo.empaquetar            # un zip por UF en reports/geo/ (fuera de git, ~400 MB)
```

- **Jurisdicciones:** regiões intermediárias e imediatas, municípios,
  distritos y bairros. Salen de unir los setores de la malla del Censo 2022,
  que trae los códigos de cada nivel, con `coverage_union_all` y
  `coverage_simplify` para que no queden huecos entre vecinos.
- **Zonas eleitorais y áreas de escuela:** aproximadas. Cada setor va a la
  escuela más cercana de su município. Es el nivel poligonal más fino y el
  equivalente del circuito de CABA. Los municípios sin escuelas con
  coordenadas van a su zona principal.
- **Coordenadas faltantes:** el archivo 2022 del TSE no trae coordenadas
  para el 5% del padrón. Se completan con la misma escuela en 2024 o 2018 y,
  si no, con el centroide del barrio del IBGE (`coord_origen = bairro`,
  aproximada: no se usa para trazar áreas). Queda sin coordenada el 3,4% del
  padrón, concentrado en BA (71% con coordenada precisa) y SE (75%). Esas
  escuelas cuentan en município, región y zona, pero no en distrito, barrio
  ni área de escuela.
- **Controles:** en las 27 UF, regiões y zonas suman exactamente lo mismo
  que municípios (salvo zonas sin ninguna escuela ubicable en BA y ES).
- **DF:** es un solo município y la malla 2022 no trae sus regiões
  administrativas. El detalle en el DF lo dan las 19 zonas y las áreas de
  escuela.
