"""
src/etl/load/serie_historica.py

Fase 0 de la metodología: serie histórica de famílias por UF y su
volatilidad entre elecciones (insumo del ruido de la simulación Montecarlo).

Une los camara_familia_uf_{ano}.parquet disponibles y calcula, por UF y
família, el cambio de % de votos respecto de la elección anterior.
La volatilidad de una família = desvío típico de esos cambios entre UFs
(cuánto se mueve esa família de una elección a la otra).

Advertencia que queda escrita en el output: con dos elecciones (2018, 2022)
hay UNA sola diferencia por UF; la volatilidad es una primera aproximación.

Salidas (data/processed/electoral/):
  serie_historica_familias.parquet   uf × família × año, con delta_pp
  volatilidad_familias.parquet       volatilidad por família (todas las UF juntas)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = ROOT / "data" / "processed" / "electoral"


def construir(anos: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    archivos = [PROCESSED_DIR / f"camara_familia_uf_{a}.parquet" for a in anos]
    disponibles = [a for a in archivos if a.exists()]
    if len(disponibles) < 2:
        raise FileNotFoundError(f"Hacen falta al menos dos años procesados; hay {len(disponibles)}")
    serie = pd.concat([pd.read_parquet(a) for a in disponibles], ignore_index=True)
    serie = serie.sort_values(["uf", "familia", "ano"])
    serie["delta_pp"] = serie.groupby(["uf", "familia"])["pct_votos"].diff() * 100

    cambios = serie.dropna(subset=["delta_pp"])
    vol = (cambios.groupby("familia")["delta_pp"]
           .agg(volatilidad_pp="std", cambio_medio_pp="mean", ufs="count").reset_index())
    vol["elecciones_comparadas"] = serie["ano"].nunique()
    vol["estados_clasificacion"] = "|".join(sorted(serie["clasificacion_estado"].unique()))
    vol["advertencia"] = (
        "Una sola diferencia entre elecciones por UF: aproximación inicial."
        if serie["ano"].nunique() == 2 else ""
    )
    return serie, vol


def main(anos: list[int]) -> list[Path]:
    serie, vol = construir(anos)
    salidas = [PROCESSED_DIR / "serie_historica_familias.parquet",
               PROCESSED_DIR / "volatilidad_familias.parquet"]
    serie.to_parquet(salidas[0], index=False)
    vol.to_parquet(salidas[1], index=False)
    log.info("Volatilidad por família (pp entre elecciones):\n%s",
             vol.sort_values("volatilidad_pp", ascending=False).round(2).to_string(index=False))
    return salidas
