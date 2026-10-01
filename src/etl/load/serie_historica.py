"""
src/etl/load/serie_historica.py

Fase 0 de la metodología: serie histórica de famílias por UF y su
volatilidad entre elecciones (insumo del ruido de la simulación Montecarlo).

Se calcula con dos composiciones de família, columna `composicion`:

  fija_<ref>  (la que usa el Montecarlo) — partidos FIJOS en su família: cada
              partido de cada elección se lleva a su sigla sucesora en el año
              de referencia (linaje de config/partidos.yaml: PSL->UNIÃO,
              PRP->PATRIOTA->PRD, ...) y se clasifica con la tabla de ese año.
              Así, un partido que cambia de família entre elecciones NO
              cuenta como movimiento de votos; solo se mide votos que se
              movieron entre partidos que hoy están en famílias distintas.
  del_ano     cada elección con su propia clasificación (la que estaba
              vigente ese año). Se guarda solo como comparación: mezcla
              movimiento de votantes con reclasificación de partidos.

Volatilidad de una família = desvío típico, entre UFs, del cambio de % de
votos de una elección a la siguiente. Con dos elecciones (2018, 2022) hay UNA
sola diferencia por UF: es una primera aproximación y queda advertido en el
output.

Salidas (data/processed/electoral/):
  serie_historica_familias.parquet   composicion × uf × família × año, con delta_pp
  volatilidad_familias.parquet       composicion × família
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.models.bloques.resolver_familia import familia_composicion_fija, tabla_ano

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = ROOT / "data" / "processed" / "electoral"


def _cargar(prefijo: str, anos: list[int]) -> pd.DataFrame:
    archivos = [PROCESSED_DIR / f"{prefijo}_{a}.parquet" for a in anos]
    disponibles = [a for a in archivos if a.exists()]
    if len(disponibles) < 2:
        raise FileNotFoundError(f"Hacen falta al menos dos años de {prefijo}; hay {len(disponibles)}")
    return pd.concat([pd.read_parquet(a) for a in disponibles], ignore_index=True)


def serie_composicion_del_ano(anos: list[int]) -> pd.DataFrame:
    serie = _cargar("camara_familia_uf", anos)
    return serie[["ano", "uf", "familia", "votos", "bancas", "pct_votos", "clasificacion_estado"]].assign(
        composicion="del_ano")


def serie_composicion_fija(anos: list[int], ano_referencia: int) -> pd.DataFrame:
    estado_ref, _ = tabla_ano(ano_referencia)
    partidos = _cargar("camara_partido_uf", anos)
    mapa = {(p, a): familia_composicion_fija(p, a, ano_referencia)
            for p, a in partidos[["partido", "ano"]].drop_duplicates().itertuples(index=False)}
    partidos["familia"] = [mapa[(p, a)] for p, a in zip(partidos["partido"], partidos["ano"])]
    serie = partidos.groupby(["ano", "uf", "familia"], as_index=False)[["votos", "bancas"]].sum()
    serie["pct_votos"] = serie["votos"] / serie.groupby(["ano", "uf"])["votos"].transform("sum")
    serie["clasificacion_estado"] = estado_ref
    return serie.assign(composicion=f"fija_{ano_referencia}")


def _completar_y_deltas(serie: pd.DataFrame) -> pd.DataFrame:
    """Rellena con 0 las famílias ausentes en una UF/año (si no, el delta se pierde) y calcula delta_pp."""
    claves = ["composicion", "uf", "familia"]
    completa = (serie.set_index([*claves, "ano"])
                .reindex(pd.MultiIndex.from_product(
                    [serie["composicion"].unique(), serie["uf"].unique(),
                     serie["familia"].unique(), sorted(serie["ano"].unique())],
                    names=[*claves, "ano"]))
                .reset_index())
    completa[["votos", "bancas", "pct_votos"]] = completa[["votos", "bancas", "pct_votos"]].fillna(0)
    completa["bancas"] = completa["bancas"].astype(int)
    completa["clasificacion_estado"] = completa.groupby("composicion")["clasificacion_estado"].transform(
        lambda s: s.dropna().iloc[0])
    completa = completa.sort_values([*claves, "ano"])
    completa["delta_pp"] = completa.groupby(claves)["pct_votos"].diff() * 100
    return completa


def construir(anos: list[int], ano_referencia: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    serie = _completar_y_deltas(pd.concat(
        [serie_composicion_fija(anos, ano_referencia), serie_composicion_del_ano(anos)],
        ignore_index=True))

    cambios = serie.dropna(subset=["delta_pp"])
    vol = (cambios.groupby(["composicion", "familia"])["delta_pp"]
           .agg(volatilidad_pp="std", cambio_medio_pp="mean", ufs="count").reset_index())
    vol["elecciones_comparadas"] = serie["ano"].nunique()
    vol["clasificacion_estado"] = vol["composicion"].map(
        serie.groupby("composicion")["clasificacion_estado"].first())
    vol["advertencia"] = (
        "Una sola diferencia entre elecciones por UF: aproximación inicial."
        if serie["ano"].nunique() == 2 else ""
    )
    return serie, vol


def main(anos: list[int], ano_referencia: int) -> list[Path]:
    serie, vol = construir(anos, ano_referencia)
    salidas = [PROCESSED_DIR / "serie_historica_familias.parquet",
               PROCESSED_DIR / "volatilidad_familias.parquet"]
    serie.to_parquet(salidas[0], index=False)
    vol.to_parquet(salidas[1], index=False)
    tabla = vol.pivot(index="familia", columns="composicion", values="volatilidad_pp").round(2)
    log.info("Volatilidad por família (pp, desvío entre UFs del cambio 2018→2022):\n%s",
             tabla.sort_values(f"fija_{ano_referencia}", ascending=False).to_string())
    return salidas
