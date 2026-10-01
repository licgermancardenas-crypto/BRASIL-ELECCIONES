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

Input:  data/raw/tse/resultados/{ano}/<version>/votacao_candidato_munzona_{ano}.zip
Output: data/processed/electoral/gobernadores_por_uf_{ano}.parquet
        data/processed/electoral/gobernadores_balotaje_pendiente_{ano}.csv
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.etl.extract.tse_extractor import ultima_version
from src.etl.transform.lector_tse import leer_zip_tse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[3] / "data" / "processed" / "electoral"

UMBRAL_PRIMERA_VUELTA = 0.50  # >50% de votos válidos evita balotaje en ese estado


COLUMNAS_CRUDAS = [
    "SG_UF", "NR_TURNO", "DS_CARGO", "NM_URNA_CANDIDATO", "SG_PARTIDO",
    "QT_VOTOS_NOMINAIS_VALIDOS", "NM_MUNICIPIO", "CD_MUNICIPIO",
]


def cargar_resultados_crudos(ano: int) -> pd.DataFrame:
    """Lee la última descarga de resultados del TSE, solo filas de gobernador."""
    return leer_zip_tse(
        ultima_version("resultados", ano),
        columnas=COLUMNAS_CRUDAS,
        # El zip de un año puede traer elecciones extraordinarias posteriores
        # (ej. el de 2022 incluye la suplementaria de gobernador de RR del
        # 21/06/2026): se excluyen siempre.
        filtro={"DS_CARGO": {"GOVERNADOR"}, "NM_TIPO_ELEICAO": {"Eleição Ordinária"}},
    )


def filtrar_gobernador(df_crudo: pd.DataFrame) -> pd.DataFrame:
    """Se queda solo con el cargo de gobernador y columnas relevantes."""
    df = df_crudo[df_crudo["DS_CARGO"].str.upper() == "GOVERNADOR"].copy()

    columnas = {
        "SG_UF": "uf",
        "NR_TURNO": "turno",
        "NM_URNA_CANDIDATO": "candidato",
        "SG_PARTIDO": "partido",
        # Válidos: excluye votos a candidaturas anuladas/sub judice
        "QT_VOTOS_NOMINAIS_VALIDOS": "votos",
        "NM_MUNICIPIO": "municipio",
    }
    df = df.rename(columns={k: v for k, v in columnas.items() if k in df.columns})
    df = df[[c for c in dict.fromkeys(columnas.values()) if c in df.columns]]
    df["turno"] = pd.to_numeric(df["turno"])
    df["votos"] = pd.to_numeric(df["votos"]).fillna(0)
    return df


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
    consolidado_t1.to_parquet(PROCESSED_DIR / f"gobernadores_por_uf_{ano}.parquet")

    balotaje = detectar_balotaje_pendiente(consolidado_t1)
    balotaje.to_csv(PROCESSED_DIR / f"gobernadores_balotaje_pendiente_{ano}.csv", index=False)

    log.info("%d: %d de 27 UFs van a balotaje de gobernador:", ano, len(balotaje))
    log.info("\n%s", balotaje.to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, default=2026)
    main(parser.parse_args().ano)
