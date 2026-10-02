"""
src/geo/censo_locales.py

Censo 2022 por LOCAL DE VOTACIÓN: cada setor censitário se asigna al local
de votación más cercano de su mismo município (por el punto interior del
setor y las coordenadas del local publicadas por el TSE), y se suman sus
datos. El resultado es el "área de influencia" de cada local, el equivalente
del circuito en el informe de CABA.

Es una aproximación (ver docs/metodologia_geoespacial.md): la gente no
siempre vota en la escuela más cercana a su casa. Los locales sin
coordenadas (~7% en 2022) quedan sin datos censales.

Variables (proporciones 0-1):
  alfabetizacion  alfabetizados / personas de 15 años o más
  preta_parda     personas pretas o pardas / total con cor o raça
  mayores_60      60 años o más / población
  jovenes_15_29   15 a 29 años / población
  banos_2mas      hogares con 2 baños o más / hogares (proxy de ingreso: el
                  Censo 2022 no publica ingreso por setor)
  cloaca_red      hogares con cloaca a red general o fosa ligada a red / hogares
  urbano          población en setores urbanos / población

Input:  data/raw/ibge/censo_2022/* (src.etl.extract.censo_extractor)
        data/processed/electoral/seccion/locales_2022.parquet
Output: data/processed/electoral/seccion/locales_censo_2022.parquet

Uso:
    python -m src.geo.censo_locales                    # las 27 UF (malla por UF en raw/)
    python -m src.geo.censo_locales --malla AC.gpkg    # para probar con una UF
"""
from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from src.etl.extract.censo_extractor import _config as config_censo, ultima_malla_uf, ultima_version
from src.etl.transform.base_locales import salida as salida_locales
from src.models.analisis_seccion import LOCALES_CENSO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LOCAL = ["uf", "cd_municipio", "nr_zona", "nr_local"]
V = lambda a, b: [f"V{i:05d}" for i in range(a, b + 1)]
VARIABLES = {  # archivo -> {conteo: columnas que se suman}
    "demografia": {"pop": ["V01006"], "mayores_60": ["V01040", "V01041"], "jovenes_15_29": ["V01034", "V01035", "V01036"]},
    "alfabetizacion": {"pop15": V(644, 656), "alfab": V(748, 760)},
    "color_raza": {"cor_total": V(1317, 1321), "preta_parda": ["V01318", "V01320"]},
    "domicilio1": {"hogares": ["V00001"]},
    "domicilio2": {"banos_2mas": ["V00233", "V00234", "V00235"], "cloaca_red": ["V00309", "V00310"]},
}


def leer_conteos() -> pd.DataFrame:
    partes = []
    for archivo, conteos in VARIABLES.items():
        cols = sorted({c for cs in conteos.values() for c in cs})
        with zipfile.ZipFile(ultima_version(archivo)) as z:
            with z.open(next(n for n in z.namelist() if n.lower().endswith(".csv"))) as f:
                # Solo la clave y las columnas usadas: el CSV de alfabetización tiene ~360 columnas
                d = pd.read_csv(f, sep=";", dtype=str, encoding="latin1",
                                usecols=lambda c: c in cols or c.lower() in ("cd_setor", "setor"))
        clave = next(c for c in d.columns if c.lower() in ("cd_setor", "setor"))
        num = d[cols].apply(lambda s: pd.to_numeric(s.str.replace(",", "."), errors="coerce")).fillna(0)  # "X" = dato suprimido
        out = pd.DataFrame({k: num[cs].sum(axis=1) for k, cs in conteos.items()})
        out.index = d[clave].str.strip()
        partes.append(out)
        log.info("Censo %s: %s setores", archivo, f"{len(out):,}")
    return pd.concat(partes, axis=1).fillna(0)


def puntos_setores(mallas: list[Path]) -> pd.DataFrame:
    """Punto interior de cada setor. Una UF por vez: los polígonos no quedan en memoria."""
    return pd.concat([_puntos(m) for m in mallas], ignore_index=True)


def _puntos(malla: Path) -> pd.DataFrame:
    g = gpd.read_file(malla, columns=["CD_SETOR", "CD_MUN", "SITUACAO"])
    p = g.geometry.representative_point()
    log.info("Malla %s: %s setores", malla.name, f"{len(g):,}")
    return pd.DataFrame({"cd_setor": g["CD_SETOR"].astype(str), "cd_mun": g["CD_MUN"].astype(int),
                         "urbano": g["SITUACAO"].str.lower().str.startswith("urban").astype(float),
                         "lon": p.x.to_numpy(), "lat": p.y.to_numpy()})


def asignar(setores: pd.DataFrame, locales: pd.DataFrame) -> pd.Series:
    """Índice (en `locales`) del local más cercano de su município para cada setor."""
    asign = pd.Series(-1, index=setores.index)
    loc = locales.dropna(subset=["lat", "lon", "cd_ibge"])
    por_mun = {m: x for m, x in loc.groupby("cd_ibge")}
    for m, s in setores.groupby("cd_mun"):
        x = por_mun.get(m)
        if x is None:
            continue
        c = np.cos(np.radians(x["lat"].mean()))
        arbol = cKDTree(np.c_[x["lon"] * c, x["lat"]])
        _, i = arbol.query(np.c_[s["lon"] * c, s["lat"]])
        asign.loc[s.index] = x.index.to_numpy()[i]
    return asign


def construir(mallas: list[Path]) -> pd.DataFrame:
    locales = pd.read_parquet(salida_locales(2022))
    locales = locales[locales["uf"] != "ZZ"].reset_index(drop=True)
    setores = puntos_setores(mallas)
    log.info("Malla: %s setores", f"{len(setores):,}")
    conteos = leer_conteos()
    setores = setores.join(conteos, on="cd_setor")
    sin_censo = setores["pop"].isna().sum()
    setores = setores.fillna({c: 0 for c in conteos.columns})
    setores["pop_urbana"] = setores["urbano"] * setores["pop"]
    setores["local"] = asignar(setores, locales)
    ok = setores["local"] >= 0
    log.info("Setores sin datos del Censo: %d; asignados a un local: %s de %s (%.1f%% de la población)", sin_censo,
             f"{ok.sum():,}", f"{len(setores):,}", setores.loc[ok, "pop"].sum() / setores["pop"].sum() * 100)
    s = setores[ok].groupby("local")[list(conteos.columns) + ["pop_urbana"]].sum()
    s["setores"] = setores[ok].groupby("local").size()
    out = locales.loc[s.index, LOCAL].copy()
    out["setores"] = s["setores"].to_numpy()
    out["pop"] = s["pop"].to_numpy()
    div = lambda a, b: np.where(s[b] > 0, s[a] / s[b].where(s[b] > 0, 1), np.nan)
    out["alfabetizacion"] = div("alfab", "pop15")
    out["preta_parda"] = div("preta_parda", "cor_total")
    out["mayores_60"] = div("mayores_60", "pop")
    out["jovenes_15_29"] = div("jovenes_15_29", "pop")
    out["banos_2mas"] = div("banos_2mas", "hogares")
    out["cloaca_red"] = div("cloaca_red", "hogares")
    out["urbano"] = div("pop_urbana", "pop")
    out.to_parquet(LOCALES_CENSO, index=False)
    log.info("Locales con Censo: %s; población cubierta %s", f"{len(out):,}", f"{int(out['pop'].sum()):,}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--malla", type=Path, nargs="+", help="GeoPackages de setores (default: las 27 UF en raw/)")
    args = parser.parse_args()
    if args.malla:
        mallas = args.malla
    else:
        mallas, faltan = [], []
        for uf in config_censo()["ufs"]:
            try:
                mallas.append(ultima_malla_uf(uf))
            except FileNotFoundError:
                faltan.append(uf)
        if faltan:
            raise SystemExit(f"Falta la malla de {', '.join(faltan)}: correr "
                             "python -m src.etl.extract.censo_extractor --malla-uf " + " ".join(faltan))
    construir(mallas)


if __name__ == "__main__":
    main()
