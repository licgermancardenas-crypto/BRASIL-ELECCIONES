"""
src/models/analisis_seccion.py

Análisis mesa por mesa de la elección presidencial (2018 y 2022), con el
local de votación como unidad (como el circuito en el informe de CABA).

Bloques (cada uno deja cifras en datos.json y su figura en figs/):
  1. Distribución del voto por local y cuánto se explica por UF, por
     município y dentro del município (descomposición de la varianza).
  2. Mapa: cada local de votación ubicado por sus coordenadas (TSE).
  3. Cambio 2018 -> 2022 por município (los locales cambian de número).
  4. Transferencias entre vueltas (regresión ecológica con restricciones,
     por UF): a dónde fueron los votantes de Ciro, Tebet, blanco y abstención.
  5. Cohortes: municípios agrupados por su voto PT en 2018, seguidos hasta 2022.
  6. Abstención: dónde se vota menos y si cambia entre vueltas.
  7. Censo 2022 (si está la base locales_censo): qué explica el voto y
     tipología de territorios (src.geo.censo_locales).
  8. Implicancias para 2026: la matriz de transferencias de 2022 aplicada al
     agregado de encuestas de 1ª vuelta.

Parámetros: config/modelo.yaml, sección `seccion`.
Salida: data/processed/electoral/seccion/analisis/<fecha_utc>/{datos.json, figs/*.svg}

Uso:
    python -m src.models.analisis_seccion
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.etl.transform.base_locales import salida as salida_locales
from src.etl.transform.votacion_seccion import SALIDA_DIR
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ANALISIS_DIR = SALIDA_DIR / "analisis"
LOCALES_CENSO = SALIDA_DIR / "locales_censo_2022.parquet"
INK, MUTED, VIO, RULE = "#1D1631", "#6B6480", "#5B3F99", "#D9D2E6"
C_PT, C_BOL = "#E34948", "#2A78D6"
REGION = {**dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "Norte"),
          **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "Nordeste"),
          **dict.fromkeys(["DF", "GO", "MS", "MT"], "Centro-Oeste"),
          **dict.fromkeys(["ES", "MG", "RJ", "SP"], "Sudeste"),
          **dict.fromkeys(["PR", "RS", "SC"], "Sul"), "ZZ": "Exterior"}
ETQ = {"pt": "PT", "bolsonaro": "Bolsonaro", "ciro": "Ciro", "tebet": "Tebet", "centro": "Centro (Alckmin y otros)",
       "otros": "Otros", "blanco_nulo": "Blanco/nulo", "abstencion": "Abstención"}

plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none", "axes.edgecolor": "#BBBBBB",
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})


def limpiar(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid:
        ax.grid(axis=grid, color="#EEEEEE", zorder=0)
    ax.tick_params(labelsize=8.5)


class Salida:
    def __init__(self):
        self.dir = ANALISIS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        (self.dir / "figs").mkdir(parents=True)
        self.d: dict = {}

    def fig(self, fig, nombre):
        fig.savefig(self.dir / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
        plt.close(fig)

    def guardar(self):
        def conv(o):
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            raise TypeError(type(o))
        (self.dir / "datos.json").write_text(json.dumps(self.d, ensure_ascii=False, indent=1, default=conv), encoding="utf-8")


def cargar(ano: int, min_aptos: int) -> pd.DataFrame:
    loc = pd.read_parquet(salida_locales(ano))
    loc = loc[loc["uf"] != "ZZ"].copy()
    loc["region"] = loc["uf"].map(REGION)
    for t in (1, 2):
        val = loc[[c for c in loc.columns if c.endswith(f"_{t}") and not c.startswith(("blanco", "abst", "compar"))]].sum(axis=1)
        loc[f"validos_{t}"] = val
    loc["pt_2"] = loc["pt_2"].astype(float)
    loc["lula_pct"] = loc["pt_2"] / loc["validos_2"]
    loc["pt1_pct"] = loc["pt_1"] / loc["validos_1"]
    loc["bol1_pct"] = loc["bolsonaro_1"] / loc["validos_1"]
    loc["abst_1"] = loc["abstencion_1"] / loc["aptos"]
    loc["abst_2"] = loc["abstencion_2"] / loc["aptos"]
    loc["chico"] = loc["aptos"] < min_aptos
    return loc


# ---------------------------------------------------------------------------
# 1. Distribución y descomposición de la varianza
# ---------------------------------------------------------------------------

def descomposicion(loc: pd.DataFrame, col: str, peso: str) -> dict:
    """Parte de la varianza (ponderada) de `col` entre UF, entre municípios de una UF y dentro del município."""
    w = loc[peso].to_numpy(float)
    y = loc[col].to_numpy(float)
    media = np.average(y, weights=w)
    tot = np.average((y - media) ** 2, weights=w)
    m_uf = loc.groupby("uf").apply(lambda g: np.average(g[col], weights=g[peso]), include_groups=False)
    m_mun = loc.groupby("cd_municipio").apply(lambda g: np.average(g[col], weights=g[peso]), include_groups=False)
    y_uf = loc["uf"].map(m_uf).to_numpy()
    y_mun = loc["cd_municipio"].map(m_mun).to_numpy()
    entre_uf = np.average((y_uf - media) ** 2, weights=w)
    entre_mun = np.average((y_mun - y_uf) ** 2, weights=w)
    dentro = np.average((y - y_mun) ** 2, weights=w)
    return {"total_desvio_pp": float(np.sqrt(tot) * 100), "entre_uf": entre_uf / tot, "entre_municipios": entre_mun / tot,
            "dentro_municipio": dentro / tot}


def bloque_distribucion(S: Salida, l22: pd.DataFrame) -> None:
    g = l22[~l22["chico"]]
    pct = g["lula_pct"] * 100
    S.d["dist"] = {
        "locales": len(l22), "locales_analizados": len(g), "secciones": int(l22["secciones"].sum()),
        "electores": int(l22["aptos"].sum()),
        "lula_gana_locales": int((g["lula_pct"] > 0.5).sum()), "p10": float(pct.quantile(.1)), "p90": float(pct.quantile(.9)),
        "min": float(pct.min()), "max": float(pct.max()),
        "locales_80_lula": int((g["lula_pct"] >= 0.8).sum()), "locales_80_bolsonaro": int((g["lula_pct"] <= 0.2).sum()),
        "por_region": {r: float(np.average(x["lula_pct"], weights=x["validos_2"]) * 100)
                       for r, x in g.groupby("region")},
        "varianza": descomposicion(g, "lula_pct", "validos_2"),
    }
    fig, ax = plt.subplots(figsize=(6.8, 3.0))
    bins = np.arange(0, 101, 2)
    h, _ = np.histogram(pct, bins=bins, weights=g["validos_2"] / 1e6)
    ax.bar(bins[:-1] + 1, h, width=1.8, color=[C_PT if b >= 50 else C_BOL for b in bins[:-1]], zorder=3)
    ax.axvline(50, color=INK, lw=1, ls="--", zorder=4)
    ax.set_xlabel("% de Lula en el local de votación (2ª vuelta 2022, votos válidos)", fontsize=8.5)
    ax.set_ylabel("Millones de votos válidos", fontsize=8.5)
    ax.set_xlim(0, 100)
    limpiar(ax)
    S.fig(fig, "distribucion.svg")


# ---------------------------------------------------------------------------
# 2. Mapa de locales
# ---------------------------------------------------------------------------

def color_lula(p: np.ndarray) -> list:
    cortes = [(0.3, "#1C5CAB"), (0.4, "#5598E7"), (0.5, "#B7D3F6"), (0.6, "#F6B9B8"), (0.7, "#EA7372"), (1.01, "#B42322")]
    return [next(c for lim, c in cortes if v < lim) for v in p]


def mapa(ax, g: pd.DataFrame, s: float, titulo: str | None = None):
    g = g.dropna(subset=["lat", "lon"]).sort_values("validos_2")
    ax.scatter(g["lon"], g["lat"], s=s, c=color_lula(g["lula_pct"].to_numpy()), linewidths=0, rasterized=True)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    if titulo:
        ax.set_title(titulo, fontsize=9, color=INK, loc="left", weight="bold")


def bloque_mapa(S: Salida, l22: pd.DataFrame) -> None:
    g = l22[~l22["chico"]]
    g = g[(g["lat"].between(-34, 6)) & (g["lon"].between(-74, -34))]
    fig, ax = plt.subplots(figsize=(7.0, 7.0))
    mapa(ax, g, 1.2)
    from matplotlib.patches import Patch
    et = ["Bolsonaro 70 % o más", "Bolsonaro 60–70 %", "Bolsonaro 50–60 %", "Lula 50–60 %", "Lula 60–70 %", "Lula 70 % o más"]
    cols = ["#1C5CAB", "#5598E7", "#B7D3F6", "#F6B9B8", "#EA7372", "#B42322"]
    ax.legend(handles=[Patch(color=c, label=e) for c, e in zip(cols, et)], loc="lower left", fontsize=7.5, frameon=False)
    S.fig(fig, "mapa_brasil.svg")
    S.d["mapa"] = {"locales_con_coordenadas": int(len(g)), "de": int(len(l22[~l22["chico"]]))}

    # Zoom a las dos metrópolis más grandes
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.4))
    for ax, (nombre, (x0, x1, y0, y1)) in zip(axes, {"São Paulo (región metropolitana)": (-47.0, -46.2, -23.85, -23.35),
                                                     "Rio de Janeiro (región metropolitana)": (-43.8, -42.95, -23.05, -22.6)}.items()):
        z = g[g["lon"].between(x0, x1) & g["lat"].between(y0, y1)]
        mapa(ax, z, 6, nombre)
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
        S.d["mapa"][nombre] = {"locales": len(z), "lula_pct": float(z["pt_2"].sum() / z["validos_2"].sum() * 100)}
    S.fig(fig, "mapa_metropolis.svg")


# ---------------------------------------------------------------------------
# 3. Cambio 2018 -> 2022 por município
# ---------------------------------------------------------------------------

def por_municipio(loc: pd.DataFrame) -> pd.DataFrame:
    m = loc.groupby(["uf", "cd_municipio"]).agg(nm=("nm_municipio", "first"), aptos=("aptos", "sum"),
                                                pt_1=("pt_1", "sum"), pt_2=("pt_2", "sum"), bol_1=("bolsonaro_1", "sum"),
                                                validos_1=("validos_1", "sum"), validos_2=("validos_2", "sum"),
                                                abst_1=("abstencion_1", "sum"), abst_2=("abstencion_2", "sum"))
    m["pt2_pct"] = m["pt_2"] / m["validos_2"]
    m["pt1_pct"] = m["pt_1"] / m["validos_1"]
    return m


def bloque_cambio(S: Salida, l18: pd.DataFrame, l22: pd.DataFrame) -> pd.DataFrame:
    m = por_municipio(l18).join(por_municipio(l22), lsuffix="_18", rsuffix="_22", how="inner")
    m["cambio"] = (m["pt2_pct_22"] - m["pt2_pct_18"]) * 100
    m["region"] = m.index.get_level_values("uf").map(REGION)
    w = m["validos_2_22"]
    q = pd.qcut(m["pt2_pct_18"], 5, labels=False)
    S.d["cambio"] = {
        "municipios": len(m), "subio": int((m["cambio"] > 0).sum()), "bajo": int((m["cambio"] < 0).sum()),
        "media_ponderada": float(np.average(m["cambio"], weights=w)),
        "por_region": {r: float(np.average(x["cambio"], weights=x["validos_2_22"])) for r, x in m.groupby("region")},
        "por_quintil_2018": {int(k): float(np.average(x["cambio"], weights=x["validos_2_22"])) for k, x in m.groupby(q)},
        "corr_18_22": float(np.corrcoef(m["pt2_pct_18"], m["pt2_pct_22"])[0, 1]),
        "mayores_subas": [{"municipio": nm.title(), "uf": uf, "cambio": float(c), "electores": int(a)} for (uf, _), nm, c, a in
                          m[m["aptos_22"] > 200_000].nlargest(5, "cambio")[["nm_22", "cambio", "aptos_22"]].itertuples()],
        "mayores_bajas": [{"municipio": nm.title(), "uf": uf, "cambio": float(c), "electores": int(a)} for (uf, _), nm, c, a in
                          m[m["aptos_22"] > 200_000].nsmallest(5, "cambio")[["nm_22", "cambio", "aptos_22"]].itertuples()],
    }
    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    cols = {"Norte": "#1BAF7A", "Nordeste": C_PT, "Centro-Oeste": "#EDA100", "Sudeste": "#4A3AA7", "Sul": C_BOL}
    for r, x in m.groupby("region"):
        ax.scatter(x["pt2_pct_18"] * 100, x["pt2_pct_22"] * 100, s=np.sqrt(x["aptos_22"]) / 12, color=cols[r], alpha=0.45,
                   linewidths=0, label=r, rasterized=True)
    ax.plot([0, 100], [0, 100], color="#BBBBBB", lw=1, ls="--")
    ax.annotate("sin cambios", (82, 79), rotation=38, fontsize=7.5, color=MUTED)
    ax.set_xlabel("% Haddad, 2ª vuelta 2018", fontsize=8.5)
    ax.set_ylabel("% Lula, 2ª vuelta 2022", fontsize=8.5)
    ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    ley = ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    for h in ley.legend_handles:
        h.set_sizes([30])
        h.set_alpha(0.8)
    limpiar(ax, grid="both")
    S.fig(fig, "cambio_municipios.svg")
    return m


# ---------------------------------------------------------------------------
# 4. Transferencias entre vueltas
# ---------------------------------------------------------------------------

def matriz_transferencia(X: np.ndarray, Y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """B (K x J) con B >= 0 y filas que suman 1 que minimiza sum_i w_i ||Y_i - X_i B||^2."""
    K, J = X.shape[1], Y.shape[1]
    w = w / w.sum()  # con pesos en electores el objetivo es ~1e8 y SLSQP no se mueve del punto inicial
    XtX = (X * w[:, None]).T @ X
    XtY = (X * w[:, None]).T @ Y

    def f(b):
        B = b.reshape(K, J)
        return float(np.sum(B * (XtX @ B)) - 2 * np.sum(B * XtY))

    def grad(b):
        B = b.reshape(K, J)
        return (2 * XtX @ B - 2 * XtY).ravel()

    restr = [{"type": "eq", "fun": (lambda b, k=k: b.reshape(K, J)[k].sum() - 1),
              "jac": (lambda b, k=k: np.eye(K)[k].repeat(J))} for k in range(K)]
    b0 = np.full(K * J, 1 / J)
    r = minimize(f, b0, jac=grad, bounds=[(0, 1)] * (K * J), constraints=restr, method="SLSQP",
                 options={"maxiter": 500, "ftol": 1e-12})
    return r.x.reshape(K, J)


def transferencias(loc: pd.DataFrame, origen: list[str], destino: list[str]) -> tuple[pd.DataFrame, dict]:
    """Matriz nacional = promedio de las matrices por UF ponderado por los votos de cada origen en la UF."""
    g = loc[~loc["chico"]]
    tot = pd.DataFrame(0.0, index=origen, columns=destino)
    por_uf = {}
    for uf, x in g.groupby("uf"):
        X = x[[f"{o}_1" for o in origen]].to_numpy(float) / x["aptos"].to_numpy(float)[:, None]
        Y = x[[f"{d}_2" for d in destino]].to_numpy(float) / x["aptos"].to_numpy(float)[:, None]
        B = matriz_transferencia(X, Y, x["aptos"].to_numpy(float))
        masa = x[[f"{o}_1" for o in origen]].sum().to_numpy(float)
        tot += B * masa[:, None]
        por_uf[uf] = pd.DataFrame(B, index=origen, columns=destino)
    T = tot.div(tot.sum(axis=1), axis=0)
    return T, por_uf


def heat(T: pd.DataFrame, nombre: str, S: Salida, figsize=(5.6, 3.6)):
    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(T.to_numpy() * 100, cmap="Purples", vmin=0, vmax=100, aspect="auto")
    for i in range(T.shape[0]):
        for j in range(T.shape[1]):
            v = T.iat[i, j] * 100
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=9, color="white" if v > 55 else INK)
    ax.set_xticks(range(T.shape[1]), [ETQ[c] for c in T.columns], fontsize=8.5)
    ax.set_yticks(range(T.shape[0]), [ETQ[c] for c in T.index], fontsize=8.5)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    S.fig(fig, nombre)


def bloque_transferencias(S: Salida, l18: pd.DataFrame, l22: pd.DataFrame) -> pd.DataFrame:
    dest = ["pt", "bolsonaro", "blanco_nulo", "abstencion"]
    o22 = ["pt", "bolsonaro", "ciro", "tebet", "otros", "blanco_nulo", "abstencion"]
    o18 = ["pt", "bolsonaro", "ciro", "centro", "otros", "blanco_nulo", "abstencion"]
    T22, uf22 = transferencias(l22, o22, dest)
    T18, _ = transferencias(l18, o18, dest)
    heat(T22, "transfer22.svg", S)
    heat(T18, "transfer18.svg", S)
    # Validación: la matriz reproduce el resultado de la 2ª vuelta a partir de la 1ª
    g = l22[~l22["chico"]]
    pred = sum(np.outer(g[f"{o}_1"], T22.loc[o]) for o in o22)
    pred = pd.DataFrame(pred, columns=dest, index=g.index)
    real_pt = g["pt_2"].sum() / (g["pt_2"].sum() + g["bolsonaro_2"].sum())
    pred_pt = pred["pt"].sum() / (pred["pt"].sum() + pred["bolsonaro"].sum())
    err_local = (pred["pt"] / (pred["pt"] + pred["bolsonaro"]) - g["lula_pct"]).abs()
    S.d["transfer"] = {
        "t22": {o: {d: float(T22.loc[o, d]) for d in dest} for o in o22},
        "t18": {o: {d: float(T18.loc[o, d]) for d in dest} for o in o18},
        "validacion": {"lula_real": real_pt * 100, "lula_predicho": pred_pt * 100,
                       "error_mediano_local_pp": float(err_local.median() * 100)},
        "ciro_a_lula_por_region": {r: float(np.average([uf22[u].loc["ciro", "pt"] for u in us],
                                                       weights=[l22.loc[l22["uf"] == u, "ciro_1"].sum() for u in us]))
                                   for r, us in pd.Series(list(uf22)).groupby(pd.Series(list(uf22)).map(REGION))},
    }
    return T22


# ---------------------------------------------------------------------------
# 5. Cohortes y 6. Abstención
# ---------------------------------------------------------------------------

def bloque_cohortes(S: Salida, m: pd.DataFrame) -> None:
    q = pd.qcut(m["pt2_pct_18"], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    serie = {}
    for k, x in m.groupby(q, observed=True):
        serie[k] = {"2018 · 1ª": x["pt_1_18"].sum() / x["validos_1_18"].sum() * 100,
                    "2018 · 2ª": x["pt_2_18"].sum() / x["validos_2_18"].sum() * 100,
                    "2022 · 1ª": x["pt_1_22"].sum() / x["validos_1_22"].sum() * 100,
                    "2022 · 2ª": x["pt_2_22"].sum() / x["validos_2_22"].sum() * 100,
                    "municipios": len(x), "electores": int(x["aptos_22"].sum())}
    S.d["cohortes"] = serie
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    et = list(next(iter(serie.values())))[:4]
    paleta = ["#1C5CAB", "#5598E7", "#9E9E9E", "#EA7372", "#B42322"]
    for (k, v), c in zip(serie.items(), paleta):
        ax.plot(range(4), [v[e] for e in et], marker="o", color=c, lw=2, ms=5)
        ax.annotate(f"{k}  {v['2022 · 2ª']:.0f} %".replace(".", ","), (3, v["2022 · 2ª"]), xytext=(7, 0),
                    textcoords="offset points", va="center", fontsize=8, color=INK)
    ax.set_xticks(range(4), et, fontsize=8.5)
    ax.set_ylabel("% PT (votos válidos)", fontsize=8.5)
    ax.set_xlim(-0.2, 3.7)
    limpiar(ax)
    S.fig(fig, "cohortes.svg")


def bloque_abstencion(S: Salida, l22: pd.DataFrame) -> None:
    g = l22[~l22["chico"]]
    q = pd.qcut(g["lula_pct"], 5, labels=False)
    S.d["abstencion"] = {
        "nacional_1": float(g["abstencion_1"].sum() / g["aptos"].sum() * 100),
        "nacional_2": float(g["abstencion_2"].sum() / g["aptos"].sum() * 100),
        "por_quintil_lula": {int(k): {"lula": float(x["pt_2"].sum() / x["validos_2"].sum() * 100),
                                      "abst_1": float(x["abstencion_1"].sum() / x["aptos"].sum() * 100),
                                      "abst_2": float(x["abstencion_2"].sum() / x["aptos"].sum() * 100)}
                             for k, x in g.groupby(q)},
        "por_region": {r: float(x["abstencion_2"].sum() / x["aptos"].sum() * 100) for r, x in g.groupby("region")},
    }
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    d = S.d["abstencion"]["por_quintil_lula"]
    x = np.arange(5)
    ax.bar(x - 0.2, [d[k]["abst_1"] for k in range(5)], width=0.38, color="#C9BEE4", label="1ª vuelta", zorder=3)
    ax.bar(x + 0.2, [d[k]["abst_2"] for k in range(5)], width=0.38, color=VIO, label="2ª vuelta", zorder=3)
    ax.set_xticks(x, [f"{d[k]['lula']:.0f} %" for k in range(5)], fontsize=8.5)
    ax.set_xlabel("Locales agrupados por % de Lula en la 2ª vuelta (quintiles)", fontsize=8.5)
    ax.set_ylabel("% de abstención", fontsize=8.5)
    ax.legend(fontsize=8, frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    limpiar(ax)
    S.fig(fig, "abstencion.svg")


# ---------------------------------------------------------------------------
# 7. Censo
# ---------------------------------------------------------------------------

CENSO = [("alfabetizacion", "Alfabetizados (15 años o más)"), ("preta_parda", "Población preta o parda"),
         ("banos_2mas", "Hogares con 2 baños o más"), ("cloaca_red", "Hogares con cloaca a red"),
         ("mayores_60", "60 años o más"), ("jovenes_15_29", "15 a 29 años"), ("urbano", "Setores urbanos")]


def bloque_censo(S: Salida, l22: pd.DataFrame, seed: int) -> None:
    if not LOCALES_CENSO.exists():
        log.warning("Sin %s: se omite el bloque del Censo (correr src.geo.censo_locales)", LOCALES_CENSO.name)
        return
    import statsmodels.api as sm
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    c = pd.read_parquet(LOCALES_CENSO)
    k = ["uf", "cd_municipio", "nr_zona", "nr_local"]
    g = l22[~l22["chico"]].merge(c, on=k, how="inner").dropna(subset=[v for v, _ in CENSO])
    X = g[[v for v, _ in CENSO]]
    Z = (X - X.mean()) / X.std()
    w = g["validos_2"]
    ols = sm.WLS(g["lula_pct"] * 100, sm.add_constant(X * 100), weights=w).fit()
    ols_z = sm.WLS((g["lula_pct"] - g["lula_pct"].mean()) / g["lula_pct"].std(), sm.add_constant(Z), weights=w).fit()
    reg_uf = sm.WLS(g["lula_pct"] * 100, sm.add_constant(pd.concat([X * 100, pd.get_dummies(g["uf"], drop_first=True, dtype=float)], axis=1)),
                    weights=w).fit()
    solo_uf = sm.WLS(g["lula_pct"] * 100, sm.add_constant(pd.get_dummies(g["uf"], drop_first=True, dtype=float)), weights=w).fit()
    S.d["reg"] = {"n": len(g), "r2": ols.rsquared, "r2_con_uf": reg_uf.rsquared, "r2_solo_uf": solo_uf.rsquared,
                  "coef": {v: float(ols.params[v]) for v, _ in CENSO},
                  "beta": {v: float(ols_z.params[v]) for v, _ in CENSO},
                  "ic": {v: [float(a), float(b)] for v, (a, b) in ols_z.conf_int().loc[[v for v, _ in CENSO]].iterrows()},
                  "coef_con_uf": {v: float(reg_uf.params[v]) for v, _ in CENSO}}
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    orden = sorted(CENSO, key=lambda t: S.d["reg"]["beta"][t[0]])
    for i, (v, et) in enumerate(orden):
        b = S.d["reg"]["beta"][v]; lo, hi = S.d["reg"]["ic"][v]
        col = C_PT if b > 0 else C_BOL
        ax.plot([lo, hi], [i, i], color=col, lw=2.2, alpha=0.5)
        ax.scatter([b], [i], s=55, color=col, zorder=3)
        ax.annotate(f"{b:+.2f}".replace(".", ","), (max(hi, b) + 0.03, i), va="center", fontsize=8, color=INK)
    ax.axvline(0, color="#999", lw=1)
    ax.set_yticks(range(len(orden)), [et for _, et in orden], fontsize=8.5)
    ax.set_xlabel("Efecto sobre el % de Lula (desvíos estándar)", fontsize=8.5)
    limpiar(ax, grid="x")
    S.fig(fig, "betas.svg")

    # Tipología: k-medias sobre el Censo estandarizado
    km = KMeans(4, n_init=30, random_state=seed).fit(Z)
    g["tipo"] = km.labels_
    perfiles = g.groupby("tipo").apply(lambda x: pd.Series({
        "locales": len(x), "electores": x["aptos"].sum(), "lula": x["pt_2"].sum() / x["validos_2"].sum() * 100,
        **{v: np.average(x[v], weights=x["aptos"]) * 100 for v, _ in CENSO}}), include_groups=False)
    perfiles = perfiles.sort_values("lula")
    S.d["tipos"] = perfiles.reset_index().to_dict(orient="records")


# ---------------------------------------------------------------------------
# 8. Implicancias para 2026
# ---------------------------------------------------------------------------

def bloque_2026(S: Salida, T22: pd.DataFrame) -> None:
    agr = ELECTORAL_DIR / "intencion_voto_presidencial.parquet"
    if not agr.exists():
        return
    a = pd.read_parquet(agr)
    a1 = a[a["vuelta"] == 1].set_index("candidato")["pct_validos"] / 100
    terceros = a1.drop(["lula", "flavio_bolsonaro"], errors="ignore")
    # Proporción de cada tipo de votante 2022 que va a Lula entre quienes votan a alguien en la 2ª
    def a_lula(o):
        r = T22.loc[o]
        return r["pt"] / (r["pt"] + r["bolsonaro"])
    escenarios = {}
    for nombre, o in (("como Ciro 2022", "ciro"), ("como Tebet 2022", "tebet"), ("como 'otros' 2022", "otros")):
        p = a_lula(o)
        lula = a1.get("lula", 0) + terceros.sum() * p
        escenarios[nombre] = {"a_lula": float(p), "lula_2v": float(lula / (a1.get("lula", 0) + a1.get("flavio_bolsonaro", 0) + terceros.sum()) * 100)}
    analogia = cargar_config()["seccion"]["analogia_2026"]
    lula_mix = a1.get("lula", 0) + sum(v * a_lula(analogia.get(k, "otros")) for k, v in terceros.items())
    escenarios["por analogía (Cury como Ciro; Caiado como Tebet; Zema y Santos como otros)"] = {
        "a_lula": float((lula_mix - a1.get("lula", 0)) / terceros.sum()),
        "lula_2v": float(lula_mix / (a1.get("lula", 0) + a1.get("flavio_bolsonaro", 0) + terceros.sum()) * 100)}
    S.d["proy_2026"] = {"agregado_1v": {k: float(v * 100) for k, v in a1.items()}, "terceros": float(terceros.sum() * 100),
                        "escenarios": escenarios, "analogia": analogia,
                        "cruce_encuestas_lula": float(a[(a["vuelta"] == 2) & (a["escenario"] == "flavio_bolsonaro|lula")
                                                        & (a["candidato"] == "lula")]["pct_validos"].iloc[0]),
                        "retencion_pt_2022": float(a_lula("pt")), "retencion_bolsonaro_2022": float(1 - a_lula("bolsonaro"))}


def main() -> Path:
    cfg = cargar_config()["seccion"]
    S = Salida()
    l18, l22 = cargar(2018, cfg["min_aptos_local"]), cargar(2022, cfg["min_aptos_local"])
    log.info("1 · distribución"); bloque_distribucion(S, l22)
    log.info("2 · mapas"); bloque_mapa(S, l22)
    log.info("3 · cambio 2018-2022"); m = bloque_cambio(S, l18, l22)
    log.info("4 · transferencias"); T22 = bloque_transferencias(S, l18, l22)
    log.info("5 · cohortes"); bloque_cohortes(S, m)
    log.info("6 · abstención"); bloque_abstencion(S, l22)
    log.info("7 · censo"); bloque_censo(S, l22, cfg["random_seed"])
    log.info("8 · 2026"); bloque_2026(S, T22)
    S.d["corrida_utc"] = S.dir.name
    S.guardar()
    log.info("Listo: %s", S.dir.relative_to(ROOT).as_posix())
    return S.dir


if __name__ == "__main__":
    main()
