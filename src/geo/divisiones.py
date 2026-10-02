"""
src/geo/divisiones.py

Capas geoespaciales por estado con resultados electorales: cada jurisdicción
(polígono) y cada local de votación / sección (punto) lleva sus votos de
presidente 2018/2022 y gobernador 2022, la abstención y el Censo 2022.

Jurisdicciones (todas salen de la malla de setores del Censo 2022, que trae
los códigos de cada nivel; se unen los setores de cada unidad):
  regioes_intermediarias, regioes_imediatas, municipios, distritos, bairros
  (solo donde el IBGE define barrios), areas_escuelas (área de influencia de
  cada local de votación: los setores asignados a la escuela más cercana; el
  nivel más fino con polígono, como el circuito de CABA), zonas_eleitorais (APROXIMADAS: el TSE
  no publica polígonos; cada setor va a la zona de la escuela más cercana de
  su município, la misma asignación que src.geo.censo_locales).
Puntos: locales (escuelas, con coordenadas del TSE) y secciones (cada mesa en
la coordenada de su escuela).

Los votos se asignan a cada polígono así: município y regiones por código
IBGE (exacto, incluye escuelas sin coordenadas); distrito y bairro por el
punto de la escuela (solo escuelas con coordenadas); zona por el número de
zona del TSE (exacto).

Geometrías: unión con shapely.coverage_union_all y simplificación con
coverage_simplify (respeta los bordes compartidos: no deja huecos ni
superposiciones entre vecinos). GeoJSON en EPSG:4326 (WGS84), 6 decimales.

Salida por UF en data/processed/geo/<UF>/:
  <capa>.geojson (una por jurisdicción + locales.geojson), secciones.csv,
  <UF>.gpkg (todas las capas juntas, para SIG) y figs/ para el informe.

Uso:
    python -m src.geo.divisiones                 # las 27 UF (una por vez, memoria acotada)
    python -m src.geo.divisiones --uf SP RJ
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

from src.etl.extract.censo_extractor import ultima_malla_uf
from src.etl.extract.tse_extractor import UFS
from src.etl.transform.base_locales import LOCAL, salida as salida_locales
from src.etl.transform.votacion_seccion import salida as salida_pres, salida_gobernador
from src.geo.censo_locales import asignar
from src.models.analisis_seccion import LOCALES_CENSO, cargar
from src.models.montecarlo.proyeccion_bancas import ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("pyogrio").setLevel(logging.WARNING)

GEO_DIR = ROOT / "data" / "processed" / "geo"
# capa -> (columna código, columna nombre, tolerancia de simplificación en grados ~ 1e-3 = 110 m)
NIVELES = {
    "distritos": ("CD_DIST", "NM_DIST", 0.0008),
    "municipios": ("CD_MUN", "NM_MUN", 0.0015),
    "regioes_imediatas": ("CD_RGI", "NM_RGI", 0.003),
    "regioes_intermediarias": ("CD_RGINT", "NM_RGINT", 0.005),
}
TOL_BAIRRO, TOL_ZONA = 0.0003, 0.001
COLS_MALLA = ["CD_SETOR", "CD_MUN", "NM_MUN", "CD_DIST", "NM_DIST", "CD_BAIRRO", "NM_BAIRRO", "CD_RGI", "NM_RGI",
              "CD_RGINT", "NM_RGINT", "AREA_KM2", "v0001"]
CORTES = [(0.3, "#1C5CAB"), (0.4, "#5598E7"), (0.5, "#B7D3F6"), (0.6, "#F6B9B8"), (0.7, "#EA7372"), (1.01, "#B42322")]


def unir(g: gpd.GeoDataFrame, clave: str, tol: float) -> gpd.GeoDataFrame:
    """Une los polígonos de cada `clave` y simplifica la cobertura resultante sin abrir huecos."""
    geoms = {k: shapely.coverage_union_all(x.geometry.values) for k, x in g.groupby(clave)}
    s = gpd.GeoSeries(list(geoms.values()), index=list(geoms.keys()), crs=g.crs)
    try:
        s = gpd.GeoSeries(shapely.coverage_simplify(s.values, tol), index=s.index, crs=g.crs)
    except Exception:  # coberturas no válidas (raras): simplificación clásica
        s = s.simplify(tol, preserve_topology=True)
    return gpd.GeoDataFrame(geometry=s).rename_axis(clave)


def metricas(df: pd.DataFrame, por: str | list[str]) -> pd.DataFrame:
    """Votos y porcentajes agregados por `por` a partir de la tabla de locales (con columnas de vueltas)."""
    a = df.groupby(por).agg(
        locales=("nr_local", "size"), secciones=("secciones", "sum"), electores=("aptos", "sum"),
        pt_1=("pt_1", "sum"), bol_1=("bolsonaro_1", "sum"), val_1=("validos_1", "sum"),
        pt_2=("pt_2", "sum"), bol_2=("bolsonaro_2", "sum"), val_2=("validos_2", "sum"), abst_2=("abstencion_2", "sum"),
        **{c: (c, "sum") for c in ("gob_g1", "gob_g2", "gob_val") if c in df})
    out = pd.DataFrame(index=a.index)
    out["locales"], out["secciones"], out["electores"] = a["locales"], a["secciones"], a["electores"]
    out["lula_1v"] = (a["pt_1"] / a["val_1"] * 100).round(2)
    out["bolsonaro_1v"] = (a["bol_1"] / a["val_1"] * 100).round(2)
    out["lula_2v"] = (a["pt_2"] / a["val_2"] * 100).round(2)
    out["abstencion_2v"] = (a["abst_2"] / a["electores"] * 100).round(2)
    out["votos_lula_2v"], out["votos_bolsonaro_2v"] = a["pt_2"], a["bol_2"]
    if "gob_g1" in a:
        out["gob_1_pct"] = (a["gob_g1"] / a["gob_val"] * 100).round(2)
        out["gob_2_pct"] = (a["gob_g2"] / a["gob_val"] * 100).round(2)
    return out


def gobernador_por_local(uf: str) -> tuple[pd.DataFrame, dict]:
    g = pd.read_parquet(salida_gobernador(2022), filters=[("uf", "==", uf), ("turno", "==", 1)])
    cols = [c for c in g.columns if c.startswith("v_") and g[c].sum() > 0]
    val = [c for c in cols if c not in ("v_95", "v_96")]
    top = g[val].sum().nlargest(2).index.tolist()
    loc = g.groupby(LOCAL)[cols].sum()
    out = pd.DataFrame({"gob_g1": loc[top[0]], "gob_g2": loc[top[1]], "gob_val": loc[val].sum(axis=1)}).reset_index()
    cand = pd.read_csv(salida_gobernador(2022).with_suffix(".candidatos.csv"))
    nom = cand[(cand["uf"] == uf) & (cand["nr_turno"] == 1)].set_index("nr_votavel")["nm_votavel"]
    return out, {"gob_1": str(nom.get(int(top[0][2:]), top[0])).title(), "gob_2": str(nom.get(int(top[1][2:]), top[1])).title()}


def mapa_coropletico(ax, capa: gpd.GeoDataFrame, col: str, borde: str = "white", lw: float = 0.25):
    v = capa[col].to_numpy() / 100
    colores = [next((c for lim, c in CORTES if x < lim), CORTES[-1][1]) if np.isfinite(x) else "#EEEEEE" for x in v]
    capa.plot(ax=ax, color=colores, edgecolor=borde, linewidth=lw)
    ax.set_axis_off()
    ax.set_aspect("equal")


def figuras(uf: str, capas: dict, out: Path, capital_cd: str) -> None:
    (out / "figs").mkdir(exist_ok=True)
    tit = lambda ax, t: ax.set_title(t, fontsize=9, loc="left", color="#1D1631", weight="bold")
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.2))
    mapa_coropletico(axes[0], capas["municipios"], "lula_2v", lw=0.2)
    tit(axes[0], f"Municípios ({len(capas['municipios'])})")
    mapa_coropletico(axes[1], capas["regioes_imediatas"], "lula_2v", lw=0.6)
    for _, r in capas["regioes_imediatas"].nlargest(12, "electores").iterrows():
        p = r.geometry.representative_point()
        axes[1].annotate(str(r["nombre"])[:16], (p.x, p.y), fontsize=5.5, ha="center", color="#1D1631")
    tit(axes[1], f"Regiões imediatas ({len(capas['regioes_imediatas'])})")
    mapa_coropletico(axes[2], capas["zonas_eleitorais"], "lula_2v", lw=0.3)
    capas["municipios"].boundary.plot(ax=axes[2], color="#1D1631", linewidth=0.15)
    tit(axes[2], f"Zonas eleitorais ({len(capas['zonas_eleitorais'])}, aprox.)")
    from matplotlib.patches import Patch
    et = ["Bolsonaro 70 %+", "Bolsonaro 60–70", "Bolsonaro 50–60", "Lula 50–60", "Lula 60–70", "Lula 70 %+"]
    fig.legend(handles=[Patch(color=c, label=e) for (_, c), e in zip(CORTES, et)], loc="lower center", ncol=6,
               fontsize=7.5, frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout()
    fig.savefig(out / "figs" / "divisiones.svg", format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Capital: área de influencia de cada escuela, con los barrios del IBGE encima si existen
    a = capas["areas_escuelas"]
    a = a[a["cd_municipio_ibge"] == capital_cd]
    loc = capas["locales"]
    loc = loc[loc["cd_municipio_ibge"] == capital_cd]
    fig, ax = plt.subplots(figsize=(6.0, 5.6))
    mapa_coropletico(ax, a, "lula_2v", borde="#FFFFFF", lw=0.15)
    b = capas.get("bairros")
    b = b[b["cd_municipio_ibge"] == capital_cd] if b is not None and len(b) else None
    if b is not None and len(b):
        b.boundary.plot(ax=ax, color="#1D1631", linewidth=0.25)
    # zoom al núcleo urbano: percentiles 8-92 de las escuelas, con margen
    if len(loc) > 10:
        x0, x1 = loc.geometry.x.quantile([0.08, 0.92]); y0, y1 = loc.geometry.y.quantile([0.08, 0.92])
        mx, my = (x1 - x0) * 0.35, (y1 - y0) * 0.35
        ax.set_xlim(x0 - mx, x1 + mx); ax.set_ylim(y0 - my, y1 + my)
    tit(ax, f"Capital: área de cada escuela ({len(a)})" + (f" y {len(b)} barrios" if b is not None and len(b) else ""))
    fig.savefig(out / "figs" / "capital.svg", format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def procesar_uf(uf: str, l22: pd.DataFrame, l18: pd.DataFrame, censo: pd.DataFrame) -> dict:
    out = GEO_DIR / uf
    out.mkdir(parents=True, exist_ok=True)
    malla = gpd.read_file(ultima_malla_uf(uf), columns=COLS_MALLA)
    malla = malla[malla.geometry.notna() & ~malla.geometry.is_empty]
    for c in ("CD_MUN", "CD_DIST", "CD_RGI", "CD_RGINT", "CD_BAIRRO"):
        malla[c] = malla[c].astype(str)
    malla["pop"] = pd.to_numeric(malla["v0001"], errors="coerce").fillna(0)
    malla["area"] = pd.to_numeric(malla["AREA_KM2"].astype(str).str.replace(",", "."), errors="coerce").fillna(0)
    for c in ("NM_RGI", "NM_RGINT", "NM_MUN", "NM_DIST", "NM_BAIRRO"):  # la malla trae el guion largo como "¿"
        malla[c] = malla[c].astype(str).str.replace("¿", "–", regex=False).replace("nan", None)
    nombres = {k: malla.drop_duplicates(cd).set_index(cd)[nm] for k, (cd, nm, _) in NIVELES.items()}
    jer = malla.drop_duplicates("CD_DIST").set_index("CD_DIST")[["CD_MUN", "CD_RGI", "CD_RGINT"]]

    # ---- locales de la UF con gobernador y Censo
    L = l22[l22["uf"] == uf].copy()
    L["cd_ibge"] = L["cd_ibge"].astype("Int64").astype(str)
    gob, nombres_gob = gobernador_por_local(uf)
    L = L.merge(gob, on=LOCAL, how="left").merge(censo.drop(columns=["setores"], errors="ignore"), on=LOCAL, how="left")
    pts = gpd.GeoDataFrame(L, geometry=gpd.points_from_xy(L["lon"], L["lat"]), crs="EPSG:4674")
    con_xy = pts[pts["lat"].notna()]  # incluye centroides de barrio: sirven para asignar distrito y barrio

    # ---- jurisdicciones oficiales: setor -> distrito -> município -> regiones
    capas = {}
    dist = unir(malla, "CD_DIST", NIVELES["distritos"][2])
    sj = gpd.sjoin(con_xy[LOCAL + ["geometry"]], dist.reset_index()[["CD_DIST", "geometry"]], how="left", predicate="within")
    L = L.merge(sj.drop_duplicates(LOCAL)[LOCAL + ["CD_DIST"]], on=LOCAL, how="left")
    L["CD_RGI"] = L["cd_ibge"].map(jer.drop_duplicates("CD_MUN").set_index("CD_MUN")["CD_RGI"])
    L["CD_RGINT"] = L["cd_ibge"].map(jer.drop_duplicates("CD_MUN").set_index("CD_MUN")["CD_RGINT"])
    for capa, (cd, _, tol) in NIVELES.items():
        geo = dist if capa == "distritos" else unir(malla, cd, tol)
        clave_l = {"distritos": "CD_DIST", "municipios": "cd_ibge", "regioes_imediatas": "CD_RGI",
                   "regioes_intermediarias": "CD_RGINT"}[capa]
        m = metricas(L.dropna(subset=[clave_l]), clave_l)
        p = malla.groupby(cd).agg(poblacion=("pop", "sum"), area_km2=("area", "sum"), setores=("CD_SETOR", "size"))
        g = geo.join(p).join(m)
        g.insert(0, "nombre", nombres[capa].reindex(g.index).to_numpy())
        if capa == "distritos":
            g.insert(1, "cd_municipio_ibge", jer.reindex(g.index)["CD_MUN"].to_numpy())
        capas[capa] = g.reset_index().rename(columns={cd: "codigo"})

    # municipios: 2018 (exacto por código) para el cambio
    m18 = l18[l18["uf"] == uf].assign(cd_ibge=lambda x: x["cd_ibge"].astype("Int64").astype(str)).groupby("cd_ibge")[["pt_2", "validos_2"]].sum()
    mu = capas["municipios"]
    mu["haddad_2v_2018"] = mu["codigo"].map(m18["pt_2"] / m18["validos_2"] * 100).round(2)
    mu["cambio_2018_2022"] = (mu["lula_2v"] - mu["haddad_2v_2018"]).round(2)

    # ---- bairros (donde existen)
    mb = malla[(malla["CD_BAIRRO"] != ".") & (malla["CD_BAIRRO"] != "nan")]
    if len(mb):
        bai = unir(mb, "CD_BAIRRO", TOL_BAIRRO)
        sjb = gpd.sjoin(con_xy[LOCAL + ["geometry"]], bai.reset_index()[["CD_BAIRRO", "geometry"]], how="inner", predicate="within")
        Lb = L.merge(sjb.drop_duplicates(LOCAL)[LOCAL + ["CD_BAIRRO"]], on=LOCAL, how="inner")
        p = mb.groupby("CD_BAIRRO").agg(poblacion=("pop", "sum"), area_km2=("area", "sum"), setores=("CD_SETOR", "size"))
        g = bai.join(p).join(metricas(Lb, "CD_BAIRRO") if len(Lb) else None)
        meta_b = mb.drop_duplicates("CD_BAIRRO").set_index("CD_BAIRRO")
        g.insert(0, "nombre", meta_b["NM_BAIRRO"].reindex(g.index).to_numpy())
        g.insert(1, "cd_municipio_ibge", meta_b["CD_MUN"].reindex(g.index).to_numpy())
        g.insert(2, "municipio", meta_b["NM_MUN"].reindex(g.index).to_numpy())
        capas["bairros"] = g.reset_index().rename(columns={"CD_BAIRRO": "codigo"})

    # ---- zonas eleitorais (aproximadas)
    setp = pd.DataFrame({"cd_mun": malla["CD_MUN"].astype(int), "lon": malla.geometry.representative_point().x,
                         "lat": malla.geometry.representative_point().y}, index=malla.index)
    Lz = L.reset_index(drop=True)
    Lz["cd_ibge"] = pd.to_numeric(Lz["cd_ibge"], errors="coerce")
    idx = asignar(setp, Lz)
    malla["zona"] = np.where(idx >= 0, Lz["nr_zona"].reindex(idx.clip(lower=0)).to_numpy(), -1)
    # municípios sin escuelas con coordenadas: sus setores van a la zona con más electores del município
    zona_mun = (Lz.dropna(subset=["cd_ibge"]).sort_values("aptos", ascending=False)
                .drop_duplicates("cd_ibge").set_index("cd_ibge")["nr_zona"])
    sin = malla["zona"] < 0
    malla.loc[sin, "zona"] = malla.loc[sin, "CD_MUN"].astype(int).map(zona_mun).fillna(-1).astype(int).to_numpy()
    zz = unir(malla[malla["zona"] >= 0], "zona", TOL_ZONA)
    pz = malla[malla["zona"] >= 0].groupby("zona").agg(poblacion=("pop", "sum"), area_km2=("area", "sum"), setores=("CD_SETOR", "size"))
    zonas = zz.join(pz).join(metricas(L, "nr_zona"))
    zonas.insert(0, "municipios", L.groupby("nr_zona")["nm_municipio"].agg(lambda s: ", ".join(sorted(set(map(str, s)))[:6])).reindex(zonas.index))
    capas["zonas_eleitorais"] = zonas.reset_index().rename(columns={"zona": "zona"})

    # ---- áreas de influencia de cada escuela (setores asignados a ella): el nivel más fino con polígono
    malla["local_idx"] = idx.to_numpy()
    ae = unir(malla[malla["local_idx"] >= 0], "local_idx", TOL_BAIRRO)
    pa = malla[malla["local_idx"] >= 0].groupby("local_idx").agg(poblacion=("pop", "sum"), area_km2=("area", "sum"),
                                                                 setores=("CD_SETOR", "size"))
    claves = Lz.loc[ae.index, LOCAL + ["nm_local", "nm_municipio"]]
    ma = metricas(L, LOCAL).reindex(pd.MultiIndex.from_frame(claves[LOCAL]))
    areas = ae.join(pa)
    for c in LOCAL + ["nm_local", "nm_municipio"]:
        areas[c] = claves[c].to_numpy()
    areas["cd_municipio_ibge"] = Lz.loc[ae.index, "cd_ibge"].astype("Int64").astype(str).to_numpy()
    for c in ma.columns:
        areas[c] = ma[c].to_numpy()
    capas["areas_escuelas"] = areas.reset_index(drop=True)

    # ---- puntos: locales y secciones
    loc = gpd.GeoDataFrame(L, geometry=gpd.points_from_xy(L["lon"], L["lat"]), crs="EPSG:4674")
    loc = loc[loc["lat"].notna()].copy()
    m = metricas(L, LOCAL)
    cols_p = LOCAL + ["nm_local", "bairro", "nm_municipio", "cd_ibge"] + (["coord_origen"] if "coord_origen" in loc else [])
    loc = loc[cols_p + ["geometry"]].merge(m.reset_index(), on=LOCAL)
    for c in ["alfabetizacion", "preta_parda", "banos_2mas", "cloaca_red", "mayores_60", "urbano", "pop"]:
        if c in L:
            loc[c if c == "pop" else f"censo_{c}"] = L.set_index(LOCAL).reindex(loc.set_index(LOCAL).index)[c].round(4).to_numpy()
    loc = loc.rename(columns={"cd_ibge": "cd_municipio_ibge", "pop": "poblacion_area_influencia"})
    capas["locales"] = loc
    sec = pd.read_parquet(salida_pres(2022), filters=[("uf", "==", uf)])
    sec = sec.pivot_table(index=["cd_municipio", "nr_zona", "nr_secao", "nr_local"], columns="turno",
                          values=["v_13", "v_22", "comparecencia"], aggfunc="sum")
    sec.columns = [f"{'lula' if v == 'v_13' else 'bolsonaro' if v == 'v_22' else 'comparecencia'}_{t}v" for v, t in sec.columns]
    sec = sec.reset_index().merge(L[["cd_municipio", "nr_zona", "nr_local", "nm_local", "nm_municipio", "lat", "lon"]],
                                  on=["cd_municipio", "nr_zona", "nr_local"], how="left")
    sec.to_csv(out / "secciones.csv", index=False, float_format="%.6f")

    # ---- escritura
    gpkg = out / f"{uf}.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    resumen = {"uf": uf, "gobernador_2022": nombres_gob, "capas": {}}
    for nombre, g in capas.items():
        g = gpd.GeoDataFrame(g, geometry="geometry", crs="EPSG:4674")
        g4 = g.to_crs("EPSG:4326")
        g4.to_file(out / f"{nombre}.geojson", driver="GeoJSON", layer_options={"COORDINATE_PRECISION": 6, "RFC7946": "YES"})
        g.to_file(gpkg, layer=nombre, driver="GPKG")
        resumen["capas"][nombre] = {"n": int(len(g)), "mb": round((out / f"{nombre}.geojson").stat().st_size / 1e6, 1)}
    resumen["secciones"] = int(len(sec))
    capital = mu.sort_values("electores", ascending=False)["codigo"].iloc[0]
    resumen["capital_cd"] = capital
    figuras(uf, capas, out, capital)
    # tablas para el informe
    resumen["regioes_intermediarias"] = capas["regioes_intermediarias"].drop(columns="geometry").sort_values(
        "electores", ascending=False).to_dict(orient="records")
    resumen["zonas_top"] = capas["zonas_eleitorais"].drop(columns="geometry").sort_values("electores", ascending=False).head(8).to_dict(orient="records")
    if "bairros" in capas:
        bc = capas["bairros"][capas["bairros"]["cd_municipio_ibge"] == capital].dropna(subset=["lula_2v"])
        bc = bc[bc["electores"] >= 2000]
        resumen["bairros_capital"] = {"n": int((capas["bairros"]["cd_municipio_ibge"] == capital).sum()),
                                      "mas_lula": bc.nlargest(4, "lula_2v")[["nombre", "lula_2v", "electores"]].to_dict(orient="records"),
                                      "menos_lula": bc.nsmallest(4, "lula_2v")[["nombre", "lula_2v", "electores"]].to_dict(orient="records")}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                                      encoding="utf-8")
    log.info("%s: %s", uf, ", ".join(f"{k} {v['n']} ({v['mb']} MB)" for k, v in resumen["capas"].items()))
    return resumen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", nargs="+", default=UFS)
    args = parser.parse_args()
    l22, l18 = cargar(2022, 0), cargar(2018, 0)
    censo = pd.read_parquet(LOCALES_CENSO)
    for uf in args.uf:
        procesar_uf(uf, l22, l18, censo)


if __name__ == "__main__":
    main()
