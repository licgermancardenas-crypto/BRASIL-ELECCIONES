"""
src/etl/extract/tse_extractor.py

Descarga datasets crudos del CDN de Dados Abertos do TSE y los deja en
data/raw/tse/<carpeta>/<año>/<fecha_descarga>/ sin transformar.

Principio: raw es inmutable. Cada descarga va a una carpeta nueva fechada,
con un manifest.json (url, sha256, tamaño, fecha). Si el archivo es idéntico
(mismo sha256) a la última versión ya guardada, no se duplica.

Validación de completitud (Fase 1): si lo descargado no es un zip válido con
al menos un CSV adentro, se descarta y no llega a raw/ (ej.: el TSE publica
placeholders de 1 byte para datasets todavía no liberados).

Uso:
    python -m src.etl.extract.tse_extractor --dataset resultados --ano 2022
    python -m src.etl.extract.tse_extractor --dataset encuestas_registradas --ano 2018 2022 2026
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
RAW_DIR = ROOT / "data" / "raw" / "tse"


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def datasets_disponibles() -> list[str]:
    return list(cargar_config()["tse"]["cdn"]["datasets"])


def _validar_zip(path: Path) -> dict:
    if not zipfile.is_zipfile(path):
        raise DescargaInvalida(f"{path.name} no es un zip válido ({path.stat().st_size} bytes)")
    with zipfile.ZipFile(path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
        if not csvs:
            raise DescargaInvalida(f"{path.name} no contiene CSV")
        # El TSE publica zips "cascarón" (solo encabezados) para elecciones
        # que todavía no ocurrieron: al menos un CSV tiene que tener datos.
        con_datos = False
        for n in csvs:
            with z.open(n) as f:
                if len(f.readlines(1 << 16)) > 1:
                    con_datos = True
                    break
        if not con_datos:
            raise DescargaInvalida(f"{path.name} solo trae encabezados, sin filas de datos")
    return {"archivos_internos": csvs}


def carpeta_dataset(dataset: str, ano: int) -> Path:
    carpeta = cargar_config()["tse"]["cdn"]["datasets"][dataset]["carpeta"]
    return RAW_DIR / carpeta / str(ano)


def ultima_version(dataset: str, ano: int) -> Path:
    """Ruta al zip de la última descarga válida de (dataset, año)."""
    try:
        return ultima_version_en(carpeta_dataset(dataset, ano))
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No hay descargas de {dataset} {ano} — correr antes "
            f"`python -m src.etl.extract.tse_extractor --dataset {dataset} --ano {ano}`"
        ) from None


def descargar_dataset(dataset: str, ano: int, timeout: int = 120) -> Path | None:
    cfg = cargar_config()["tse"]["cdn"]
    ruta = cfg["datasets"][dataset]["ruta"].format(ano=ano)
    return descargar_versionado(
        url=f"{cfg['base_url']}/{ruta}",
        base=carpeta_dataset(dataset, ano),
        nombre=Path(ruta).name,
        meta={"dataset": dataset, "ano": ano},
        validar=_validar_zip,
        timeout=timeout,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extractor de datos abertos do TSE (CDN)")
    parser.add_argument("--dataset", required=True, nargs="+", choices=datasets_disponibles())
    parser.add_argument("--ano", required=True, type=int, nargs="+")
    args = parser.parse_args()

    fallidos = []
    for dataset in args.dataset:
        for ano in args.ano:
            if descargar_dataset(dataset, ano) is None:
                fallidos.append(f"{dataset} {ano}")
    if fallidos:
        log.warning("No disponibles / inválidos: %s", ", ".join(fallidos))


if __name__ == "__main__":
    main()
