"""
src/viz/mapas_espaciales.py

Mapas de los resultados de R/analisis_espacial.R (última corrida en
data/processed/geo/_espacial/<fecha>/), con la paleta de Atlas. Deja los SVG en
<corrida>/figs/:

  nacionales: lisa_municipios, gi_cambio, gwr_coeficientes, gwr_r2, skater_4,
              lisa_metropolis, acceso_deciles, acceso_mapa
  por estado: <UF>_lisa_escuelas (focos escuela por escuela), <UF>_skater

Uso:
    python -m src.viz.mapas_espaciales
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch

from src.etl.extract.tse_extractor import UFS
from src.geo.divisiones import CAPITALES, GEO_DIR
from src.geo.mapas_grandes import HALO, INK, rotular

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("pyogrio").setLevel(logging.WARNING)

ESPACIAL = GEO_DIR / "_espacial"
NAC = GEO_DIR / "_nacional"
LISA_COL = {"High-High": "#B42322", "Low-Low": "#1C5CAB", "High-Low": "#F6B9B8", "Low-High": "#9EC5F4",
            "Not significant": "#E6E3EC", "Isolated": "#FFFFFF", "Undefined": "#FFFFFF"}
LISA_ETQ = {"High-High": "Foco lulista (alto rodeado de alto)", "Low-Low": "Foco bolsonarista (bajo rodeado de bajo)",
            "High-Low": "Isla lulista en zona bolsonarista", "Low-High": "Isla bolsonarista en zona lulista",
            "Not significant": "Sin patrón significativo"}
GI_COL = {"Foco de suba de Lula": "#B42322", "Foco de baja de Lula": "#1C5CAB", "Not significant": "#E6E3EC"}
VAR_ETQ = {"alfabetizacion": "Alfabetización", "preta_parda": "Población preta o parda", "banos_2mas": "Hogares con 2+ baños",
           "mayores_60": "60 años o más", "urbano": "Urbanización"}
FIG = (11.6, 7.4)


def guardar(fig, ruta: Path):
    fig.savefig(ruta, format="svg", bbox_inches="tight", facecolor="white", dpi=180)
    plt.close(fig)


def leyenda_cat(ax, colores: dict, etiquetas: dict, titulo: str, loc="lower left"):
    hs = [Patch(color=colores[k], label=v) for k, v in etiquetas.items() if k in colores]
    ax.legend(handles=hs, title=titulo, title_fontsize=8.5, fontsize=8, loc=loc, frameon=True, facecolor="white",
              edgecolor="#DDDDDD", framealpha=0.92)


def ufs_contorno(mun: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return mun[["uf", "geometry"]].dissolve("uf").reset_index()


def mapa_lisa_nacional(mun, ufs, figs):
    fig, ax = plt.subplots(figsize=FIG)
    mun.plot(ax=ax, color=mun["lisa_lula"].map(LISA_COL).fillna("#FFFFFF"), edgecolor="none", rasterized=True)
    ufs.boundary.plot(ax=ax, color=INK, linewidth=0.5)
    ax.set_axis_off(); ax.set_aspect("equal")
    leyenda_cat(ax, LISA_COL, LISA_ETQ, "Lula, 2ª vuelta 2022 · LISA (p < 0,01)")
    guardar(fig, figs / "lisa_municipios.svg")


def mapa_gi(mun, ufs, figs):
    fig, ax = plt.subplots(figsize=FIG)
    mun.plot(ax=ax, color=mun["gi_cambio"].map(GI_COL).fillna("#FFFFFF"), edgecolor="none", rasterized=True)
    ufs.boundary.plot(ax=ax, color=INK, linewidth=0.5)
    ax.set_axis_off(); ax.set_aspect("equal")
    leyenda_cat(ax, GI_COL, {"Foco de suba de Lula": "Foco de suba de Lula (2018 → 2022)",
                             "Foco de baja de Lula": "Foco de baja de Lula (2018 → 2022)",
                             "Not significant": "Sin foco significativo"}, "Getis-Ord Gi* (p < 0,01)")
    guardar(fig, figs / "gi_cambio.svg")


def mapa_gwr(mun, ufs, figs):
    vs = ["alfabetizacion", "preta_parda", "banos_2mas", "mayores_60"]
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.6))
    for ax, v in zip(axes.ravel(), vs):
        c = mun[f"gwr_{v}"]
        lim = np.nanpercentile(np.abs(c), 97)
        mun.plot(ax=ax, column=f"gwr_{v}", cmap="RdBu_r", norm=TwoSlopeNorm(0, -lim, lim), edgecolor="none",
                 missing_kwds={"color": "#FFFFFF"}, rasterized=True, legend=True,
                 legend_kwds={"shrink": 0.6, "label": "pp de Lula por desvío estándar"})
        ufs.boundary.plot(ax=ax, color=INK, linewidth=0.3)
        ax.set_title(VAR_ETQ[v], fontsize=10, loc="left", color=INK, weight="bold")
        ax.set_axis_off(); ax.set_aspect("equal")
    fig.tight_layout()
    guardar(fig, figs / "gwr_coeficientes.svg")
    fig, ax = plt.subplots(figsize=(6.2, 5.6))
    mun.plot(ax=ax, column="gwr_r2", cmap="Purples", vmin=0.3, vmax=1, edgecolor="none", missing_kwds={"color": "#FFFFFF"},
             rasterized=True, legend=True, legend_kwds={"shrink": 0.6, "label": "R² local"})
    ufs.boundary.plot(ax=ax, color=INK, linewidth=0.3)
    ax.set_axis_off(); ax.set_aspect("equal")
    guardar(fig, figs / "gwr_r2.svg")


def mapa_skater_uf(mun_uf: gpd.GeoDataFrame, ax, titulo: str | None = None, rot: bool = True):
    from src.geo.mapas_grandes import colores
    s = mun_uf.dropna(subset=["region_skater"])
    reg = s.dissolve("region_skater", aggfunc={"lula_2v": "mean", "electores": "sum"}).reset_index()
    # % de Lula de la región ponderado por electores
    pesos = s.assign(v=s["lula_2v"] * s["electores"]).groupby("region_skater")[["v", "electores"]].sum()
    reg["lula_reg"] = reg["region_skater"].map(pesos["v"] / pesos["electores"])
    mun_uf.plot(ax=ax, color="#FFFFFF", edgecolor="#DDDDDD", linewidth=0.2, rasterized=True)
    reg.plot(ax=ax, color=colores(reg["lula_reg"]), edgecolor=INK, linewidth=0.8, rasterized=True)
    if rot:
        for _, r in reg.iterrows():
            p = r.geometry.representative_point()
            ax.annotate(f"{r['lula_reg']:.0f}".replace(".", ","), (p.x, p.y), fontsize=6.5, ha="center", va="center",
                        color=INK, weight="bold", path_effects=HALO)
    ax.set_axis_off(); ax.set_aspect("equal")
    if titulo:
        ax.set_title(titulo, fontsize=10, loc="left", color=INK, weight="bold")
    return len(reg)


def mapa_lisa_escuelas(uf: str, lisa: pd.DataFrame, figs: Path, ax=None, capital: bool = False, titulo=None):
    e = gpd.read_file(NAC / f"escuelas_{uf}.gpkg")
    e = e.merge(lisa[lisa["uf"] == uf], on=["uf", "cd_municipio", "nr_zona", "nr_local"], how="left")
    propio = ax is None
    if propio:
        fig, ax = plt.subplots(figsize=FIG)
    if capital:
        e = e[e["cd_municipio_ibge"] == CAPITALES[uf]]
    e.plot(ax=ax, color=e["lisa"].map(LISA_COL).fillna("#FFFFFF"), edgecolor="none", rasterized=True)
    if not capital:
        mu = gpd.read_file(GEO_DIR / uf / "municipios.geojson")
        mu.boundary.plot(ax=ax, color="#8A8983", linewidth=0.15, rasterized=True)
        x0, y0, x1, y1 = mu.total_bounds
        rotular(ax, mu, "nombre", 10, 7, min_dist=max(x1 - x0, y1 - y0) * 0.07)
    ax.set_axis_off(); ax.set_aspect("equal")
    if titulo:
        ax.set_title(titulo, fontsize=10, loc="left", color=INK, weight="bold")
    if propio:
        leyenda_cat(ax, LISA_COL, LISA_ETQ, "Lula 2ª vuelta 2022 · LISA por escuela (p < 0,01)")
        guardar(fig, figs / f"{uf}_lisa_escuelas.svg")
    return e["lisa"].value_counts().to_dict()


def acceso(figs: Path, corrida: Path, mun):
    dec = pd.read_csv(corrida / "accesibilidad_deciles.csv")
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.plot(dec["dist_km_mediana"], dec["abstencion"], marker="o", color="#5B3F99", lw=2)
    for _, r in dec.iterrows():
        ax.annotate(f"{r['abstencion']:.1f}".replace(".", ","), (r["dist_km_mediana"], r["abstencion"]), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=7.5, color=INK)
    ax.set_xscale("log")
    ax.set_xticks([0.2, 0.5, 1, 2, 5], ["0,2", "0,5", "1", "2", "5"])
    ax.set_xlabel("Distancia mediana a la escuela (km, escala logarítmica) · deciles de escuelas", fontsize=8.5)
    ax.set_ylabel("% de abstención (2ª vuelta)", fontsize=8.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#EEEEEE")
    guardar(fig, figs / "acceso_deciles.svg")
    fig, ax = plt.subplots(figsize=(6.2, 5.6))
    mun.plot(ax=ax, column="dist_km", cmap="Purples", scheme=None, vmin=0, vmax=np.nanpercentile(mun["dist_km"], 95),
             edgecolor="none", missing_kwds={"color": "#FFFFFF"}, rasterized=True, legend=True,
             legend_kwds={"shrink": 0.6, "label": "km a la escuela (promedio por habitante)"})
    ax.set_axis_off(); ax.set_aspect("equal")
    guardar(fig, figs / "acceso_mapa.svg")


def main() -> Path:
    corrida = sorted(p.parent for p in ESPACIAL.glob("*/resumen.json"))[-1]
    figs = corrida / "figs"
    figs.mkdir(exist_ok=True)
    mun = gpd.read_file(corrida / "municipios.gpkg")
    ufs = ufs_contorno(mun)
    lisa = pd.read_csv(corrida / "escuelas_lisa.csv")
    mapa_lisa_nacional(mun, ufs, figs)
    mapa_gi(mun, ufs, figs)
    mapa_gwr(mun, ufs, figs)
    acceso(figs, corrida, mun)
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.6))
    for ax, uf in zip(axes.ravel(), ["SP", "MG", "BA", "RS"]):
        n = mapa_skater_uf(mun[mun["uf"] == uf], ax, rot=True)
        ax.set_title(f"{uf}: {n} regiones", fontsize=10, loc="left", color=INK, weight="bold")
    fig.tight_layout()
    guardar(fig, figs / "skater_4.svg")
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 6.0))
    for ax, uf, nom in zip(axes, ["SP", "RJ"], ["São Paulo (ciudad)", "Rio de Janeiro (ciudad)"]):
        mapa_lisa_escuelas(uf, lisa, figs, ax=ax, capital=True, titulo=nom)
    leyenda_cat(axes[0], LISA_COL, LISA_ETQ, "LISA por escuela (p < 0,01)")
    fig.tight_layout()
    guardar(fig, figs / "lisa_metropolis.svg")
    por_uf = {}
    for uf in UFS:
        cuenta = mapa_lisa_escuelas(uf, lisa, figs)
        fig, ax = plt.subplots(figsize=FIG)
        sub = mun[mun["uf"] == uf]
        n = mapa_skater_uf(sub, ax) if sub["region_skater"].notna().any() else 0
        if n:
            from src.geo.mapas_grandes import leyenda
            leyenda(ax, "Lula 2ª vuelta 2022, promedio de la región")
        guardar(fig, figs / f"{uf}_skater.svg")
        por_uf[uf] = {"lisa_escuelas": cuenta, "skater_regiones": n}
        log.info("%s: LISA %s | SKATER %d regiones", uf, cuenta, n)
    (corrida / "figs_resumen.json").write_text(json.dumps(por_uf, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Mapas en %s", figs.relative_to(GEO_DIR.parents[2]).as_posix())
    return corrida


if __name__ == "__main__":
    main()
