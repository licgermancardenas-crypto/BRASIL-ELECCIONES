"""
src/etl/extract/wikipedia_extractor.py

Descarga las páginas de Wikipedia (en) con los resultados publicados de las
encuestas presidenciales 2018/2022/2026, versionadas en
data/raw/encuestas_wikipedia/{ano}/<fecha_utc>/ con manifest.json.

Se baja la respuesta JSON de la API (action=parse): trae el HTML renderizado
de la página y el `revid` de la revisión, que queda en el manifest. Así cada
número del agregador es trazable a una revisión concreta de la página.

Uso:
    python -m src.etl.extract.wikipedia_extractor --ano 2018 2022 2026
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import yaml

from src.etl.extract.versionado import DescargaInvalida, descargar_versionado, ultima_version_en

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "fuentes.yaml"
RAW_DIR = ROOT / "data" / "raw" / "encuestas_wikipedia"

MINIMO_TABLAS = 5  # cada página tiene 1ª y 2ª vuelta en varios períodos


def _config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["wikipedia"]


def _validar(path: Path) -> dict:
    try:
        parse = json.loads(path.read_text(encoding="utf-8"))["parse"]
    except (ValueError, KeyError) as e:
        raise DescargaInvalida(f"respuesta de la API con formato inesperado: {e}") from e
    tablas = parse["text"].count("<table")
    if tablas < MINIMO_TABLAS:
        raise DescargaInvalida(f"solo {tablas} tablas en la página")
    return {"revid": parse["revid"], "titulo": parse["title"], "tablas": tablas}


def ultima_version(ano: int) -> Path:
    return ultima_version_en(RAW_DIR / str(ano))


def descargar(ano: int) -> Path | None:
    cfg = _config()
    titulo = cfg["paginas_encuestas_presidenciales"][ano]
    url = cfg["api"] + "?" + urlencode({"action": "parse", "page": titulo, "prop": "text|revid",
                                        "format": "json", "formatversion": 2})
    # La API no manda Last-Modified: forzar=True evita el atajo por cabecera;
    # si el contenido es idéntico (mismo sha256) no se duplica igual.
    return descargar_versionado(url, RAW_DIR / str(ano), f"encuestas_presidenciales_{ano}.json",
                                meta={"dataset": "encuestas_wikipedia", "ano": ano}, validar=_validar,
                                forzar=True, headers={"User-Agent": cfg["user_agent"]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", nargs="+", type=int, required=True)
    args = parser.parse_args()
    for ano in args.ano:
        descargar(ano)


if __name__ == "__main__":
    main()
