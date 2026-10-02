# ATLAS Brasil 2026

Proyecto de ATLAS Analytics: inteligencia electoral y territorial para las
elecciones generales de Brasil (4 de octubre de 2026 — presidencial,
gubernamental, Câmara dos Deputados y Senado, con eventual balotaje
presidencial el 25 de octubre).

Metodología hermana de `atlas-caba-jg2027` y `atlas-congreso-2027`: análisis
histórico de bloques/alianzas + simulación Montecarlo, extendido acá con
una capa geoespacial de máximo detalle (setor censitário / seção eleitoral).

## Estructura del repositorio

```
atlas-brasil-2026/
├── data/
│   ├── raw/                  # Datos crudos, inmutables, tal cual se bajan de la fuente
│   │   ├── tse/               # Candidaturas, resultados, padrón, financiamiento
│   │   ├── ibge/               # Malhas geoespaciales, censo, IDH
│   │   └── legislativo/        # Câmara y Senado (dados abertos)
│   ├── interim/               # Datos en transformación intermedia (no versionar)
│   └── processed/             # Datasets finales, listos para modelar/visualizar
│       ├── electoral/
│       ├── geoespacial/
│       ├── socioeconomico/
│       └── legislativo/
├── src/
│   ├── etl/
│   │   ├── extract/            # Descarga desde fuente (TSE, IBGE, Câmara, Senado)
│   │   ├── transform/          # Limpieza, normalización, cruces por código IBGE/TSE
│   │   │                        #   incluye gobernadores_por_uf.py (balotaje es POR ESTADO, no nacional)
│   │   └── load/                # Escritura a processed/ en formato parquet
│   ├── geo/                    # Geocodificación, join espacial, agregación por nivel
│   ├── models/
│   │   ├── montecarlo/          # Simulación de bancas y escenarios de balotaje
│   │   └── bloques/              # Clasificación partido → família política
│   └── viz/                    # Generación de mapas y gráficos para reports/
├── config/
│   ├── fuentes.yaml             # Catálogo único de URLs/endpoints — nunca hardcodear
│   └── familias_partidarias.yaml # Clasificación partido → família (versionada por legislatura)
├── notebooks/                  # Exploración — nada de lógica productiva acá
├── reports/
│   ├── figures/
│   └── briefs/                  # Informes ejecutivos (uno por hito: 1ra vuelta, balotaje, etc.)
├── tests/
└── docs/
    ├── arquitectura.md
    ├── metodologia_geoespacial.md
    └── diccionario_datos.md
```

## Principio de diseño

1. **`raw/` es sagrado**: nunca se edita a mano ni se sobreescribe. Si una
   fuente cambia de formato, se versiona la carpeta (`resultados/2026_v2/`).
2. **Todo endpoint vive en `config/fuentes.yaml`.** Ningún script tiene una
   URL hardcodeada.
3. **La família partidaria nunca se hardcodea en el dataset electoral.**
   Se resuelve en tiempo de ETL contra `config/familias_partidarias.yaml`,
   porque en Brasil la migración de bancada (troca-troca) es moneda corriente.
4. **Separación estricta UF / município / setor censitário / seção eleitoral.**
   No son la misma unidad geográfica y el join entre electoral y geoespacial
   es aproximado — está documentado en `docs/metodologia_geoespacial.md` para
   que cualquier número que salga del modelo sea trazable a su nivel de
   agregación real.
5. **Reproducibilidad**: toda simulación fija `RANDOM_SEED`. Los resultados
   de Montecarlo se versionan junto con la fecha de corte de encuestas usada.

## Quickstart

```bash
pip install -r requirements.txt

# 1. Extracción (CDN del TSE; cada descarga queda versionada con manifest.json)
python -m src.etl.extract.tse_extractor --dataset resultados resultados_partido detalle_votacion --ano 2018 2022
python -m src.etl.extract.tse_extractor --dataset encuestas_registradas candidatos coligaciones --ano 2018 2022 2026
python -m src.etl.extract.ibge_geo_extractor --nivel setores_censitarios --ano 2022
python -m src.etl.extract.referencia_extractor --fuente ibge_municipios tse_ibge_betafcc
python -m src.etl.inventario   # regenera docs/inventario_datos.md

# 1b. Fichas técnicas de encuestas (PesqEle) normalizadas 2018/2022/2026
python -m src.etl.transform.encuestas_fichas

# 1c. Tabla de correspondencia município TSE <-> IBGE (versionada en git:
#     src/etl/transform/correspondencia/municipios_tse_ibge.csv)
python -m src.etl.transform.correspondencia_municipios

# 1d. Cobertura de la clasificación partido -> familia por año
python -m src.models.bloques.resolver_familia --reporte

# 2. Pipeline completo: extracción -> transformación -> família -> carga
#    (plan en config/pipeline.yaml; registro de cada corrida en data/processed/_corridas/)
python -m src.etl.transform.run_pipeline
python -m src.etl.transform.run_pipeline --sin-descarga --desde familia
python -m src.etl.transform.run_pipeline --permitir-propuesta   # solo exploración

# 2b. Gobernadores por UF (detecta qué estados van a balotaje el 25/10 —
#     es un balotaje independiente por estado, no uno nacional)
python -m src.etl.transform.gobernadores_por_uf --ano 2026

# 3. Modelado — Câmara 2026: base resultado 2022 en famílias/listas 2026 +
#    ruido medido por família (parámetros en config/modelo.yaml). Cada corrida
#    queda versionada en data/processed/legislativo/camara/<fecha>/ con meta.json.
python -m src.models.montecarlo.proyeccion_bancas

# 3b. Senado post-2026: 27 que siguen (partido actual, API del Senado) + 54 en
#     juego por família. NO nombra ganadores; leer docs/modelo_senado.md.
python -m src.models.montecarlo.proyeccion_senado

# 3c. Gobernadores 2026: 27 elecciones independientes con balotaje por UF,
#     ventaja de incumbente calibrada con 2018+2022. Ver docs/modelo_gobernadores.md.
python -m src.models.montecarlo.proyeccion_gobernadores

# 3d. Presidencial: ESCENARIO de 2ª vuelta Lula vs Flávio Bolsonaro sobre la
#     base 2022 (no pronóstico). Ver docs/escenario_presidencial.md.
python -m src.models.montecarlo.proyeccion_presidencial

# 4. Encuestas presidenciales (Wikipedia) -> agregador con track record 2018/2022,
#    house effects y backtest -> Montecarlo 1ª/2ª vuelta. PRONÓSTICO nacional;
#    leer docs/agregacion_encuestas.md (sesgo histórico contra el bolsonarismo).
python -m src.etl.extract.wikipedia_extractor --ano 2018 2022 2026
python -m src.etl.transform.encuestas_resultados
python -m src.models.agregacion_encuestas
python -m src.models.montecarlo.proyeccion_presidencial_encuestas

# 5. Mesa por mesa: presidente 2018/2022 por sección (~470 mil), agregado por
#    local de votación y cruzado con el Censo 2022 por setor. Ver docs/analisis_seccion.md.
python -m src.etl.extract.tse_extractor --dataset votacion_seccion_presidente locales_votacion --ano 2018 2022
python -m src.etl.extract.censo_extractor
python -m src.etl.transform.votacion_seccion && python -m src.etl.transform.locales_votacion
python -m src.etl.transform.base_locales && python -m src.geo.censo_locales
python -m src.models.analisis_seccion && python -m src.viz.informe_seccion_pdf

# 5b. Estado por estado: presidente + gobernador mesa por mesa, PDF de 27 capítulos.
python -m src.etl.extract.tse_extractor --dataset votacion_seccion_uf --ano 2018 2022
python -m src.etl.transform.votacion_seccion --cargo gobernador --ano 2018 2022
python -m src.models.analisis_estados && python -m src.viz.informe_estados_pdf

# 5c. Capas geoespaciales por UF (GeoJSON/GeoPackage con resultados) y zips de entrega.
python -m src.etl.transform.coordenadas_locales && python -m src.geo.divisiones && python -m src.geo.empaquetar

# 5d. Análisis espacial en R (LISA, Gi*, GWR, SKATER, accesibilidad) e informe.
python -m src.geo.insumos_espaciales && Rscript R/analisis_espacial.R
python -m src.viz.mapas_espaciales && python -m src.viz.informe_espacial_pdf
```

## Fuentes (resumen — detalle completo en `config/fuentes.yaml`)

| Capa | Fuente | Nivel máximo de detalle |
|---|---|---|
| Resultados electorales | TSE — Dados Abertos / API de totalización | Seção eleitoral |
| Resultados procesados | CEPESPData (FGV) | Município / microrregião |
| Geoespacial | IBGE — Malhas Territoriais | Setor censitário |
| Socioeconómico | IBGE (censo, PIB) / Atlas do Desenvolvimento Humano | Município |
| Legislativo | Dados Abertos da Câmara / Senado | Votación nominal por diputado/senador |
| Encuestas | Fichas técnicas registradas en TSE | Según muestra (nacional/UF) |

## Estado

Proyecto en etapa de scaffolding — ver `docs/arquitectura.md` para el detalle
de cada fase y `/areas/atlas-brasil-2026.md` en memoria para el estado vivo.
