"""
src/etl/extract/censo_extractor.py

Descarga el Censo 2022 por setor censitário (agregados en CSV y malla en
GeoPackage) a data/raw/ibge/censo_2022/<archivo>/<fecha_utc>/, versionado
con manifest.json como el resto de raw/. URLs en config/fuentes.yaml
(ibge.censo_2022_setores).

Uso:
    python -m src.etl.extract.censo_extractor                 # todos
    python -m src.etl.extract.censo_extractor --archivo basico malla_setores
"""
from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path

import yaml

from src.etl.extract.versionado import DescargaInvalida, descargar_versionado, ultima_version_en

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "fuentes.yaml"
RAW_DIR = ROOT / "data" / "raw" / "ibge" / "censo_2022"


def _config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["ibge"]["censo_2022_setores"]


def _validar(path: Path) -> dict:
    nombre = path.name.lstrip(".").removesuffix(".part")
    if nombre.endswith(".zip"):
        if not zipfile.is_zipfile(path):
            raise DescargaInvalida(f"{nombre} no es un zip válido")
        with zipfile.ZipFile(path) as z:
            return {"archivos_internos": z.namelist()}
    if nombre.endswith(".gpkg"):
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise DescargaInvalida(f"{nombre} no es un GeoPackage (SQLite)")
    return {}


def ultima_version(archivo: str) -> Path:
    return ultima_version_en(RAW_DIR / archivo)


def descargar(archivo: str) -> Path | None:
    cfg = _config()
    ruta = cfg["archivos"][archivo]
    return descargar_versionado(f"{cfg['base_url']}/{ruta}", RAW_DIR / archivo, Path(ruta).name,
                                meta={"dataset": f"censo_2022_{archivo}", "ano": 2022}, validar=_validar,
                                timeout=600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archivo", nargs="+", choices=list(_config()["archivos"]))
    args = parser.parse_args()
    for a in args.archivo or list(_config()["archivos"]):
        descargar(a)


if __name__ == "__main__":
    main()
