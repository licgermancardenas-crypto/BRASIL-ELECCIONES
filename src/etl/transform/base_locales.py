"""
src/etl/transform/base_locales.py

Base por LOCAL DE VOTACIÓN (escuela donde votan varias secciones): es la
unidad del análisis mesa por mesa, como el circuito en CABA. Una sección
sola es demasiado chica (~330 electores) y no tiene ubicación propia; el
local sí (latitud/longitud del TSE) y agrupa ~5 secciones.

Para cada local y año: padrón, y por vuelta (_1, _2) votos de cada grupo de
config/modelo.yaml (seccion.grupos), otros, blanco_nulo, abstencion y
comparecencia. El local es el de la tabla de votos (donde efectivamente se
votó); las coordenadas, el promedio de las de sus secciones en el padrón.

Input:  data/processed/electoral/seccion/presidente_seccion_{ano}.parquet
        data/processed/electoral/seccion/padron_seccion_{ano}.parquet
Output: data/processed/electoral/seccion/locales_{ano}.parquet

Uso:
    python -m src.etl.transform.base_locales --ano 2018 2022
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from src.etl.transform.locales_votacion import salida as salida_padron
from src.etl.transform.votacion_seccion import SALIDA_DIR, salida as salida_votos
from src.models.montecarlo.proyeccion_bancas import ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CORRESPONDENCIA = ROOT / "src" / "etl" / "transform" / "correspondencia" / "municipios_tse_ibge.csv"
SECCION = ["uf", "cd_municipio", "nr_zona", "nr_secao"]
LOCAL = ["uf", "cd_municipio", "nr_zona", "nr_local"]


def salida(ano: int):
    return SALIDA_DIR / f"locales_{ano}.parquet"


def grupos_por_seccion(votos: pd.DataFrame, grupos: dict, blanco_nulo: list[int]) -> pd.DataFrame:
    """Votos por grupo, otros y blanco_nulo de una vuelta (una fila por sección)."""
    cols = [c for c in votos.columns if c.startswith("v_")]
    out = votos[SECCION + ["nr_local", "comparecencia"]].copy()
    usados = set()
    for g, nums in grupos.items():
        cs = [f"v_{n}" for n in nums if f"v_{n}" in cols]
        out[g] = votos[cs].sum(axis=1)
        usados |= set(cs)
    bn = [f"v_{n}" for n in blanco_nulo if f"v_{n}" in cols]
    out["blanco_nulo"] = votos[bn].sum(axis=1)
    out["otros"] = votos[[c for c in cols if c not in usados and c not in bn]].sum(axis=1)
    return out


def construir(ano: int) -> pd.DataFrame:
    cfg = cargar_config()["seccion"]
    votos = pd.read_parquet(salida_votos(ano))
    padron = pd.read_parquet(salida_padron(ano))
    partes = []
    for turno in (1, 2):
        g = grupos_por_seccion(votos[votos["turno"] == turno], cfg["grupos"][ano][turno], cfg["blanco_nulo"])
        g = g.merge(padron[SECCION + ["aptos", "lat", "lon", "bairro", "nm_municipio"]], on=SECCION, how="left")
        g["abstencion"] = (g["aptos"] - g["comparecencia"]).clip(lower=0)
        nombres = list(cfg["grupos"][ano][turno]) + ["otros", "blanco_nulo", "abstencion", "comparecencia"]
        agg = g.groupby(LOCAL).agg(**{f"{c}_{turno}": (c, "sum") for c in nombres},
                                   **({"aptos": ("aptos", "sum"), "secciones": ("nr_secao", "size"),
                                       "lat": ("lat", "mean"), "lon": ("lon", "mean"),
                                       "bairro": ("bairro", "first"), "nm_municipio": ("nm_municipio", "first")}
                                      if turno == 1 else {}))
        partes.append(agg)
    loc = partes[0].join(partes[1], how="outer").reset_index()
    nombres_local = votos.drop_duplicates(LOCAL).set_index(LOCAL)["nm_local"]
    loc["nm_local"] = loc.set_index(LOCAL).index.map(nombres_local)

    corr = pd.read_csv(CORRESPONDENCIA, dtype={"codigo_tse": int, "codigo_ibge": "Int64"})
    loc = loc.merge(corr[["codigo_tse", "codigo_ibge"]].rename(columns={"codigo_tse": "cd_municipio", "codigo_ibge": "cd_ibge"}),
                    on="cd_municipio", how="left")
    loc.insert(0, "ano", ano)
    loc.to_parquet(salida(ano), index=False)

    nac = loc.drop(columns="ZZ", errors="ignore")
    log.info("%d: %s locales (%s en el exterior), %s electores; %.1f%% de locales con coordenadas; "
             "%d sin código IBGE (exterior)", ano, f"{len(loc):,}", f"{(loc['uf'] == 'ZZ').sum():,}",
             f"{int(loc['aptos'].sum()):,}", loc["lat"].notna().mean() * 100, loc["cd_ibge"].isna().sum())
    for t in (1, 2):
        g = list(cfg["grupos"][ano][t])
        val = nac[[f"{c}_{t}" for c in g + ["otros"]]].sum()
        log.info("  vuelta %d (válidos): %s", t, ", ".join(f"{c} {v / val.sum() * 100:.2f}%" for c, v in
                                                       zip(g + ["otros"], val)))
    return loc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", nargs="+", type=int, default=[2018, 2022])
    args = parser.parse_args()
    for ano in args.ano:
        construir(ano)


if __name__ == "__main__":
    main()
