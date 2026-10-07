"""
src/models/balotaje_2026.py

Balotaje presidencial 2026 (25/10) a partir del resultado de la 1ª vuelta
(TSE, por município), no de encuestas.

El balotaje se decide en los ~9 M de votos de los terceros (Cury, Renan
Santos, Caiado, Zema y otros) y en quién vuelve a votar. Dos métodos para
repartirlos, los dos con la misma regla para el resto del electorado:

  Lula / Flávio de la 1ª vuelta, blanco-nulo y abstención: fila de la matriz
  1ª -> 2ª vuelta de la elección anterior (2022, por UF, estimada en
  locales de votación en analisis_seccion) que corresponde a su grupo.

  Terceros: la misma fila de la matriz de su ANÁLOGO 2022 dice qué parte vota
  válido en la 2ª vuelta (el resto, blanco-nulo o abstención). Cómo se
  reparte esa parte entre Lula y Flávio es lo que cambia:

  A · analogía: como su análogo 2022 (Cury como Ciro, Caiado como Tebet,
      Renan Santos, Zema y otros como "otros"). Supuesto, no dato.
  R · origen:   regresión ecológica 2ª vuelta 2022 -> 1ª vuelta 2026 por
      município (con restricciones, por UF o región): de qué lado venía cada
      votante de tercero. Los que venían de Lula vuelven a Lula, los de
      Bolsonaro a Flávio, y los que venían de blanco/abstención se reparten
      como el análogo.

Backtest: lo mismo un ciclo atrás (base 2018 -> 1ª vuelta 2022), contra la 2ª
vuelta real de 2022, nacional y por UF. El error del backtest fija el desvío
del Montecarlo (shock nacional + shock por UF).

Parámetros: config/modelo.yaml, sección `balotaje`.
Salida: data/processed/electoral/balotaje_2026/<fecha_utc>/
    resumen.json, por_uf.csv, backtest.csv, matrices.json, meta.json

Uso:
    python -m src.models.balotaje_2026
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.etl.transform.base_locales import salida as salida_locales
from src.models.analisis_seccion import REGION, cargar, matriz_transferencia, transferencias
from src.models.conteo_2026 import SALIDA as CONTEO_UF, SALIDA_FINAL as RESULTADO_2026
from src.models.montecarlo.proyeccion_bancas import CONFIG_MODELO, ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "balotaje_2026"
ORIGEN = ["pt", "bolsonaro", "blanco_nulo", "abstencion"]   # 2ª vuelta de la elección anterior
DESTINO_2V = ["pt", "bolsonaro", "blanco_nulo", "abstencion"]

# Por elección: grupos de 1ª vuelta (el 1º es el PT, el 2º el bolsonarismo) y terceros.
GRUPOS_1V = {
    2018: ["pt", "bolsonaro", "ciro", "centro", "otros", "blanco_nulo", "abstencion"],
    2022: ["pt", "bolsonaro", "ciro", "tebet", "otros", "blanco_nulo", "abstencion"],
    2026: ["pt", "bolsonaro", "cury", "renan_santos", "caiado", "otros", "blanco_nulo", "abstencion"],
}
NO_TERCEROS = {"pt", "bolsonaro", "blanco_nulo", "abstencion"}


# ---------------------------------------------------------------------------
# Datos por município (código IBGE)
# ---------------------------------------------------------------------------

def municipios_previos(ano: int) -> pd.DataFrame:
    loc = pd.read_parquet(salida_locales(ano))
    loc = loc[loc["uf"] != "ZZ"]
    num = [c for c in loc.columns if c.endswith(("_1", "_2")) or c == "aptos"]
    m = loc.groupby("cd_ibge").agg({"uf": "first", **{c: "sum" for c in num}})
    return m.astype({c: float for c in num})


def municipios_2026() -> pd.DataFrame:
    r = pd.read_parquet(RESULTADO_2026).set_index("codigo")
    m = pd.DataFrame({
        "uf": r["uf"], "aptos": r["aptos"],
        "pt_1": r["lula"], "bolsonaro_1": r["flavio_bolsonaro"], "cury_1": r["cury"],
        "renan_santos_1": r["renan_santos"], "caiado_1": r["caiado"], "otros_1": r["zema"] + r["otros"],
        "blanco_nulo_1": r["blancos"] + r["nulos"], "abstencion_1": r["abstencion"],
    })
    m.index.name = "cd_ibge"
    return m.astype({c: float for c in m.columns if c != "uf"})


def exterior_2026() -> dict:
    """Votos válidos del exterior (no hay padrón por município: se suma con la regla nacional)."""
    v = json.loads(CONTEO_UF.read_text(encoding="utf-8"))["por_uf"]["zz"]["votos"]
    return {"pt_1": v["lula"], "bolsonaro_1": v["flavio_bolsonaro"], "cury_1": v["cury"],
            "renan_santos_1": v["renan_santos"], "caiado_1": v["caiado"], "otros_1": v["zema"] + v["otros"]}


# ---------------------------------------------------------------------------
# Regresión ecológica 2ª vuelta anterior -> 1ª vuelta actual
# ---------------------------------------------------------------------------

def matriz_origen(prev: pd.DataFrame, act: pd.DataFrame, grupos: list[str], min_mun: int) -> dict[str, pd.DataFrame]:
    """B (origen x grupo 1ª vuelta) por UF; las UF con pocos municípios usan la de su región."""
    j = prev[[f"{o}_2" for o in ORIGEN] + ["aptos"]].join(
        act[["uf"] + [f"{g}_1" for g in grupos] + ["aptos"]], how="inner", lsuffix="_prev")
    j = j[(j["aptos_prev"] > 0) & (j["aptos"] > 0)]
    X = j[[f"{o}_2" for o in ORIGEN]].to_numpy() / j[["aptos_prev"]].to_numpy()
    Y = j[[f"{g}_1" for g in grupos]].to_numpy() / j[["aptos"]].to_numpy()
    X = X / X.sum(axis=1, keepdims=True)   # padrón con tránsito: filas a 1
    Y = Y / Y.sum(axis=1, keepdims=True)
    w = j["aptos"].to_numpy(float)
    uf = j["uf"].to_numpy()
    reg = pd.Series(uf).map(REGION).to_numpy()
    out, por_region = {}, {}
    for r in np.unique(reg):
        s = reg == r
        por_region[r] = pd.DataFrame(matriz_transferencia(X[s], Y[s], w[s]), index=ORIGEN, columns=grupos)
    for u in np.unique(uf):
        s = uf == u
        out[u] = (pd.DataFrame(matriz_transferencia(X[s], Y[s], w[s]), index=ORIGEN, columns=grupos)
                  if s.sum() >= min_mun else por_region[REGION[u]])
    log.info("matriz de origen: %d municípios cruzados, %d UF propias, %d con la de su región",
             len(j), sum(1 for u in np.unique(uf) if (uf == u).sum() >= min_mun),
             sum(1 for u in np.unique(uf) if (uf == u).sum() < min_mun))
    return out, j.index


def celdas_origen(act: pd.DataFrame, prev: pd.DataFrame, B: dict, grupos: list[str], terceros: list[str]) -> pd.DataFrame:
    """Votos de cada tercero por origen y município, consistentes con lo observado (ajuste proporcional)."""
    j = act.join(prev[[f"{o}_2" for o in ORIGEN] + ["aptos"]], how="left", rsuffix="_prev")
    X = j[[f"{o}_2" for o in ORIGEN]].to_numpy(float) / j[["aptos_prev"]].to_numpy(float)
    filas = []
    for u, idx in j.groupby("uf").indices.items():
        b = B[u]
        x = X[idx]
        sin_dato = ~np.isfinite(x).all(axis=1)
        x[sin_dato] = np.nan
        for t in terceros:
            y = j[f"{t}_1"].to_numpy(float)[idx]
            peso = x * b[t].to_numpy()[None, :]
            # municípios nuevos (sin 2ª vuelta anterior): composición media de la UF
            media = np.nansum(peso * y[:, None], axis=0)
            peso[sin_dato] = media
            peso = peso / peso.sum(axis=1, keepdims=True)
            filas.append(pd.DataFrame(peso * y[:, None], columns=ORIGEN, index=j.index[idx]).assign(tercero=t, uf=u))
    return pd.concat(filas)


# ---------------------------------------------------------------------------
# Predicción de la 2ª vuelta
# ---------------------------------------------------------------------------

def predecir(act: pd.DataFrame, T: dict, analogia: dict, metodo: str, celdas: pd.DataFrame | None,
             terceros: list[str], ajuste: dict | None = None, T_mov: dict | None = None) -> pd.DataFrame:
    """Votos de 2ª vuelta por UF (pt, bolsonaro, blanco_nulo, abstencion).

    `ajuste` = {tercero: proporción a Lula entre los que votan válido} pisa al
    método (para escenarios y sensibilidad). `T_mov` = matrices por UF de otra
    elección para Lula, Flávio, blanco-nulo y abstención de la 1ª vuelta
    (retención y movilización); por defecto, las de `T`.
    """
    out = {}
    for u, x in act.groupby("uf"):
        t = T[u]
        tm = (T_mov or T)[u]
        v = pd.Series(0.0, index=DESTINO_2V)
        for g in ("pt", "bolsonaro", "blanco_nulo", "abstencion"):
            if f"{g}_1" in x:
                v += x[f"{g}_1"].sum() * tm.loc[g]
        for g in terceros:
            n = x[f"{g}_1"].sum()
            fila = t.loc[analogia[g]]
            valido = fila["pt"] + fila["bolsonaro"]
            if ajuste and g in ajuste:
                a_lula = ajuste[g]
            elif metodo == "A":
                a_lula = fila["pt"] / valido
            else:
                c = celdas[(celdas["uf"] == u) & (celdas["tercero"] == g)][ORIGEN].sum()
                indet = c["blanco_nulo"] + c["abstencion"]
                a_lula = (c["pt"] + indet * fila["pt"] / valido) / c.sum() if c.sum() > 0 else fila["pt"] / valido
            v["pt"] += n * valido * a_lula
            v["bolsonaro"] += n * valido * (1 - a_lula)
            v["blanco_nulo"] += n * fila["blanco_nulo"]
            v["abstencion"] += n * fila["abstencion"]
        out[u] = v
    df = pd.DataFrame(out).T
    df["lula_pct"] = df["pt"] / (df["pt"] + df["bolsonaro"]) * 100
    return df


def predecir_municipios(act: pd.DataFrame, T: dict, analogia: dict, celdas: pd.DataFrame,
                        terceros: list[str]) -> pd.DataFrame:
    """Método R por município: mismas reglas que `predecir`, con el origen de los terceros de cada município.

    Suma exactamente lo mismo que `predecir(..., "R", ...)` por UF: el ajuste
    proporcional de `celdas_origen` hace que el origen de cada município sume
    sus votos observados.
    """
    partes = []
    for u, x in act.groupby("uf"):
        t = T[u]
        v = pd.DataFrame(0.0, index=x.index, columns=DESTINO_2V)
        for g in ("pt", "bolsonaro", "blanco_nulo", "abstencion"):
            if f"{g}_1" in x:
                v += np.outer(x[f"{g}_1"].to_numpy(float), t.loc[g].to_numpy())
        for g in terceros:
            n = x[f"{g}_1"].to_numpy(float)
            fila = t.loc[analogia[g]]
            valido = fila["pt"] + fila["bolsonaro"]
            c = celdas[(celdas["uf"] == u) & (celdas["tercero"] == g)][ORIGEN].reindex(x.index).fillna(0)
            tot = c.sum(axis=1).to_numpy()
            a = np.where(tot > 0, (c["pt"] + (c["blanco_nulo"] + c["abstencion"]) * fila["pt"] / valido).to_numpy()
                         / np.where(tot > 0, tot, 1), fila["pt"] / valido)
            v["pt"] += n * valido * a
            v["bolsonaro"] += n * valido * (1 - a)
            v["blanco_nulo"] += n * fila["blanco_nulo"]
            v["abstencion"] += n * fila["abstencion"]
        partes.append(v.assign(uf=u))
    df = pd.concat(partes)
    df["lula_pct"] = df["pt"] / (df["pt"] + df["bolsonaro"]) * 100
    return df


def a_lula_nacional(act: pd.DataFrame, T: dict, analogia: dict, metodo: str, celdas, terceros) -> dict:
    """Proporción de cada tercero que va a Lula entre los que votan válido (nacional)."""
    res = {}
    for g in terceros:
        num = den = 0.0
        for u, x in act.groupby("uf"):
            n = x[f"{g}_1"].sum()
            p = predecir(x.assign(**{f"{h}_1": 0.0 for h in ("pt", "bolsonaro", "blanco_nulo", "abstencion")
                                     if f"{h}_1" in x}).assign(**{f"{h}_1": 0.0 for h in terceros if h != g}),
                         T, analogia, metodo, celdas, terceros)
            num += p["pt"].sum()
            den += p["pt"].sum() + p["bolsonaro"].sum()
        res[g] = num / den if den else float("nan")
    return res


def real_2v(prev_loc: pd.DataFrame) -> pd.DataFrame:
    g = prev_loc.groupby("uf")[["pt_2", "bolsonaro_2"]].sum()
    g["lula_pct"] = g["pt_2"] / (g["pt_2"] + g["bolsonaro_2"]) * 100
    return g


def nacional(df: pd.DataFrame, extra: tuple[float, float] = (0.0, 0.0)) -> float:
    pt, bol = df["pt"].sum() + extra[0], df["bolsonaro"].sum() + extra[1]
    return pt / (pt + bol) * 100


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------

def estimar(ano_base: int, ano_obj: int, analogia: dict, cfg: dict, act: pd.DataFrame | None = None):
    """Matriz 1ª->2ª vuelta de `ano_base` (locales, por UF), matriz de origen y predicciones A y R para `ano_obj`."""
    loc_base = cargar(ano_base, cfg["min_aptos_local"])
    T_nac, T = transferencias(loc_base, GRUPOS_1V[ano_base], DESTINO_2V)
    prev = municipios_previos(ano_base)
    if act is None:
        act = municipios_previos(ano_obj)
        act = act[["uf", "aptos"] + [f"{g}_1" for g in GRUPOS_1V[ano_obj]]]
    terceros = [g for g in GRUPOS_1V[ano_obj] if g not in NO_TERCEROS]
    B, _ = matriz_origen(prev, act, GRUPOS_1V[ano_obj], cfg["min_municipios_uf"])
    celdas = celdas_origen(act, prev, B, GRUPOS_1V[ano_obj], terceros)
    pred = {m: predecir(act, T, analogia, m, celdas, terceros) for m in ("A", "R")}
    return {"T": T, "T_nac": T_nac, "B": B, "celdas": celdas, "pred": pred, "act": act, "terceros": terceros}


def main() -> None:
    cfg_all = cargar_config()
    cfg = {**cfg_all["seccion"], **cfg_all["balotaje"]}
    rng = np.random.default_rng(cfg["random_seed"])
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)

    # 1 · Backtest: base 2018 -> 1ª vuelta 2022 -> ¿2ª vuelta 2022?
    log.info("backtest 2018 -> 2022")
    bt = estimar(2018, 2022, cfg["analogia_backtest"], cfg)
    real = real_2v(pd.read_parquet(salida_locales(2022)).query("uf != 'ZZ'"))
    filas = []
    for m, p in bt["pred"].items():
        e = p["lula_pct"] - real["lula_pct"]
        filas.append(pd.DataFrame({"metodo": m, "uf": p.index, "predicho": p["lula_pct"],
                                   "real": real.loc[p.index, "lula_pct"], "error": e}))
    backtest = pd.concat(filas)
    backtest.to_csv(out / "backtest.csv", index=False)
    real_nac = real["pt_2"].sum() / (real["pt_2"].sum() + real["bolsonaro_2"].sum()) * 100
    bt_res = {}
    for m, p in bt["pred"].items():
        e = backtest.query("metodo == @m")["error"]
        w = (real["pt_2"] + real["bolsonaro_2"]).loc[p.index].to_numpy()
        err_nac = nacional(p) - real_nac
        bt_res[m] = {"lula_predicho": nacional(p), "lula_real": real_nac, "error_nacional_pp": err_nac,
                     "mae_uf_pp": float(e.abs().mean()),
                     "sd_uf_sin_nacional_pp": float(np.sqrt(np.average((e.to_numpy() - err_nac) ** 2, weights=w)))}
    bt_res["a_lula_terceros"] = {m: a_lula_nacional(bt["act"], bt["T"], cfg["analogia_backtest"], m, bt["celdas"],
                                                    bt["terceros"]) for m in ("A", "R")}
    log.info("backtest: %s", json.dumps({m: {k: round(v, 2) for k, v in r.items()} for m, r in bt_res.items()
                                         if m in ("A", "R")}))

    # 2 · 2026: base 2022 -> 1ª vuelta 2026
    log.info("2026 sobre base 2022")
    act = municipios_2026()
    est = estimar(2022, 2026, cfg["analogia"], cfg, act=act)
    ext = exterior_2026()
    a_lula = {m: a_lula_nacional(act, est["T"], cfg["analogia"], m, est["celdas"], est["terceros"]) for m in ("A", "R")}

    def exterior(m):
        """Exterior: Lula y Flávio retienen; los terceros se reparten con la proporción nacional del método."""
        pt = ext["pt_1"] + sum(ext[f"{g}_1"] * a_lula[m][g] for g in est["terceros"])
        bol = ext["bolsonaro_1"] + sum(ext[f"{g}_1"] * (1 - a_lula[m][g]) for g in est["terceros"])
        return pt, bol

    pred = {m: nacional(p, exterior(m)) for m, p in est["pred"].items()}

    # Pronóstico por município (método R), base del mapa y del tablero de la noche del 25/10;
    # y el mismo cálculo un ciclo atrás (2022 desde 2018) con el resultado real, para probar el tablero.
    mun = predecir_municipios(act, est["T"], cfg["analogia"], est["celdas"], est["terceros"])
    chk = mun.groupby("uf")[["pt", "bolsonaro"]].sum() - est["pred"]["R"][["pt", "bolsonaro"]]
    assert chk.abs().max().max() < 1, "el pronóstico municipal no suma lo mismo que el de la UF"
    mun = mun.join(act[["pt_1", "bolsonaro_1", "aptos"]])
    mun.index.name = "codigo"
    mun.to_parquet(out / "municipios.parquet")
    mbt = predecir_municipios(bt["act"], bt["T"], cfg["analogia_backtest"], bt["celdas"], bt["terceros"])
    r22 = municipios_previos(2022)
    mbt = mbt.join(r22[["pt_2", "bolsonaro_2", "aptos"]]).rename(columns={"pt_2": "pt_real", "bolsonaro_2": "bolsonaro_real"})
    mbt.index.name = "codigo"
    mbt.to_parquet(out / "backtest_municipios.parquet")
    log.info("2026: Lula 2ª vuelta A=%.2f R=%.2f", pred["A"], pred["R"])

    # Composición de los terceros por origen (nacional)
    comp = est["celdas"].groupby("tercero")[ORIGEN].sum()
    comp = comp.div(comp.sum(axis=1), axis=0)

    # 3 · Montecarlo: método principal + shock nacional y por UF calibrados en el backtest
    principal = cfg["metodo_principal"]
    p_uf = est["pred"][principal].copy()
    sd_uf = bt_res[principal]["sd_uf_sin_nacional_pp"]
    sd_nac = float(np.sqrt(bt_res[principal]["error_nacional_pp"] ** 2 + ((pred["A"] - pred["R"]) / 2) ** 2
                           + cfg["sigma_nacional_extra_pp"] ** 2))
    n = cfg["n_simulaciones"]
    # t de Student escalada para que su desvío sea sd_nac: con una sola
    # observación de backtest, colas gruesas antes que una normal confiada.
    gl = cfg["grados_libertad_t"]
    eta = rng.standard_t(gl, n) * sd_nac / np.sqrt(gl / (gl - 2))
    eps = rng.normal(0, sd_uf, (n, len(p_uf)))
    lula_uf = np.clip(p_uf["lula_pct"].to_numpy()[None, :] + eta[:, None] + eps, 0, 100)
    val = (p_uf["pt"] + p_uf["bolsonaro"]).to_numpy()
    ext_pt, ext_bol = exterior(principal)
    ext_val = ext_pt + ext_bol
    ext_lula = np.clip(ext_pt / ext_val * 100 + eta, 0, 100)
    lula_nac = (lula_uf @ val + ext_lula * ext_val) / (val.sum() + ext_val)
    q = np.percentile(lula_nac, [5, 25, 50, 75, 95])

    # 4 · Sensibilidad: qué parte de los terceros tiene que ir a Lula
    sens = []
    for s in np.arange(0.30, 0.81, 0.05):
        p = predecir(act, est["T"], cfg["analogia"], principal, est["celdas"], est["terceros"],
                     ajuste={g: s for g in est["terceros"]})
        e_pt = ext["pt_1"] + s * sum(ext[f"{g}_1"] for g in est["terceros"])
        e_bol = ext["bolsonaro_1"] + (1 - s) * sum(ext[f"{g}_1"] for g in est["terceros"])
        sens.append({"a_lula_terceros": round(float(s), 2), "lula_pct": nacional(p, (e_pt, e_bol))})

    # 5 · Escenarios de apoyos (después del 4/10: Caiado y Zema con Flávio; Cury y Renan neutrales)
    escenarios = {}
    for nombre, aj in cfg["escenarios"].items():
        p = predecir(act, est["T"], cfg["analogia"], principal, est["celdas"], est["terceros"], ajuste=aj)
        todos = {**a_lula[principal], **aj}
        e_pt = ext["pt_1"] + sum(ext[f"{g}_1"] * todos[g] for g in est["terceros"])
        e_bol = ext["bolsonaro_1"] + sum(ext[f"{g}_1"] * (1 - todos[g]) for g in est["terceros"])
        escenarios[nombre] = {"a_lula": todos, "lula_pct": nacional(p, (e_pt, e_bol))}
    # Retención y movilización como en 2018 (blanco y abstención volvieron
    # más hacia el PT) en vez de como en 2022 (más hacia Bolsonaro).
    p = predecir(act, est["T"], cfg["analogia"], principal, est["celdas"], est["terceros"], T_mov=bt["T"])
    escenarios["movilizacion_como_2018"] = {"a_lula": a_lula[principal], "lula_pct": nacional(p, exterior(principal))}
    # Solo votos válidos: Lula y Flávio retienen todo, nadie entra ni sale.
    v_t = {g: act[f"{g}_1"].sum() + ext[f"{g}_1"] for g in est["terceros"]}
    pt = act["pt_1"].sum() + ext["pt_1"] + sum(v_t[g] * a_lula[principal][g] for g in v_t)
    bol = act["bolsonaro_1"].sum() + ext["bolsonaro_1"] + sum(v_t[g] * (1 - a_lula[principal][g]) for g in v_t)
    escenarios["sin_movilizacion"] = {"a_lula": a_lula[principal], "lula_pct": pt / (pt + bol) * 100}

    por_uf = p_uf[["pt", "bolsonaro", "blanco_nulo", "abstencion", "lula_pct"]].copy()
    por_uf["lula_pct_A"] = est["pred"]["A"]["lula_pct"]
    por_uf["lula_pct_R"] = est["pred"]["R"]["lula_pct"]
    por_uf["prob_lula"] = (lula_uf > 50).mean(axis=0)
    por_uf.to_csv(out / "por_uf.csv")

    v1 = act[[c for c in act.columns if c.endswith("_1")]].sum()
    resumen = {
        "primera_vuelta": {
            "validos": float(v1.drop(["blanco_nulo_1", "abstencion_1"]).sum() + sum(ext.values())),
            "lula": float(v1["pt_1"] + ext["pt_1"]), "flavio": float(v1["bolsonaro_1"] + ext["bolsonaro_1"]),
            "terceros": {g: float(v1[f"{g}_1"] + ext[f"{g}_1"]) for g in est["terceros"]},
            "blanco_nulo": float(v1["blanco_nulo_1"]), "abstencion": float(v1["abstencion_1"]),
        },
        "composicion_terceros_por_origen_2022": comp.to_dict(orient="index"),
        "a_lula_terceros": a_lula,
        "lula_2v": {"A_analogia": pred["A"], "R_origen": pred["R"], "principal": principal},
        "montecarlo": {"n": n, "sd_nacional_pp": sd_nac, "sd_uf_pp": sd_uf,
                       "prob_lula": float((lula_nac > 50).mean()), "prob_flavio": float((lula_nac < 50).mean()),
                       "lula_media": float(lula_nac.mean()), "lula_p5_25_50_75_95": [float(x) for x in q]},
        "sensibilidad": sens,
        "escenarios_apoyos": escenarios,
        "backtest_2022": bt_res,
        "retencion_2022": {g: est["T_nac"].loc[g].to_dict() for g in ("pt", "bolsonaro", "blanco_nulo", "abstencion")},
    }
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "matrices.json").write_text(json.dumps({
        "T_2022_1v_2v_nacional": est["T_nac"].to_dict(orient="index"),
        "B_origen_2022_2v_a_2026_1v": {u: b.to_dict(orient="index") for u, b in est["B"].items()},
    }, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    np.save(out / "lula_nacional_sim.npy", lula_nac)
    shutil.copy(CONFIG_MODELO, out / "modelo.yaml")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello, "resultado_2026": str(RESULTADO_2026.name)}),
                                   encoding="utf-8")
    log.info("Lula 2ª vuelta %.2f%% (P=%.0f%%) · salida %s", lula_nac.mean(), 100 * (lula_nac > 50).mean(), out)


if __name__ == "__main__":
    main()
