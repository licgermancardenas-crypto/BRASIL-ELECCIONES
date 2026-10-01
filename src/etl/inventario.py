"""
src/etl/inventario.py

Genera docs/inventario_datos.md a partir de los manifest.json de data/raw/.
El inventario nunca se escribe a mano: cada cifra sale de lo que realmente
está descargado (versión, tamaño, sha256, fecha de descarga).

Uso:
    python -m src.etl.inventario
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SALIDA = ROOT / "docs" / "inventario_datos.md"


def recolectar() -> list[dict]:
    filas = []
    for m in sorted(RAW_DIR.rglob("manifest.json")):
        d = json.loads(m.read_text(encoding="utf-8"))
        d["version"] = m.parent.name
        d["ruta"] = m.parent.relative_to(ROOT).as_posix()
        filas.append(d)
    return filas


def escribir(filas: list[dict]) -> str:
    lineas = [
        "# Inventario de datos crudos",
        "",
        f"Generado automáticamente por `python -m src.etl.inventario` "
        f"el {datetime.now():%Y-%m-%d %H:%M}. No editar a mano.",
        "",
        "`data/raw/` no se versiona en git (pesa GB): este archivo es el registro de "
        "qué versión de cada fuente se usó. Para reproducir, re-descargar y comparar sha256.",
        "",
        "| Dataset | Año | Versión (UTC) | MB | CSV | sha256 (12) | Fuente |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for f in sorted(filas, key=lambda x: (x["dataset"], x["ano"], x["version"])):
        lineas.append(
            f"| {f['dataset']} | {f['ano']} | {f['version']} | {f['bytes'] / 1e6:.1f} | "
            f"{len(f.get('archivos_internos', []))} | `{f['sha256'][:12]}` | {f['url']} |"
        )
    total = sum(f["bytes"] for f in filas) / 1e9
    lineas += ["", f"**Total:** {len(filas)} archivos, {total:.2f} GB.", ""]
    return "\n".join(lineas)


def main() -> None:
    SALIDA.write_text(escribir(recolectar()), encoding="utf-8")
    print(f"Escrito {SALIDA}")


if __name__ == "__main__":
    main()
