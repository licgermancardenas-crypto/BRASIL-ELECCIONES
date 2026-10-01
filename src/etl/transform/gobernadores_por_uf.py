"""
src/etl/transform/gobernadores_por_uf.py

Filtra y estructura el resultado de la elección a gobernador a partir del
dataset general `resultados` del TSE (mismo archivo que usa presidencial/
legislativo — se filtra por DS_CARGO = 'GOVERNADOR').

Particularidad clave del cargo de gobernador en Brasil, distinta de la
presidencial: **el balotaje es por estado, no nacional**. Un estado puede
definirse en primera vuelta (4/10) mientras otro va a segunda vuelta
(25/10) — son 27 procesos independientes, no uno solo. El pipeline tiene
que resolver esto estado por estado, nunca asumir una fecha única de cierre
para todo el país.

Input:  data/raw/tse/resultados/{ano}/resultados_{ano}.zip
Output: data/processed/electoral/gobernadores_por_uf.parquet
        data/processed/electoral/gobernadores_balotaje_pendiente.csv
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "tse" / "resultados"
PROCESSED_DIR = Path(__file__).resolve().parents[3] / "data" / "processed" / "electoral"

UMBRAL_PRIMERA_VUELTA = 0.50  # >50% de votos válidos evita balotaje en ese estado


def cargar_resultados_crudos(ano: int) -> pd.DataFrame:
    """Lee el zip de resultados del TSE y devuelve un DataFrame crudo."""
    zip_path = RAW_DIR / str(ano) / f"resultados_{ano}.zip"
    if not zip_path.exists():
        raise FileNotFoundError(
            f"No existe {zip_path} — correr antes "
            f"`python -m src.etl.extract.tse_extractor --dataset resultados --ano {ano}`"
        )

    with zipfile.ZipFile(zip_path) as z:
        # El TSE distribuye un CSV por UF dentro del zip; se concatenan todos.
        csvs = [n for n in z.namelist() if n.endswith(".csv")]
        frames = [
            pd.read_csv(z.open(n), sep=";", encoding="latin-1", low_memory=False)
            for n in csvs
        ]
    return pd.concat(frames, ignore_index=True)


def filtrar_gobernador(df_crudo: pd.DataFrame) -> pd.DataFrame:
    """Se queda solo con el cargo de gobernador y columnas relevantes."""
    df = df_crudo[df_crudo["DS_CARGO"].str.upper() == "GOVERNADOR"].copy()

    columnas = {
        "SG_UF": "uf",
        "NR_TURNO": "turno",
        "NM_CANDIDATO": "candidato",
        "SG_PARTIDO": "partido",
        "QT_VOTOS_NOMINAIS_VALIDOS": "votos",
        "NM_MUNICIPIO": "municipio",
    }
    df = df.rename(columns={k: v for k, v in columnas.items() if k in df.columns})
    return df[[c for c in columnas.values() if c in df.columns]]


def consolidar_por_uf(df_gob: pd.DataFrame, turno: int = 1) -> pd.DataFrame:
    """
    Agrega votos por candidato a nivel UF (sumando todos los municipios)
    para un turno dado, y calcula el porcentaje sobre votos válidos del estado.
    """
    df_turno = df_gob[df_gob["turno"] == turno]
    agregado = (
        df_turno.groupby(["uf", "candidato", "partido"])["votos"]
        .sum()
        .reset_index()
    )
    total_uf = agregado.groupby("uf")["votos"].transform("sum")
    agregado["porcentaje"] = agregado["votos"] / total_uf
    return agregado.sort_values(["uf", "porcentaje"], ascending=[True, False])


def detectar_balotaje_pendiente(df_consolidado_t1: pd.DataFrame) -> pd.DataFrame:
    """
    Por cada UF, si el candidato más votado en primera vuelta no superó el
    umbral, esa UF va a balotaje. Devuelve la lista de UFs en esa condición
    con el líder y el porcentaje faltante para evitarlo.
    """
    lider_por_uf = df_consolidado_t1.loc[
        df_consolidado_t1.groupby("uf")["porcentaje"].idxmax()
    ]
    pendientes = lider_por_uf[lider_por_uf["porcentaje"] < UMBRAL_PRIMERA_VUELTA].copy()
    pendientes["margen_faltante_pp"] = (UMBRAL_PRIMERA_VUELTA - pendientes["porcentaje"]) * 100
    return pendientes[["uf", "candidato", "partido", "porcentaje", "margen_faltante_pp"]]


def main(ano: int = 2026) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    crudo = cargar_resultados_crudos(ano)
    gobernadores = filtrar_gobernador(crudo)

    consolidado_t1 = consolidar_por_uf(gobernadores, turno=1)
    consolidado_t1.to_parquet(PROCESSED_DIR / "gobernadores_por_uf.parquet")

    balotaje = detectar_balotaje_pendiente(consolidado_t1)
    balotaje.to_csv(PROCESSED_DIR / "gobernadores_balotaje_pendiente.csv", index=False)

    log.info("%d de 27 UFs van a balotaje de gobernador el 25/10:", len(balotaje))
    log.info("\n%s", balotaje.to_string(index=False))


if __name__ == "__main__":
    main()
