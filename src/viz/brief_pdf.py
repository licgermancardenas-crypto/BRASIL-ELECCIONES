"""
src/viz/brief_pdf.py

Brief en PDF con la identidad de Atlas Analytics (mismo formato que los
informes CABA de sep-2026: A4 apaisado, Arial, portada duotono, páginas con
kicker + título + bajada, figuras SVG e impresión con Chrome headless).

No recalcula modelos: lee la última corrida de cada uno
  data/processed/electoral/encuestas_agregadas/     (agregador + backtest)
  data/processed/electoral/presidencial_encuestas_sim/
  data/processed/electoral/gobernadores_sim/
  data/processed/legislativo/camara/  y  /senado/
y recalcula solo la tendencia diaria del agregador para el gráfico. Si cambian
los datos, primero se corren los modelos (ver README).

Output: reports/briefs/ATLAS_Brasil_Brief_1a_Vuelta_<corte>.pdf
        (HTML y figuras de trabajo en reports/briefs/_build/, fuera de git)

Uso:
    python -m src.viz.brief_pdf [--corte 2026-10-01]
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
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import yaml

from src.etl.transform.encuestas_resultados import CONFIG_CASAS
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, LEGISLATIVO_DIR, ROOT
from src.viz.tendencia_presidencial import calcular, corte_por_defecto

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BRIEFS = ROOT / "reports" / "briefs"
BUILD = BRIEFS / "_build"
CSS_MARCA = Path(__file__).with_name("atlas_marca.css")
CHROME = [r"C:/Program Files/Google/Chrome/Application/chrome.exe",
          r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
          r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]
PORTADA = Path(r"E:/ATLAS CONTENIDO/ATLAS ANALYTICS INSTAGRAM/CONCEPTOS DE EJEMPLO (IMAGENES)/ESTILO ATLAS/duotono/07-4d7e94332383.jpg")

INK, MUTED, VIO, RULE = "#1D1631", "#6B6480", "#5B3F99", "#D9D2E6"
# Famílias: convención de color brasileña (PT rojo, PL azul); misma paleta que los informes CABA.
COL = {"gobierno_lula": "#E34948", "direita_bolsonarista": "#2A78D6", "centrao": "#EDA100",
       "centro_liberal": "#1BAF7A", "esquerda_independente": "#4A3AA7", "sin_alineamiento": "#8A8983"}
FAM = {"gobierno_lula": "Gobierno Lula", "direita_bolsonarista": "Derecha bolsonarista", "centrao": "Centrão",
       "centro_liberal": "Centro liberal", "esquerda_independente": "Izquierda independiente",
       "sin_alineamiento": "Sin alineamiento"}
CAND = {"lula": "Lula (PT)", "flavio_bolsonaro": "Flávio Bolsonaro (PL)", "renan_santos": "Santos (Missão)",
        "cury": "Cury (Avante)", "caiado": "Caiado (PSD)", "zema": "Zema (Novo)", "otros": "Otros"}
C_LULA, C_FLAVIO = COL["gobierno_lula"], COL["direita_bolsonarista"]

plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none", "axes.edgecolor": "#BBBBBB",
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})

f1 = lambda x: f"{x:.1f}".replace(".", ",")
f0 = lambda x: f"{x:,.0f}".replace(",", ".")
pe = lambda x: f"{x * 100:.0f} %"
ps = lambda x: f"{x:.0f} %"
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))


def ultima(base: Path) -> Path:
    corridas = sorted(p.parent for p in base.glob("*/meta.json"))
    if not corridas:
        raise FileNotFoundError(f"Sin corridas en {base}")
    return corridas[-1]


def nombre_propio(s: str) -> str:
    t = s.title()
    for p in (" De ", " Da ", " Do ", " Dos ", " Das "):
        t = t.replace(p, p.lower())
    return t


def limpiar(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid:
        ax.grid(axis=grid, color="#EEEEEE", zorder=0)
    ax.tick_params(labelsize=8.5)


def guardar(fig, nombre: str) -> None:
    fig.savefig(BUILD / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------

def fig_tendencia(meta, val, tend) -> None:
    fig, ax = plt.subplots(figsize=(7.4, 5.0))
    for c, col in (("lula", C_LULA), ("flavio_bolsonaro", C_FLAVIO)):
        ax.scatter(meta["fecha_fin"], val[c] * 100, s=16, color=col, alpha=0.3, linewidths=0, zorder=2)
        ax.plot(tend.index, tend[c] * 100, color=col, lw=2, zorder=3)
        u = tend[c].iloc[-1] * 100
        ax.scatter([tend.index[-1]], [u], s=40, color=col, edgecolors="white", linewidths=1.5, zorder=4)
        ax.annotate(f"{CAND[c].split(' (')[0]} {f1(u)} %", (tend.index[-1], u), xytext=(7, 0),
                    textcoords="offset points", va="center", fontsize=8.5, color=INK, weight="bold")
    ax.set_ylim(30, 50)
    ax.yaxis.set_major_locator(plt.MultipleLocator(4))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.set_xticks(pd.date_range(meta["fecha_fin"].min(), tend.index[-1], freq="W-MON"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.set_xlim(right=tend.index[-1] + pd.Timedelta(days=10))
    limpiar(ax)
    guardar(fig, "tendencia.svg")


def fig_probabilidad(prin: dict, corr: dict) -> None:
    fig, ax = plt.subplots(figsize=(7.0, 1.9))
    filas = [("Estimación principal", prin), ("Si se repite el sesgo\nde 2018 y 2022", corr)]
    for i, (et, p) in enumerate(filas):
        fl, lu = p.get("flavio_bolsonaro", 0) * 100, p.get("lula", 0) * 100
        ax.barh(i, fl, color=C_FLAVIO, height=0.6, zorder=3)
        ax.barh(i, lu, left=fl, color=C_LULA, height=0.6, zorder=3)
        ax.text(2, i, f"Flávio {ps(fl)}", va="center", color="white", fontsize=9, weight="bold", zorder=4)
        ax.text(98, i, f"Lula {ps(lu)}", va="center", ha="right", color="white", fontsize=9, weight="bold", zorder=4)
    ax.axvline(50, color="white", lw=1, ls=(0, (2, 2)), zorder=5)
    ax.set_yticks(range(len(filas)), [f for f, _ in filas], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    guardar(fig, "probabilidad.svg")


def fig_sesgo(bt: pd.DataFrame) -> None:
    b = bt[bt["candidato"] == "bolsonaro"].copy()
    b["et"] = [f"{a} · " + ("1ª vuelta" if v == 1 else "cruce antes de la 1ª" if pre else "2ª vuelta")
               for a, v, pre in zip(b["ano"], b["vuelta"], b["cruce_antes_1v"])]
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    y = range(len(b))
    cols = [C_FLAVIO if pre or v == 1 else "#9EC3F0" for v, pre in zip(b["vuelta"], b["cruce_antes_1v"])]
    ax.barh(list(y), b["error_agregado_pp"], color=cols, height=0.62, zorder=3)
    for i, e in zip(y, b["error_agregado_pp"]):
        ax.text(e + (0.25 if e > 0 else -0.25), i, sg(e), va="center", ha="left" if e > 0 else "right", fontsize=8.5, color=INK)
    ax.axvline(0, color="#999", lw=1)
    ax.set_yticks(list(y), b["et"], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(-8.5, 4)
    ax.set_xlabel("Error del agregador sobre el candidato bolsonarista (puntos de votos válidos)", fontsize=8, color=MUTED)
    limpiar(ax, grid="x")
    guardar(fig, "sesgo.svg")


def fig_gobernadores(fav: pd.DataFrame) -> None:
    f = fav.sort_values("prob_ganar")
    fig, ax = plt.subplots(figsize=(6.4, 7.0))
    ax.barh(f["uf"], f["prob_ganar"] * 100, color=[COL[c] for c in f["familia"]], height=0.68, zorder=3)
    for i, r in enumerate(f.itertuples()):
        ax.text(r.prob_ganar * 100 + 1, i, f"{nombre_propio(r.nombre)}{' (inc.)' if r.incumbente else ''} · {ps(r.prob_ganar * 100)}",
                va="center", fontsize=7.2, color=INK)
    ax.axvline(50, color=INK, lw=0.8, ls="--", zorder=4)
    ax.set_xlim(0, 150)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100 %"])
    ax.tick_params(axis="y", labelsize=8)
    limpiar(ax, grid="x")
    presentes = [k for k in COL if k in set(f["familia"])]
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=COL[k]) for k in presentes], labels=[FAM[k] for k in presentes],
              loc="lower right", fontsize=7.5, frameon=False)
    guardar(fig, "gobernadores.svg")


def fig_congreso(cam: pd.DataFrame, sen: pd.DataFrame) -> None:
    fams = [f for f in ["centrao", "gobierno_lula", "direita_bolsonarista", "centro_liberal"] if f in cam.index]
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.6))
    for ax, d, cols, mayoria, titulo, tope in (
            (axes[0], cam, ("p10", "mediana", "p90"), 257, "Câmara dos Deputados (513)", 300),
            (axes[1], sen, ("total_p10", "total_mediana", "total_p90"), 41, "Senado Federal (81)", 45)):
        for i, f in enumerate(fams):
            lo, me, hi = (d.loc[f, c] for c in cols)
            ax.plot([lo, hi], [i, i], color=COL[f], lw=2.4, alpha=0.5, solid_capstyle="round")
            ax.scatter([me], [i], s=55, color=COL[f], zorder=3)
            ax.text(me, i - 0.3, f"{me:.0f}", ha="center", va="bottom", fontsize=9, color=INK, weight="bold")
        ax.axvline(mayoria, color=INK, lw=1, ls="--")
        ax.text(mayoria + tope * 0.01, -0.85, f"mayoría: {mayoria}", ha="left", fontsize=8, color=INK)
        ax.set_yticks(range(len(fams)), [FAM[f] for f in fams])
        ax.set_ylim(len(fams) - 0.4, -1)
        ax.set_xlim(0, tope)
        ax.set_title(titulo, fontsize=9, color=INK, loc="left", weight="bold")
        limpiar(ax, grid="x")
    axes[1].set_yticklabels([])
    fig.tight_layout()
    guardar(fig, "congreso.svg")


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

class Documento:
    def __init__(self, marca: str):
        self.paginas: list[str] = []
        self.marca = marca

    def pagina(self, cuerpo, pie="", kicker="", titulo="", bajada="", clase=""):
        cab = ""
        if titulo:
            cab = (f'<div class="cab"><div class="kicker">{kicker}</div><h2>{titulo}</h2>'
                   + (f'<p class="bajada">{bajada}</p>' if bajada else "") + "</div>")
        self.paginas.append(f'<section class="page {clase}">{cab}<div class="cuerpo">{cuerpo}</div>'
                            f'<div class="pie"><span>{pie}</span><span class="marca">{self.marca}</span>'
                            f'<span class="folio"></span></div></section>')


def tabla(cols, filas, num=()):
    th = "".join(f'<th class="{"num" if i in num else ""}">{c}</th>' for i, c in enumerate(cols))
    tr = "".join("<tr>" + "".join(f'<td class="{"num" if i in num else ""}">{v}</td>' for i, v in enumerate(f)) + "</tr>"
                 for f in filas)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


kpi = lambda v, l, n="": f'<div class="kpi"><div class="kpi-v">{v}</div><div class="kpi-l">{l}</div><div class="kpi-n">{n}</div></div>'
insight = lambda t: f'<div class="insight">{t}</div>'
fuente = lambda t: f'<p class="fuente">{t}</p>'
fig = lambda n, clase="fig": f'<img class="{clase}" src="figs/{n}">'

CSS_EXTRA = """
.fig-tend { max-height:12.2cm; }
.fig-prob { max-height:4.4cm; margin-top:.1cm; }
.fig-sesgo { max-height:8.2cm; }
.fig-gob { max-height:15cm; }
.fig-cong { max-height:9.4cm; }
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
.td-wrap td { white-space:normal; }
.td-wrap td.num { white-space:nowrap; }
.pag-gob .td-wrap table { font-size:8.4pt; } .pag-gob .td-wrap td { padding:.1cm .16cm; }
.pag-gob .insight { font-size:9pt; margin:.18cm 0; padding:.22cm .32cm; }
.p-der img { object-position: center 30%; }
"""


def construir(corte: date) -> Path:
    agr_dir = ultima(ELECTORAL_DIR / "encuestas_agregadas")
    mc_dir = ultima(ELECTORAL_DIR / "presidencial_encuestas_sim")
    gob_dir = ultima(ELECTORAL_DIR / "gobernadores_sim")
    cam_dir, sen_dir = ultima(LEGISLATIVO_DIR / "camara"), ultima(LEGISLATIVO_DIR / "senado")
    R = json.loads((mc_dir / "resumen.json").read_text(encoding="utf-8"))
    meta_agr = json.loads((agr_dir / "meta.json").read_text(encoding="utf-8"))
    meta_gob = json.loads((gob_dir / "meta.json").read_text(encoding="utf-8"))
    if R["fecha_corte_encuestas"] != corte.isoformat():
        log.warning("El Montecarlo es del corte %s y el brief pide %s", R["fecha_corte_encuestas"], corte)
    bt = pd.read_csv(agr_dir / "backtest.csv")
    tr = pd.read_csv(agr_dir / "track_record.csv")
    he = pd.read_csv(agr_dir / "house_effects.csv")
    prob_uf = pd.read_csv(gob_dir / "probabilidad_uf.csv")
    gob = pd.read_csv(gob_dir / "resumen.csv").set_index("familia")
    cam = pd.read_csv(cam_dir / "resumen.csv").set_index("familia")
    sen = pd.read_csv(sen_dir / "resumen.csv").set_index("familia")
    with open(CONFIG_CASAS, encoding="utf-8") as f:
        nombre_casa = {k: v["nombre"].split(" (")[0] for k, v in yaml.safe_load(f)["casas"].items()}

    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "figs").mkdir(parents=True)
    meta, val, tend = calcular(corte)
    fig_tendencia(meta, val, tend)
    C = R["sensibilidad_con_correccion_de_sesgo"]
    fig_probabilidad(R["prob_presidente"], C["prob_presidente"])
    fig_sesgo(bt)
    fav = prob_uf.sort_values("prob_ganar", ascending=False).groupby("uf").head(1)
    bal_uf = prob_uf.drop_duplicates("uf").set_index("uf")["prob_balotaje_uf"]
    fig_gobernadores(fav)
    fig_congreso(cam, sen)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")

    # ---- cifras
    a1 = R["agregado_1v_pct"]
    q = R["pct_validos_1v"]
    lu, fl = a1["lula"], a1["flavio_bolsonaro"]
    p2v, p2v_c = R["prob_hay_segunda_vuelta"], C["prob_hay_segunda_vuelta"]
    pres, pres_c = R["prob_presidente"], C["prob_presidente"]
    cruce = R["pct_lula_cruce_vs_flavio_bolsonaro"]
    cruce_c = C["pct_lula_cruce_vs_flavio_bolsonaro"]
    inc = R["incertidumbre_pp"]
    brecha = tend["lula"] - tend["flavio_bolsonaro"]
    sep = brecha[(brecha.index >= "2026-09-08") & (brecha.index <= "2026-09-16")].mean() * 100
    terceros = {k: v for k, v in a1.items() if k not in ("lula", "flavio_bolsonaro", "otros")}
    t2 = bt[bt["top2"]]
    mae_agr = t2.groupby(["ano", "vuelta", "cruce_antes_1v"])["error_agregado_pp"].apply(lambda s: s.abs().mean())
    mae_ind = t2.groupby(["ano", "vuelta", "cruce_antes_1v"])["mae_encuestas_individuales_top2_pp"].first()
    gana_agr = int((mae_agr < mae_ind).sum())
    sesgo_bol = bt[(bt["candidato"] == "bolsonaro") & ((bt["vuelta"] == 1) | bt["cruce_antes_1v"])]["error_agregado_pp"]
    n_centrao = int((fav["familia"] == "centrao").sum())
    balotajes = bal_uf.sum()
    abiertas = fav[fav["prob_ganar"] < 0.62].sort_values("prob_ganar")
    fl_corr = q["flavio_bolsonaro"]["mediana"] - inc["sesgo_1v"]["direita_bolsonarista"]
    umbral = (fl + fl_corr) / 2

    marca = "Atlas Analytics · Brasil 2026"
    D = Documento(marca)
    fecha_txt = f"{corte.day} de octubre de {corte.year}" if corte.month == 10 else corte.strftime("%d/%m/%Y")

    # ================================================================ portada
    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil antes del 4 de octubre</h1>
    <div class="p-sub">Brief previo a la primera vuelta: presidencial con encuestas agregadas, gobernadores y Congreso.
      Lo que dicen los números a tres días de la elección y dónde pueden fallar.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Encuestas</span> {meta.shape[0]} encuestas nacionales de 1ª vuelta y cruces de 2ª · campaña hasta el {meta['fecha_fin'].max():%d/%m}</div>
      <div><span>Historia</span> resultados oficiales del TSE 2018 y 2022 para medir el error de cada encuestadora</div>
      <div><span>Modelos</span> 10.000 simulaciones por modelo · corte {corte:%d/%m/%Y}</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    # ================================================================ resumen
    tesis = [
        ("La presidencial va a segunda vuelta, y es Lula contra Flávio",
         f"Probabilidad de balotaje: {pe(p2v)}. En votos válidos, Lula tiene {f1(lu)} % y Flávio Bolsonaro {f1(fl)} %; "
         f"ningún tercero llega al 5 %. El par Lula–Flávio aparece en prácticamente todas las simulaciones."),
        ("El balotaje está abierto, con ventaja de Flávio",
         f"Los cruces de segunda vuelta dan a Lula {f1(cruce['mediana'])} %. La probabilidad de ser presidente es "
         f"Flávio {pe(pres.get('flavio_bolsonaro', 0))} y Lula {pe(pres.get('lula', 0))}."),
        ("El riesgo está de un solo lado",
         f"En 2018 y 2022, antes de la primera vuelta, las encuestas subestimaron al candidato bolsonarista en las "
         f"{len(sesgo_bol)} mediciones, entre {f1(abs(sesgo_bol.max()))} y {f1(abs(sesgo_bol.min()))} puntos. "
         f"Si se repite, Flávio pasa a {pe(pres_c.get('flavio_bolsonaro', 0))}."),
        ("La tendencia favorece a Flávio",
         f"La ventaja de Lula en primera vuelta bajó de {f1(sep)} puntos a mediados de septiembre a "
         f"{f1(brecha.iloc[-1] * 100)} hoy."),
        ("En los estados manda el Centrão",
         f"Es favorito en {n_centrao} de las 27 UF y se esperan unos {balotajes:.0f} balotajes estaduales el 25/10. "
         "Este modelo no usa encuestas: parte del voto de 2022 y de la ventaja del gobernador en ejercicio."),
        ("Nadie gobierna solo en el Congreso",
         f"El Centrão rondaría los {cam.loc['centrao', 'mediana']:.0f} diputados y {sen.loc['centrao', 'total_mediana']:.0f} "
         "senadores, sin mayoría propia en ninguna cámara. Sigue siendo el bloque que define la gobernabilidad."),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(pe(p2v), "probabilidad de balotaje", "presidencial, 25 de octubre")
              + kpi(pe(pres.get("flavio_bolsonaro", 0)), "Flávio presidente", f"Lula {pe(pres.get('lula', 0))}")
              + kpi(f"{f1(brecha.iloc[-1] * 100)} pts", "ventaja de Lula en 1ª vuelta", f"era {f1(sep)} a mediados de sept.")
              + kpi(pe(pres_c.get("flavio_bolsonaro", 0)), "Flávio, si se repite el sesgo", "de 2018 y 2022")
              + kpi(f"{n_centrao}/27", "UF con el Centrão favorito", "gobernadores")
              + kpi(f"~{balotajes:.0f}", "balotajes estaduales", "esperados el 25/10")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(tesis))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="Una presidencial abierta y un Congreso que vuelve a depender del Centrão",
             bajada="Los seis hallazgos del brief. Cada uno se desarrolla en las páginas siguientes.",
             pie="Cifras presidenciales en votos válidos (sin blancos ni nulos), como las publica el TSE.")

    # ================================================================ 1ª vuelta
    orden = sorted(a1, key=lambda k: -a1[k])
    filas = [[CAND.get(k, k), f1(a1[k]) + " %", f"{f1(q[k]['p10'])} – {f1(q[k]['p90'])}"] for k in orden]
    he1 = he[he["vuelta"] == 1].set_index("casa")
    alto = he1["flavio_bolsonaro"].nlargest(2).index
    bajo = he1["flavio_bolsonaro"].nsmallest(3).index
    cuerpo = ('<div class="dos-col dos-col-60"><div>' + fig("tendencia.svg", "fig fig-tend")
              + fuente("Puntos: cada encuesta, en votos válidos. Línea: agregado ATLAS de cada día (corrige el sesgo propio de "
                       "cada encuestadora, pondera por historial y tamaño de muestra, y da más peso a lo reciente).")
              + "</div><div>"
              + tabla(["Candidato", "Votos válidos", "Rango p10–p90"], filas, num=(1, 2))
              + insight(f"<b>Lula adelante, pero lejos del 50 %.</b> Con {f1(lu)} %, la probabilidad de que gane en primera vuelta "
                        f"es de {pe(R['prob_gana_en_1v'].get('lula', 0))}.")
              + insight(f"<b>Flávio viene subiendo.</b> Pasó de unos {f1(tend['flavio_bolsonaro'].loc['2026-09-08':'2026-09-16'].mean() * 100)} "
                        f"a {f1(fl)} % en dos semanas, mientras Lula se mantuvo estable.")
              + insight(f"<b>Los terceros suman {f1(sum(terceros.values()))} %</b> y son los que se reparten en el balotaje. "
                        "Ninguno tiene chances de pasar a la segunda vuelta.")
              + insight(f"<b>Las encuestadoras difieren poco entre sí.</b> {' y '.join(nombre_casa.get(c, c) for c in alto)} muestran a "
                        f"Flávio algo más alto; {', '.join(nombre_casa.get(c, c) for c in bajo)}, algo más bajo. Ninguna se aparta "
                        "más de 1,7 puntos del resto.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="1 · PRIMERA VUELTA", titulo="Lula adelante, Flávio achicando la distancia",
             bajada="Intención de voto en votos válidos, del 16 de agosto al cierre de campo de las últimas encuestas.",
             pie=f"Encuestas publicadas, compiladas en Wikipedia (revisión {meta_agr['revid_wikipedia']['2026']}); rango p10–p90 "
                 "del Montecarlo.")

    # ================================================================ 2ª vuelta y sesgo
    filas = [
        ["Probabilidad de 2ª vuelta", pe(p2v), pe(p2v_c)],
        ["Lula gana en 1ª vuelta", pe(R["prob_gana_en_1v"].get("lula", 0)), pe(C["prob_gana_en_1v"].get("lula", 0))],
        ["Flávio gana en 1ª vuelta", pe(R["prob_gana_en_1v"].get("flavio_bolsonaro", 0)),
         pe(C["prob_gana_en_1v"].get("flavio_bolsonaro", 0))],
        ["% Lula en el cruce (mediana)", f1(cruce["mediana"]) + " %", f1(cruce_c["mediana"]) + " %"],
        ["Rango p10–p90 del cruce", f"{f1(cruce['p10'])} – {f1(cruce['p90'])}", f"{f1(cruce_c['p10'])} – {f1(cruce_c['p90'])}"],
        ["<b>Flávio presidente</b>", f"<b>{pe(pres.get('flavio_bolsonaro', 0))}</b>", f"<b>{pe(pres_c.get('flavio_bolsonaro', 0))}</b>"],
    ]
    cuerpo = ('<div class="dos-col"><div>' + fig("probabilidad.svg", "fig fig-prob")
              + fuente("Probabilidad de ganar la presidencia en 10.000 simulaciones.")
              + fig("sesgo.svg", "fig fig-sesgo")
              + fuente("Error del agregador de ATLAS al reconstruir 2018 y 2022 con las encuestas que había la víspera. "
                       "Negativo: las encuestas dieron al candidato bolsonarista menos de lo que sacó.")
              + "</div><div>"
              + tabla(["", "Principal", "Con corrección"], filas, num=(1, 2))
              + insight(f"<b>Con las encuestas tal cual, es casi una moneda al aire.</b> Lula sacaría {f1(cruce['mediana'])} % en el "
                        f"cruce contra Flávio, y el rango va de {f1(cruce['p10'])} a {f1(cruce['p90'])} %.")
              + insight(f"<b>El error de las encuestas apuntó siempre al mismo lado.</b> Antes de la primera vuelta subestimaron al "
                        f"bolsonarismo en {f1(abs(inc['sesgo_1v']['direita_bolsonarista']))} puntos en promedio. Corrigiendo ese sesgo, "
                        f"Flávio pasa a {pe(pres_c.get('flavio_bolsonaro', 0))}.")
              + insight("<b>No lo corregimos de oficio:</b> son dos elecciones de historia. Por eso mostramos las dos cifras; "
                        "la noche del 4 de octubre va a decir cuál se acerca más.")
              + insight("<b>Después de la primera vuelta el cruce acierta.</b> En 2018 y 2022, las encuestas de balotaje "
                        "hechas después del primer turno erraron 2 puntos o menos. El número se recalibra desde el 5 de octubre.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="2 · SEGUNDA VUELTA", titulo="Un balotaje parejo, con un riesgo que apunta hacia Flávio",
             bajada="Probabilidad de ser presidente según se corrija o no el sesgo histórico de las encuestas.",
             pie="Los cruces de 2ª vuelta se midieron antes de la 1ª: en 2018 y 2022 ese tipo de medición erró entre 4 y 6 puntos.")

    # ================================================================ cómo se construye el número
    bb = bt[bt["candidato"] == "bolsonaro"]
    filas_bt = [[f"{r.ano} · " + ("1ª vuelta" if r.vuelta == 1 else "cruce antes de la 1ª" if r.cruce_antes_1v else "2ª vuelta"),
                 f1(r.real_pct) + " %", f1(r.agregado_pct) + " %", sg(r.error_agregado_pp),
                 f1(mae_agr[(r.ano, r.vuelta, r.cruce_antes_1v)]), f1(mae_ind[(r.ano, r.vuelta, r.cruce_antes_1v)])]
                for r in bb.itertuples()]
    trs = tr.sort_values("peso_calidad", ascending=False)
    filas_tr = [[nombre_casa.get(r.casa, r.casa), r.elecciones, f1(r.rmse_pp), f1(r.peso_calidad).replace(",0", ",0")]
                for r in trs.itertuples()]
    cuerpo = ('<div class="dos-col dos-col-55"><div>'
              + '<h3 class="sub">Prueba contra el resultado real (candidato bolsonarista)</h3>'
              + tabla(["Medición", "Real", "Agregado", "Error", "Error medio agregador", "Error medio encuestas"], filas_bt,
                      num=(1, 2, 3, 4, 5))
              + fuente("Errores medios sobre los dos más votados, en puntos. 'Encuestas': promedio de las encuestas individuales "
                       "de la última semana.")
              + insight(f"<b>El agregador erra menos que la encuesta promedio en {gana_agr} de 6 mediciones</b> "
                        f"({f1(mae_agr.mean())} contra {f1(mae_ind.mean())} puntos en promedio). La ventaja es chica: el error "
                        "grande es de toda la industria, no de una encuestadora.")
              + insight("<b>El peso de lo reciente se calibró con esta misma prueba</b> (vida media de 3 días): en 2018 y 2022 hubo "
                        "un movimiento de último momento hacia Bolsonaro que los promedios más lentos no captaron.")
              + "</div><div>"
              + '<h3 class="sub">Historial de cada encuestadora (2018 y 2022)</h3>'
              + tabla(["Encuestadora", "Elecciones", "Error (pts)", "Peso"], filas_tr, num=(1, 2, 3))
              + fuente("Error cuadrático medio contra el TSE en la última semana. Peso 1 = promedio de la industria. Las casas sin "
                       "historial, o con cambios de razón social sin verificar (Ipec, Ideia, Vox Brasil, Gerp), pesan 1.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="3 · CÓMO SE CONSTRUYE EL NÚMERO", titulo="Cada encuestadora pesa según cuánto acertó en 2018 y 2022",
             bajada="El agregador se probó reconstruyendo las dos elecciones anteriores con las encuestas que había la víspera.",
             pie="Resultados oficiales del TSE; encuestas publicadas compiladas en Wikipedia (revisiones fijadas por año).")

    # ================================================================ gobernadores
    filas_ab = []
    for r in abiertas.itertuples():
        seg = prob_uf[prob_uf["uf"] == r.uf].nlargest(2, "prob_ganar").iloc[1]
        filas_ab.append([r.uf, f"{nombre_propio(r.nombre)}{' (inc.)' if r.incumbente else ''}", pe(r.prob_ganar),
                         nombre_propio(seg["nombre"]), pe(seg["prob_ganar"]), pe(bal_uf[r.uf])])
    top_bal = bal_uf.sort_values(ascending=False).head(5)
    sp = prob_uf[prob_uf["uf"] == "SP"].nlargest(2, "prob_ganar")
    calib = meta_gob["aciertos_familia_ganadora_calibracion"]
    cuerpo = ('<div class="dos-col pag-gob"><div>' + fig("gobernadores.svg", "fig fig-gob") + "</div><div>"
              + '<h3 class="sub">Las carreras más abiertas</h3>'
              + f'<div class="td-wrap">{tabla(["UF", "Favorito", "Gana", "Retador", "Gana", "Balotaje"], filas_ab, num=(2, 4, 5))}</div>'
              + insight(f"<b>El Centrão es favorito en {n_centrao} de las 27 UF</b> (entre {gob.loc['centrao', 'p10']:.0f} y "
                        f"{gob.loc['centrao', 'p90']:.0f} gobernaciones según la simulación). Gobierno Lula retiene sus bastiones del "
                        "Nordeste y la derecha bolsonarista compite en serio solo en SC.")
              + insight("<b>Más probables de ir a balotaje:</b> "
                        + ", ".join(f"{uf} ({pe(p)})" for uf, p in top_bal.items())
                        + f". En SP, {nombre_propio(sp.iloc[0]['nombre'])} {pe(sp.iloc[0]['prob_ganar'])} contra "
                          f"{nombre_propio(sp.iloc[1]['nombre'])} {pe(sp.iloc[1]['prob_ganar'])}.")
              + insight(f"<b>Modelo estructural, sin encuestas.</b> Acierta la família ganadora en {calib['modelo']} de "
                        f"{calib['elecciones']} elecciones de prueba ({calib['ingenua_incumbente']} si siempre ganara el gobernador "
                        "en ejercicio). Los candidatos de una misma família se muestran juntos.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="4 · GOBERNADORES", titulo="El Centrão domina los estados; seis carreras siguen abiertas",
             bajada="Probabilidad de ganar del favorito en cada UF, coloreada por família. Cada estado tiene su propio balotaje.",
             pie="Base: voto por família en 2022 y ventaja del gobernador en ejercicio, calibrada con 2018 y 2022. No incorpora encuestas.")

    # ================================================================ congreso
    cuerpo = (fig("congreso.svg", "fig fig-cong")
              + fuente("Punto: mediana de 10.000 simulaciones. Barra: rango p10–p90. Línea punteada: mayoría absoluta.")
              + '<div class="dos-col">'
              + insight(f"<b>Câmara:</b> el Centrão tendría {cam.loc['centrao', 'mediana']:.0f} diputados (entre "
                        f"{cam.loc['centrao', 'p10']:.0f} y {cam.loc['centrao', 'p90']:.0f}), sin llegar a los 257. Gobierno Lula, "
                        f"{cam.loc['gobierno_lula', 'mediana']:.0f}; la derecha bolsonarista, {cam.loc['direita_bolsonarista', 'mediana']:.0f}, "
                        "con el rango más amplio: es la família que más se mueve entre elecciones.")
              + insight(f"<b>Senado:</b> se renuevan 54 de 81 bancas. El Centrão quedaría con {sen.loc['centrao', 'total_mediana']:.0f} "
                        f"senadores y llega a 41 solo en el {pe(sen.loc['centrao', 'prob_mayoria_propia'])} de las simulaciones. "
                        "El próximo presidente, sea quien sea, va a necesitarlo para gobernar.")
              + insight("<b>Son modelos sin encuestas:</b> parten del voto a diputados de 2022 con los partidos agrupados como hoy, "
                        "más el ruido observado entre 2018 y 2022. Miden la estructura, no el clima de campaña.")
              + "</div>")
    D.pagina(cuerpo, kicker="5 · CONGRESO", titulo="Ninguna família tiene mayoría propia en ninguna de las dos cámaras",
             bajada="Bancas proyectadas por família política para la legislatura que empieza en 2027.",
             pie="Câmara: reparto proporcional por UF con la cláusula de barrera vigente. Senado: 27 bancas que siguen + 54 en juego.")

    # ================================================================ qué mirar
    acciones = [
        (f"Flávio por encima de {f1(umbral)} % de los válidos",
         f"Es la mitad del camino entre lo que dicen las encuestas ({f1(fl)} %) y lo que daría el sesgo de 2018 y 2022 "
         f"(~{f1(fl_corr)} %). Si lo supera, el escenario corregido pasa a ser el principal para el balotaje."),
        ("Lula por encima del 50 %",
         f"Probabilidad de {pe(R['prob_gana_en_1v'].get('lula', 0))}. Si pasa, no hay balotaje presidencial."),
        ("El destino de los votos de Santos, Cury y Caiado",
         f"Suman {f1(sum(terceros.values()))} % y deciden el balotaje. Cury compite dentro del espacio de gobierno; Santos y "
         "Caiado, desde la centroderecha."),
        ("SC, MA, RJ, RN y MG",
         "Definen cuántos estados van a balotaje y si alguna família distinta del Centrão gana una UF grande."),
        ("Recalibrar el 5 de octubre",
         "Con el resultado oficial, el modelo de segunda vuelta pasa a usar solo encuestas de balotaje hechas después del primer "
         "turno, que en 2018 y 2022 fueron mucho más precisas."),
    ]
    cuerpo = ('<div class="dos-col"><div>'
              + "".join(f'<div class="reco"><div class="r-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(acciones))
              + '</div><div class="nota-metodo">'
              '<h3>De dónde sale cada cosa</h3>'
              f'<p><b>Las encuestas.</b> Resultados publicados de {meta.shape[0]} encuestas nacionales de primera vuelta y de los cruces '
              'de segunda, compilados en Wikipedia. Se guarda la revisión exacta de cada página para poder reproducir el cálculo. '
              'Todavía no están cruzadas una por una con el registro oficial del TSE.</p>'
              '<p><b>El historial.</b> Resultados oficiales del TSE de 2018 y 2022, contra los que se mide el error de cada '
              'encuestadora y del propio agregador.</p>'
              '<p><b>Los modelos estructurales.</b> Gobernadores, Câmara y Senado parten del voto de 2022 con los partidos agrupados '
              'en famílias políticas como están hoy, y simulan el cambio con lo observado entre 2018 y 2022.</p>'
              '<h3>Cómo leer los números</h3>'
              '<p>Las cifras presidenciales están en votos válidos, sin blancos ni nulos: por eso son más altas que las que publica la '
              'prensa. Los rangos no son el margen de error de una encuesta, sino el error que tuvo el método en las dos elecciones '
              'anteriores.</p>'
              '<p>Una probabilidad de 54 % no es una predicción de victoria: quiere decir que, con la información de hoy, ese '
              'resultado ocurre algo más de la mitad de las veces.</p>'
              '<h3>Alcance</h3>'
              '<p>La presidencial es nacional; no hay estimación por estado con encuestas. Con dos elecciones de historia, el error '
              'y el sesgo se miden sobre pocos casos.</p></div></div>')
    D.pagina(cuerpo, kicker="QUÉ MIRAR EL 4 DE OCTUBRE", titulo="Cinco señales para leer la noche electoral",
             pie=f"Atlas Analytics · {fecha_txt} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil antes del 4 de octubre</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "brief.html").write_text(html, encoding="utf-8")

    chrome = next((c for c in CHROME if Path(c).exists()), None)
    if chrome is None:
        raise FileNotFoundError("No se encontró Chrome/Edge para imprimir el PDF")
    pdf = BRIEFS / f"ATLAS_Brasil_Brief_1a_Vuelta_{corte:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "brief.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas)", pdf.relative_to(ROOT).as_posix(), len(D.paginas))
    return pdf


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corte", type=date.fromisoformat)
    args = parser.parse_args(argv)
    construir(args.corte or corte_por_defecto())


if __name__ == "__main__":
    main()
