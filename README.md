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

# 2. Transform (normaliza, cruza con familias_partidarias.yaml)
python -m src.etl.transform.run_pipeline

# 2b. Gobernadores por UF (detecta qué estados van a balotaje el 25/10 —
#     es un balotaje independiente por estado, no uno nacional)
python -m src.etl.transform.gobernadores_por_uf --ano 2026

# 3. Modelado
python -m src.models.montecarlo.proyeccion_bancas
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
