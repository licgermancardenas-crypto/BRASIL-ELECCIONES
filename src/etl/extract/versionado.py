"""
src/etl/extract/versionado.py

Descarga versionada a data/raw/ (principio: raw es inmutable).

Cada descarga va a <base>/<fecha_utc>/<archivo> con un manifest.json (url,
sha256, tamaño, fecha). Si el contenido es idéntico (mismo sha256) a la
última versión guardada, no se duplica. Antes de descargar se consulta la
cabecera (HEAD): si Last-Modified y tamaño coinciden con la última versión,
ni siquiera se baja (los resultados del TSE pesan cientos de MB).
Si `validar` levanta DescargaInvalida, el archivo se descarta y no llega a raw/.
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


def _sin_cambios_remotos(url: str, base: Path, timeout: int) -> Path | None:
    """Última versión local si la cabecera remota indica que no cambió; si no, None."""
    try:
        previo = ultima_version_en(base)
    except FileNotFoundError:
        return None
    manifest = json.loads((previo.parent / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("last_modified_fuente"):
        return None
    try:
        cab = requests.head(url, timeout=timeout, allow_redirects=True).headers
    except requests.RequestException:
        return None
    if (cab.get("Last-Modified") == manifest["last_modified_fuente"]
            and str(manifest["bytes"]) == cab.get("Content-Length")):
        return previo
    return None


def descargar_versionado(
    url: str,
    base: Path,
    nombre: str,
    meta: dict,
    validar: Callable[[Path], dict] | None = None,
    timeout: int = 120,
    forzar: bool = False,
    headers: dict | None = None,
) -> Path | None:
    """Baja `url` a `base`. `validar(path)` devuelve metadata extra para el manifest.
    Con forzar=True se descarga aunque la cabecera remota no indique cambios."""
    if not forzar:
        previo = _sin_cambios_remotos(url, base, timeout)
        if previo is not None:
            log.info("Sin cambios en la fuente (Last-Modified y tamaño iguales): %s", previo.parent.name)
            return previo

    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{nombre}.part"

    log.info("Descargando %s", url)
    with requests.get(url, stream=True, timeout=timeout, headers=headers) as resp:
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
