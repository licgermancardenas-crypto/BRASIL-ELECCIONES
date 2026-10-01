"""
src/etl/extract/referencia_extractor.py

Descarga tablas de referencia chicas (catálogos, no datos electorales) a
data/raw/referencia/<fuente>/<fecha_utc>/, versionadas con manifest.json.

Fuentes (URLs en config/fuentes.yaml):
  ibge_municipios   -> IBGE Localidades API, lista oficial de municípios
  tse_ibge_betafcc  -> tabla comunitaria TSE↔IBGE (solo para validación)
  senado_en_ejercicio -> Senado Federal, senadores en ejercicio con partido actual

Uso:
    python -m src.etl.extract.referencia_extractor --fuente ibge_municipios tse_ibge_betafcc
"""
from __future__ import annotations

import argparse
import io
import json
import logging
from pathlib import Path

import pandas as pd
import yaml

from src.etl.extract.versionado import DescargaInvalida, descargar_versionado, ultima_version_en

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "fuentes.yaml"
RAW_DIR = ROOT / "data" / "raw" / "referencia"

MINIMO_MUNICIPIOS = 5500  # Brasil tiene ~5.570; menos que esto = respuesta truncada


def _validar_json_municipios(path: Path) -> dict:
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise DescargaInvalida(f"JSON inválido: {e}") from e
    if len(datos) < MINIMO_MUNICIPIOS:
        raise DescargaInvalida(f"solo {len(datos)} municípios (esperado >= {MINIMO_MUNICIPIOS})")
    return {"registros": len(datos)}


def _validar_csv_betafcc(path: Path) -> dict:
    df = pd.read_csv(io.BytesIO(path.read_bytes()), dtype=str)
    faltan = {"codigo_tse", "codigo_ibge", "uf"} - set(df.columns)
    if faltan:
        raise DescargaInvalida(f"faltan columnas {faltan}")
    if len(df) < MINIMO_MUNICIPIOS:
        raise DescargaInvalida(f"solo {len(df)} filas")
    return {"registros": len(df)}


def _validar_json_senado(path: Path) -> dict:
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
        senadores = datos["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    except (ValueError, KeyError) as e:
        raise DescargaInvalida(f"respuesta del Senado con formato inesperado: {e}") from e
    if len(senadores) != 81:
        raise DescargaInvalida(f"{len(senadores)} senadores (se esperaban 81)")
    return {"registros": len(senadores)}


def _fuentes() -> dict[str, tuple[str, str, callable]]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "ibge_municipios": (cfg["ibge"]["localidades_api"]["municipios"],
                            "municipios_ibge.json", _validar_json_municipios),
        "tse_ibge_betafcc": (cfg["referencia_comunitaria"]["tse_ibge_betafcc"]["url"],
                             "municipios_brasileiros_tse.csv", _validar_csv_betafcc),
        "senado_en_ejercicio": (cfg["legislativo"]["senado_dados_abertos"]["senadores_en_ejercicio"],
                                "senadores_en_ejercicio.json", _validar_json_senado),
    }


def ultima_version(fuente: str) -> Path:
    return ultima_version_en(RAW_DIR / fuente)


def descargar(fuente: str) -> Path | None:
    url, nombre, validar = _fuentes()[fuente]
    return descargar_versionado(url, RAW_DIR / fuente, nombre,
                                meta={"dataset": fuente, "ano": "referencia"}, validar=validar,
                                headers={"Accept": "application/json"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuente", nargs="+", required=True, choices=list(_fuentes()))
    args = parser.parse_args()
    for f in args.fuente:
        descargar(f)


if __name__ == "__main__":
    main()
