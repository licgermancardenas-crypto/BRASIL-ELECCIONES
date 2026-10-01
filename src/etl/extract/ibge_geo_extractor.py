"""
src/etl/extract/ibge_geo_extractor.py

Descarga las mallas territoriales del IBGE (setores censitários, municípios,
UFs) en shapefile, y las deja en data/raw/ibge/malhas/<nivel>/.

El nivel de detalle máximo es setor censitário (EPSG:4674 / SIRGAS 2000).
Para análisis electoral por sección, el cruce con setor censitário es
aproximado (no son la misma unidad) — ver docs/metodologia_geoespacial.md.

Uso:
    python -m src.etl.extract.ibge_geo_extractor --nivel setores_censitarios --ano 2022
    python -m src.etl.extract.ibge_geo_extractor --nivel municipios --ano 2024
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "fuentes.yaml"
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "ibge" / "malhas"


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def descargar_malla(nivel: str, ano: int, timeout: int = 120) -> Path:
    cfg = cargar_config()["ibge"]["malhas_territoriales"]
    ruta_relativa = cfg[nivel]
    url = f"{cfg['base_url']}/{ruta_relativa}/{ano}/Brasil/BR_{nivel}_{ano}.zip"

    destino = RAW_DIR / nivel
    destino.mkdir(parents=True, exist_ok=True)

    log.info("Descargando malla %s %s desde %s", nivel, ano, url)
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()

    archivo = destino / f"{nivel}_{ano}.zip"
    with open(archivo, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    log.info("Guardado en %s (EPSG:%s)", archivo, cfg["epsg"])
    return archivo


def main() -> None:
    parser = argparse.ArgumentParser(description="Extractor de malhas IBGE")
    parser.add_argument("--nivel", required=True,
                         choices=["setores_censitarios", "municipios", "uf"])
    parser.add_argument("--ano", required=True, type=int)
    args = parser.parse_args()

    descargar_malla(args.nivel, args.ano)


if __name__ == "__main__":
    main()
