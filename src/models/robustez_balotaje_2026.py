"""
src/models/robustez_balotaje_2026.py

¿Cuánto se mueve el pronóstico del balotaje (Lula 47,3 %, P(Lula) ≈ 4 %) si
cambian los datos, el método o los supuestos?

  1. Bootstrap (n réplicas): se remuestrean municípios (matriz de origen
     2022 -> 2026) y locales de votación (matriz 1ª -> 2ª vuelta 2022) dentro
     de cada UF, se reestiman las dos matrices y se recalcula el pronóstico
     sobre el resultado real completo del 4/10. Mide el error de estimación.
  2. Métodos:
       R    origen = 2ª vuelta 2022 (el del pronóstico)
       R1   origen = 1ª vuelta 2022 (Lula, Bolsonaro, Ciro, Tebet, otros,
            blanco-nulo, abstención); cada origen va a Lula como lo hizo en la
            2ª vuelta de 2022 (matriz T22). Otra identificación de los mismos votos.
       A    analogía (Cury como Ciro, etc.)
       R con todas las UF con matriz propia / todas con la de su región.
  3. Supuestos:
       retorno ρ: parte de los votantes de terceros que vuelve al lado que
       votó en 2022 (1 en el pronóstico); el resto se reparte mitad y mitad.
       incertidumbre: piso 1,0 / 1,5 / 2,0 pts y normal en vez de t(4).

Para cada variante: % Lula y P(Lula) con el mismo esquema del Montecarlo.

Salida: data/processed/electoral/robustez_balotaje_2026/<fecha_utc>/
    resumen.json, bootstrap.csv, variantes.csv

Uso:
    python -m src.models.robustez_balotaje_2026 [--n-boot 200]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.models.analisis_seccion import REGION, cargar, matriz_transferencia, transferencias
from src.models.balotaje_2026 import (DESTINO_2V, GRUPOS_1V, SALIDA_DIR as BALOTAJE_DIR, exterior_2026,
                                      municipios_2026, municipios_previos)
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "robustez_balotaje_2026"
TERCEROS = ["cury", "renan_santos", "caiado", "otros"]
ORIGEN_2V = ["pt", "bolsonaro", "blanco_nulo", "abstencion"]
ORIGEN_1V = GRUPOS_1V[2022]          # pt, bolsonaro, ciro, tebet, otros, blanco_nulo, abstencion
logging.getLogger("src.models.balotaje_2026").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Piezas genéricas (origen con cualquier conjunto de columnas)
# ---------------------------------------------------------------------------

def matriz(X: pd.DataFrame, Y: pd.DataFrame, uf: pd.Series, w: pd.Series, min_mun: int | float) -> dict:
    """B por UF (origen x destino) con restricciones; UF chicas -> matriz de su región."""
    Xn = X.to_numpy(float)
    Yn = Y.to_numpy(float)
    Xn = Xn / Xn.sum(axis=1, keepdims=True)
    Yn = Yn / Yn.sum(axis=1, keepdims=True)
    wn, un = w.to_numpy(float), uf.to_numpy()
    reg = pd.Series(un).map(REGION).to_numpy()
    por_reg = {r: matriz_transferencia(Xn[reg == r], Yn[reg == r], wn[reg == r]) for r in np.unique(reg)}
    out = {}
    for u in np.unique(un):
        s = un == u
        B = matriz_transferencia(Xn[s], Yn[s], wn[s]) if s.sum() >= min_mun else por_reg[REGION[u]]
        out[u] = pd.DataFrame(B, index=X.columns, columns=Y.columns)
    return out


def a_lula_por_uf(Xmun: pd.DataFrame, act: pd.DataFrame, B: dict, lado, rho: float = 1.0) -> dict:
    """Proporción a Lula (entre válidos) de cada tercero por UF.

    Xmun: composición de origen por município (filas suman 1), mismo índice que act.
    lado(u, t): proporción a Lula de cada origen en la UF u para el tercero t.
    rho: parte que vuelve a su lado; el resto (1-rho) se reparte 50/50.
    """
    out = {}
    for u, x in act.groupby("uf"):
        xm = Xmun.loc[x.index].to_numpy(float)
        b = B[u]
        out[u] = {}
        for t in TERCEROS:
            peso = xm * b[t].to_numpy()[None, :]
            peso = np.nan_to_num(peso)
            peso = peso / np.where(peso.sum(axis=1, keepdims=True) > 0, peso.sum(axis=1, keepdims=True), 1)
            c = (peso * x[f"{t}_1"].to_numpy(float)[:, None]).sum(axis=0)
            s = pd.Series(lado(u, t))
            a = float((c * s[Xmun.columns].to_numpy()).sum() / c.sum()) if c.sum() > 0 else 0.5
            out[u][t] = rho * a + (1 - rho) * 0.5
    return out


def pronostico(act: pd.DataFrame, T: dict, analogia: dict, a: dict, ext: dict) -> float:
    """% Lula nacional: Lula, Flávio, blanco y abstención según T; terceros válidos según su análogo y `a`."""
    pt = bol = 0.0
    for u, x in act.groupby("uf"):
        t = T[u]
        for g in ("pt", "bolsonaro", "blanco_nulo", "abstencion"):
            pt += x[f"{g}_1"].sum() * t.loc[g, "pt"]
            bol += x[f"{g}_1"].sum() * t.loc[g, "bolsonaro"]
        for g in TERCEROS:
            fila = t.loc[analogia[g]]
            v = x[f"{g}_1"].sum() * (fila["pt"] + fila["bolsonaro"])
            pt += v * a[u][g]
            bol += v * (1 - a[u][g])
    nac_a = {g: np.average([a[u][g] for u in a], weights=[act.loc[act["uf"] == u, f"{g}_1"].sum() for u in a])
             for g in TERCEROS}
    pt += ext["pt_1"] + sum(ext[f"{g}_1"] * nac_a[g] for g in TERCEROS)
    bol += ext["bolsonaro_1"] + sum(ext[f"{g}_1"] * (1 - nac_a[g]) for g in TERCEROS)
    return pt / (pt + bol) * 100


def prob_lula(mu: float, sd: float, gl: float | None, n: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    z = rng.standard_t(gl, n) / np.sqrt(gl / (gl - 2)) if gl else rng.standard_normal(n)
    return float((mu + sd * z > 50).mean())


# ---------------------------------------------------------------------------
# Datos y corrida
# ---------------------------------------------------------------------------

def preparar(cfg: dict) -> dict:
    act = municipios_2026()
    m22 = municipios_previos(2022)
    loc22 = cargar(2022, cfg["min_aptos_local"])
    j = act.join(m22, rsuffix="_22", how="inner")
    j = j[(j["aptos"] > 0) & (j["aptos_22"] > 0)]
    X2 = j[[f"{o}_2" for o in ORIGEN_2V]].set_axis(ORIGEN_2V, axis=1)
    X1 = j[[f"{o}_1_22" if f"{o}_1_22" in j else f"{o}_1" for o in ORIGEN_1V]].copy()
    # en el join, las columnas *_1 de 2022 quedan con sufijo _22 (chocan con las de 2026)
    X1.columns = ORIGEN_1V
    Y = j[[f"{g}_1" for g in GRUPOS_1V[2026]]].set_axis(GRUPOS_1V[2026], axis=1)
    return {"act": act, "loc22": loc22, "j": j, "X2": X2, "X1": X1, "Y": Y, "ext": exterior_2026()}


def lado_fn(T: dict, origen: str, analogia: dict, T_nac: pd.DataFrame):
    """Proporción a Lula de cada origen, por UF y tercero.

    2v: pt -> 1, bolsonaro -> 0; blanco y abstención de 2022 -> como el análogo del
        tercero en la UF (igual que el pronóstico publicado).
    1v: pt -> 1, bolsonaro -> 0; Ciro, Tebet, otros, blanco y abstención de 2022 ->
        como votó ese grupo en la 2ª vuelta de 2022 en la UF (matriz T22).
    """
    def f(u, t):
        tu = T[u]
        r_nac = T_nac["pt"] / (T_nac["pt"] + T_nac["bolsonaro"])
        r = (tu["pt"] / (tu["pt"] + tu["bolsonaro"])).fillna(r_nac)   # grupo sin válidos estimados en la UF
        if origen == "2v":
            ra = float(r[analogia[t]])
            return {"pt": 1.0, "bolsonaro": 0.0, "blanco_nulo": ra, "abstencion": ra}
        return {o: (1.0 if o == "pt" else 0.0 if o == "bolsonaro" else float(r[o])) for o in ORIGEN_1V}
    return f


def una(P: dict, cfg: dict, T: dict, T_nac: pd.DataFrame, origen: str, min_mun, rho: float = 1.0,
        idx_mun=None) -> float:
    j = P["j"] if idx_mun is None else P["j"].iloc[idx_mun]
    X = (P["X2"] if origen == "2v" else P["X1"])
    X = X if idx_mun is None else X.iloc[idx_mun]
    Y = P["Y"] if idx_mun is None else P["Y"].iloc[idx_mun]
    B = matriz(X.reset_index(drop=True), Y.reset_index(drop=True), j["uf"].reset_index(drop=True),
               j["aptos"].reset_index(drop=True), min_mun)
    Xfull = (P["X2"] if origen == "2v" else P["X1"])
    Xfull = Xfull.div(Xfull.sum(axis=1), axis=0)
    act = P["act"].loc[Xfull.index]
    a = a_lula_por_uf(Xfull, act, B, lado_fn(T, origen, cfg["analogia"], T_nac), rho)
    return pronostico(P["act"], T, cfg["analogia"], a, P["ext"])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-boot", type=int, default=200)
    args = ap.parse_args(argv)
    cfg_all = cargar_config()
    cfg = {**cfg_all["seccion"], **cfg_all["balotaje"]}
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)
    base_run = sorted(p.parent for p in BALOTAJE_DIR.glob("*/meta.json"))[-1]
    R = json.loads((base_run / "resumen.json").read_text(encoding="utf-8"))
    sd_base, n_mc, gl = R["montecarlo"]["sd_nacional_pp"], 20000, cfg["grados_libertad_t"]

    P = preparar(cfg)
    T_nac, T = transferencias(P["loc22"], GRUPOS_1V[2022], DESTINO_2V)
    mm = cfg["min_municipios_uf"]

    # 2 y 3 · variantes
    var = []
    def agregar(nombre, grupo, mu, sd=sd_base, g=gl):
        var.append({"variante": nombre, "grupo": grupo, "lula_pct": mu, "sd_pp": sd,
                    "prob_lula": prob_lula(mu, sd, g, n_mc, cfg["random_seed"])})
        log.info("%-55s Lula %.2f  P(Lula) %.1f%%", nombre, mu, 100 * var[-1]["prob_lula"])

    base = una(P, cfg, T, T_nac, "2v", mm)
    agregar("Pronóstico: origen 2ª vuelta 2022 (R)", "base", base)
    agregar("Origen 1ª vuelta 2022 (R1)", "método", una(P, cfg, T, T_nac, "1v", mm))
    agregar("Analogía (A)", "método", R["lula_2v"]["A_analogia"])
    agregar("R con matriz propia en todas las UF", "método", una(P, cfg, T, T_nac, "2v", 0))
    agregar("R con la matriz de la región en todas las UF", "método", una(P, cfg, T, T_nac, "2v", np.inf))
    for rho in (0.8, 0.6):
        agregar(f"Retorno de los terceros a su lado de 2022: {rho:.0%}", "supuesto", una(P, cfg, T, T_nac, "2v", mm, rho))
    agregar("Movilización como en 2018", "supuesto", R["escenarios_apoyos"]["movilizacion_como_2018"]["lula_pct"])
    agregar("Sin movilización (solo votos válidos)", "supuesto", R["escenarios_apoyos"]["sin_movilizacion"]["lula_pct"])
    for piso in (1.0, 2.0):
        sd = float(np.sqrt(sd_base ** 2 - cfg["sigma_nacional_extra_pp"] ** 2 + piso ** 2))
        agregar(f"Piso de incertidumbre {f'{piso:.1f}'.replace('.', ',')} pts", "incertidumbre", base, sd)
    agregar("Incertidumbre normal en vez de t(4)", "incertidumbre", base, sd_base, None)

    # 1 · bootstrap
    rng = np.random.default_rng(cfg["random_seed"])
    j = P["j"]
    grupos_uf = j.reset_index().groupby("uf").indices
    loc = P["loc22"]
    boot = []
    for b in range(args.n_boot):
        idx_mun = np.concatenate([rng.choice(ix, len(ix), replace=True) for ix in grupos_uf.values()])
        loc_b = loc.groupby("uf").sample(frac=1, replace=True, random_state=int(rng.integers(1e9)))
        Tn_b, T_b = transferencias(loc_b, GRUPOS_1V[2022], DESTINO_2V)
        boot.append({"replica": b, "lula_pct": una(P, cfg, T_b, Tn_b, "2v", mm, idx_mun=idx_mun)})
        if (b + 1) % 20 == 0:
            log.info("bootstrap %d/%d", b + 1, args.n_boot)
    boot = pd.DataFrame(boot)
    boot.to_csv(out / "bootstrap.csv", index=False)
    sd_boot = float(boot["lula_pct"].std())
    q = boot["lula_pct"].quantile([0.05, 0.5, 0.95]).to_list()
    sd_total = float(np.sqrt(sd_base ** 2 + sd_boot ** 2))
    agregar("Incertidumbre + error de estimación del bootstrap", "incertidumbre", base, sd_total)

    v = pd.DataFrame(var)
    v.to_csv(out / "variantes.csv", index=False)
    resumen = {"base_lula": base, "pronostico_publicado": R["montecarlo"]["lula_media"],
               "prob_publicada": R["montecarlo"]["prob_lula"],
               "bootstrap": {"n": args.n_boot, "media": float(boot["lula_pct"].mean()), "sd": sd_boot,
                             "p5_p50_p95": q, "max": float(boot["lula_pct"].max())},
               "rango_variantes": [float(v["lula_pct"].min()), float(v["lula_pct"].max())],
               "prob_max": float(v["prob_lula"].max()),
               "variantes": v.to_dict(orient="records"), "corrida_balotaje": base_run.name}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello}), encoding="utf-8")
    log.info("bootstrap: sd %.2f pts, p5-p95 %.2f–%.2f; variantes %.2f–%.2f; P(Lula) máx %.1f%%", sd_boot, q[0], q[2],
             v["lula_pct"].min(), v["lula_pct"].max(), 100 * v["prob_lula"].max())
    log.info("salida %s", out)


if __name__ == "__main__":
    main()
