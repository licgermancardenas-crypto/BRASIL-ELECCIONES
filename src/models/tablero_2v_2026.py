"""
src/models/tablero_2v_2026.py

Tablero para la noche del balotaje (25/10/2026): conteo del TSE contra el
pronóstico por município, sin encuestas.

Idea: el conteo no llega parejo (el Nordeste suele contar más tarde), así que
el % contado engaña durante horas. Cada município contado se compara con su
pronóstico (src/models/balotaje_2026.py, municipios.parquet):

    desvío_i = % Lula contado_i − % Lula pronosticado_i

El desvío medio ponderado por votos se calcula por UF, se encoge hacia el de
su región y el de la región hacia el nacional (K votos de "pseudo-conteo",
config `tablero.k_votos`). Lo que falta contar en cada município se proyecta
con su pronóstico más su propio desvío (si ya contó una parte, pesado por el %
de secciones contadas) o el de su UF. La incertidumbre arranca en la del
Montecarlo del pronóstico y se achica con la parte de los votos ya contada.

Gobernadores (7 UF con balotaje): % contado del primero contra el pronóstico.

Salidas:
    data/processed/electoral/tablero_2v/<fecha_utc>/estado.json   (una foto por corrida)
    data/processed/electoral/tablero_2v/historia.csv               (la proyección a lo largo de la noche)
    reports/tablero/tablero_2v.html                                (se recarga solo cada 60 s)

Uso:
    python -m src.models.tablero_2v_2026                 # una lectura del TSE
    python -m src.models.tablero_2v_2026 --loop 180      # cada 3 minutos hasta el 100 %
    python -m src.models.tablero_2v_2026 --simular-2022  # prueba con la 2ª vuelta de 2022
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from math import erf, sqrt

import numpy as np
import pandas as pd

from src.models.analisis_seccion import REGION
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.balotaje_gobernadores_2026 import SALIDA_DIR as GOBERNADORES_DIR
from src.models.conteo_2026 import CLAVES, _get
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "tablero_2v"
HTML = ROOT / "reports" / "tablero" / "tablero_2v.html"
BASE = "https://resultados.tse.jus.br/oficial/ele2026/{e}"
ELE_PRES, ELE_GOB, ELE_PRES_1V = "6258", "6260", "6257"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa",
       "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def phi(z: float) -> float:
    return 0.5 * (1 + erf(z / sqrt(2)))


def ultima(base):
    return sorted(p.parent for p in base.glob("*/meta.json"))[-1]


# ---------------------------------------------------------------------------
# Pronóstico
# ---------------------------------------------------------------------------

def cargar_pronostico() -> dict:
    run = ultima(BALOTAJE_DIR)
    R = json.loads((run / "resumen.json").read_text(encoding="utf-8"))
    mun = pd.read_parquet(run / "municipios.parquet")
    mun["validos_pred"] = mun["pt"] + mun["bolsonaro"]
    mun["p"] = mun["pt"] / mun["validos_pred"]
    pv = R["primera_vuelta"]
    # exterior: 1ª vuelta del exterior + terceros con la proporción nacional del método R
    from src.models.conteo_2026 import SALIDA as CONTEO_1V
    zz = json.loads(CONTEO_1V.read_text(encoding="utf-8"))["por_uf"]["zz"]["votos"]
    a = R["a_lula_terceros"]["R"]
    terc = {"cury": zz["cury"], "renan_santos": zz["renan_santos"], "caiado": zz["caiado"],
            "otros": zz["zema"] + zz["otros"]}
    ext_pt = zz["lula"] + sum(v * a[k] for k, v in terc.items())
    ext_val = zz["lula"] + zz["flavio_bolsonaro"] + sum(terc.values())
    gob = None
    try:
        gob = pd.read_csv(ultima(GOBERNADORES_DIR) / "por_uf.csv")
    except IndexError:
        pass
    return {"run": run.name, "mun": mun[["uf", "validos_pred", "p"]], "lula": R["montecarlo"]["lula_media"],
            "sd": R["montecarlo"]["sd_nacional_pp"], "prob": R["montecarlo"]["prob_lula"],
            "ext_p": ext_pt / ext_val, "ext_val": ext_val, "gob": gob, "validos_1v": pv["validos"]}


# ---------------------------------------------------------------------------
# Estimador
# ---------------------------------------------------------------------------

def proyectar(pron: dict, cont: pd.DataFrame, ext: tuple[float, float, float], k: float) -> dict:
    """cont: por município (índice = código) lula, flavio, pct (0-1). ext: (lula, flavio, pct) del exterior."""
    m = pron["mun"].join(cont, how="left").fillna({"lula": 0, "flavio": 0, "pct": 0})
    m["region"] = m["uf"].map(REGION)
    c = m["lula"] + m["flavio"]
    m["r"] = np.where(c > 0, m["lula"] / c.where(c > 0, 1) - m["p"], np.nan)
    hay = c > 0

    def media(g):
        w = c[g.index][hay[g.index]]
        return (float((m.loc[w.index, "r"] * w).sum()), float(w.sum()))

    tot_r, tot_w = media(m)
    nac = tot_r / tot_w if tot_w else 0.0
    reg = {}
    for r, g in m.groupby("region"):
        s, w = media(g)
        reg[r] = (s + k * nac) / (w + k)
    swing_uf = {}
    for u, g in m.groupby("uf"):
        s, w = media(g)
        swing_uf[u] = (s + k * reg[REGION[u]]) / (w + k)
    m["swing"] = m["uf"].map(swing_uf)
    # tamaño final estimado: lo contado escalado por % de secciones, o el pronóstico
    total = np.where(m["pct"] > 0.02, c / m["pct"].clip(lower=0.02), m["validos_pred"])
    total = np.maximum(total, c)
    resto = total - c
    own = m["r"].fillna(0) * m["pct"] + m["swing"] * (1 - m["pct"])
    p_resto = (m["p"] + own).clip(0, 1)
    lula_proj = m["lula"] + resto * p_resto
    ext_l, ext_f, ext_pct = ext
    ext_c = ext_l + ext_f
    ext_tot = max(pron["ext_val"], ext_c)
    ext_proj_l = ext_l + (ext_tot - ext_c) * (pron["ext_p"] + nac)
    L = lula_proj.sum() + ext_proj_l
    V = total.sum() + ext_tot
    contado_l, contado_v = m["lula"].sum() + ext_l, c.sum() + ext_c
    frac = contado_v / V if V else 0
    proj = L / V * 100
    sd = max(pron["sd"] * (1 - frac), 0.15)
    por_uf = m.assign(c=c, lula_proj=lula_proj, total=total, esperado=m["p"] * c).groupby("uf").agg(
        contado_l=("lula", "sum"), contado_v=("c", "sum"), esperado_l=("esperado", "sum"),
        proj_l=("lula_proj", "sum"), total=("total", "sum"))
    por_uf["pct_contado"] = por_uf["contado_v"] / por_uf["total"] * 100
    por_uf["lula_contado"] = por_uf["contado_l"] / por_uf["contado_v"].where(por_uf["contado_v"] > 0) * 100
    por_uf["lula_esperado_en_lo_contado"] = por_uf["esperado_l"] / por_uf["contado_v"].where(por_uf["contado_v"] > 0) * 100
    por_uf["desvio"] = por_uf["lula_contado"] - por_uf["lula_esperado_en_lo_contado"]
    por_uf["lula_proj"] = por_uf["proj_l"] / por_uf["total"] * 100
    por_uf["pronostico"] = pron["mun"].assign(pt=pron["mun"]["p"] * pron["mun"]["validos_pred"]).groupby("uf") \
        .apply(lambda g: g["pt"].sum() / g["validos_pred"].sum() * 100, include_groups=False)
    esperado_contado = (m["p"] * c).sum() + pron["ext_p"] * ext_c
    return {"votos_contados_pct": frac * 100,
            "lula_contado": contado_l / contado_v * 100 if contado_v else None,
            "lula_esperado_en_lo_contado": esperado_contado / contado_v * 100 if contado_v else None,
            "desvio_nacional_pp": nac * 100, "desvio_por_region_pp": {r: v * 100 for r, v in reg.items()},
            "lula_proyectado": proj, "sd_pp": sd, "prob_lula": phi((proj - 50) / sd),
            "lula_pronostico": pron["lula"], "por_uf": por_uf.reset_index()}


# ---------------------------------------------------------------------------
# TSE
# ---------------------------------------------------------------------------

def leer_pres(d: dict) -> tuple[float, float, float]:
    v = {}
    for a in d["carg"][0]["agr"]:
        for p in a["par"]:
            for c in p["cand"]:
                v[CLAVES.get(c["nmu"], c["nmu"])] = int(c["vap"])
    return v.get("lula", 0), v.get("flavio_bolsonaro", 0), _num(d["s"]["pst"]) / 100


def bajar_conteo(previo: pd.DataFrame | None) -> tuple[pd.DataFrame, tuple, dict]:
    """Conteo presidencial por município (incremental) y el exterior. Lanza si el TSE todavía no publica."""
    base = BASE.format(e=ELE_PRES)
    ext = leer_pres(json.loads(_get(f"{base}/dados/zz/zz-c0001-e00{ELE_PRES}-u.json")))
    cfg = None
    for e in (ELE_PRES, ELE_PRES_1V):
        try:
            cfg = json.loads(_get(f"{BASE.format(e=e)}/config/mun-e00{e}-cm.json"))
            break
        except Exception:
            continue
    lista = [(a["cd"], m["cd"], int(m["cdi"])) for a in cfg["abr"] if a["cd"] != "zz" for m in a["mu"]]
    hechos = set() if previo is None else set(previo.index[previo["pct"] >= 1])
    pedir = [t for t in lista if t[2] not in hechos]

    def uno(t):
        uf, mu, ibge = t
        try:
            return ibge, leer_pres(json.loads(_get(f"{base}/dados/{uf}/{uf}{mu}-c0001-e00{ELE_PRES}-u.json", 2)))
        except Exception:
            return ibge, None

    with ThreadPoolExecutor(6) as ex:
        filas = {i: r for i, r in ex.map(uno, pedir) if r is not None}
    nuevo = pd.DataFrame.from_dict(filas, orient="index", columns=["lula", "flavio", "pct"])
    df = nuevo if previo is None else pd.concat([previo.drop(nuevo.index, errors="ignore"), nuevo])
    df.index.name = "codigo"
    uf_hora = json.loads(_get(f"{base}/dados/sp/sp-c0001-e00{ELE_PRES}-u.json"))
    return df, ext, {"hora_tse": f'{uf_hora["dg"]} {uf_hora["hg"]}', "pedidos": len(pedir), "recibidos": len(filas)}


def bajar_gobernadores(gob: pd.DataFrame | None) -> list[dict]:
    if gob is None:
        return []
    out = []
    for r in gob.itertuples():
        fila = {"uf": r.uf, "A": r.A, "B": r.B, "pronostico_A": r.pct_A_2v, "prob_A": r.prob_A}
        try:
            d = json.loads(_get(f"{BASE.format(e=ELE_GOB)}/dados/{r.uf.lower()}/{r.uf.lower()}-c0003-e00{ELE_GOB}-u.json", 1))
            v = {c["nmu"]: int(c["vap"]) for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
            a, b = v.get(r.A, 0), v.get(r.B, 0)
            fila.update({"pct_secciones": _num(d["s"]["pst"]), "A_contado": a / (a + b) * 100 if a + b else None})
        except Exception:
            fila.update({"pct_secciones": 0.0, "A_contado": None})
        out.append(fila)
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def f1(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1f}".replace(".", ",")


def svg_historia(h: pd.DataFrame, pronostico: float) -> str:
    if len(h) < 2:
        return '<p class="nota">La curva aparece a partir de la segunda lectura.</p>'
    W, H, pad = 640, 220, 34
    x = h["votos_contados_pct"].to_numpy()
    ys = np.concatenate([h["lula_contado"].dropna().to_numpy(), h["lula_proyectado"].to_numpy(), [50, pronostico]])
    lo, hi = np.floor(ys.min() - 1), np.ceil(ys.max() + 1)
    X = lambda v: pad + (W - 2 * pad) * v / 100
    Y = lambda v: H - pad - (H - 2 * pad) * (v - lo) / (hi - lo)
    linea = lambda col, c: " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(x, h[col]) if pd.notna(b))
    return (f'<svg viewBox="0 0 {W} {H}" class="hist">'
            f'<line x1="{pad}" x2="{W - pad}" y1="{Y(50):.1f}" y2="{Y(50):.1f}" class="eje"/>'
            f'<text x="{W - pad}" y="{Y(50) - 4:.1f}" class="et" text-anchor="end">50 %</text>'
            f'<line x1="{pad}" x2="{W - pad}" y1="{Y(pronostico):.1f}" y2="{Y(pronostico):.1f}" class="pron"/>'
            f'<text x="{pad}" y="{Y(pronostico) - 4:.1f}" class="et">pronóstico {f1(pronostico)} %</text>'
            f'<polyline points="{linea("lula_contado", "c")}" class="contado"/>'
            f'<polyline points="{linea("lula_proyectado", "p")}" class="proy"/>'
            f'<text x="{pad}" y="{H - 8}" class="et">0 % contado</text>'
            f'<text x="{W - pad}" y="{H - 8}" class="et" text-anchor="end">100 %</text></svg>')


def html(est: dict, gob: list, meta: dict, hist: pd.DataFrame) -> str:
    uf = est["por_uf"].sort_values("total", ascending=False)
    filas = "".join(
        f'<tr><td>{r.uf}</td><td class="n">{f1(r.pct_contado)}</td><td class="n">{f1(r.lula_contado)}</td>'
        f'<td class="n">{f1(r.lula_esperado_en_lo_contado)}</td>'
        f'<td class="n {"pos" if (r.desvio or 0) > 0.5 else "neg" if (r.desvio or 0) < -0.5 else ""}">'
        f'{"" if pd.isna(r.desvio) else ("+" if r.desvio > 0 else "")}{f1(r.desvio)}</td>'
        f'<td class="n">{f1(r.lula_proj)}</td><td class="n">{f1(r.pronostico)}</td></tr>' for r in uf.itertuples())
    filas_g = "".join(
        f'<tr><td>{g["uf"]}</td><td>{g["A"].title()} vs {g["B"].title()}</td><td class="n">{f1(g["pct_secciones"])}</td>'
        f'<td class="n">{f1(g["A_contado"])}</td><td class="n">{f1(g["pronostico_A"])}</td>'
        f'<td class="n">{round(g["prob_A"] * 100)} %</td></tr>' for g in gob) or         '<tr><td colspan="6" class="nota">Sin datos de gobernador en esta lectura.</td></tr>'
    d = est["desvio_nacional_pp"]
    lado = "Lula" if d > 0 else "Flávio"
    reg = " · ".join(f"{r} {'+' if v > 0 else ''}{f1(v)}" for r, v in sorted(est["desvio_por_region_pp"].items()))
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Tablero balotaje Brasil</title><style>
:root {{ --ink:#1D1631; --muted:#6B6480; --vio:#5B3F99; --rule:#D9D2E6; --bg:#FAF8FD; --lula:#E34948; --fla:#2A78D6; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font-family:Arial,Helvetica,sans-serif; color:var(--ink); background:#fff; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 48px; }}
.kicker {{ font-size:11px; letter-spacing:.14em; color:var(--vio); font-weight:bold; }}
h1 {{ font-size:26px; margin:6px 0 4px; }} .sub {{ color:var(--muted); font-size:13px; margin:0 0 18px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:22px; }}
.kpi {{ border-top:3px solid var(--vio); background:var(--bg); padding:12px; }}
.kpi b {{ display:block; font-size:28px; }} .kpi span {{ font-size:12px; color:var(--muted); }}
.alerta {{ border-left:4px solid var(--vio); background:#F3EFF9; padding:12px 16px; font-size:15px; margin-bottom:20px; }}
.dos {{ display:grid; grid-template-columns:1.1fr .9fr; gap:24px; }} @media (max-width:820px) {{ .dos {{ grid-template-columns:1fr; }} }}
h2 {{ font-size:15px; margin:18px 0 8px; border-bottom:2px solid var(--ink); padding-bottom:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }} th {{ background:var(--ink); color:#fff; text-align:left; padding:6px; font-size:11px; }}
td {{ padding:5px 6px; border-bottom:1px solid #EDEAF3; }} td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pos {{ color:var(--lula); font-weight:bold; }} .neg {{ color:var(--fla); font-weight:bold; }}
.hist {{ width:100%; height:auto; }} .eje {{ stroke:var(--ink); stroke-width:1; }} .pron {{ stroke:var(--muted); stroke-dasharray:4 3; }}
.contado {{ fill:none; stroke:#B8B0C8; stroke-width:2.5; }} .proy {{ fill:none; stroke:var(--vio); stroke-width:3; }}
.et {{ font-size:11px; fill:var(--muted); }} .nota {{ font-size:12px; color:var(--muted); }}
.ley i {{ display:inline-block; width:18px; height:3px; vertical-align:middle; margin:0 6px 0 12px; }}
</style></head><body><main>
<div class="kicker">ATLAS ANALYTICS · BALOTAJE BRASIL 2026 · {meta.get("modo", "TSE")}</div>
<h1>Lula proyectado: {f1(est["lula_proyectado"])} % <small style="font-weight:normal;color:var(--muted);font-size:15px">(rango del 90 %: {f1(est["lula_proyectado"] - 1.645 * est["sd_pp"])} a {f1(est["lula_proyectado"] + 1.645 * est["sd_pp"])})</small></h1>
<p class="sub">Hora TSE {meta.get("hora_tse", "—")} · lectura {meta["sello"]} · pronóstico base {meta["pronostico"]} · se recarga cada 60 s</p>
<div class="kpis">
 <div class="kpi"><b>{f1(est["votos_contados_pct"])} %</b><span>de los votos válidos estimados, contados</span></div>
 <div class="kpi"><b>{f1(est["lula_contado"])} %</b><span>Lula en lo contado (engaña: depende de qué se contó)</span></div>
 <div class="kpi"><b>{f1(est["lula_esperado_en_lo_contado"])} %</b><span>lo que el pronóstico esperaba en esos mismos municipios</span></div>
 <div class="kpi"><b>{f1(est["lula_proyectado"])} %</b><span>proyección final (pronóstico {f1(est["lula_pronostico"])} %)</span></div>
 <div class="kpi"><b>{round(est["prob_lula"] * 100)} %</b><span>probabilidad de que gane Lula</span></div>
</div>
<div class="alerta"><b>Lula rinde {f1(abs(d))} pts {"por encima" if d > 0 else "por debajo"} del pronóstico en lo contado</b>
 (a favor de {lado}). Por región: {reg}.</div>
<div class="dos"><section><h2>Lula a lo largo de la noche</h2>{svg_historia(hist, est["lula_pronostico"])}
<p class="nota ley"><i style="background:#B8B0C8"></i>contado <i style="background:var(--vio)"></i>proyectado</p>
<h2>Gobernadores en balotaje</h2><table><tr><th>UF</th><th>Finalistas</th><th>% secc.</th><th>1º contado</th><th>Pronóstico</th><th>P(1º)</th></tr>{filas_g}</table></section>
<section><h2>Por estado</h2><table><tr><th>UF</th><th>% contado</th><th>Lula contado</th><th>Esperado</th><th>Desvío</th><th>Proyección</th><th>Pronóstico</th></tr>{filas}</table>
<p class="nota">Esperado: lo que el pronóstico daba a Lula en los municipios ya contados. Desvío positivo: Lula rinde más de lo previsto.</p></section></div>
</main></body></html>"""


# ---------------------------------------------------------------------------
# Corridas
# ---------------------------------------------------------------------------

def registrar(est: dict, gob: list, meta: dict) -> None:
    out = SALIDA_DIR / meta["sello"]
    out.mkdir(parents=True, exist_ok=True)
    estado = {k: v for k, v in est.items() if k != "por_uf"}
    estado["por_uf"] = est["por_uf"].to_dict(orient="records")
    (out / "estado.json").write_text(json.dumps({**estado, "gobernadores": gob, **meta}, ensure_ascii=False, indent=1,
                                                default=float), encoding="utf-8")
    hist_f = SALIDA_DIR / ("historia_simulada.csv" if meta.get("modo") != "TSE" else "historia.csv")
    fila = pd.DataFrame([{"sello": meta["sello"], **{k: estado[k] for k in
                          ("votos_contados_pct", "lula_contado", "lula_esperado_en_lo_contado", "lula_proyectado",
                           "sd_pp", "prob_lula", "desvio_nacional_pp")}}])
    hist = pd.concat([pd.read_csv(hist_f), fila]) if hist_f.exists() and meta.get("continuar") else fila
    hist.to_csv(hist_f, index=False)
    HTML.parent.mkdir(parents=True, exist_ok=True)
    HTML.write_text(html(est, gob, meta, hist), encoding="utf-8")


def una_lectura(pron: dict, k: float, previo: pd.DataFrame | None, continuar: bool):
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    cont, ext, info = bajar_conteo(previo)
    est = proyectar(pron, cont, ext, k)
    gob = bajar_gobernadores(pron["gob"])
    registrar(est, gob, {"sello": sello, "pronostico": pron["run"], "modo": "TSE", "continuar": continuar, **info})
    log.info("%s · %.1f%% contado · Lula contado %s, proyectado %.2f ± %.2f (P=%.0f%%)", info["hora_tse"],
             est["votos_contados_pct"], f1(est["lula_contado"]), est["lula_proyectado"], 1.645 * est["sd_pp"],
             100 * est["prob_lula"])
    return cont, est


def simular_2022(k: float, pasos: int, seed: int, sesgo_pron: float = 0.0, sesgo_mun: float = 0.04) -> pd.DataFrame:
    """Noche simulada: pronóstico 2022 (desde 2018) contra el resultado real.

    Para que la prueba no sea fácil: el Sudeste y el Sur cuentan antes y el
    Nordeste arranca tarde; lo contado de cada município no es representativo
    (desvío N(0, sesgo_mun) que se achica a medida que se completa); y el
    pronóstico se puede correr `sesgo_pron` en contra de Lula.
    """
    run = ultima(BALOTAJE_DIR)
    b = pd.read_parquet(run / "backtest_municipios.parquet")
    b = b[b["pt_real"] + b["bolsonaro_real"] > 0]
    pron = {"run": f"{run.name} (backtest 2022)", "lula": float(b["pt"].sum() / (b["pt"] + b["bolsonaro"]).sum() * 100),
            "sd": 1.5, "prob": None, "ext_p": 0.5, "ext_val": 0.0, "gob": None,
            "mun": pd.DataFrame({"uf": b["uf"], "validos_pred": b["pt"] + b["bolsonaro"],
                                 "p": (b["pt"] / (b["pt"] + b["bolsonaro"]) - sesgo_pron).clip(0, 1)})}
    pron["lula"] -= sesgo_pron * 100
    real = b["pt_real"].sum() / (b["pt_real"] + b["bolsonaro_real"]).sum() * 100
    rng = np.random.default_rng(seed)
    velocidad = b["uf"].map(REGION).map({"Sudeste": 1.6, "Sul": 1.5, "Centro-Oeste": 1.2, "Norte": 0.8, "Nordeste": 0.7})
    nordeste = (b["uf"].map(REGION) == "Nordeste").to_numpy()
    arranque = pd.Series(np.where(nordeste, rng.uniform(0.15, 0.5, len(b)), rng.uniform(0, 0.35, len(b))), index=b.index)
    eps = pd.Series(rng.normal(0, sesgo_mun, len(b)), index=b.index)
    share_real = b["pt_real"] / (b["pt_real"] + b["bolsonaro_real"])
    filas = []
    for i in range(1, pasos + 1):
        t = i / pasos
        pct = ((t * 1.25 - arranque) * velocidad).clip(0, 1) if i < pasos else pd.Series(1.0, index=b.index)
        v = (b["pt_real"] + b["bolsonaro_real"]) * pct
        sh = (share_real + eps * (1 - pct)).clip(0, 1)
        cont = pd.DataFrame({"lula": (v * sh).round(), "flavio": (v * (1 - sh)).round(), "pct": pct})
        est = proyectar(pron, cont, (0, 0, 0), k)
        filas.append({"paso": i, "votos_contados_pct": est["votos_contados_pct"], "lula_contado": est["lula_contado"],
                      "lula_proyectado": est["lula_proyectado"], "sd_pp": est["sd_pp"], "real": real,
                      "error_contado": (est["lula_contado"] or np.nan) - real, "error_proyectado": est["lula_proyectado"] - real})
        if i in (2, pasos // 2, pasos):
            registrar(est, [], {"sello": f"simulacion-paso-{i:02d}", "pronostico": pron["run"], "modo": "SIMULACIÓN 2022",
                                "hora_tse": f"paso {i} de {pasos}", "continuar": i != 2})
    return pd.DataFrame(filas)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="segundos entre lecturas (0 = una sola)")
    ap.add_argument("--simular-2022", action="store_true")
    ap.add_argument("--pasos", type=int, default=12)
    ap.add_argument("--sesgo-pronostico", type=float, default=0.0, help="pts que se le restan a Lula en el pronóstico simulado")
    args = ap.parse_args(argv)
    k = cargar_config()["tablero"]["k_votos"]
    if args.simular_2022:
        r = simular_2022(k, args.pasos, 2026, sesgo_pron=args.sesgo_pronostico / 100)
        print(r.round(2).to_string(index=False))
        log.info("tablero de prueba: %s", HTML)
        return
    pron = cargar_pronostico()
    previo, primera = None, True
    while True:
        try:
            previo, est = una_lectura(pron, k, previo, continuar=not primera)
            primera = False
            if args.loop == 0 or est["votos_contados_pct"] >= 99.99:
                break
        except Exception as e:
            log.warning("el TSE todavía no publica la 2ª vuelta o falló la lectura: %s", e)
            if args.loop == 0:
                break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
