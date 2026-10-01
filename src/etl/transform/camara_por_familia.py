"""
src/etl/transform/camara_por_familia.py

Resultado de Câmara dos Deputados agregado por família política, para un
año de elección. Es la fase "resolución de família" del pipeline: el
partido se resuelve contra config/familias_partidarias.yaml PARA ESE AÑO
(nunca se hardcodea la família en el dataset).

Votos: votacao_partido_munzona, elección ordinaria, cargo Deputado Federal.
  votos del partido = QT_VOTOS_NOMINAIS_VALIDOS (a sus candidatos)
                    + QT_TOTAL_VOTOS_LEG_VALIDOS (de legenda + nominales convertidos)
  OJO: QT_TOTAL_VOTOS_LEG_VALIDOS solo NO es el total del partido (en 2022
  son 4,3 M de 109,3 M).
Bancas: consulta_cand, candidatos con DS_SIT_TOT_TURNO "ELEITO*".

Salidas (data/processed/electoral/):
  camara_familia_municipio_{ano}.parquet  votos por município (código TSE e IBGE) × família
  camara_familia_uf_{ano}.parquet         votos, % y bancas por UF × família
  camara_partido_uf_{ano}.parquet         votos y bancas por UF × partido (con su família
                                          del año); insumo de la volatilidad con
                                          composición fija (src/etl/load/serie_historica.py)

Cada fila lleva `clasificacion_estado` (vigente/propuesta) para que nunca se
confunda un output exploratorio con uno validado.

Uso:
    python -m src.etl.transform.camara_por_familia --ano 2022 [--permitir-propuesta]
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.etl.extract.tse_extractor import ultima_version
from src.etl.transform.correspondencia_municipios import agregar_codigo_ibge
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import asignar_familia, normalizar_sigla, tabla_ano

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = ROOT / "data" / "processed" / "electoral"

FILTRO_CAMARA = {"NM_TIPO_ELEICAO": {"Eleição Ordinária"}, "DS_CARGO": {"DEPUTADO FEDERAL"}}
BANCAS_CAMARA = 513


def votos_partido_municipio(ano: int) -> pd.DataFrame:
    """Votos válidos a Câmara por município (código TSE e IBGE) y partido (sigla normalizada)."""
    crudo = leer_zip_tse(
        ultima_version("resultados_partido", ano),
        columnas=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "SG_PARTIDO",
                  "QT_VOTOS_NOMINAIS_VALIDOS", "QT_TOTAL_VOTOS_LEG_VALIDOS"],
        filtro=FILTRO_CAMARA,
    )
    crudo = crudo[crudo["SG_UF"] != "ZZ"]  # Câmara no tiene voto en el exterior
    crudo["votos"] = (pd.to_numeric(crudo["QT_VOTOS_NOMINAIS_VALIDOS"]).fillna(0)
                      + pd.to_numeric(crudo["QT_TOTAL_VOTOS_LEG_VALIDOS"]).fillna(0))
    crudo["SG_PARTIDO"] = crudo["SG_PARTIDO"].map(normalizar_sigla)
    df = (crudo.groupby(["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "SG_PARTIDO"], as_index=False)["votos"].sum()
          .rename(columns={"SG_UF": "uf", "CD_MUNICIPIO": "codigo_tse", "NM_MUNICIPIO": "municipio",
                           "SG_PARTIDO": "partido"}))
    df = agregar_codigo_ibge(df, col_tse="codigo_tse")
    df["codigo_tse"] = df["codigo_tse"].str.zfill(5)
    return df


def bancas_partido_uf(ano: int) -> pd.DataFrame:
    cand = leer_zip_tse(
        ultima_version("candidatos", ano),
        columnas=["SG_UF", "SG_PARTIDO", "DS_SIT_TOT_TURNO"],
        filtro=FILTRO_CAMARA,
    )
    electos = cand[cand["DS_SIT_TOT_TURNO"].str.upper().str.startswith("ELEITO", na=False)]
    electos = electos.assign(partido=electos["SG_PARTIDO"].map(normalizar_sigla))
    return electos.rename(columns={"SG_UF": "uf"}).groupby(["uf", "partido"]).size().rename("bancas").reset_index()


def construir(ano: int, permitir_propuesta: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (família × município, família × UF, partido × UF)."""
    estado, _ = tabla_ano(ano)
    vpm = votos_partido_municipio(ano)

    partido_uf = vpm.groupby(["uf", "partido"], as_index=False)["votos"].sum()
    partido_uf = partido_uf.merge(bancas_partido_uf(ano), on=["uf", "partido"], how="outer")
    partido_uf["votos"] = partido_uf["votos"].fillna(0)
    partido_uf["bancas"] = partido_uf["bancas"].fillna(0).astype(int)
    total_bancas = partido_uf["bancas"].sum()
    if total_bancas and total_bancas != BANCAS_CAMARA:
        raise ValueError(f"{ano}: {total_bancas} bancas electas, se esperaban {BANCAS_CAMARA}")
    partido_uf = asignar_familia(partido_uf, ano, permitir_propuesta=permitir_propuesta)
    partido_uf["ano"] = ano

    mun = asignar_familia(vpm, ano, permitir_propuesta=permitir_propuesta)
    mun = (mun.groupby(["uf", "codigo_tse", "codigo_ibge", "municipio", "familia"], as_index=False)["votos"].sum()
           .assign(ano=ano))

    uf = partido_uf.groupby(["uf", "familia"], as_index=False)[["votos", "bancas"]].sum()
    uf["pct_votos"] = uf["votos"] / uf.groupby("uf")["votos"].transform("sum")
    uf["ano"] = ano

    for df in (mun, uf, partido_uf):
        df["clasificacion_estado"] = estado
    return mun, uf, partido_uf


def main(ano: int, permitir_propuesta: bool = False) -> list[Path]:
    mun, uf, partido_uf = construir(ano, permitir_propuesta)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    salidas = [PROCESSED_DIR / f"camara_familia_municipio_{ano}.parquet",
               PROCESSED_DIR / f"camara_familia_uf_{ano}.parquet",
               PROCESSED_DIR / f"camara_partido_uf_{ano}.parquet"]
    mun.to_parquet(salidas[0], index=False)
    uf.to_parquet(salidas[1], index=False)
    partido_uf.to_parquet(salidas[2], index=False)
    nacional = uf.groupby("familia")[["votos", "bancas"]].sum()
    nacional["pct_votos"] = (nacional["votos"] / nacional["votos"].sum() * 100).round(2)
    log.info("Câmara %d por família (%s):\n%s", ano, uf["clasificacion_estado"].iat[0],
             nacional.sort_values("votos", ascending=False).to_string())
    return salidas


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, required=True)
    parser.add_argument("--permitir-propuesta", action="store_true",
                        help="usar una clasificación no validada (solo exploración)")
    a = parser.parse_args()
    main(a.ano, a.permitir_propuesta)
