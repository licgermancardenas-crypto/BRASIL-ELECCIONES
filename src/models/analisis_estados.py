"""
src/models/analisis_estados.py

Análisis mesa por mesa ESTADO POR ESTADO (27 UF): presidente y gobernador
2018/2022, con el local de votación como unidad y la sección (mesa) para
detectar urnas atípicas. Alimenta el informe de 27 capítulos
(src/viz/informe_estados_pdf.py).

Por UF:
  - presidencial: mapa por local, municípios principales, cambio 2018->2022,
    transferencias 1ª->2ª vuelta de la UF, abstención;
  - gobernador 2022 (y ganador 2018): resultado, mapa por local de los dos
    primeros, voto cruzado con el presidencial (correlación por local y locales
    donde gana un bando distinto en cada cargo), transferencias si hubo 2ª vuelta;
  - Censo: tipos de territorio (tipología nacional) y qué explica el voto
    dentro de la UF;
  - mesas atípicas: secciones cuyo % de Lula se aparta mucho del resto de su
    escuela (z robusto > 4). Atípica no quiere decir irregular: suele ser una
    sección especial (cárcel, hospital, aldea) o una urna muy chica.

Insumos: bases de src.etl.transform (presidente_seccion, gobernador_seccion,
locales_{ano}), Censo por local (src.geo.censo_locales) y la última corrida
de src.models.analisis_seccion (tipología). Salida:
data/processed/electoral/seccion/estados/<fecha_utc>/{datos.json, figs/<UF>_*.svg}

Uso:
    python -m src.models.analisis_estados [--uf SP RJ]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from src.etl.extract.tse_extractor import UFS, ultima_version
from src.etl.transform.base_locales import LOCAL
from src.etl.transform.lector_tse import leer_zip_tse
from src.etl.transform.votacion_seccion import SALIDA_DIR, salida as salida_pres, salida_gobernador
from src.models.analisis_seccion import (ANALISIS_DIR, CENSO, INK, LOCALES_CENSO, MUTED, VIO, cargar, color_lula, limpiar,
                                         mapa, por_municipio, transferencias)
from src.models.bloques.resolver_familia import familia
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ESTADOS_DIR = SALIDA_DIR / "estados"
NOMBRE_UF = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
             "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
             "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
             "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
             "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
             "TO": "Tocantins"}
C_G1, C_G2 = VIO, "#EDA100"
Z_ATIPICA = 4.0


def nombre_propio(s: str) -> str:
    t = str(s).title()
    for x in (" De ", " Da ", " Do ", " Dos ", " Das ", " E "):
        t = t.replace(x, x.lower())
    return t


# ---------------------------------------------------------------------------
# Gobernador por local
# ---------------------------------------------------------------------------

def candidatos_gobernador(ano: int) -> pd.DataFrame:
    c = leer_zip_tse(ultima_version("candidatos", ano), columnas=["SG_UF", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"],
                     filtro={"DS_CARGO": {"GOVERNADOR"}})
    c = c.drop_duplicates(["SG_UF", "NR_CANDIDATO"]).rename(columns={"SG_UF": "uf", "NR_CANDIDATO": "nr",
                                                                    "NM_URNA_CANDIDATO": "nombre", "SG_PARTIDO": "partido"})
    c["nr"] = c["nr"].astype(int)
    c["familia"] = [familia(p, ano) for p in c["partido"]]
    return c[["uf", "nr", "nombre", "partido", "familia"]]


def gobernador_locales(ano: int, aptos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(votos a gobernador por local y vuelta con columnas g1/g2/otros/blanco_nulo/abstencion, resumen por UF)."""
    g = pd.read_parquet(salida_gobernador(ano))
    cand = candidatos_gobernador(ano).set_index(["uf", "nr"])
    filas, resumen = [], []
    for uf, x in g.groupby("uf"):
        cols = [c for c in x.columns if c.startswith("v_") and x[c].sum() > 0]
        t1 = x[x["turno"] == 1][cols].sum()
        validos = t1.drop(["v_95", "v_96"], errors="ignore")
        top = validos.nlargest(2).index.tolist()
        hay_2v = (x["turno"] == 2).any()
        t2 = x[x["turno"] == 2][cols].sum() if hay_2v else None
        ganador = (t2.drop(["v_95", "v_96"], errors="ignore").idxmax() if hay_2v else top[0])
        info = lambda c: cand.loc[(uf, int(c[2:]))].to_dict() if (uf, int(c[2:])) in cand.index else {"nombre": c, "partido": "?", "familia": "?"}
        resumen.append({"uf": uf, "segunda_vuelta": bool(hay_2v), "ganador": info(ganador) | {"nr": int(ganador[2:])},
                        "candidatos_1v": [info(c) | {"nr": int(c[2:]), "pct": float(validos[c] / validos.sum() * 100)}
                                          for c in validos.nlargest(5).index],
                        "candidatos_2v": ([info(c) | {"nr": int(c[2:]), "pct": float(v / t2.drop(["v_95", "v_96"], errors="ignore").sum() * 100)}
                                           for c, v in t2.drop(["v_95", "v_96"], errors="ignore").nlargest(2).items()]
                                          if hay_2v else []),
                        "top": [int(c[2:]) for c in top]})
        for turno, y in x.groupby("turno"):
            loc = y.groupby(LOCAL)[cols].sum()
            out = pd.DataFrame(index=loc.index)
            out["g1"], out["g2"] = loc[top[0]], loc[top[1]]
            bn = [c for c in ("v_95", "v_96") if c in loc]
            out["blanco_nulo"] = loc[bn].sum(axis=1)
            out["otros"] = loc[cols].sum(axis=1) - out["g1"] - out["g2"] - out["blanco_nulo"]
            out.columns = [f"{c}_{turno}" for c in out.columns]
            filas.append(out)
    # Unir vueltas por local
    v1 = pd.concat([f for f in filas if f.columns[0].endswith("_1")])
    v2 = pd.concat([f for f in filas if f.columns[0].endswith("_2")]) if any(f.columns[0].endswith("_2") for f in filas) else None
    gl = v1.join(v2, how="left") if v2 is not None else v1
    gl = gl.reset_index().merge(aptos, on=LOCAL, how="left")
    for t in (1, 2):
        if f"g1_{t}" in gl:
            comp = gl[[f"g1_{t}", f"g2_{t}", f"otros_{t}", f"blanco_nulo_{t}"]].sum(axis=1)
            gl[f"abstencion_{t}"] = (gl["aptos"] - comp).clip(lower=0)
    return gl, pd.DataFrame(resumen).set_index("uf")


# ---------------------------------------------------------------------------
# Mesas atípicas
# ---------------------------------------------------------------------------

def secciones_atipicas(ano: int = 2022) -> pd.DataFrame:
    """Secciones de la 2ª vuelta presidencial con |z| > Z_ATIPICA respecto del resto de su local.
    z = (p_sección − p_resto_local) / sqrt(p(1−p)/n + tau²), tau² = varianza entre secciones de un mismo
    local que no se explica por el azar (estimada en todo el país)."""
    s = pd.read_parquet(salida_pres(ano))
    s = s[(s["turno"] == 2) & (s["uf"] != "ZZ")].copy()
    s["n"] = s["v_13"] + s["v_22"]
    s = s[s["n"] > 0]
    g = s.groupby(LOCAL)
    s["n_loc"], s["l_loc"], s["k"] = g["n"].transform("sum"), g["v_13"].transform("sum"), g["n"].transform("size")
    s = s[s["k"] >= 3]
    p = s["v_13"] / s["n"]
    resto = (s["l_loc"] - s["v_13"]) / (s["n_loc"] - s["n"])
    var_bin = resto * (1 - resto) / s["n"]
    resid = p - resto
    tau2 = max(float(np.median(resid ** 2) / 0.455 - np.median(var_bin)), 0.0)  # mediana de chi²(1) ≈ 0,455
    s["z"] = resid / np.sqrt(var_bin + tau2)
    s["lula_seccion"], s["lula_resto_local"] = p * 100, resto * 100
    out = s[s["z"].abs() > Z_ATIPICA][LOCAL + ["nr_secao", "nm_local", "n", "lula_seccion", "lula_resto_local", "z"]]
    log.info("Mesas atípicas (|z| > %.0f): %d de %s (tau = %.1f pp)", Z_ATIPICA, len(out), f"{len(s):,}", np.sqrt(tau2) * 100)
    return out, len(s), float(np.sqrt(tau2) * 100)


# ---------------------------------------------------------------------------
# Figuras por UF
# ---------------------------------------------------------------------------

def fig_mapa_uf(g: pd.DataFrame, uf: str, ruta) -> None:
    g = g.dropna(subset=["lat", "lon"])
    lat, lon = g["lat"], g["lon"]
    lo_lat, hi_lat = lat.quantile([0.002, 0.998])
    lo_lon, hi_lon = lon.quantile([0.002, 0.998])
    g = g[lat.between(lo_lat, hi_lat) & lon.between(lo_lon, hi_lon)]
    ancho, alto = hi_lon - lo_lon, hi_lat - lo_lat
    fig, ax = plt.subplots(figsize=(6.2, 6.2 * min(max(alto / max(ancho, 1e-6), 0.55), 1.35)))
    s = float(np.clip(18000 / max(len(g), 1), 1.0, 14))
    mapa(ax, g, s)
    et = ["Bolsonaro 70 % o más", "Bolsonaro 60–70 %", "Bolsonaro 50–60 %", "Lula 50–60 %", "Lula 60–70 %", "Lula 70 % o más"]
    cols = ["#1C5CAB", "#5598E7", "#B7D3F6", "#F6B9B8", "#EA7372", "#B42322"]
    ax.legend(handles=[Patch(color=c, label=e) for c, e in zip(cols, et)], loc="upper center", bbox_to_anchor=(0.5, -0.01),
              ncol=3, fontsize=7, frameon=False)
    fig.savefig(ruta, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_gobernador(gg: pd.DataFrame, n1: str, n2: str, ruta) -> None:
    g = gg.dropna(subset=["lat", "lon"]).copy()
    v = g["g1_1"] + g["g2_1"]
    g = g[v > 0]
    m = (g["g1_1"] - g["g2_1"]) / (g["g1_1"] + g["g2_1"])
    lat, lon = g["lat"], g["lon"]
    q = lambda s: s.quantile([0.002, 0.998])
    (a, b), (c, d) = q(lat), q(lon)
    g, m = g[lat.between(a, b) & lon.between(c, d)], m[lat.between(a, b) & lon.between(c, d)]
    alto, ancho = b - a, d - c
    fig, ax = plt.subplots(figsize=(6.2, 6.2 * min(max(alto / max(ancho, 1e-6), 0.55), 1.35)))
    cortes = [(-0.4, "#B5760A"), (-0.15, "#EDA100"), (0, "#F7D58C"), (0.15, "#CFC3EA"), (0.4, "#8E74C8"), (1.01, "#4A2F87")]
    col = [next(cc for lim, cc in cortes if x < lim) for x in m]
    ax.scatter(g["lon"], g["lat"], s=float(np.clip(18000 / max(len(g), 1), 1.0, 14)), c=col, linewidths=0, rasterized=True)
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    et = [f"{n2} +40", f"{n2} +15 a +40", f"{n2} hasta +15", f"{n1} hasta +15", f"{n1} +15 a +40", f"{n1} +40"]
    ax.legend(handles=[Patch(color=cc, label=e) for (_, cc), e in zip(cortes, et)], loc="upper center",
              bbox_to_anchor=(0.5, -0.01), ncol=3, fontsize=7, frameon=False)
    fig.savefig(ruta, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_cruzado(x: pd.Series, y: pd.Series, w: pd.Series, n1: str, ruta) -> None:
    fig, ax = plt.subplots(figsize=(4.6, 3.6))
    ax.scatter(x * 100, y * 100, s=np.clip(w / w.max() * 40, 2, 40), color=VIO, alpha=0.25, linewidths=0, rasterized=True)
    ax.axvline(50, color="#BBBBBB", lw=1, ls="--"); ax.axhline(50, color="#BBBBBB", lw=1, ls="--")
    ax.set_xlabel("% Lula en el local (2ª vuelta 2022)", fontsize=8.5)
    ax.set_ylabel(f"% {n1} (gobernador, 1ª vuelta)", fontsize=8.5)
    ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    limpiar(ax, grid="both")
    fig.savefig(ruta, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None):
    import statsmodels.api as sm

    parser = argparse.ArgumentParser()
    parser.add_argument("--uf", nargs="+", default=UFS)
    args = parser.parse_args(argv)
    cfg = cargar_config()["seccion"]
    out = ESTADOS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    (out / "figs").mkdir(parents=True)

    l18, l22 = cargar(2018, cfg["min_aptos_local"]), cargar(2022, cfg["min_aptos_local"])
    m = por_municipio(l18).join(por_municipio(l22), lsuffix="_18", rsuffix="_22", how="inner")
    m["cambio"] = (m["pt2_pct_22"] - m["pt2_pct_18"]) * 100
    aptos = l22[LOCAL + ["aptos", "lat", "lon", "chico", "nm_municipio"]]
    gob22, res22 = gobernador_locales(2022, aptos)
    try:
        _, res18 = gobernador_locales(2018, l18[LOCAL + ["aptos", "lat", "lon", "chico", "nm_municipio"]])
    except FileNotFoundError:
        log.warning("Sin gobernador 2018 por sección: los capítulos no mencionan al ganador 2018")
        res18 = pd.DataFrame()
    gob22["chico"] = gob22["chico"].fillna(True)
    censo = pd.read_parquet(LOCALES_CENSO)
    tipos_dir = sorted(p.parent for p in ANALISIS_DIR.glob("*/tipos_locales.parquet"))[-1]
    tipos = pd.read_parquet(tipos_dir / "tipos_locales.parquet")
    perfiles = {t["tipo"]: t for t in json.loads((tipos_dir / "datos.json").read_text(encoding="utf-8"))["tipos"]}
    atip, n_secciones, tau = secciones_atipicas()
    gsim = sorted(p.parent for p in (ELECTORAL_DIR / "gobernadores_sim").glob("*/meta.json"))[-1]
    prob26 = pd.read_csv(gsim / "probabilidad_uf.csv")

    o22 = ["pt", "bolsonaro", "ciro", "tebet", "otros", "blanco_nulo", "abstencion"]
    dest = ["pt", "bolsonaro", "blanco_nulo", "abstencion"]
    T, T_uf = transferencias(l22, o22, dest)
    g22 = l22[~l22["chico"]]
    datos = {"_nacional": {"secciones_analizadas_atipicas": n_secciones, "tau_pp": tau, "atipicas": len(atip),
                           "abst_2": float(g22["abstencion_2"].sum() / g22["aptos"].sum() * 100),
                           "lula_2v": float(g22["pt_2"].sum() / g22["validos_2"].sum() * 100),
                           "tipos": {int(k): v for k, v in perfiles.items()}, "tipologia_de": tipos_dir.name}}

    for uf in args.uf:
        L = l22[(l22["uf"] == uf) & ~l22["chico"]].merge(censo, on=LOCAL, how="left").merge(tipos, on=LOCAL, how="left")
        L18 = l18[(l18["uf"] == uf) & ~l18["chico"]]
        G = gob22[(gob22["uf"] == uf) & ~gob22["chico"]].merge(L[LOCAL + ["lula_pct", "validos_2"]], on=LOCAL, how="inner")
        r22, r18 = res22.loc[uf], res18.loc[uf] if uf in res18.index else None
        d = {"nombre": NOMBRE_UF[uf], "locales": len(L), "secciones": int(L["secciones"].sum()), "electores": int(L["aptos"].sum()),
             "municipios": int(L["cd_municipio"].nunique()),
             "lula_2v": float(L["pt_2"].sum() / L["validos_2"].sum() * 100),
             "lula_1v": float(L["pt_1"].sum() / L["validos_1"].sum() * 100),
             "bolsonaro_1v": float(L["bolsonaro_1"].sum() / L["validos_1"].sum() * 100),
             "haddad_2v_2018": float(L18["pt_2"].sum() / L18["validos_2"].sum() * 100),
             "abst_2": float(L["abstencion_2"].sum() / L["aptos"].sum() * 100),
             "lula_gana_locales": float((L["lula_pct"] > 0.5).mean() * 100)}
        d["cambio"] = d["lula_2v"] - d["haddad_2v_2018"]
        mm = m.loc[uf].sort_values("aptos_22", ascending=False).head(8)
        d["municipios_clave"] = [{"municipio": nombre_propio(r.nm_22), "electores": int(r.aptos_22), "lula": float(r.pt2_pct_22 * 100),
                                  "cambio": float(r.cambio)} for r in mm.itertuples()]
        # capital = município con más electores
        fig_mapa_uf(L, uf, out / "figs" / f"{uf}_mapa.svg")

        # Transferencias presidenciales de la UF
        Tu = T_uf[uf]
        a_l = lambda o: float(Tu.loc[o, "pt"] / max(Tu.loc[o, "pt"] + Tu.loc[o, "bolsonaro"], 1e-9))
        d["transfer"] = {"ciro_a_lula": a_l("ciro"), "tebet_a_lula": a_l("tebet"),
                         "ciro_pct_1v": float(L["ciro_1"].sum() / L["validos_1"].sum() * 100),
                         "tebet_pct_1v": float(L["tebet_1"].sum() / L["validos_1"].sum() * 100),
                         "abst_se_queda": float(Tu.loc["abstencion", "abstencion"])}

        # Gobernador
        n1 = nombre_propio(r22["candidatos_1v"][0]["nombre"]); n2 = nombre_propio(r22["candidatos_1v"][1]["nombre"])
        d["gob"] = {"segunda_vuelta": bool(r22["segunda_vuelta"]), "ganador": r22["ganador"], "candidatos_1v": r22["candidatos_1v"],
                    "candidatos_2v": r22["candidatos_2v"], "ganador_2018": (r18["ganador"] if r18 is not None else None)}
        G1 = G[(G["g1_1"] + G["g2_1"]) > 0]
        val1 = G1[["g1_1", "g2_1", "otros_1"]].sum(axis=1)
        p1 = G1["g1_1"] / val1
        corr1 = float(np.corrcoef(G1["lula_pct"], p1)[0, 1]) if len(G1) > 5 else float("nan")
        p2g = G1["g2_1"] / val1
        corr2 = float(np.corrcoef(G1["lula_pct"], p2g)[0, 1]) if len(G1) > 5 else float("nan")
        # Bando del gobernador alineado con Lula = el de mayor correlación positiva
        alineado_1 = corr1 >= corr2
        gana_g_lulista = (G1["g1_1"] > G1["g2_1"]) == alineado_1
        # Solo tiene sentido si los dos primeros se reparten los bandos presidenciales: correlaciones con Lula de
        # signo opuesto y ninguna débil. Si no (ej. AM: ambos positivos), no se calcula.
        separa = (corr1 * corr2 < 0) and min(abs(corr1), abs(corr2)) >= 0.2
        cruzado = float(((G1["lula_pct"] > 0.5) != gana_g_lulista).mean() * 100) if separa else None
        d["gob"].update({"corr_g1_lula": corr1, "corr_g2_lula": corr2, "locales_voto_cruzado_pct": cruzado,
                         "g1_gana_locales_pct": float((G1["g1_1"] > G1["g2_1"]).mean() * 100)})
        fig_gobernador(G, n1, n2, out / "figs" / f"{uf}_gobernador.svg")
        fig_cruzado(G1["lula_pct"], p1, G1["validos_2"], n1, out / "figs" / f"{uf}_cruzado.svg")
        if r22["segunda_vuelta"] and "g1_2" in G:
            Gt = G.dropna(subset=["g1_2"]).copy()
            Gt["uf"] = uf
            Gt["chico"] = False
            Tg, _ = transferencias(Gt, ["g1", "g2", "otros", "blanco_nulo", "abstencion"], ["g1", "g2", "blanco_nulo", "abstencion"])
            d["gob"]["transfer_otros"] = {k: float(v) for k, v in Tg.loc["otros"].items()}

        # Gobernador 2026 (modelo estructural)
        p26 = prob26[prob26["uf"] == uf].sort_values("prob_ganar", ascending=False)
        d["gob_2026"] = [{"nombre": nombre_propio(r.nombre), "familia": r.familia, "incumbente": bool(r.incumbente),
                          "prob": float(r.prob_ganar)} for r in p26.head(3).itertuples()]
        d["gob_2026_balotaje"] = float(p26["prob_balotaje_uf"].iloc[0]) if len(p26) else None

        # Censo dentro de la UF y tipos
        C = L.dropna(subset=[v for v, _ in CENSO])
        if len(C) > 40:
            X = C[[v for v, _ in CENSO]]
            sd = X.std().replace(0, np.nan)
            Z = ((X - X.mean()) / sd).dropna(axis=1)
            y = (C["lula_pct"] - C["lula_pct"].mean()) / C["lula_pct"].std()
            r = sm.WLS(y, sm.add_constant(Z), weights=C["validos_2"]).fit()
            d["reg"] = {"n": len(C), "r2": float(r.rsquared), "beta": {k: float(v) for k, v in r.params.drop("const").items()}}
        tp = L.dropna(subset=["tipo"]).groupby("tipo").agg(electores=("aptos", "sum"), pt=("pt_2", "sum"), val=("validos_2", "sum"))
        d["tipos"] = {int(t): {"electores_pct": float(x.electores / tp["electores"].sum() * 100), "lula": float(x.pt / x.val * 100)}
                      for t, x in tp.iterrows()}

        # Mesas atípicas
        a = atip[atip["uf"] == uf].sort_values("z", key=abs, ascending=False)
        d["atipicas"] = {"n": len(a), "por_mil": float(len(a) / max(d["secciones"], 1) * 1000),
                         "top": [{"municipio": nombre_propio(L.loc[L["cd_municipio"] == r.cd_municipio, "nm_municipio"].iloc[0])
                                  if (L["cd_municipio"] == r.cd_municipio).any() else str(r.cd_municipio),
                                  "zona": int(r.nr_zona), "seccion": int(r.nr_secao), "local": nombre_propio(r.nm_local),
                                  "votos": int(r.n), "lula_seccion": float(r.lula_seccion), "lula_resto": float(r.lula_resto_local),
                                  "z": float(r.z)} for r in a.head(5).itertuples()]}
        datos[uf] = d
        log.info("%s: Lula %.1f%% | gob %s %s | cruzado %s | atípicas %d", uf, d["lula_2v"], nombre_propio(r22["ganador"]["nombre"]),
                 "(2ª vuelta)" if r22["segunda_vuelta"] else "", "—" if cruzado is None else f"{cruzado:.0f}%", len(a))

    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        raise TypeError(type(o))
    (out / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=conv), encoding="utf-8")
    log.info("Listo: %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
