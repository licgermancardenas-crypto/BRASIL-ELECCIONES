"""
src/etl/transform/run_pipeline.py

Orquestador del pipeline: extracción -> transformación -> resolución de
família -> carga. El plan (qué datasets, qué años) vive en
config/pipeline.yaml, no acá.

Comportamiento ante fallas:
  - Un paso requerido que falla CORTA el pipeline: no corre ningún paso
    posterior (preferible un dato faltante a uno corrupto propagado).
  - Un paso opcional que falla (ej. resultados 2026 todavía no publicados)
    se registra como "omitido" y se sigue.
  - Al final se imprime un resumen por fase y, si cortó, en qué fase, en qué
    paso y con qué error.

Cada corrida deja un registro en data/processed/_corridas/<fecha_utc>.json
(estado y duración de cada paso, versiones de raw usadas, outputs).

Uso:
    python -m src.etl.transform.run_pipeline
    python -m src.etl.transform.run_pipeline --sin-descarga      # usa lo que ya hay en raw/
    python -m src.etl.transform.run_pipeline --desde familia     # retoma desde una fase
    python -m src.etl.transform.run_pipeline --permitir-propuesta  # solo exploración
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PIPELINE = ROOT / "config" / "pipeline.yaml"
CORRIDAS_DIR = ROOT / "data" / "processed" / "_corridas"

FASES = ["extraccion", "transformacion", "familia", "carga"]


class PasoOmitido(Exception):
    """El paso no aplica en esta corrida (ej. no hay datos de ese año todavía)."""


@dataclass
class Paso:
    fase: str
    nombre: str
    funcion: Callable[[], object]
    requerido: bool = True
    estado: str = "pendiente"
    segundos: float = 0.0
    detalle: str = ""
    salidas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- pasos

def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _paso_descarga_tse(dataset: str, ano: int, requerido: bool, sin_descarga: bool) -> Callable:
    def correr():
        from src.etl.extract.tse_extractor import descargar_dataset, ultima_version
        if sin_descarga:
            return [ultima_version(dataset, ano)]
        destino = descargar_dataset(dataset, ano)
        if destino is None:
            msg = f"{dataset} {ano}: la fuente no publicó datos válidos todavía"
            if requerido:
                raise RuntimeError(msg)
            raise PasoOmitido(msg)
        return [destino]

    def correr_opcional():
        try:
            return correr()
        except FileNotFoundError as e:
            raise PasoOmitido(str(e)) from None

    return correr if requerido else correr_opcional


def _paso_descarga_referencia(fuente: str, sin_descarga: bool) -> Callable:
    def correr():
        from src.etl.extract.referencia_extractor import descargar, ultima_version
        if sin_descarga:
            return [ultima_version(fuente)]
        destino = descargar(fuente)
        if destino is None:
            raise RuntimeError(f"{fuente}: descarga inválida")
        return [destino]
    return correr


def _hay_resultados(ano: int) -> bool:
    from src.etl.extract.tse_extractor import ultima_version
    try:
        ultima_version("resultados", ano)
        ultima_version("resultados_partido", ano)
        return True
    except FileNotFoundError:
        return False


def _paso_correspondencia() -> Callable:
    def correr():
        from src.etl.transform import correspondencia_municipios as cm
        cm.main()
        return [cm.SALIDA_CSV, cm.SALIDA_META]
    return correr


def _paso_gobernadores(ano: int) -> Callable:
    def correr():
        if not _hay_resultados(ano):
            raise PasoOmitido(f"sin resultados {ano} descargados")
        from src.etl.transform import gobernadores_por_uf as g
        g.main(ano)
        return [g.PROCESSED_DIR / f"gobernadores_por_uf_{ano}.parquet",
                g.PROCESSED_DIR / f"gobernadores_balotaje_pendiente_{ano}.csv"]
    return correr


def _paso_familia(ano: int, permitir_propuesta: bool) -> Callable:
    def correr():
        if not _hay_resultados(ano):
            raise PasoOmitido(f"sin resultados {ano} descargados")
        from src.etl.transform import camara_por_familia
        return camara_por_familia.main(ano, permitir_propuesta)
    return correr


def _paso_serie_historica(anos: list[int], ano_referencia: int) -> Callable:
    def correr():
        from src.etl.load import serie_historica
        return serie_historica.main(anos, ano_referencia)
    return correr


def _paso_inventario() -> Callable:
    def correr():
        from src.etl import inventario
        inventario.main()
        return [inventario.SALIDA]
    return correr


def armar_plan(cfg: dict, sin_descarga: bool, permitir_propuesta: bool) -> list[Paso]:
    pasos: list[Paso] = []

    for item in cfg["extraccion"]["tse"]:
        for ano in item.get("anos", []):
            pasos.append(Paso("extraccion", f"tse {item['dataset']} {ano}",
                              _paso_descarga_tse(item["dataset"], ano, True, sin_descarga)))
        for ano in item.get("anos_opcionales", []):
            pasos.append(Paso("extraccion", f"tse {item['dataset']} {ano} (opcional)",
                              _paso_descarga_tse(item["dataset"], ano, False, sin_descarga),
                              requerido=False))
    for fuente in cfg["extraccion"].get("referencia", []):
        pasos.append(Paso("extraccion", f"referencia {fuente}",
                          _paso_descarga_referencia(fuente, sin_descarga)))

    tr = cfg["transformacion"]
    if tr.get("correspondencia_municipios"):
        pasos.append(Paso("transformacion", "correspondencia TSE-IBGE", _paso_correspondencia()))
    for ano in tr.get("gobernadores_anos", []):
        pasos.append(Paso("transformacion", f"gobernadores {ano}", _paso_gobernadores(ano)))

    fam = cfg["familia"]
    permitir = permitir_propuesta or fam.get("permitir_propuesta", False)
    for ano in fam["anos"]:
        pasos.append(Paso("familia", f"câmara por família {ano}", _paso_familia(ano, permitir)))

    pasos.append(Paso("carga", "serie histórica y volatilidad", _paso_serie_historica(fam["anos"], fam["ano_referencia_composicion"])))
    pasos.append(Paso("carga", "inventario de datos", _paso_inventario()))
    return pasos


# ---------------------------------------------------------------- ejecución

def ejecutar(pasos: list[Paso], desde: str | None = None) -> Paso | None:
    """Corre los pasos en orden. Devuelve el paso que cortó el pipeline, o None."""
    inicio_idx = FASES.index(desde) if desde else 0
    fase_actual = None
    for paso in pasos:
        if FASES.index(paso.fase) < inicio_idx:
            paso.estado = "salteado"
            continue
        if paso.fase != fase_actual:
            fase_actual = paso.fase
            log.info("═══ FASE %s ═══", paso.fase.upper())
        t0 = time.perf_counter()
        try:
            salidas = paso.funcion() or []
            paso.salidas = [_rel(Path(s)) for s in salidas]
            paso.estado = "ok"
        except PasoOmitido as e:
            paso.estado = "omitido"
            paso.detalle = str(e)
            log.warning("[%s] %s — omitido: %s", paso.fase, paso.nombre, e)
        except Exception as e:  # noqa: BLE001 — el orquestador registra cualquier falla
            paso.segundos = time.perf_counter() - t0
            paso.detalle = f"{type(e).__name__}: {e}"
            if paso.requerido:
                paso.estado = "FALLÓ"
                log.error("[%s] %s — FALLÓ: %s\n%s", paso.fase, paso.nombre, paso.detalle,
                          traceback.format_exc())
                return paso
            paso.estado = "omitido"
            log.warning("[%s] %s (opcional) — falló, se sigue: %s", paso.fase, paso.nombre, paso.detalle)
        paso.segundos = time.perf_counter() - t0
        if paso.estado == "ok":
            log.info("[%s] %s — ok (%.1f s)", paso.fase, paso.nombre, paso.segundos)
    return None


def resumen(pasos: list[Paso], corte: Paso | None) -> str:
    lineas = ["", "RESUMEN DEL PIPELINE"]
    for fase in FASES:
        de_fase = [p for p in pasos if p.fase == fase]
        conteo = {}
        for p in de_fase:
            conteo[p.estado] = conteo.get(p.estado, 0) + 1
        lineas.append(f"  {fase:<15} " + ", ".join(f"{k}: {v}" for k, v in sorted(conteo.items())))
        for p in de_fase:
            if p.estado in ("omitido", "FALLÓ"):
                lineas.append(f"      - {p.nombre}: {p.estado} — {p.detalle}")
    if corte:
        lineas.append(f"  >>> CORTADO en fase '{corte.fase}', paso '{corte.nombre}': {corte.detalle}")
        lineas.append("  >>> Los pasos posteriores no corrieron; data/processed/ no se tocó más allá de este punto.")
    else:
        lineas.append("  >>> Pipeline completo.")
    return "\n".join(lineas)


def registrar(pasos: list[Paso], corte: Paso | None, args: argparse.Namespace) -> Path:
    CORRIDAS_DIR.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    registro = {
        "inicio_utc": ahora.isoformat(timespec="seconds"),
        "argumentos": vars(args),
        "resultado": "cortado" if corte else "completo",
        "corte": {"fase": corte.fase, "paso": corte.nombre, "error": corte.detalle} if corte else None,
        "pasos": [{"fase": p.fase, "paso": p.nombre, "estado": p.estado,
                   "segundos": round(p.segundos, 2), "detalle": p.detalle, "salidas": p.salidas}
                  for p in pasos],
    }
    path = CORRIDAS_DIR / f"{ahora:%Y-%m-%dT%H%M%SZ}.json"
    path.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline ATLAS Brasil 2026")
    parser.add_argument("--sin-descarga", action="store_true",
                        help="no consultar fuentes; usar la última versión de data/raw/")
    parser.add_argument("--desde", choices=FASES, help="retomar desde esta fase")
    parser.add_argument("--permitir-propuesta", action="store_true",
                        help="aceptar clasificaciones de família no validadas (solo exploración)")
    args = parser.parse_args(argv)

    with open(CONFIG_PIPELINE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    pasos = armar_plan(cfg, args.sin_descarga, args.permitir_propuesta)
    corte = ejecutar(pasos, args.desde)
    log.info(resumen(pasos, corte))
    log.info("Registro de la corrida: %s", _rel(registrar(pasos, corte, args)))
    return 1 if corte else 0


if __name__ == "__main__":
    sys.exit(main())
