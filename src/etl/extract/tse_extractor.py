"""
src/etl/extract/tse_extractor.py

Descarga datasets crudos del Portal de Dados Abertos do TSE y los deja en
data/raw/tse/<dataset>/<año>/ sin transformar (principio: raw es inmutable).

Uso:
    python -m src.etl.extract.tse_extractor --dataset resultados --ano 2026
    python -m src.etl.extract.tse_extractor --dataset candidatos --ano 2026
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
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "tse"


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def descargar_dataset(dataset: str, ano: int, timeout: int = 60) -> Path:
    cfg = cargar_config()["tse"]["dados_abertos"]
    endpoint = cfg["datasets"][dataset].format(ano=ano)
    url = f"{cfg['base_url']}/{endpoint}"

    destino = RAW_DIR / dataset / str(ano)
    destino.mkdir(parents=True, exist_ok=True)

    log.info("Descargando %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()

    archivo = destino / f"{dataset}_{ano}.zip"
    archivo.write_bytes(resp.content)
    log.info("Guardado en %s (%.1f MB)", archivo, len(resp.content) / 1e6)
    return archivo


def main() -> None:
    parser = argparse.ArgumentParser(description="Extractor de datos abertos do TSE")
    parser.add_argument("--dataset", required=True,
                         choices=["candidatos", "resultados", "padron",
                                  "prestacao_contas", "bens_candidatos"])
    parser.add_argument("--ano", required=True, type=int)
    args = parser.parse_args()

    descargar_dataset(args.dataset, args.ano)


if __name__ == "__main__":
    main()
