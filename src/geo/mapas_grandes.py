"""
src/geo/mapas_grandes.py

Mapas a página completa por estado, a partir de las capas de src.geo.divisiones
(no recalcula nada):
  <UF>/figs/estado_grande.svg   municípios (Lula, 2ª vuelta 2022) con bordes de
                                regiões imediatas y nombres de las ciudades principales
  <UF>/figs/capital_grande.svg  capital: área de cada escuela, barrios del IBGE
                                encima y nombres de los barrios con más electores

Uso:
    python -m src.geo.mapas_grandes [--uf SP RJ]
"""
from __future__ import annotations

import argparse
import json
import logging

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

from src.etl.extract.tse_extractor import UFS
from src.geo.divisiones import CAPITALES, CORTES, GEO_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("pyogrio").setLevel(logging.WARNING)

INK = "#1D1631"
ETQ = ["Bolsonaro 70 % o más", "Bolsonaro 60–70 %", "Bolsonaro 50–60 %", "Lula 50–60 %", "Lula 60–70 %", "Lula 70 % o más"]
HALO = [pe.withStroke(linewidth=2.2, foreground="white")]
FIG = (11.6, 7.4)  # pulgadas: el cuerpo de una página A4 apaisada


def colores(v) -> list:
    v = np.asarray(v, dtype=float) / 100
    return [next((c for lim, c in CORTES if x < lim), CORTES[-1][1]) if np.isfinite(x) else "#EEEEEE" for x in v]


def leyenda(ax, titulo: str):
    ax.legend(handles=[Patch(color=c, label=e) for (_, c), e in zip(CORTES, ETQ)], title=titulo, title_fontsize=8.5,
              loc="lower left", fontsize=8, frameon=True, facecolor="white", edgecolor="#DDDDDD", framealpha=0.92)


def rotular(ax, gdf, col_nombre: str, n: int, tam: float, orden: str = "electores", min_dist: float = 0.0):
    """Nombres de las `n` unidades con más `orden`, sin encimarse (descarta las que caen a menos de min_dist)."""
    puestos = []
    for _, r in gdf.sort_values(orden, ascending=False).head(n * 3).iterrows():
        if len(puestos) >= n:
            break
        p = r.geometry.representative_point()
        if any(np.hypot(p.x - x, p.y - y) < min_dist for x, y in puestos):
            continue
        puestos.append((p.x, p.y))
        ax.annotate(str(r[col_nombre]), (p.x, p.y), fontsize=tam, ha="center", va="center", color=INK, weight="bold",
                    path_effects=HALO)


def mapa_estado(uf: str) -> None:
    d = GEO_DIR / uf
    mu = gpd.read_file(d / "municipios.geojson")
    rgi = gpd.read_file(d / "regioes_imediatas.geojson")
    fig, ax = plt.subplots(figsize=FIG)
    mu.plot(ax=ax, color=colores(mu["lula_2v"]), edgecolor="white", linewidth=0.3)
    rgi.boundary.plot(ax=ax, color=INK, linewidth=0.9)
    x0, y0, x1, y1 = mu.total_bounds
    rotular(ax, mu, "nombre", 16, 7.5, min_dist=max(x1 - x0, y1 - y0) * 0.06)
    ax.set_axis_off()
    ax.set_aspect("equal")
    leyenda(ax, "Lula, 2ª vuelta 2022")
    ax.annotate("Líneas gruesas: regiões imediatas (IBGE)", (0.99, 0.01), xycoords="axes fraction", ha="right",
                fontsize=7.5, color="#6B6480")
    fig.savefig(d / "figs" / "estado_grande.svg", format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def mapa_capital(uf: str, capital_cd: str, figsize=FIG, nombre: str = "capital_grande.svg", n_rot: int = 22) -> dict:
    d = GEO_DIR / uf
    a = gpd.read_file(d / "areas_escuelas.geojson")
    a = a[a["cd_municipio_ibge"] == capital_cd]
    loc = gpd.read_file(d / "locales.geojson")
    loc = loc[loc["cd_municipio_ibge"] == capital_cd]
    b = gpd.read_file(d / "bairros.geojson") if (d / "bairros.geojson").exists() else None
    b = b[b["cd_municipio_ibge"] == capital_cd] if b is not None else None
    nivel = "barrios del IBGE"
    if b is None or len(b) < 5:  # capitales sin barrios en la malla (ej. São Paulo): distritos
        dd = gpd.read_file(d / "distritos.geojson")
        dd = dd[dd["cd_municipio_ibge"] == capital_cd]
        if len(dd) >= 5:
            b, nivel = dd, "distritos del IBGE"
    fig, ax = plt.subplots(figsize=figsize)
    a.plot(ax=ax, color=colores(a["lula_2v"]), edgecolor="white", linewidth=0.15)
    if b is not None and len(b):
        b.boundary.plot(ax=ax, color=INK, linewidth=0.35)
    ax.scatter(loc.geometry.x, loc.geometry.y, s=1.5, color=INK, alpha=0.45, linewidths=0)
    if len(loc) > 10:
        x0, x1 = loc.geometry.x.quantile([0.05, 0.95]); y0, y1 = loc.geometry.y.quantile([0.05, 0.95])
        mx, my = (x1 - x0) * 0.25, (y1 - y0) * 0.25
        ax.set_xlim(x0 - mx, x1 + mx); ax.set_ylim(y0 - my, y1 + my)
        ancho = max(x1 - x0, y1 - y0)
    else:
        ancho = 0.1
    if b is not None and len(b.dropna(subset=["electores"])):
        bb = b.dropna(subset=["electores"])
        bb = bb.cx[ax.get_xlim()[0]:ax.get_xlim()[1], ax.get_ylim()[0]:ax.get_ylim()[1]]
        rotular(ax, bb, "nombre", n_rot, 6.5, min_dist=ancho * 0.07)
    ax.set_axis_off()
    ax.set_aspect("equal")
    leyenda(ax, "Lula, 2ª vuelta 2022")
    fig.text(0.5, 0.005, f"Cada polígono: área de influencia de una escuela. Puntos: escuelas. Líneas y nombres: {nivel}.",
             ha="center", fontsize=7.5, color="#6B6480")
    fig.savefig(d / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"areas": len(a), "escuelas": len(loc), "bairros": 0 if b is None else len(b), "nivel": nivel}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", nargs="+", default=UFS)
    args = parser.parse_args()
    for uf in args.uf:
        r = json.loads((GEO_DIR / uf / "resumen.json").read_text(encoding="utf-8"))
        r["capital_cd"] = CAPITALES[uf]
        import pyogrio
        mn = pyogrio.read_dataframe(GEO_DIR / uf / "municipios.geojson", read_geometry=False, columns=["codigo", "nombre"])
        r["capital_nombre"] = str(mn.loc[mn["codigo"] == r["capital_cd"], "nombre"].iloc[0])
        mapa_estado(uf)
        c = mapa_capital(uf, r["capital_cd"])
        mapa_capital(uf, r["capital_cd"], figsize=(6.0, 5.6), nombre="capital.svg", n_rot=10)  # versión chica
        # barrios extremos de la capital (corrige corridas donde la capital era el município con más electores)
        bf = GEO_DIR / uf / "bairros.geojson"
        r.pop("bairros_capital", None)
        if bf.exists():
            b = gpd.read_file(bf)
            nb = int((b["cd_municipio_ibge"] == r["capital_cd"]).sum())
            bc = b[(b["cd_municipio_ibge"] == r["capital_cd"]) & (b["electores"].fillna(0) >= 2000)].dropna(subset=["lula_2v"])
            if len(bc) >= 6:
                r["bairros_capital"] = {"n": nb, "mas_lula": bc.nlargest(4, "lula_2v")[["nombre", "lula_2v", "electores"]].to_dict(orient="records"),
                                        "menos_lula": bc.nsmallest(4, "lula_2v")[["nombre", "lula_2v", "electores"]].to_dict(orient="records")}
        log.info("%s: mapas grandes listos (capital: %d áreas, %d escuelas, %d %s)", uf, c["areas"], c["escuelas"], c["bairros"], c["nivel"])
        r["capital_mapa"] = c
        (GEO_DIR / uf / "resumen.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
