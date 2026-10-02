"""
src/etl/transform/coordenadas_locales.py

Completa las coordenadas de los locales de votación de un año cuando el
archivo del TSE de ese año no las trae (en 2022 faltan en ~7% de los locales,
~30% en BA y SE). Cadena de respaldo, con el origen en `coord_origen`:

  tse          coordenada del TSE del mismo año
  tse_<año>    misma escuela en otro año del TSE (2024, 2018...): primero por
               (UF, município, zona, número de local) y si no por nombre
               normalizado dentro del município
  bairro       punto interior del barrio del IBGE con el mismo nombre que el
               barrio que informa el TSE (aproximada: no se usa para trazar
               áreas de escuela, sí para mapas de puntos y conteos por barrio)

Se aplica sobre data/processed/electoral/seccion/locales_{ano}.parquet
(src.etl.transform.base_locales) y lo reescribe.

Uso:
    python -m src.etl.transform.coordenadas_locales --ano 2022 --respaldo 2024 2018
"""
from __future__ import annotations

import argparse
import logging
import re
import unicodedata
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd

from src.etl.extract.censo_extractor import ultima_malla_uf
from src.etl.extract.tse_extractor import UFS, ultima_version
from src.etl.transform.base_locales import salida as salida_locales

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("pyogrio").setLevel(logging.WARNING)


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def coordenadas_tse(ano: int) -> pd.DataFrame:
    with zipfile.ZipFile(ultima_version("locales_votacion", ano)) as z:
        n = next(x for x in z.namelist() if x.lower().endswith(".csv"))
        d = pd.read_csv(z.open(n), sep=";", encoding="latin1", dtype=str,
                        usecols=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO",
                                 "NR_LATITUDE", "NR_LONGITUDE"])
    d["lat"] = pd.to_numeric(d["NR_LATITUDE"].str.replace(",", "."), errors="coerce")
    d["lon"] = pd.to_numeric(d["NR_LONGITUDE"].str.replace(",", "."), errors="coerce")
    d = d[d["lat"].between(-34, 6) & d["lon"].between(-74, -28) & (d["lat"].abs() > 0.01)]
    d = d.rename(columns={"SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio", "NR_ZONA": "nr_zona", "NR_LOCAL_VOTACAO": "nr_local"})
    for c in ("cd_municipio", "nr_zona", "nr_local"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
    d["nombre_n"] = d["NM_LOCAL_VOTACAO"].map(norm)
    return d.groupby(["uf", "cd_municipio", "nr_zona", "nr_local", "nombre_n"], as_index=False)[["lat", "lon"]].mean()


def centroides_bairro() -> pd.DataFrame:
    partes = []
    for uf in UFS:
        g = gpd.read_file(ultima_malla_uf(uf), columns=["CD_MUN", "NM_BAIRRO", "CD_BAIRRO"])
        g = g[g["CD_BAIRRO"].astype(str) != "."]
        if g.empty:
            continue
        g["b"] = g["NM_BAIRRO"].map(norm)
        u = g.dissolve(["CD_MUN", "b"]).geometry.representative_point()
        partes.append(pd.DataFrame({"cd_ibge": u.index.get_level_values(0).astype(int), "bairro_n": u.index.get_level_values(1),
                                    "lat_b": u.y.to_numpy(), "lon_b": u.x.to_numpy()}))
    return pd.concat(partes, ignore_index=True)


def completar(ano: int, respaldos: list[int]) -> pd.DataFrame:
    loc = pd.read_parquet(salida_locales(ano))
    loc["coord_origen"] = np.where(loc["lat"].notna(), "tse", None)
    loc["nombre_n"] = loc["nm_local"].map(norm)
    k = ["uf", "cd_municipio", "nr_zona", "nr_local"]
    for r in respaldos:
        c = coordenadas_tse(r)
        falta = loc["lat"].isna()
        por_num = c.drop_duplicates(k).set_index(k)[["lat", "lon"]]
        idx = pd.MultiIndex.from_frame(loc.loc[falta, k].astype({"cd_municipio": "Int64", "nr_zona": "Int64", "nr_local": "Int64"}))
        m = por_num.reindex(idx)
        # mismo número de local, pero el nombre tiene que parecerse (los números se reasignan entre elecciones)
        nombres = c.drop_duplicates(k).set_index(k)["nombre_n"].reindex(idx).to_numpy()
        coincide = [isinstance(a, str) and (a[:12] == b[:12]) for a, b in zip(nombres, loc.loc[falta, "nombre_n"])]
        sel = falta[falta].index[np.array(coincide) & m["lat"].notna().to_numpy()]
        loc.loc[sel, ["lat", "lon"]] = m.loc[np.array(coincide) & m["lat"].notna().to_numpy(), ["lat", "lon"]].to_numpy()
        loc.loc[sel, "coord_origen"] = f"tse_{r}"
        # por nombre dentro del município
        falta = loc["lat"].isna()
        pn = c.drop_duplicates(["uf", "cd_municipio", "nombre_n"]).set_index(["uf", "cd_municipio", "nombre_n"])[["lat", "lon"]]
        idx2 = pd.MultiIndex.from_frame(loc.loc[falta, ["uf", "cd_municipio", "nombre_n"]].astype({"cd_municipio": "Int64"}))
        m2 = pn.reindex(idx2)
        ok = m2["lat"].notna().to_numpy()
        sel2 = falta[falta].index[ok]
        loc.loc[sel2, ["lat", "lon"]] = m2.loc[ok, ["lat", "lon"]].to_numpy()
        loc.loc[sel2, "coord_origen"] = f"tse_{r}"
        log.info("%d: respaldo %d completó %d locales", ano, r, len(sel) + len(sel2))
    # centroide de barrio IBGE
    falta = loc["lat"].isna() & loc["bairro"].notna() & loc["cd_ibge"].notna()
    cb = centroides_bairro().drop_duplicates(["cd_ibge", "bairro_n"]).set_index(["cd_ibge", "bairro_n"])
    idx3 = pd.MultiIndex.from_arrays([loc.loc[falta, "cd_ibge"].astype(int), loc.loc[falta, "bairro"].map(norm)])
    m3 = cb.reindex(idx3)
    ok = m3["lat_b"].notna().to_numpy()
    sel3 = falta[falta].index[ok]
    loc.loc[sel3, ["lat", "lon"]] = m3.loc[ok, ["lat_b", "lon_b"]].to_numpy()
    loc.loc[sel3, "coord_origen"] = "bairro"
    loc = loc.drop(columns="nombre_n")
    loc.to_parquet(salida_locales(ano), index=False)
    nac = loc[loc["uf"] != "ZZ"]
    peso = nac.groupby("coord_origen", dropna=False)["aptos"].sum() / nac["aptos"].sum() * 100
    log.info("%d: electores por origen de coordenada: %s", ano, ", ".join(f"{k}: {v:.1f}%" for k, v in peso.items()))
    por_uf = nac.assign(ok=nac["coord_origen"].isin(["tse"] + [f"tse_{r}" for r in respaldos])).groupby("uf").apply(
        lambda x: (x["aptos"] * x["ok"]).sum() / x["aptos"].sum() * 100, include_groups=False)
    log.info("%d: %% del padrón con coordenada precisa, UF más bajas: %s", ano,
             ", ".join(f"{u} {v:.0f}%" for u, v in por_uf.nsmallest(6).items()))
    return loc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, default=2022)
    parser.add_argument("--respaldo", type=int, nargs="+", default=[2024, 2018])
    args = parser.parse_args()
    completar(args.ano, args.respaldo)


if __name__ == "__main__":
    main()
