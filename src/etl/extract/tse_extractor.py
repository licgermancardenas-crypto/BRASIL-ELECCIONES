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
import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "fuentes.yaml"
RAW_DIR = ROOT / "data" / "raw" / "tse"


class DescargaInvalida(Exception):
    """El archivo bajado no pasa la validación de completitud."""


def cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def datasets_disponibles() -> list[str]:
    return list(cargar_config()["tse"]["cdn"]["datasets"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _validar_zip(path: Path) -> list[str]:
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
    return csvs


def carpeta_dataset(dataset: str, ano: int) -> Path:
    carpeta = cargar_config()["tse"]["cdn"]["datasets"][dataset]["carpeta"]
    return RAW_DIR / carpeta / str(ano)


def ultima_version(dataset: str, ano: int) -> Path:
    """Ruta al zip de la última descarga válida de (dataset, año)."""
    base = carpeta_dataset(dataset, ano)
    versiones = sorted(p for p in base.glob("*/manifest.json")) if base.exists() else []
    if not versiones:
        raise FileNotFoundError(
            f"No hay descargas de {dataset} {ano} en {base} — correr antes "
            f"`python -m src.etl.extract.tse_extractor --dataset {dataset} --ano {ano}`"
        )
    manifest = json.loads(versiones[-1].read_text(encoding="utf-8"))
    return versiones[-1].parent / manifest["archivo"]


def descargar_dataset(dataset: str, ano: int, timeout: int = 120) -> Path | None:
    cfg = cargar_config()["tse"]["cdn"]
    ruta = cfg["datasets"][dataset]["ruta"].format(ano=ano)
    url = f"{cfg['base_url']}/{ruta}"
    nombre = Path(ruta).name

    base = carpeta_dataset(dataset, ano)
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{nombre}.part"

    log.info("Descargando %s", url)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        last_modified = resp.headers.get("Last-Modified")
        with open(tmp, "wb") as f:
            for bloque in resp.iter_content(chunk_size=1 << 20):
                f.write(bloque)

    try:
        csvs = _validar_zip(tmp)
    except DescargaInvalida as e:
        tmp.unlink()
        log.error("Descarga descartada: %s", e)
        return None

    sha = _sha256(tmp)
    try:
        previo = ultima_version(dataset, ano)
        if _sha256(previo) == sha:
            tmp.unlink()
            log.info("Sin cambios respecto de %s — no se duplica.", previo.parent.name)
            return previo
    except FileNotFoundError:
        pass

    ahora = datetime.now(timezone.utc)
    version = ahora.strftime("%Y-%m-%dT%H%M%SZ")
    destino_dir = base / version
    destino_dir.mkdir()
    destino = destino_dir / nombre
    tmp.rename(destino)

    manifest = {
        "dataset": dataset,
        "ano": ano,
        "url": url,
        "archivo": nombre,
        "sha256": sha,
        "bytes": destino.stat().st_size,
        "descargado_utc": ahora.isoformat(timespec="seconds"),
        "last_modified_fuente": last_modified,
        "archivos_internos": csvs,
    }
    (destino_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Guardado en %s (%.1f MB, %d CSV)", destino, manifest["bytes"] / 1e6, len(csvs))
    return destino


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
