"""
src/models/balotaje_gobernadores_2026.py

Balotajes de gobernador del 25/10/2026 desde el resultado de la 1ª vuelta
(TSE), sin encuestas (decisión del 2026-10-07).

Siete UF van a 2ª vuelta. En cada una, presidente y gobernador se votaron el
mismo día y con los mismos electores, así que el voto presidencial sirve de
"origen" del voto a gobernador:

  1. Unidad: município × zona electoral (el TSE publica la divulgación por
     zona; el DF, con un solo município, tiene 19 zonas).
  2. Regresión ecológica con restricciones, por UF: grupos presidenciales
     (Lula, Flávio, terceros, blanco-nulo) -> grupos de gobernador
     (finalista A, finalista B, eliminados, blanco-nulo), en proporción de
     la comparecencia.
  3. Los votantes de eliminados se descomponen por grupo presidencial en
     cada unidad (ajuste proporcional a lo observado) y cada grupo se reparte
     entre A y B como se repartió en la 1ª vuelta entre quienes votaron a A o B:
         P(A | g) = B[g, A] / (B[g, A] + B[g, B])
  4. Ingenuo (referencia): cada finalista conserva su proporción de 1ª vuelta.

Backtest con los 26 balotajes de gobernador de 2018 y 2022 (mismas unidades,
desde las secciones), para tres pronósticos: origen, ingenuo y el promedio de
los dos (`balotaje.gobernador_metodo`). El error cuadrático medio del elegido
fija la incertidumbre de cada UF en el Montecarlo (t de Student, 4 gl).

Salida: data/processed/electoral/balotaje_gobernadores_2026/<fecha_utc>/
    resumen.json, por_uf.csv, backtest.csv, matrices.json, meta.json

Uso:
    python -m src.models.balotaje_gobernadores_2026
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.etl.transform.votacion_seccion import SALIDA_DIR as SECCION_DIR
from src.models.analisis_seccion import matriz_transferencia
from src.models.conteo_2026 import CLAVES, RAW, _get
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "balotaje_gobernadores_2026"
ZONAS_RAW = RAW / "zonas"
BASE = "https://resultados.tse.jus.br/oficial/ele2026/{e}"
ELEICAO_PRES, ELEICAO_EST = "6257", "6259"
CARGO = {"presidente": ("0001", ELEICAO_PRES), "gobernador": ("0003", ELEICAO_EST)}
PRES = ["pt", "bolsonaro", "terceros", "blanco_nulo"]
GOB = ["A", "B", "elim", "blanco_nulo"]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


# ---------------------------------------------------------------------------
# Datos 2026 (TSE, divulgación)
# ---------------------------------------------------------------------------

def resultado_uf_gobernador() -> dict:
    """Por UF: candidatos (número, nombre, partido, votos, situación) del 1º turno."""
    from src.models.conteo_2026 import UFS

    def uno(uf):
        d = json.loads(_get(f"{BASE.format(e=ELEICAO_EST)}/dados/{uf}/{uf}-c0003-e00{ELEICAO_EST}-u.json"))
        cands = [{"n": c["n"], "nombre": c["nmu"], "partido": p["sg"], "votos": int(c["vap"]),
                  "pct": _num(c["pvapn"]), "situacion": c["st"]}
                 for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]]
        return uf.upper(), sorted(cands, key=lambda c: -c["votos"])

    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(uno, [u for u in UFS if u != "zz"]))


def zonas(ufs: list[str], cargo: str) -> pd.DataFrame:
    """Una fila por município × zona: votos por candidato (columna = número), blancos, nulos, comparecencia."""
    cod, ele = CARGO[cargo]
    cfg = json.loads(_get(f"{BASE.format(e=ele)}/config/mun-e00{ele}-cm.json"))
    pedidos = [(a["cd"], m["cd"], z) for a in cfg["abr"] if a["cd"] in ufs for m in a["mu"] for z in m["z"]]
    carpeta = ZONAS_RAW / f"{ele}_c{cod}"
    carpeta.mkdir(parents=True, exist_ok=True)

    def uno(t):
        uf, mu, z = t
        destino = carpeta / f"{uf}{mu}-z{z}.json"
        if destino.exists():
            crudo = destino.read_bytes()
        else:
            crudo = _get(f"{BASE.format(e=ele)}/dados/{uf}/{uf}{mu}-z{z}-c{cod}-e00{ele}-u.json")
            destino.write_bytes(crudo)
        d = json.loads(crudo)
        fila = {"uf": uf.upper(), "mu": mu, "zona": z, "pct_secciones": _num(d["s"]["pst"]),
                "aptos": int(d["e"]["te"]), "comparecencia": int(d["e"]["c"]),
                "blanco_nulo": int(d["v"]["vb"]) + int(d["v"]["tvn"])}
        for a in d["carg"][0]["agr"]:
            for p in a["par"]:
                for c in p["cand"]:
                    clave = CLAVES.get(c["nmu"], c["n"]) if cargo == "presidente" else c["n"]
                    fila[clave] = fila.get(clave, 0) + int(c["vap"])
        return fila

    with ThreadPoolExecutor(6) as ex:
        df = pd.DataFrame(list(ex.map(uno, pedidos))).fillna(0)
    log.info("%s: %d unidades município×zona en %s", cargo, len(df), ",".join(u.upper() for u in ufs))
    return df


# ---------------------------------------------------------------------------
# Grupos y método
# ---------------------------------------------------------------------------

def grupos_pres(df: pd.DataFrame, pt: str, bol: str) -> pd.DataFrame:
    cand = [c for c in df.columns if c not in ("uf", "mu", "zona", "pct_secciones", "aptos", "comparecencia", "blanco_nulo")]
    return pd.DataFrame({"pt": df[pt], "bolsonaro": df[bol],
                         "terceros": df[[c for c in cand if c not in (pt, bol)]].sum(axis=1),
                         "blanco_nulo": df["blanco_nulo"]}, index=df.index)


def grupos_gob(df: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    cand = [c for c in df.columns if c not in ("uf", "mu", "zona", "pct_secciones", "aptos", "comparecencia", "blanco_nulo")]
    return pd.DataFrame({"A": df[a], "B": df[b], "elim": df[[c for c in cand if c not in (a, b)]].sum(axis=1),
                         "blanco_nulo": df["blanco_nulo"]}, index=df.index)


def proyectar(P: pd.DataFrame, G: pd.DataFrame) -> dict:
    """P y G: votos por unidad (mismo índice). Devuelve matriz, reparto de eliminados y % de A en la 2ª vuelta."""
    X = P[PRES].to_numpy(float)
    Y = G[GOB].to_numpy(float)
    X = X / X.sum(axis=1, keepdims=True)
    Y = Y / Y.sum(axis=1, keepdims=True)
    w = P[PRES].sum(axis=1).to_numpy(float)
    Bm = pd.DataFrame(matriz_transferencia(X, Y, w), index=PRES, columns=GOB)
    # votantes de eliminados por grupo presidencial en cada unidad
    peso = X * Bm["elim"].to_numpy()[None, :]
    peso = peso / np.where(peso.sum(axis=1, keepdims=True) > 0, peso.sum(axis=1, keepdims=True), 1)
    elim_g = peso * G["elim"].to_numpy(float)[:, None]
    a_g = (Bm["A"] / (Bm["A"] + Bm["B"])).fillna(0.5).to_numpy()
    va, vb, ve = G["A"].sum(), G["B"].sum(), G["elim"].sum()
    a_elim = float((elim_g.sum(axis=0) * a_g).sum() / ve) if ve else 0.5
    return {"B": Bm, "a_por_grupo": dict(zip(PRES, a_g)), "elim_por_grupo": dict(zip(PRES, elim_g.sum(axis=0) / ve)),
            "a_elim": a_elim, "pct_A": (va + ve * a_elim) / (va + vb + ve) * 100,
            "pct_A_ingenuo": va / (va + vb) * 100, "pct_A_1v": va / (va + vb + ve + 0) * 100}


# ---------------------------------------------------------------------------
# Backtest 2022
# ---------------------------------------------------------------------------

BOLSONARO = {2018: "v_17", 2022: "v_22"}
BN = ("v_95", "v_96", "v_97")


def backtest(ano: int) -> pd.DataFrame:
    g = pd.read_parquet(SECCION_DIR / f"gobernador_seccion_{ano}.parquet")
    p = pd.read_parquet(SECCION_DIR / f"presidente_seccion_{ano}.parquet")
    bol = BOLSONARO[ano]
    clave = ["uf", "cd_municipio", "nr_zona"]
    vcols = lambda d: [c for c in d.columns if c.startswith("v_")]
    p1 = p[p["turno"] == 1].groupby(clave)[vcols(p) + ["comparecencia"]].sum()
    g1 = g[g["turno"] == 1].groupby(clave)[vcols(g)].sum()
    g2 = g[g["turno"] == 2].groupby(clave)[vcols(g)].sum()
    filas = []
    for uf in sorted(g2.index.get_level_values("uf").unique()):
        t2 = g2.xs(uf, level="uf").sum()
        fin = t2.drop(list(BN), errors="ignore").nlargest(2)
        a, b = fin.index
        real = t2[a] / (t2[a] + t2[b]) * 100
        pu = p1.xs(uf, level="uf", drop_level=False)
        gu = g1.xs(uf, level="uf", drop_level=False).reindex(pu.index).fillna(0)
        cand_p = [c for c in vcols(p) if c not in BN]
        cand_g = [c for c in vcols(g) if c not in BN]
        P = pd.DataFrame({"pt": pu["v_13"], "bolsonaro": pu[bol],
                          "terceros": pu[[c for c in cand_p if c not in ("v_13", bol)]].sum(axis=1),
                          "blanco_nulo": pu[[c for c in BN if c in pu]].sum(axis=1)})
        G = pd.DataFrame({"A": gu[a], "B": gu[b], "elim": gu[[c for c in cand_g if c not in (a, b)]].sum(axis=1),
                          "blanco_nulo": gu[[c for c in BN if c in gu]].sum(axis=1)})
        ok = (P.sum(axis=1) > 0) & (G.sum(axis=1) > 0)
        r = proyectar(P[ok], G[ok])
        filas.append({"ano": ano, "uf": uf, "finalista_A": a, "finalista_B": b, "unidades": int(ok.sum()),
                      "pct_A_1v_entre_finalistas": r["pct_A_ingenuo"], "real": real,
                      "predicho": r["pct_A"], "error": r["pct_A"] - real,
                      "error_ingenuo": r["pct_A_ingenuo"] - real,
                      "promedio": (r["pct_A"] + r["pct_A_ingenuo"]) / 2,
                      "error_promedio": (r["pct_A"] + r["pct_A_ingenuo"]) / 2 - real,
                      "elim_pct_1v": float(G["elim"].sum() / G[["A", "B", "elim"]].sum().sum() * 100),
                      "ganador_ok": (r["pct_A"] > 50) == (real > 50),
                      "ganador_ok_ingenuo": (r["pct_A_ingenuo"] > 50) == (real > 50),
                      "ganador_ok_promedio": ((r["pct_A"] + r["pct_A_ingenuo"]) / 2 > 50) == (real > 50),
                      "remontada": r["pct_A_ingenuo"] < 50})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = cargar_config()["balotaje"]
    rng = np.random.default_rng(cfg["random_seed"])
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)

    log.info("backtest 2018 y 2022")
    bt = pd.concat([backtest(2018), backtest(2022)], ignore_index=True)
    bt.to_csv(out / "backtest.csv", index=False)
    met = {m: {"rmse_pp": float(np.sqrt((bt[e] ** 2).mean())), "mae_pp": float(bt[e].abs().mean()),
               "sesgo_pp": float(bt[e].mean()), "ganador_ok": int(bt[g].sum())}
           for m, e, g in (("origen", "error", "ganador_ok"), ("ingenuo", "error_ingenuo", "ganador_ok_ingenuo"),
                           ("promedio", "error_promedio", "ganador_ok_promedio"))}
    for m, v in met.items():
        log.info("backtest %-8s RMSE %.2f pp · ganador %d/%d", m, v["rmse_pp"], v["ganador_ok"], len(bt))
    log.info("remontadas (ganó el 2º de la 1ª vuelta): %d de %d", bt["remontada"].sum(), len(bt))
    principal = cfg["gobernador_metodo"]
    rmse = met[principal]["rmse_pp"]

    res_uf = resultado_uf_gobernador()
    bal = {uf: c[:2] for uf, c in res_uf.items() if sum(x["situacion"] == "2º turno" for x in c) == 2}
    ufs = sorted(u.lower() for u in bal)
    log.info("balotaje de gobernador en %s", ", ".join(u.upper() for u in ufs))
    zp, zg = zonas(ufs, "presidente"), zonas(ufs, "gobernador")
    clave = ["uf", "mu", "zona"]
    zp, zg = zp.set_index(clave), zg.set_index(clave).reindex(zp.set_index(clave).index).fillna(0)

    gl = 4
    escala = rmse / np.sqrt(gl / (gl - 2))
    filas, matrices = [], {}
    for uf in sorted(bal):
        a, b = bal[uf]
        P = grupos_pres(zp.xs(uf, level="uf"), "lula", "flavio_bolsonaro")
        G = grupos_gob(zg.xs(uf, level="uf"), a["n"], b["n"])
        r = proyectar(P, G)
        centro = {"origen": r["pct_A"], "ingenuo": r["pct_A_ingenuo"],
                  "promedio": (r["pct_A"] + r["pct_A_ingenuo"]) / 2}[principal]
        sim = centro + rng.standard_t(gl, cfg["n_simulaciones"]) * escala
        matrices[uf] = {"B": r["B"].to_dict(orient="index"), "a_por_grupo": r["a_por_grupo"],
                        "elim_por_grupo": r["elim_por_grupo"]}
        filas.append({"uf": uf, "A": a["nombre"], "partido_A": a["partido"], "pct_A_1v": a["pct"],
                      "B": b["nombre"], "partido_B": b["partido"], "pct_B_1v": b["pct"],
                      "elim_pct_1v": 100 - a["pct"] - b["pct"],
                      "eliminados": "; ".join(f"{c['nombre']} ({c['partido']}) {c['pct']:.1f}" for c in res_uf[uf][2:5]),
                      "unidades": len(P), "a_elim": r["a_elim"], "pct_A_origen": r["pct_A"],
                      "pct_A_ingenuo": r["pct_A_ingenuo"], "pct_A_2v": centro,
                      "lula_entre_A": r["B"].loc["pt", "A"] / r["B"]["A"].mul(P[PRES].sum().to_numpy() / P[PRES].sum().sum()).sum()
                      if r["B"]["A"].sum() else np.nan,
                      "a_de_lula": r["a_por_grupo"]["pt"], "a_de_flavio": r["a_por_grupo"]["bolsonaro"],
                      "a_de_terceros": r["a_por_grupo"]["terceros"],
                      "p5": float(np.percentile(sim, 5)), "p95": float(np.percentile(sim, 95)),
                      "prob_A": float((sim > 50).mean())})
    df = pd.DataFrame(filas).drop(columns="lula_entre_A")
    df.to_csv(out / "por_uf.csv", index=False)
    resumen = {"ufs_balotaje": df.to_dict(orient="records"),
               "backtest_2018_2022": {"metodos": met, "n": len(bt), "remontadas": int(bt["remontada"].sum()),
                                      "principal": principal},
               "montecarlo": {"n": cfg["n_simulaciones"], "t_gl": gl, "sd_pp": rmse},
               "primera_vuelta_por_uf": res_uf}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "matrices.json").write_text(json.dumps(matrices, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello}), encoding="utf-8")
    for r in filas:
        log.info("%s: %s %.1f%% (P=%.0f%%) vs %s · eliminados a A: %.0f%%", r["uf"], r["A"], r["pct_A_2v"],
                 100 * r["prob_A"], r["B"], 100 * r["a_elim"])
    log.info("salida %s", out)


if __name__ == "__main__":
    main()
