"""
src/etl/extract/versionado.py

Descarga versionada a data/raw/ (principio: raw es inmutable).

Cada descarga va a <base>/<fecha_utc>/<archivo> con un manifest.json (url,
sha256, tamaño, fecha). Si el contenido es idéntico (mismo sha256) a la
última versión guardada, no se duplica. Si `validar` levanta DescargaInvalida,
el archivo se descarta y no llega a raw/.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)


class DescargaInvalida(Exception):
    """El archivo bajado no pasa la validación de completitud."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def ultima_version_en(base: Path) -> Path:
    """Ruta al archivo de la última descarga válida guardada en `base`."""
    manifests = sorted(base.glob("*/manifest.json")) if base.exists() else []
    if not manifests:
        raise FileNotFoundError(f"No hay descargas en {base}")
    manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    return manifests[-1].parent / manifest["archivo"]


def descargar_versionado(
    url: str,
    base: Path,
    nombre: str,
    meta: dict,
    validar: Callable[[Path], dict] | None = None,
    timeout: int = 120,
) -> Path | None:
    """Baja `url` a `base`. `validar(path)` devuelve metadata extra para el manifest."""
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
        extra = validar(tmp) if validar else {}
    except DescargaInvalida as e:
        tmp.unlink()
        log.error("Descarga descartada: %s", e)
        return None

    digest = sha256(tmp)
    try:
        previo = ultima_version_en(base)
        if sha256(previo) == digest:
            tmp.unlink()
            log.info("Sin cambios respecto de %s — no se duplica.", previo.parent.name)
            return previo
    except FileNotFoundError:
        pass

    ahora = datetime.now(timezone.utc)
    destino_dir = base / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    destino_dir.mkdir()
    destino = destino_dir / nombre
    tmp.rename(destino)

    manifest = {
        **meta,
        "url": url,
        "archivo": nombre,
        "sha256": digest,
        "bytes": destino.stat().st_size,
        "descargado_utc": ahora.isoformat(timespec="seconds"),
        "last_modified_fuente": last_modified,
        **extra,
    }
    (destino_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Guardado en %s (%.2f MB)", destino, manifest["bytes"] / 1e6)
    return destino
