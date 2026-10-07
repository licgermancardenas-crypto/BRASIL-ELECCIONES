"""
src/viz/brief_balotaje_pdf.py

Brief del balotaje presidencial (25/10/2026) en PDF con la identidad de Atlas
Analytics: mismo formato y piezas que src/viz/brief_pdf.py.

No recalcula el modelo: lee la última corrida de src/models/balotaje_2026.py
(data/processed/electoral/balotaje_2026/) y el resultado final de la 1ª
vuelta por município.

Output: reports/briefs/ATLAS_Brasil_Brief_Balotaje_<fecha>.pdf
        (HTML y figuras de trabajo en reports/briefs/_build_balotaje/, fuera de git)

Uso:
    python -m src.viz.brief_balotaje_pdf [--fecha 2026-10-07]
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.etl.transform.base_locales import salida as salida_locales
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.balotaje_gobernadores_2026 import SALIDA_DIR as GOBERNADORES_DIR
from src.models.conteo_2026 import SALIDA_FINAL as RESULTADO_2026
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.models.movilizacion_2026 import SALIDA_DIR as MOVILIZACION_DIR
import src.viz.carrusel_linkedin as cl
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, to_hex
from src.viz.post_pronostico import cargar_municipios
from src.viz.brief_pdf import (BRIEFS, C_FLAVIO, C_LULA, CHROME, CSS_MARCA, INK, MUTED, PORTADA, RULE, VIO,
                               Documento, f0, f1, fig, fuente, insight, kpi, limpiar, pe, sg, tabla, ultima)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_balotaje"
GRIS, GRIS_CLARO = "#8A8983", "#CFCBD6"
TERC = {"cury": "Cury (Avante)", "renan_santos": "Renan Santos (Missão)", "caiado": "Caiado (PSD)",
        "otros": "Zema (Novo) y otros"}
ORIG = {"pt": ("Votó Lula", C_LULA), "bolsonaro": ("Votó Bolsonaro", C_FLAVIO),
        "blanco_nulo": ("Blanco o nulo", GRIS), "abstencion": ("No votó", GRIS_CLARO)}
ESC = {"caiado_y_zema_con_flavio": "Caiado y Zema con Flávio (80 % de sus votantes)",
       "mas_renan_con_flavio": "… y además Renan Santos con Flávio",
       "cury_con_lula": "Cury con Lula (65 % de sus votantes)",
       "movilizacion_como_2018": "Blanco y abstención vuelven como en 2018",
       "sin_movilizacion": "Solo votos válidos: nadie entra ni sale"}
mill = lambda x: f1(x / 1e6) + " M"

plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none", "axes.edgecolor": "#BBBBBB",
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})


def nombre_mun(s: str) -> str:
    t = s.title()
    for p in (" De ", " Da ", " Do ", " Dos ", " Das "):
        t = t.replace(p, p.lower())
    return t


def guardar(f, nombre: str) -> None:
    f.savefig(BUILD / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(f)


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------

def fig_primera(pv: dict) -> None:
    val = pv["validos"]
    filas = [("Flávio Bolsonaro (PL)", pv["flavio"], C_FLAVIO), ("Lula (PT)", pv["lula"], C_LULA)] + \
            [(TERC[k], v, GRIS) for k, v in sorted(pv["terceros"].items(), key=lambda kv: -kv[1])]
    f, ax = plt.subplots(figsize=(6.6, 3.3))
    for i, (n, v, c) in enumerate(filas):
        ax.barh(i, v / val * 100, color=c, height=0.62, zorder=2)
        ax.text(v / val * 100 + 0.6, i, f"{f1(v / val * 100)} %  ·  {mill(v)}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=9)
    ax.set_ylim(len(filas) - 0.4, -0.6)
    ax.set_xlim(0, 62)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    limpiar(ax, grid="x")
    guardar(f, "primera.svg")


def fig_origen(comp: dict, votos: dict) -> None:
    orden = sorted(comp, key=lambda k: -votos[k])
    f, ax = plt.subplots(figsize=(7.2, 2.9))
    for i, t in enumerate(orden):
        x0 = 0
        for o, (et, c) in ORIG.items():
            w = comp[t][o] * 100
            ax.barh(i, w, left=x0, color=c, height=0.6, edgecolor="white", linewidth=1)
            if w >= 7:
                ax.text(x0 + w / 2, i, f"{w:.0f}", ha="center", va="center", fontsize=8.5,
                        color="white" if o in ("pt", "bolsonaro", "blanco_nulo") else INK, weight="bold")
            x0 += w
    ax.set_yticks(range(len(orden)), [f"{TERC[t]}\n{mill(votos[t])}" for t in orden], fontsize=8.5)
    ax.set_ylim(len(orden) - 0.4, -0.6)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for _, c in ORIG.values()],
              labels=[e for e, _ in ORIG.values()], ncol=4, frameon=False, fontsize=8,
              loc="upper center", bbox_to_anchor=(0.45, -0.12))
    limpiar(ax, grid=None)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    guardar(f, "origen.svg")


def fig_backtest(bt: pd.DataFrame) -> None:
    f, ax = plt.subplots(figsize=(5.4, 4.6))
    ax.plot([15, 80], [15, 80], color=INK, lw=0.8, ls="--", zorder=1)
    for m, c, a, lab in (("A", GRIS_CLARO, 0.9, "A · analogía"), ("R", VIO, 1, "R · origen (principal)")):
        d = bt[bt["metodo"] == m]
        ax.scatter(d["real"], d["predicho"], s=26 if m == "R" else 18, color=c, alpha=a, zorder=3 if m == "R" else 2,
                   label=lab, edgecolors="white", linewidths=0.6)
    for r in bt[(bt["metodo"] == "R") & (bt["error"].abs() > 2.2)].itertuples():
        ax.annotate(r.uf, (r.real, r.predicho), xytext=(4, -3), textcoords="offset points", fontsize=7.5, color=MUTED)
    ax.set_xlabel("Lula real, 2ª vuelta 2022 (%)", fontsize=8.5)
    ax.set_ylabel("Lula predicho desde la 1ª vuelta (%)", fontsize=8.5)
    ax.set_xlim(15, 80)
    ax.set_ylim(15, 80)
    ax.set_aspect("equal")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    limpiar(ax, grid="both")
    guardar(f, "backtest.svg")


def fig_distribucion(sim: np.ndarray, media: float) -> None:
    f, ax = plt.subplots(figsize=(7.0, 3.6))
    bins = np.arange(40, 55.01, 0.25)
    h, b = np.histogram(np.clip(sim, 40, 55), bins=bins)
    centro = (b[:-1] + b[1:]) / 2
    ax.bar(centro, h / len(sim) * 100, width=0.23, color=[C_LULA if c > 50 else C_FLAVIO for c in centro], zorder=2)
    ax.axvline(50, color=INK, lw=1)
    tr = ax.get_xaxis_transform()
    ax.text(50.2, 1.03, "Lula gana →", fontsize=8.5, color=C_LULA, weight="bold", transform=tr)
    ax.text(49.8, 1.03, "← Flávio gana", fontsize=8.5, color=C_FLAVIO, weight="bold", ha="right", transform=tr)
    ax.axvline(media, color=MUTED, lw=1, ls=":")
    ax.text(media - 0.15, ax.get_ylim()[1] * 0.98, f"media {f1(media)} %", ha="right", va="top", fontsize=8.5,
            color=INK, weight="bold")
    ax.set_xlim(41, 54)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.set_ylabel("Simulaciones", fontsize=8.5)
    ax.set_xlabel("Lula en la 2ª vuelta (votos válidos)", fontsize=8.5)
    limpiar(ax)
    guardar(f, "distribucion.svg")


def fig_uf(uf: pd.DataFrame) -> None:
    d = uf.sort_values("lula_pct")
    f, ax = plt.subplots(figsize=(5.6, 7.4))
    y = np.arange(len(d))
    ax.axvline(50, color=INK, lw=0.9)
    for i, r in enumerate(d.itertuples()):
        ax.plot([r.lula_2022, r.lula_pct], [i, i], color=RULE, lw=2, zorder=1)
        ax.scatter(r.lula_2022, i, s=22, facecolors="white", edgecolors=MUTED, linewidths=1, zorder=2)
        ax.scatter(r.lula_pct, i, s=34, color=C_LULA if r.lula_pct > 50 else C_FLAVIO, zorder=3)
    ax.set_yticks(y, d.index, fontsize=8)
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xlim(15, 80)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.scatter([], [], s=22, facecolors="white", edgecolors=MUTED, label="Lula 2ª vuelta 2022 (real)")
    ax.scatter([], [], s=34, color=INK, label="Lula 2026 (pronóstico)")
    ax.legend(frameon=False, fontsize=7.8, loc="lower right")
    limpiar(ax, grid="x")
    guardar(f, "uf.svg")


def fig_sensibilidad(sens: list, quiebre: float, modelo: float, lula_modelo: float) -> None:
    s = pd.DataFrame(sens)
    x = np.linspace(0.25, 0.95, 50)
    a, b = np.polyfit(s["a_lula_terceros"], s["lula_pct"], 1)
    f, ax = plt.subplots(figsize=(6.6, 3.7))
    ax.axhline(50, color=INK, lw=0.9)
    ax.plot(x * 100, a * x + b, color=VIO, lw=2, zorder=2)
    ax.scatter([modelo * 100], [lula_modelo], s=46, color=VIO, zorder=3, edgecolors="white", linewidths=1.2)
    ax.annotate(f"Modelo: {modelo * 100:.0f} % → Lula {f1(lula_modelo)} %", (modelo * 100, lula_modelo),
                xytext=(8, -14), textcoords="offset points", fontsize=8.5, color=INK, weight="bold")
    ax.axvline(quiebre * 100, color=C_LULA, lw=1, ls="--")
    ax.text(quiebre * 100 - 1, 46.0, f"Empate: {quiebre * 100:.0f} %", fontsize=8.5, color=C_LULA, ha="right", weight="bold")
    ax.axvspan(18, 32, color="#EEEEEE", zorder=0)
    ax.text(25, 50.6, "2022:\n~30 %", fontsize=7.5, color=MUTED, ha="center")
    ax.axvspan(58, 68, color="#F7E1E1", zorder=0)
    ax.text(63, 45.6, "2018:\n~63 %", fontsize=7.5, color=MUTED, ha="center")
    ax.set_xlim(15, 95)
    ax.set_ylim(45, 52)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.set_xlabel("Parte de los votantes de terceros que elige a Lula (entre los que votan a alguien)", fontsize=8.5)
    ax.set_ylabel("Lula en la 2ª vuelta", fontsize=8.5)
    limpiar(ax)
    guardar(f, "sensibilidad.svg")


def fig_reserva(M: dict) -> None:
    r, h = M["reserva"], M["lo_que_hace_falta"]
    filas = [("Brecha a cerrar\n(pronóstico de balotaje)", h["brecha_votos"], INK),
             ("Votantes de Lula 2022\nque no votaron el 4/10", r["de_lula_2022"], C_LULA),
             ("Votantes de Bolsonaro 2022\nque no votaron el 4/10", r["de_bolsonaro_2022"], C_FLAVIO),
             ("Reserva neta de Lula", r["neta_lula"], VIO)]
    f, ax = plt.subplots(figsize=(6.6, 3.0))
    for i, (n, v, c) in enumerate(filas):
        ax.barh(i, v / 1e6, color=c, height=0.6, zorder=2)
        ax.text(v / 1e6 + 0.1, i, mill(v), va="center", fontsize=9, color=INK, weight="bold")
    ax.axvline(h["brecha_votos"] / 1e6, color=INK, lw=0.8, ls="--", zorder=1)
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=8.5)
    ax.set_ylim(len(filas) - 0.4, -0.6)
    ax.set_xlim(0, 7.6)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} M")
    limpiar(ax, grid="x")
    guardar(f, "reserva.svg")


def fig_entre_vueltas(M: dict) -> None:
    h = M["entre_vueltas_historia"]
    x = np.arange(5)
    f, ax = plt.subplots(figsize=(6.2, 3.0))
    ax.bar(x - 0.2, h["2018"], width=0.38, color="#C9BEE4", label="2018", zorder=2)
    ax.bar(x + 0.2, h["2022"], width=0.38, color=VIO, label="2022", zorder=2)
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xticks(x, ["Q1\nmás bolsonarista", "Q2", "Q3", "Q4", "Q5\nmás petista"], fontsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.1f}".replace(".", ","))
    ax.set_ylabel("Cambio de la abstención\n1ª → 2ª vuelta (pp)", fontsize=8.5)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    limpiar(ax)
    guardar(f, "entre_vueltas.svg")


def mapas_municipales(mun: pd.DataFrame) -> pd.DataFrame:
    """Dos mapas por município: pronóstico de Lula en la 2ª vuelta y cambio contra la 2ª vuelta real de 2022."""
    cl.BUILD = BUILD / "figs"   # mapa_png escribe en cl.BUILD
    geo = cargar_municipios()
    geo = geo.assign(codigo=geo.codigo.astype(int)).merge(
        mun[["lula_pct"]].reset_index().astype({"codigo": int}), on="codigo", how="left")
    geo["cambio"] = geo["lula_pct"] - geo["lula_2v"]
    cl.mapa_png(geo, cl.colores_voto(geo["lula_pct"]), "mapa_pronostico.png", 1400)
    cmap = LinearSegmentedColormap.from_list("cambio", [C_FLAVIO, "#9DB8D9", "#EFEAF3", "#E8A6A0", C_LULA])
    norm = TwoSlopeNorm(vcenter=0, vmin=-10, vmax=10)
    cl.mapa_png(geo, ["#DDDDDD" if pd.isna(x) else to_hex(cmap(norm(np.clip(x, -10, 10)))) for x in geo["cambio"]],
                "mapa_cambio.png", 1400)
    return geo


def fig_gobernadores(g: pd.DataFrame) -> None:
    d = g.sort_values("prob_A")
    f, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.axvline(50, color=INK, lw=0.9)
    for i, r in enumerate(d.itertuples()):
        ax.plot([r.p5, r.p95], [i, i], color=RULE, lw=5, solid_capstyle="round", zorder=1)
        ax.scatter(r.pct_A_2v, i, s=60, color=VIO, zorder=3, edgecolors="white", linewidths=1)
        ax.text(r.p95 + 1, i, f"{nombre_mun(r.A)} {f1(r.pct_A_2v)} %", va="center", fontsize=8, color=INK)
    ax.set_yticks(range(len(d)), [f"{r.uf}" for r in d.itertuples()], fontsize=9, weight="bold")
    ax.set_ylim(-0.6, len(d) - 0.4)
    ax.set_xlim(30, 100)
    ax.set_xticks([30, 40, 50, 60, 70, 80])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    limpiar(ax, grid="x")
    guardar(f, "gobernadores.svg")


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

CSS_EXTRA = """
.kpis { margin-bottom:.8cm; }
.kpis .kpi-v { font-size:22pt; }
.kpi-l { font-size:9pt; } .kpi-n { font-size:8pt; }
.tesis { gap:.75cm 1cm; }
.t h3 { font-size:11.5pt; } .t p { font-size:9.8pt; line-height:1.42; } .t-n { font-size:19pt; }
.insight { font-size:9.6pt; line-height:1.4; padding:.28cm .36cm; margin:.24cm 0; }
table { font-size:9.2pt; } th { font-size:7.8pt; } td { padding:.15cm .2cm; }
.fuente { font-size:7.6pt; }
.reco { margin-bottom:.6cm; }
.reco h3 { font-size:11pt; }
.reco p { font-size:9.6pt; line-height:1.42; }
.nota-metodo h3 { font-size:10pt; } .nota-metodo p { font-size:9.2pt; line-height:1.45; }
h3.sub { font-size:10.5pt; margin:0 0 .2cm; }
td { white-space:nowrap; }
.fig-primera { max-height:8.2cm; }
.fig-origen { max-height:8.4cm; }
.fig-bt { max-height:12.4cm; }
.fig-dist { max-height:9cm; }
.fig-uf { max-height:15.4cm; }
.fig-sens { max-height:9.6cm; }
.fig-reserva { max-height:7.4cm; }
.fig-ev { max-height:7cm; }
.fig-gob { max-height:9.6cm; }
.mapas { display:flex; gap:.5cm; }
.mapas > div { flex:1; } .mapas img { width:100%; max-height:11.2cm; object-fit:contain; }
.mapas h3 { font-size:10pt; margin:0 0 .15cm; } .grad-ley { display:flex; align-items:center; gap:.2cm; font-size:7.6pt; color:#6B6480; }
.grad-ley i { display:inline-block; width:3.2cm; height:.22cm; }
.td-wrap td { white-space:normal; } .td-wrap td.num { white-space:nowrap; } .td-wrap table { font-size:8.2pt; }
.cuenta { display:flex; gap:.3cm; align-items:stretch; margin:.3cm 0 .1cm; }
.cuenta > div { flex:1; background:#FAF8FD; border-top:3px solid #5B3F99; padding:.22cm .25cm; }
.cuenta b { display:block; font-size:16pt; }
.cuenta span { font-size:8pt; color:#6B6480; }
"""


def construir(fecha: date) -> Path:
    corrida = ultima(BALOTAJE_DIR)
    R = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    bt = pd.read_csv(corrida / "backtest.csv")
    uf = pd.read_csv(corrida / "por_uf.csv", index_col=0)
    sim = np.load(corrida / "lula_nacional_sim.npy")
    loc22 = pd.read_parquet(salida_locales(2022)).query("uf != 'ZZ'").groupby("uf")[["pt_2", "bolsonaro_2"]].sum()
    uf["lula_2022"] = loc22["pt_2"] / (loc22["pt_2"] + loc22["bolsonaro_2"]) * 100
    m26 = pd.read_parquet(RESULTADO_2026)
    M = json.loads((ultima(MOVILIZACION_DIR) / "resumen.json").read_text(encoding="utf-8"))
    gob_dir = ultima(GOBERNADORES_DIR)
    Gb = json.loads((gob_dir / "resumen.json").read_text(encoding="utf-8"))
    Gb_uf = pd.read_csv(gob_dir / "por_uf.csv")
    Gb_bt = pd.read_csv(gob_dir / "backtest.csv")
    t26 = m26.groupby("uf")[["cury", "renan_santos", "caiado", "zema", "otros", "validos"]].sum()

    pv = R["primera_vuelta"]
    val = pv["validos"]
    terc = pv["terceros"]
    n_terc = sum(terc.values())
    brecha = pv["flavio"] - pv["lula"]
    necesita = (val / 2 - pv["lula"]) / n_terc
    mc = R["montecarlo"]
    a_r, a_a = R["a_lula_terceros"]["R"], R["a_lula_terceros"]["A"]
    a_pond = sum(a_r[k] * terc[k] for k in terc) / n_terc
    comp = R["composicion_terceros_por_origen_2022"]
    btR, btA = R["backtest_2022"]["R"], R["backtest_2022"]["A"]
    esc = R["escenarios_apoyos"]
    s = pd.DataFrame(R["sensibilidad"])
    pend, ord0 = np.polyfit(s["a_lula_terceros"], s["lula_pct"], 1)
    quiebre = (50 - ord0) / pend
    lula = mc["lula_media"]
    q5, q25, q50, q75, q95 = mc["lula_p5_25_50_75_95"]
    gana_lula = uf[uf["lula_pct"] > 50].index.tolist()
    reñidos = uf[(uf["lula_pct"] > 45) & (uf["lula_pct"] < 55)].sort_values("lula_pct")
    voltea = uf[(uf["lula_2022"] > 50) & (uf["lula_pct"] < 50)].sort_values("lula_2022", ascending=False)
    ret = R["retencion_2022"]
    caiado_go = t26.loc["GO", "caiado"] / t26.loc["GO", "validos"] * 100

    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "figs").mkdir(parents=True)
    fig_primera(pv)
    fig_origen(comp, terc)
    fig_backtest(bt)
    fig_distribucion(sim, lula)
    fig_uf(uf)
    fig_sensibilidad(R["sensibilidad"], quiebre, a_pond, lula)
    fig_reserva(M)
    fig_entre_vueltas(M)
    fig_gobernadores(Gb_uf)
    mun_pred = pd.read_parquet(corrida / "municipios.parquet")
    geo = mapas_municipales(mun_pred)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")

    marca = "Atlas Analytics · Brasil 2026"
    D = Documento(marca)
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"

    # ================================================================ portada
    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil rumbo al 25 de octubre</h1>
    <div class="p-sub">Brief del balotaje presidencial. A dónde van los 9 millones de votos de los terceros,
      cuánto le falta a Lula y qué tendría que pasar para que el resultado se dé vuelta.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Datos</span> resultado oficial del TSE de la 1ª vuelta, 5.571 municípios, 100 % de las secciones</div>
      <div><span>Historia</span> 1ª y 2ª vuelta 2018 y 2022 por local de votación, para estimar y probar el método</div>
      <div><span>Modelo</span> {f0(mc['n'])} simulaciones · {fecha:%d/%m/%Y} · sin encuestas</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    # ================================================================ resumen
    tesis = [
        ("Flávio es claro favorito",
         f"Con el resultado de la 1ª vuelta, Lula llegaría a {f1(lula)} % de los válidos. Gana en "
         f"{pe(mc['prob_lula'])} de las simulaciones; Flávio en {pe(mc['prob_flavio'])}."),
        ("La cuenta es cuesta arriba para Lula",
         f"Flávio sacó {mill(brecha)} de votos más. Los terceros suman {mill(n_terc)}: aun si todos volvieran a votar, "
         f"Lula necesitaría {pe(necesita)} de ellos. En 2022 los terceros fueron en su mayoría a Bolsonaro."),
        ("Los terceros llegaron más desde la derecha que desde Lula",
         f"Cerca de un tercio de los votantes de Cury, Renan Santos y Caiado había votado a Lula en 2022. "
         f"Por eso el modelo le da a Lula {pe(a_pond)} de ellos, lejos de lo que necesita."),
        ("El método aprobó su prueba",
         f"Aplicado un ciclo atrás, predijo la 2ª vuelta de 2022 con {f1(abs(btR['error_nacional_pp']))} puntos de error "
         f"nacional. El método por analogía, el que usa el sentido común, erró por {f1(btA['error_nacional_pp'])}."),
        ("Los apoyos apuntan al mismo lado",
         f"Caiado y Zema ya están con Flávio y Renan Santos lo da como ganador. Con esos apoyos, Lula bajaría a "
         f"{f1(esc['mas_renan_con_flavio']['lula_pct'])} %. El mejor escenario para Lula no pasa de "
         f"{f1(max(v['lula_pct'] for v in esc.values()))} %."),
        ("Tampoco alcanza con movilizar",
         f"{mill(M['reserva']['de_lula_2022'])} de votantes de Lula de 2022 no votaron el 4/10, menos que la brecha de "
         f"{mill(M['lo_que_hace_falta']['brecha_votos'])}, y del otro lado hay {mill(M['reserva']['de_bolsonaro_2022'])} de "
         "votantes de Bolsonaro en la misma situación. En 2018 y 2022 la 2ª vuelta movilizó más a las zonas bolsonaristas."),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(pe(mc["prob_flavio"]), "Flávio presidente", f"Lula {pe(mc['prob_lula'])}")
              + kpi(f"{f1(lula)} %", "Lula en la 2ª vuelta", f"rango 90 %: {f1(q5)} – {f1(q95)}")
              + kpi(mill(brecha), "ventaja de Flávio", "en la 1ª vuelta")
              + kpi(mill(n_terc), "votos de terceros", "Cury, Renan Santos, Caiado, Zema")
              + kpi(pe(necesita), "de ellos necesita Lula", f"el modelo le da {pe(a_pond)}")
              + kpi(sg(btR["error_nacional_pp"]) + " pts", "error en el backtest", "2ª vuelta 2022")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(tesis))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="Flávio llega al balotaje con una ventaja que los terceros no alcanzan a dar vuelta",
             bajada="Los seis hallazgos del brief. Cada uno se desarrolla en las páginas siguientes.",
             pie="Cifras en votos válidos (sin blancos ni nulos), como las publica el TSE.")

    # ================================================================ 1 · punto de partida
    filas = [["Flávio Bolsonaro", mill(pv["flavio"]), f1(pv["flavio"] / val * 100) + " %"],
             ["Lula", mill(pv["lula"]), f1(pv["lula"] / val * 100) + " %"],
             ["<b>Diferencia</b>", f"<b>{mill(brecha)}</b>", f"<b>{f1(brecha / val * 100)} pts</b>"],
             ["Terceros (en juego)", mill(n_terc), f1(n_terc / val * 100) + " %"],
             ["Blanco y nulo", mill(pv["blanco_nulo"]), "—"],
             ["No votaron", mill(pv["abstencion"]), "—"]]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("primera.svg", "fig fig-primera")
              + fuente("Resultado oficial del TSE al 100 % de las secciones, incluido el exterior. Porcentaje sobre votos válidos.")
              + '<div class="cuenta">'
              + f'<div><b>{mill(val / 2 - pv["lula"])}</b><span>votos que le faltan a Lula para el 50 %, si votan los mismos</span></div>'
              + f'<div><b>{mill(val / 2 - pv["flavio"])}</b><span>votos que le faltan a Flávio</span></div>'
              + f'<div><b>{pe(necesita)}</b><span>de los terceros que Lula necesita llevarse</span></div>'
              + "</div></div><div>"
              + tabla(["", "Votos", "% válidos"], filas, num=(1, 2))
              + insight(f"<b>Flávio está a {f1((val / 2 - pv['flavio']) / val * 100)} puntos del 50 %.</b> Le alcanza con "
                        f"{pe(1 - necesita)} de los votos de terceros, o con que una parte se quede en casa.")
              + insight(f"<b>Los terceros no son un bloque.</b> Cury compitió por el espacio del gobierno, Caiado desde la "
                        f"centroderecha (sacó {f1(caiado_go)} % en Goiás) y Renan Santos y Zema desde la derecha antipetista.")
              + insight(f"<b>La otra reserva son los que no votaron:</b> {mill(pv['abstencion'])} de electores, más "
                        f"{mill(pv['blanco_nulo'])} de blancos y nulos. Una diferencia chica en quién vuelve a votar mueve "
                        "más que cualquier apoyo.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="1 · EL PUNTO DE PARTIDA", titulo=f"Flávio ganó la 1ª vuelta por {mill(brecha)} de votos",
             bajada="Resultado del 4 de octubre y la cuenta que tiene que hacer cada candidato para llegar al 50 %.",
             pie="TSE, divulgación oficial por município y por UF (elección 6257).")

    # ================================================================ 2 · de dónde vienen los terceros
    filas = [[TERC[k], mill(terc[k]), pe(a_r[k]), pe(a_a[k])] for k in sorted(terc, key=lambda k: -terc[k])]
    filas.append(["<b>Total ponderado</b>", f"<b>{mill(n_terc)}</b>", f"<b>{pe(a_pond)}</b>",
                  f"<b>{pe(sum(a_a[k] * terc[k] for k in terc) / n_terc)}</b>"])
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("origen.svg", "fig fig-origen")
              + fuente("Qué votó en la 2ª vuelta de 2022 cada electorado de tercero de 2026. Regresión ecológica con "
                       "restricciones entre municípios, por UF (las UF con menos de 80 municípios usan la de su región).")
              + insight("<b>Cómo se lee:</b> de cada 100 votantes de Cury, 34 habían votado a Lula en 2022 y 44 a Bolsonaro; "
                        "el resto había votado en blanco o no había ido. Lo mismo para cada candidato.")
              + "</div><div>"
              + '<h3 class="sub">Parte que iría a Lula (entre los que votan a alguien)</h3>'
              + tabla(["Tercero", "Votos", "Por origen", "Por analogía"], filas, num=(1, 2, 3))
              + fuente("Por origen: cada votante vuelve al lado que eligió en 2022. Por analogía: reparte como su análogo de "
                       "2022 (Cury como Ciro, Caiado como Tebet, el resto como los demás candidatos de 2022).")
              + insight(f"<b>Caiado es el que más se acerca a una mitad y mitad</b> ({pe(a_r['caiado'])} a Lula): su electorado "
                        "venía en partes iguales de los dos lados. Pero ya anunció su apoyo a Flávio, y eso no está en el "
                        "pronóstico base.")
              + insight(f"<b>Ninguno llega al {pe(necesita)} que necesita Lula.</b> El más favorable es Caiado, y aun Cury, "
                        f"el más cercano al gobierno, queda en {pe(a_r['cury'])}.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="2 · A DÓNDE VAN LOS TERCEROS",
             titulo="Los votantes de los terceros venían más del bolsonarismo que de Lula",
             bajada="Origen 2022 de cada electorado de tercero y la parte que iría a Lula en la 2ª vuelta.",
             pie="Inferencia ecológica: describe territorios, no personas. Los electorados chicos (Zema y otros) son los más inciertos.")

    # ================================================================ 3 · backtest
    filas = [["A · analogía", f1(btA["lula_predicho"]) + " %", f1(btA["lula_real"]) + " %", sg(btA["error_nacional_pp"]),
              f1(btA["mae_uf_pp"])],
             ["<b>R · origen</b>", f"<b>{f1(btR['lula_predicho'])} %</b>", f1(btR["lula_real"]) + " %",
              f"<b>{sg(btR['error_nacional_pp'])}</b>", f"<b>{f1(btR['mae_uf_pp'])}</b>"]]
    bta = R["backtest_2022"]["a_lula_terceros"]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("backtest.svg", "fig fig-bt")
              + fuente("Cada punto es una UF. Sobre la diagonal, el método acierta. Se estimó con la 2ª vuelta de 2018 y la "
                       "1ª de 2022, sin mirar el resultado que había que predecir.")
              + "</div><div>"
              + tabla(["Método", "Lula predicho", "Real", "Error nacional", "Error medio por UF"], filas, num=(1, 2, 3, 4))
              + insight(f"<b>Usar el voto anterior funciona; usar el parecido entre candidatos, no.</b> En 2018 los votantes "
                        f"de Ciro fueron casi todos a Haddad, y la analogía le dio a Lula {pe(bta['A']['ciro'])} de los de "
                        f"Ciro en 2022. Por su origen, el modelo dijo {pe(bta['R']['ciro'])}, y acertó más.")
              + insight(f"<b>Por eso el pronóstico usa el método por origen.</b> Erró {f1(abs(btR['error_nacional_pp']))} "
                        f"puntos a nivel nacional y {f1(btR['mae_uf_pp'])} en promedio por estado.")
              + insight("<b>Es una sola prueba.</b> Un error nacional tan chico puede tener algo de suerte. Por eso la "
                        "incertidumbre del pronóstico es bastante más amplia que ese error.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="3 · CÓMO SABEMOS QUE FUNCIONA",
             titulo=f"El método predijo la 2ª vuelta de 2022 con {f1(abs(btR['error_nacional_pp']))} puntos de error",
             bajada="Prueba hacia atrás: con la 2ª vuelta de 2018 y la 1ª de 2022, ¿qué habría dicho el modelo del balotaje de 2022?",
             pie="TSE, resultados por local de votación 2018 y 2022, agregados a município.")

    # ================================================================ 4 · pronóstico
    filas = [["Lula en la 2ª vuelta (media)", f1(lula) + " %"],
             ["Rango del 50 % central", f"{f1(q25)} – {f1(q75)} %"],
             ["Rango del 90 %", f"{f1(q5)} – {f1(q95)} %"],
             ["<b>Flávio presidente</b>", f"<b>{pe(mc['prob_flavio'])}</b>"],
             ["Lula presidente", pe(mc["prob_lula"])]]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("distribucion.svg", "fig fig-dist")
              + fuente(f"{f0(mc['n'])} simulaciones. Rojo: Lula supera el 50 %. Azul: gana Flávio.")
              + "</div><div>"
              + tabla(["Pronóstico", "Valor"], filas, num=(1,))
              + insight(f"<b>Lula pierde en 24 de cada 25 simulaciones.</b> Para ganar necesita que todo salga mal para "
                        "el modelo a la vez y en su favor.")
              + insight(f"<b>Ni Lula ni Flávio retienen todo.</b> En 2022, cerca de {pe(1 - ret['pt']['pt'])} de los "
                        "votantes de Lula de la 1ª vuelta no volvieron a votarlo, contra menos del 1 % de los de Bolsonaro, y "
                        "los que habían votado en blanco o no habían ido volvieron más hacia Bolsonaro. El modelo supone que "
                        "eso se repite.")
              + insight(f"<b>La incertidumbre es deliberadamente amplia:</b> ±{f1(mc['sd_nacional_pp'])} puntos de desvío "
                        "nacional, con colas gruesas, por lo que no se ve en una sola elección de prueba: campaña, debates, "
                        "quién vuelve a votar.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="4 · EL PRONÓSTICO", titulo=f"Lula llegaría a {f1(lula)} %: Flávio gana en {pe(mc['prob_flavio'])} de los casos",
             bajada="Distribución del voto de Lula en la 2ª vuelta, en votos válidos, según el resultado de la 1ª.",
             pie="Shock nacional t de Student (4 gl) y shock por UF calibrado con el error por estado del backtest.")

    # ================================================================ 5 · estados
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("uf.svg", "fig fig-uf") + "</div><div>"
              + insight(f"<b>Lula gana en {len(gana_lula)} estados</b>: {', '.join(gana_lula)}. Es el Nordeste completo y nada "
                        "más: en 2022 había ganado además en el Norte y en Minas Gerais.")
              + insight("<b>Los estados en juego:</b> "
                        + ", ".join(f"{u} ({f1(r.lula_pct)} %)" for u, r in reñidos.iterrows())
                        + ". Ninguno define la elección por sí solo: la diferencia está repartida en todo el país.")
              + (insight("<b>Los que Lula ganó en 2022 y ahora perdería:</b> "
                         + ", ".join(f"{u} ({f1(r.lula_2022)} → {f1(r.lula_pct)} %)" for u, r in voltea.iterrows())
                         + ". Minas Gerais repite su papel: el que gana ahí gana Brasil.") if len(voltea) else "")
              + insight(f"<b>São Paulo pesa más que cualquier swing.</b> Con Lula en {f1(uf.loc['SP', 'lula_pct'])} %, Flávio "
                        f"saca allí una ventaja de {mill(uf.loc['SP', 'bolsonaro'] - uf.loc['SP', 'pt'])} de votos: "
                        f"{pe((uf.loc['SP', 'bolsonaro'] - uf.loc['SP', 'pt']) / (uf['bolsonaro'].sum() - uf['pt'].sum()))} "
                        "de su diferencia nacional.")
              + fuente("Puntos: pronóstico 2026 (rojo si gana Lula, azul si gana Flávio). Círculo vacío: resultado real de Lula "
                       "en la 2ª vuelta de 2022.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="5 · ESTADO POR ESTADO", titulo="El mapa de 2022 se corre hacia Flávio en casi todas partes",
             bajada="Voto de Lula en la 2ª vuelta por UF: pronóstico 2026 contra el resultado real de 2022.",
             pie="El exterior suma al total nacional pero no se muestra.")

    # ================================================================ 5b · el mapa
    g_ok = geo.dropna(subset=["lula_pct", "lula_2v"])
    n26, n22 = int((g_ok["lula_pct"] > 50).sum()), int((g_ok["lula_2v"] > 50).sum())
    baja = (g_ok["cambio"] < 0).mean()
    vol = g_ok[(g_ok["lula_2v"] > 50) & (g_ok["lula_pct"] < 50)]
    por_uf_vol = vol.groupby("uf").size().sort_values(ascending=False).head(4)
    camb_uf = g_ok.groupby("uf")["cambio"].median().sort_values()
    cuerpo = ('<div class="mapas"><div><h3>Lula en la 2ª vuelta, pronóstico 2026</h3>'
              '<img src="figs/mapa_pronostico.png">'
              f'<div class="grad-ley">Flávio<i style="background:linear-gradient(90deg,{cl.FLAVIO},#EDE6DA,{cl.LULA})"></i>Lula'
              '<span>(25 % a 75 %)</span></div></div>'
              '<div><h3>Cambio contra la 2ª vuelta real de 2022</h3><img src="figs/mapa_cambio.png">'
              f'<div class="grad-ley">Hacia Flávio<i style="background:linear-gradient(90deg,{C_FLAVIO},#EFEAF3,{C_LULA})"></i>'
              'Hacia Lula<span>(−10 a +10 pts)</span></div></div>'
              '<div style="flex:.85">'
              + insight(f"<b>Lula ganaría en {f0(n26)} municipios, contra {f0(n22)} en 2022.</b> Los "
                        f"{f0(len(vol))} que cambian de lado están sobre todo en "
                        + ", ".join(f"{u} ({n})" for u, n in por_uf_vol.items()) + ".")
              + insight(f"<b>El corrimiento es general:</b> Lula baja en {pe(baja)} de los municipios. Las bajas más grandes "
                        "están en " + ", ".join(f"{u} ({f1(v)} pts)" for u, v in camb_uf.head(3).items()) + ", en mediana por municipio.")
              + insight("<b>Es la base del tablero del 25/10:</b> cada municipio que el TSE vaya contando se compara con su "
                        "pronóstico, y la diferencia se proyecta sobre lo que falta contar.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="5 · MUNICIPIO POR MUNICIPIO", titulo=f"Lula ganaría en {f0(n26)} municipios, {f0(n22 - n26)} menos que en 2022",
             bajada="Pronóstico de la 2ª vuelta por municipio y cambio contra el resultado real de 2022.",
             pie="Método por origen aplicado a cada municipio; suma lo mismo que el pronóstico por estado. Error medio por municipio "
                 "en la prueba contra 2022: 1,1 pts.")

    # ================================================================ 6 · escenarios
    filas = [[ESC[k], f1(v["lula_pct"]) + " %", sg(v["lula_pct"] - lula)] for k, v in esc.items()]
    filas.insert(0, ["<b>Pronóstico base</b>", f"<b>{f1(lula)} %</b>", "—"])
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("sensibilidad.svg", "fig fig-sens")
              + fuente("Línea: voto de Lula si todos los terceros fueran a él en la proporción del eje, con la retención y "
                       "movilización de 2022. Bandas: lo que hicieron los terceros en 2022 (a Bolsonaro) y en 2018 (a Haddad), "
                       "según el resultado.")
              + "</div><div>"
              + tabla(["Escenario", "Lula", "Cambio"], filas, num=(1, 2))
              + insight(f"<b>Lula necesita que {quiebre * 100:.0f} % de los terceros lo elijan.</b> Es más que el 63 % de la "
                        "cuenta simple, porque en 2022 la 2ª vuelta movilizó más a Bolsonaro que al PT. Ni en 2018, cuando "
                        "Ciro venía de la izquierda, el PT se llevó tanto.")
              + insight("<b>El escenario que más ayuda a Lula no es un apoyo, es la participación.</b> Si se vota como el 4/10, "
                        f"sin altas ni bajas, Lula llega a {f1(esc['sin_movilizacion']['lula_pct'])} %. Su campaña tiene que "
                        "recuperar a sus votantes de 2022 que no fueron el 4/10, pero esa reserva tampoco alcanza (página siguiente).")
              + "</div></div>")
    D.pagina(cuerpo, kicker="6 · ESCENARIOS", titulo="Ningún escenario razonable lleva a Lula al 50 %",
             bajada="Qué pasa con los apoyos anunciados después del 4/10 y con distintos supuestos de participación.",
             pie="Los porcentajes de los escenarios de apoyo son supuestos para leer su efecto, no estimaciones.")

    # ================================================================ 7 · movilización: cuánto hay
    res, falta, part = M["reserva"], M["lo_que_hace_falta"], M["participacion"]
    qq = part["por_quintil_lula_2022"]
    filas = [[r, mill(v["pt_abst"]), mill(v["bolsonaro_abst"]),
              ("+" if v["reserva_neta"] >= 0 else "−") + mill(abs(v["reserva_neta"]))]
             for r, v in sorted(res["por_region"].items(), key=lambda kv: -kv[1]["reserva_neta"])]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("reserva.svg", "fig fig-reserva")
              + fuente("Votantes de la 2ª vuelta de 2022 que no votaron el 4/10, según la misma regresión ecológica del "
                       "pronóstico (2ª vuelta 2022 → 1ª vuelta 2026, por UF), ajustada a la abstención observada en cada município.")
              + '<h3 class="sub" style="margin-top:.4cm">Dónde está la reserva</h3>'
              + tabla(["Región", "De Lula 2022", "De Bolsonaro 2022", "Neta para Lula"], filas, num=(1, 2, 3))
              + "</div><div>"
              + insight(f"<b>Aunque volvieran todos, no alcanza.</b> {mill(res['de_lula_2022'])} de votantes de Lula de 2022 no "
                        f"fueron a votar el 4/10. La brecha a cerrar es de {mill(falta['brecha_votos'])}: Lula necesitaría "
                        f"{pe(falta['fraccion_reserva_lula_para_empatar'])} de esa reserva, y sin que vuelva ningún votante de Flávio.")
              + insight(f"<b>Del otro lado también hay reserva:</b> {mill(res['de_bolsonaro_2022'])} de votantes de Bolsonaro "
                        f"de 2022 tampoco votaron. La ventaja neta de Lula entre los que se quedaron en casa es de {mill(res['neta_lula'])}.")
              + insight(f"<b>Su base ya votó.</b> En el 20 % de municípios más petistas, la abstención bajó de "
                        f"{f1(qq[4]['abst_1v_2022'])} % en 2022 a {f1(qq[4]['abst_1v_2026'])} % el 4/10. Lula perdió votos "
                        f"sobre todo en el Sudeste ({mill(abs(part['por_region']['Sudeste']['lula_cambio']))}) y el Sur "
                        f"({mill(abs(part['por_region']['Sul']['lula_cambio']))}), donde la abstención subió.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="7 · MOVILIZACIÓN", titulo="La reserva de Lula existe, pero es más chica que la brecha",
             bajada="Votantes de 2022 que no fueron a votar el 4 de octubre, según de qué lado venían.",
             pie="Inferencia ecológica: describe territorios, no personas.")

    # ================================================================ 8 · movilización: lo que dice la historia
    top = M["top_municipios_reserva_neta"][:12]
    filas = [[nombre_mun(t["nombre"]), t["uf"], f0(t["pt_abst"] / 1e3) + " mil", f0(t["bolsonaro_abst"] / 1e3) + " mil",
              f0(t["reserva_neta"] / 1e3) + " mil"] for t in top]
    hist = M["entre_vueltas_historia"]
    cuerpo = ('<div class="dos-col"><div>' + fig("entre_vueltas.svg", "fig fig-ev")
              + fuente("Municípios agrupados en quintiles por el voto al PT en la 2ª vuelta. Positivo: más abstención en la 2ª "
                       "vuelta que en la 1ª.")
              + insight("<b>En las dos últimas elecciones, la 2ª vuelta movilizó relativamente más a las zonas bolsonaristas.</b> "
                        f"En 2018 la abstención subió {f1(hist['2018'][4])} pp en el quintil más petista contra "
                        f"{f1(hist['2018'][0])} en el más bolsonarista; en 2022 bajó {f1(abs(hist['2022'][0]))} pp en el más "
                        "bolsonarista y subió en el más petista.")
              + insight(f"<b>Para empatar haría falta una baja de {f1(falta['pp_menos_abstencion_para_empatar'])} pp de la "
                        f"abstención</b> en los {f0(falta['municipios_lula_gana_2022'])} municípios donde ganó Lula en 2022. "
                        f"El mayor movimiento entre vueltas de los dos últimos ciclos fue de "
                        f"{f1(falta['mayor_baja_historica_entre_vueltas_pp'])} pp.")
              + "</div><div>"
              + '<h3 class="sub">Los 12 municípios con más reserva neta</h3>'
              + tabla(["Município", "UF", "De Lula 2022", "De Bolsonaro 2022", "Neta"], filas, num=(2, 3, 4))
              + insight(f"<b>La reserva es metropolitana.</b> São Paulo capital concentra {f0(top[0]['reserva_neta'] / 1e3)} mil "
                        "votos netos; le siguen Rio, Fortaleza y el ABC paulista.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="8 · MOVILIZACIÓN",
             titulo="La historia juega en contra: la 2ª vuelta suele favorecer la participación bolsonarista",
             bajada="Cambio de la abstención entre vueltas en 2018 y 2022, y dónde están los votantes que Lula podría recuperar.",
             pie="TSE por local de votación 2018 y 2022 y por município 2026. Estimaciones municipales: orden de magnitud, no conteo.")

    # ================================================================ 9 · gobernadores
    gu = Gb_uf.sort_values("prob_A", ascending=False)
    bt_g = Gb["backtest_2018_2022"]
    mg_ = bt_g["metodos"]

    def senal(r):
        d = r.pct_A_origen - r.pct_A_ingenuo
        if abs(d) < 2:
            return "neutra"
        return "al 1º" if d > 0 else "al 2º"

    filas = [[r.uf, f"{nombre_mun(r.A)} ({r.partido_A})", f1(r.pct_A_1v) + " %", f"{nombre_mun(r.B)} ({r.partido_B})",
              f1(r.pct_B_1v) + " %", f"<b>{f1(r.pct_A_2v)} %</b>", f"<b>{pe(r.prob_A)}</b>", senal(r)]
             for r in gu.itertuples()]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("gobernadores.svg", "fig fig-gob")
              + fuente("Punto: % del primero en la 1ª vuelta sobre los votos de los dos finalistas en la 2ª. Barra: rango del 90 % "
                       "de las simulaciones, con el error medido en los balotajes de 2018 y 2022.")
              + "</div><div>"
              + f'<div class="td-wrap">{tabla(["UF", "Primero", "1ª v.", "Segundo", "1ª v.", "2ª v.", "Gana", "Señal"], filas, num=(2, 4, 5, 6))}</div>'
              + fuente("Señal: hacia qué finalista empuja el voto de los candidatos que quedaron afuera, según cómo votaron "
                       "para presidente (regresión ecológica por município y zona). Es una señal, no entra en el número.")
              + insight("<b>Cuatro favoritos:</b> Omar Aziz en AM y Mailza en AC superan el 60 % de los votos de los "
                        "finalistas, y en 2018 y 2022 ningún líder por encima de esa marca perdió. Celina Leão en el DF y "
                        "Pazolini en ES quedan apenas debajo, en la franja donde los líderes ganaron 4 de 6 balotajes.")
              + insight(f"<b>RJ, abierto con ventaja de Ruas:</b> {f1(gu.set_index('uf').loc['RJ', 'pct_A_2v'])} %. Los votantes "
                        "de los eliminados empujan levemente hacia Paes.")
              + insight("<b>RN y TO, empates.</b> En RN el número oculta lo más importante: los votantes de Álvaro Dias (PL, "
                        "26,7 %) habían votado a Flávio y, por esa vía, irían a Allyson y no al candidato del PT.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="9 · GOBERNADORES", titulo="Siete estados eligen gobernador en 2ª vuelta: cuatro con favorito y tres abiertos",
             bajada="Proyección de cada balotaje estadual del 25 de octubre desde el resultado de la 1ª vuelta.",
             pie="TSE, divulgación oficial del 4/10 por UF y por zona electoral. Sin encuestas.")

    # ================================================================ 10 · gobernadores: método
    filas_m = [["Ingenuo: cada finalista conserva su proporción", f1(mg_["ingenuo"]["rmse_pp"]), f"{mg_['ingenuo']['ganador_ok']} de {bt_g['n']}"],
               ["Promedio de los dos", f1(mg_["promedio"]["rmse_pp"]), f"{mg_['promedio']['ganador_ok']} de {bt_g['n']}"],
               ["Origen: los eliminados según su voto presidencial", f1(mg_["origen"]["rmse_pp"]), f"{mg_['origen']['ganador_ok']} de {bt_g['n']}"]]
    rem = Gb_bt[Gb_bt["remontada"]]
    filas_r = [[str(r.ano), r.uf, f1(100 - r.pct_A_1v_entre_finalistas) + " %", f1(r.real) + " %"] for r in rem.itertuples()]
    cuerpo = ('<div class="dos-col"><div>'
              + '<h3 class="sub">Prueba con los 26 balotajes de gobernador de 2018 y 2022</h3>'
              + tabla(["Método", "Error (pp)", "Ganador correcto"], filas_m, num=(1, 2))
              + fuente("Error cuadrático medio del % del ganador, en puntos. Mismas unidades que en 2026 (município × zona).")
              + insight("<b>El método más simple es el que mejor funcionó.</b> Repartir a los eliminados según su voto presidencial "
                        "falló en 2018, cuando Zema, Witzel y Moisés crecieron entre vueltas por fuera de esa lógica. Por eso el "
                        "pronóstico usa el ingenuo y la señal de los eliminados queda como contexto.")
              + insight(f"<b>La incertidumbre es grande:</b> ±{f1(mg_['ingenuo']['rmse_pp'])} puntos. Una elección de gobernador se "
                        "mueve mucho más que la presidencial en tres semanas: alianzas, apoyos de los eliminados y el arrastre "
                        "del candidato a presidente.")
              + "</div><div>"
              + f'<h3 class="sub">Remontadas: ganó el segundo de la 1ª vuelta ({len(rem)} de {bt_g["n"]})</h3>'
              + tabla(["Año", "UF", "Líder en 1ª v.", "Ganador en 2ª v."], filas_r, num=(2, 3))
              + fuente("Líder en 1ª v.: % del primero sobre los dos finalistas. Ganador: % del que remontó.")
              + insight("<b>Todas las remontadas partieron de líderes por debajo del 60 %.</b> En 2026 están en esa zona "
                        "cinco de los siete: DF y ES apenas debajo, y RJ, RN y TO por debajo del 55 %, donde en 2018 y 2022 "
                        "los líderes ganaron 8 de 12.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="10 · GOBERNADORES", titulo="Uno de cada cuatro balotajes de gobernador se dio vuelta en 2018 y 2022",
             bajada="Cómo se proyectan los balotajes estaduales y cuánto se equivocaron los métodos en las dos elecciones anteriores.",
             pie="TSE, resultados por sección 2018 y 2022 agregados a município × zona.")

    # ================================================================ qué mirar
    acciones = [
        ("El voto de Cury",
         f"Es el tercero más grande ({mill(terc['cury'])}) y el único neutral que no se inclina por Flávio. Si se acerca a Lula, "
         f"vale cerca de {f1(esc['cury_con_lula']['lula_pct'] - lula)} puntos."),
        ("La participación en São Paulo y en las capitales del Nordeste",
         f"Ahí está la reserva neta de Lula: {mill(M['por_uf']['SP']['reserva_neta'])} en SP, y Fortaleza, São Luís y "
         "Salvador. Si la abstención baja ahí el 25/10 y sube en el Sur y el Centro-Oeste, el pronóstico se queda corto."),
        ("La participación en el Sur",
         f"Es donde más subió la abstención entre 2022 y 2026 (de {f1(M['participacion']['por_region']['Sul']['abst_1v_2022'])} "
         f"a {f1(M['participacion']['por_region']['Sul']['abst_1v_2026'])} %) y donde Flávio saca sus márgenes más amplios. "
         "Si ese electorado vuelve a votar como en la 2ª vuelta de 2022, la diferencia se amplía."),
        ("Minas Gerais y Pará",
         f"MG ({f1(uf.loc['MG', 'lula_pct'])} %) y PA ({f1(uf.loc['PA', 'lula_pct'])} %) son los estados grandes más parejos. "
         "Si Lula los gana con holgura, el pronóstico se está equivocando a su favor."),
    ]
    cuerpo = ('<div class="dos-col"><div>'
              + "".join(f'<div class="reco"><div class="r-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(acciones))
              + '</div><div class="nota-metodo">'
              '<h3>De dónde sale cada cosa</h3>'
              '<p><b>El resultado.</b> Divulgación oficial del TSE del 4/10 al 100 % de las secciones, por município, con padrón, '
              'abstención, blancos y nulos.</p>'
              '<p><b>Las transferencias.</b> Regresión ecológica con restricciones: compara en qué municípios creció cada tercero '
              'con cómo había votado cada município en la 2ª vuelta de 2022. Da proporciones por grupo, no por persona.</p>'
              '<p><b>Lo que pasa con el resto.</b> Cuántos votantes de Lula y de Flávio vuelven, y cuántos de los que votaron en '
              'blanco o no fueron votan en la 2ª, sale de la matriz 1ª → 2ª vuelta de 2022 por estado, estimada sobre 92.000 '
              'locales de votación.</p>'
              '<h3>Cómo leer los números</h3>'
              '<p>Las cifras están en votos válidos. Los rangos no son un margen de error de encuesta: combinan el error del '
              'método en 2022, la diferencia entre los dos métodos y un margen por lo que la prueba no ve.</p>'
              '<h3>Alcance</h3>'
              '<p>No usa encuestas, por decisión de método: solo resultados oficiales. Los apoyos de Caiado y Zema a Flávio están en los escenarios, '
              'no en el pronóstico base.</p></div></div>')
    D.pagina(cuerpo, kicker="QUÉ MIRAR HASTA EL 25 DE OCTUBRE", titulo="Cuatro señales para leer el 25 de octubre",
             pie=f"Atlas Analytics · {fecha_txt} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil rumbo al 25 de octubre</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "brief.html").write_text(html, encoding="utf-8")

    chrome = next((c for c in CHROME if Path(c).exists()), None)
    if chrome is None:
        raise FileNotFoundError("No se encontró Chrome/Edge para imprimir el PDF")
    pdf = BRIEFS / f"ATLAS_Brasil_Brief_Balotaje_{fecha:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "brief.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas) · corrida %s", pdf.relative_to(ROOT).as_posix(), len(D.paginas), corrida.name)
    return pdf


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    construir(args.fecha)


if __name__ == "__main__":
    main()
