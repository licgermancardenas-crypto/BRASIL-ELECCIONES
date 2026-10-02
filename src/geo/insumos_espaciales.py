"""
src/geo/insumos_espaciales.py

Insumos para el análisis espacial en R (R/analisis_espacial.R):

  data/processed/geo/_nacional/municipios.gpkg   los 5.570 municípios con votos,
      cambio 2018-2022, abstención, Censo (agregado de las áreas de sus escuelas,
      ponderado por población) y distancia media a la escuela
  data/processed/geo/_nacional/escuelas_<UF>.gpkg  área de influencia de cada
      escuela con las mismas variables (para focos dentro de cada estado)

Distancia a la escuela: para cada setor censitário, distancia en línea recta
(km) desde su punto interior a la escuela que tiene asignada (la más cercana
de su município, src.geo.censo_locales.asignar); promedio ponderado por
población del setor. Es la distancia mínima posible: no todos votan en la
escuela más cercana.

Uso:
    python -m src.geo.insumos_espaciales [--uf SP RJ]
"""
from __future__ import annotations

import argparse
import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from src.etl.extract.censo_extractor import ultima_malla_uf
from src.etl.extract.tse_extractor import UFS
from src.etl.transform.base_locales import LOCAL, salida as salida_locales
from src.geo.censo_locales import asignar
from src.geo.divisiones import GEO_DIR
from src.models.analisis_seccion import LOCALES_CENSO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("pyogrio").setLevel(logging.WARNING)

NAC = GEO_DIR / "_nacional"
CENSO_VARS = ["alfabetizacion", "preta_parda", "banos_2mas", "cloaca_red", "mayores_60", "jovenes_15_29", "urbano"]


def distancias_uf(uf: str, locales: pd.DataFrame) -> pd.DataFrame:
    """Distancia media (km, ponderada por población) de los setores a su escuela, por escuela."""
    g = gpd.read_file(ultima_malla_uf(uf), columns=["CD_MUN", "v0001"])
    p = g.geometry.representative_point()
    s = pd.DataFrame({"cd_mun": g["CD_MUN"].astype(int), "lon": p.x.to_numpy(), "lat": p.y.to_numpy(),
                      "pop": pd.to_numeric(g["v0001"], errors="coerce").fillna(0).to_numpy()})
    L = locales[locales["uf"] == uf].reset_index(drop=True)
    L["cd_ibge"] = pd.to_numeric(L["cd_ibge"], errors="coerce")
    idx = asignar(s, L)
    s = s[idx.to_numpy() >= 0].copy()
    s["local"] = idx[idx >= 0].to_numpy()
    la1, lo1 = np.radians(s["lat"]), np.radians(s["lon"])
    la2, lo2 = np.radians(L.loc[s["local"], "lat"].to_numpy()), np.radians(L.loc[s["local"], "lon"].to_numpy())
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    s["km"] = 2 * 6371 * np.arcsin(np.sqrt(a))
    s["km_pop"] = s["km"] * s["pop"]
    d = s.groupby("local").agg(km_pop=("km_pop", "sum"), pop=("pop", "sum"))
    out = L.loc[d.index, LOCAL].copy()
    out["dist_km"] = (d["km_pop"] / d["pop"].where(d["pop"] > 0)).to_numpy()
    out["pop_area"] = d["pop"].to_numpy()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", nargs="+", default=UFS)
    args = parser.parse_args()
    NAC.mkdir(parents=True, exist_ok=True)
    locales = pd.read_parquet(salida_locales(2022))
    censo = pd.read_parquet(LOCALES_CENSO)
    mun_partes, dist_todas = [], []
    for uf in args.uf:
        dist = distancias_uf(uf, locales)
        dist_todas.append(dist.assign(uf_=uf))
        # escuelas: áreas de influencia + Censo + distancia
        a = gpd.read_file(GEO_DIR / uf / "areas_escuelas.geojson")
        a = a.merge(censo[LOCAL + CENSO_VARS], on=LOCAL, how="left").merge(dist, on=LOCAL, how="left")
        a = a[["uf", "cd_municipio", "nr_zona", "nr_local", "nm_local", "nm_municipio", "cd_municipio_ibge", "electores",
               "lula_1v", "lula_2v", "abstencion_2v", "poblacion", "area_km2", "dist_km"] + CENSO_VARS + ["geometry"]]
        a.to_file(NAC / f"escuelas_{uf}.gpkg", layer="escuelas", driver="GPKG")
        # municípios: capa del estado + Censo y distancia agregados (ponderados por población del área)
        m = gpd.read_file(GEO_DIR / uf / "municipios.geojson")
        x = a.drop(columns="geometry").dropna(subset=["poblacion"])
        w = x["poblacion"].clip(lower=0)
        agg = {v: (x[v] * w).groupby(x["cd_municipio_ibge"]).sum() / w.where(x[v].notna(), 0).groupby(x["cd_municipio_ibge"]).sum()
               for v in CENSO_VARS + ["dist_km"]}
        m = m.join(pd.DataFrame(agg), on="codigo")
        m.insert(1, "uf", uf)
        mun_partes.append(m)
        log.info("%s: %d escuelas, distancia media %.2f km (mediana por escuela %.2f)", uf, len(a),
                 np.average(a["dist_km"].dropna(), weights=a.loc[a["dist_km"].notna(), "poblacion"].clip(lower=1)),
                 a["dist_km"].median())
    mun = pd.concat(mun_partes, ignore_index=True)
    mun = gpd.GeoDataFrame(mun, geometry="geometry", crs="EPSG:4326")
    cols = ["codigo", "uf", "nombre", "electores", "lula_1v", "lula_2v", "haddad_2v_2018", "cambio_2018_2022",
            "abstencion_2v", "gob_1_pct", "gob_2_pct", "poblacion", "area_km2"] + CENSO_VARS + ["dist_km", "geometry"]
    mun = mun[[c for c in cols if c in mun]]
    if set(args.uf) == set(UFS):
        mun.to_file(NAC / "municipios.gpkg", layer="municipios", driver="GPKG")
        pd.concat(dist_todas).to_parquet(NAC / "distancias_locales.parquet", index=False)
    log.info("Municípios: %d (sin Censo: %d)", len(mun), mun["alfabetizacion"].isna().sum())


if __name__ == "__main__":
    main()
