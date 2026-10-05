# -*- coding: utf-8 -*-
"""Carrusel para LinkedIn sobre la 1ª vuelta 2026, en la línea editorial de Atlas.

Siete láminas 1080x1350 sobre papel marfil (#F4F0E8, la variante impresa de la
marca), tinta azul noche y un acento violeta: la misma familia que los informes
en PDF, no la de Instagram. Cada lámina afirma un dato en el título y lo
muestra con un solo gráfico.

  1. Portada (mapa municipal 2026)
  2. El error de las encuestas con el candidato bolsonarista, 2018-2026
  3. Lula y Flávio por estado
  4. Focos de voto (LISA, 2º turno 2022)
  5. Efecto local de la alfabetización (GWR, 2022)
  6. Minas Gerais y el ganador
  7. Cómo se hizo

Insumos: conteo TSE (src/models/conteo_2026.py), agregador de encuestas,
análisis espacial (R/analisis_espacial.R). Se arma en HTML, se imprime con
Chrome headless y se rasteriza a JPG con PyMuPDF.

    python -m src.viz.carrusel_linkedin
"""
import json
import statistics
import subprocess
from pathlib import Path

import fitz
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, to_hex

from src.viz.post_pronostico import CONTEO, CONTEO_MUN, FECHA_1V, MINAS_HISTORIA, RAIZ, RESUMEN, SALIDA, cargar_municipios

ESPACIAL = RAIZ / "data" / "processed" / "geo" / "_espacial"
AGREGADOR = RAIZ / "data" / "processed" / "electoral" / "encuestas_agregadas"
BUILD = SALIDA / "_build_carrusel"
JPG = SALIDA / f"carrusel_linkedin_{FECHA_1V}"
PDF = SALIDA / f"ATLAS_carrusel_linkedin_{FECHA_1V}.pdf"
BRAND = Path(r"C:\Users\corra\Desktop\ANALISIS POLITICO\SERVICIOS PRESENTACIONES\brandkit")
LOGO = BRAND / "logo-horizontal" / "atlas-horizontal-negro.svg"
LOGO_V = BRAND / "logo-horizontal" / "atlas-horizontal-violeta.svg"
CHROME = [r"C:/Program Files/Google/Chrome/Application/chrome.exe",
          r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
          r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]

PAPEL, TINTA, MUTED, VIO = "#F4F0E8", "#1D1631", "#6B6480", "#5B3F99"
LULA, FLAVIO = "#E34948", "#2A78D6"
OCRE = "#C98A1B"
GRIS_MAPA = "#E4DDD1"
TOTAL = 7

plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none", "text.color": TINTA,
                     "axes.labelcolor": TINTA, "xtick.color": MUTED, "ytick.color": TINTA})

f1 = lambda x: f"{x:.1f}".replace(".", ",")
f2 = lambda x: f"{x:.2f}".replace(".", ",")
f0 = lambda x: f"{x:,.0f}".replace(",", ".")
sig = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))


# --------------------------------------------------------------------------- datos
def cargar():
    conteo = json.loads(CONTEO.read_text(encoding="utf-8"))
    res = json.loads(RESUMEN.read_text(encoding="utf-8"))
    agr = sorted(p for p in AGREGADOR.iterdir() if (p / "backtest.csv").exists())[-1]
    bt = pd.read_csv(agr / "backtest.csv")
    esp_dir = sorted(p for p in ESPACIAL.iterdir() if (p / "resumen.json").exists())[-1]
    esp = json.loads((esp_dir / "resumen.json").read_text(encoding="utf-8"))
    mun_esp = gpd.read_file(esp_dir / "municipios.gpkg",
                            columns=["codigo", "uf", "lisa_lula", "gwr_alfabetizacion", "geometry"])
    mun_esp = mun_esp[mun_esp.codigo != 0]

    mun = cargar_municipios()
    m = pd.read_parquet(CONTEO_MUN)
    m = m[(m.flavio + m.lula) > 0]
    m["lula_2026"] = 100 * m.lula / (m.lula + m.flavio)
    mun = mun.assign(codigo=mun.codigo.astype(int)).merge(
        m[["codigo", "lula_2026"]].astype({"codigo": int}), on="codigo", how="left")
    return conteo, res, bt, esp, mun_esp, mun


def por_estado(conteo):
    filas = []
    for uf, r in conteo["por_uf"].items():
        if uf == "zz":  # exterior
            continue
        v = r["votos"]
        t = sum(v.values())
        filas.append((uf.upper(), 100 * v["lula"] / t, 100 * v["flavio_bolsonaro"] / t))
    return sorted(filas, key=lambda f: f[1] - f[2])


def pct_uf(conteo, uf):
    v = conteo["por_uf"][uf]["votos"]
    t = sum(v.values())
    return 100 * v["flavio_bolsonaro"] / t, 100 * v["lula"] / t


# --------------------------------------------------------------------------- figuras
def limpiar(ax):
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=13)
    ax.set_facecolor("none")


def guardar_svg(fig, nombre):
    fig.savefig(BUILD / nombre, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return nombre


def mapa_png(gdf, colores, nombre, ancho_px, borde_uf=True):
    """Mapa en Albers con relleno por municipio y bordes de estado finos, en PNG."""
    g = gdf.to_crs("ESRI:102033").assign(_c=list(colores))
    # los contornos se disuelven antes de simplificar: si no, los huecos entre
    # municipios simplificados quedan como agujeros y se dibujan como puntos
    ufs = g[["uf", "geometry"]].dissolve("uf").buffer(1).simplify(800)
    pais = gpd.GeoSeries(ufs.union_all(), crs=g.crs).buffer(1).simplify(800)
    g = g.assign(geometry=g.geometry.simplify(250))
    x0, y0, x1, y1 = pais.total_bounds
    dpi = 200
    fig = plt.figure(figsize=(ancho_px / dpi, ancho_px / dpi * (y1 - y0) / (x1 - x0)), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    g.plot(ax=ax, color=g["_c"], linewidth=0)
    if borde_uf:
        ufs.boundary.plot(ax=ax, linewidth=0.5, color=PAPEL)
    pais.boundary.plot(ax=ax, linewidth=0.6, color=TINTA, alpha=0.55)
    fig.savefig(BUILD / nombre, dpi=dpi, transparent=True)
    plt.close(fig)
    return nombre


def colores_voto(serie):
    cmap = LinearSegmentedColormap.from_list("fl", [FLAVIO, "#9DB8D9", "#EDE6DA", "#E8A6A0", LULA])
    return [GRIS_MAPA if pd.isna(x) else to_hex(cmap((min(max(x, 25), 75) - 25) / 50)) for x in serie]


def fig_encuestas(bt, conteo, res):
    """Resultado menos promedio de encuestas en la 1ª vuelta, por campo y año."""
    b = bt[bt.vuelta == 1]
    pt = {2018: "haddad", 2022: "lula"}
    err = lambda a, c: -b[(b.ano == a) & (b.candidato == c)].error_agregado_pp.iloc[0]
    filas = [(a, err(a, "bolsonaro"), err(a, pt[a])) for a in (2018, 2022)]
    agr, real = res["agregado_1v_pct"], conteo["proyeccion_pct"]
    filas.append((2026, real["flavio_bolsonaro"] - agr["flavio_bolsonaro"], real["lula"] - agr["lula"]))

    fig, ax = plt.subplots(figsize=(8.6, 6.4))
    x = np.arange(len(filas))
    w = 0.34
    for k, (col, et) in enumerate(((FLAVIO, "Candidato bolsonarista"), (LULA, "Candidato del PT"))):
        vals = [f[1 + k] for f in filas]
        ax.bar(x + (k - 0.5) * w, vals, width=w * 0.9, color=col, label=et, zorder=3)
        for xi, v in zip(x, vals):
            ax.text(xi + (k - 0.5) * w, v + (0.25 if v >= 0 else -0.25), sig(v),
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=14, weight="bold", color=TINTA)
    ax.axhline(0, color=TINTA, lw=0.8)
    ax.set_xticks(x, [str(f[0]) for f in filas], fontsize=15, color=TINTA)
    ax.tick_params(axis="x", pad=10)
    ax.set_yticks([])
    ax.set_ylim(-2.6, 7.2)
    limpiar(ax)
    ax.legend(loc="upper left", frameon=False, fontsize=13, ncol=2, bbox_to_anchor=(0, 1.04), handlelength=1)
    return guardar_svg(fig, "encuestas.svg")


def fig_estados(conteo):
    filas = por_estado(conteo)
    nac = conteo["proyeccion_pct"]
    fig, ax = plt.subplots(figsize=(8.6, 8.4))
    y = np.arange(len(filas))[::-1]
    for yi, (uf, l, f) in zip(y, filas):
        ax.plot([min(l, f), max(l, f)], [yi, yi], color="#CFC6B8", lw=2, zorder=2)
        ax.scatter([l], [yi], s=62, color=LULA, zorder=3, linewidths=0)
        ax.scatter([f], [yi], s=62, color=FLAVIO, zorder=3, linewidths=0)
    for v, col in ((nac["lula"], LULA), (nac["flavio_bolsonaro"], FLAVIO)):
        ax.axvline(v, color=col, lw=1, ls=(0, (3, 3)), alpha=0.8, zorder=1)
    ax.set_yticks(y, [f[0] for f in filas], fontsize=12.5, fontfamily="Consolas")
    ax.set_xlim(18, 76)
    ax.set_ylim(-0.8, len(filas) - 0.2)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.xaxis.tick_top()
    ax.grid(axis="x", color="#E2DACD", lw=0.8, zorder=0)
    limpiar(ax)
    return guardar_svg(fig, "estados.svg"), filas


# --------------------------------------------------------------------------- HTML
CSS = """
@page { size: 1080px 1350px; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: %(t)s; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.l { width: 1080px; height: 1350px; padding: 72px 88px 66px; background: %(p)s; position: relative; overflow: hidden;
     page-break-after: always; display: flex; flex-direction: column; }
.l:last-child { page-break-after: auto; }
.top { display: flex; justify-content: space-between; align-items: center; padding-bottom: 22px; border-bottom: 1px solid #CFC6B8; }
.top img { height: 30px; }
.folio { font-family: Consolas, monospace; font-size: 15px; letter-spacing: .12em; color: %(m)s; }
.kicker { font-family: Consolas, monospace; font-size: 16px; letter-spacing: .16em; color: %(v)s; margin: 48px 0 18px; text-transform: uppercase; }
h1 { font-size: 50px; line-height: 1.1; letter-spacing: -.012em; margin: 0; font-weight: bold; max-width: 880px; }
.sub { font-size: 22px; line-height: 1.45; color: %(m)s; margin: 18px 0 0; max-width: 860px; }
.fig { flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; margin: 22px 0 10px; }
.fig img { max-width: 100%%; max-height: 100%%; }
.txt { font-size: 20px; line-height: 1.5; color: #3A3350; margin: 0 0 4px; max-width: 900px; }
.txt b { color: %(t)s; }
.fuente { border-top: 1px solid #CFC6B8; padding-top: 14px; margin-top: 18px; font-size: 14px; line-height: 1.5; color: %(m)s; }
.ley { display: flex; gap: 28px; font-size: 15px; color: #3A3350; align-items: center; flex-wrap: wrap; }
.ley i { display: inline-block; width: 13px; height: 13px; margin-right: 8px; vertical-align: -1px; }
.grad { display: inline-block; width: 170px; height: 10px; vertical-align: 1px; margin: 0 10px; }
.cifras { display: flex; border-top: 1px solid #CFC6B8; margin-top: 14px; }
.cifras > div { flex: 1; padding: 16px 20px 0 0; }
.cifras > div + div { padding-left: 24px; border-left: 1px solid #CFC6B8; }
.cifras b { display: block; font-size: 36px; letter-spacing: -.01em; }
.cifras span { font-size: 15px; color: %(m)s; line-height: 1.4; display: block; margin-top: 4px; }

.portada h1 { font-size: 78px; line-height: 1.02; letter-spacing: -.022em; max-width: 640px; margin-top: 8px; }
.portada h1 em { font-style: normal; color: %(v)s; }
.portada .sub { font-size: 24px; max-width: 520px; }
.portada .mapa { position: absolute; right: -24px; bottom: 128px; width: 690px; }
.portada .firma { margin-top: auto; display: flex; justify-content: space-between; align-items: flex-end;
                  border-top: 1px solid #CFC6B8; padding-top: 18px; font-size: 15px; color: %(m)s; position: relative; }

.duo { flex: 1; display: flex; gap: 40px; margin-top: 30px; min-height: 0; }
.duo .izq { width: 280px; flex: none; display: flex; flex-direction: column; }
.duo .der { flex: 1; display: flex; align-items: center; justify-content: center; min-width: 0; margin-right: -64px; }
.duo .der img { max-width: 100%%; max-height: 100%%; }
.dato { padding: 16px 0; border-bottom: 1px solid #CFC6B8; }
.dato:first-child { padding-top: 0; }
.dato b { display: block; font-size: 40px; letter-spacing: -.01em; }
.dato span { font-size: 15px; color: %(m)s; line-height: 1.4; display: block; margin-top: 4px; }
.nota { font-size: 16.5px; line-height: 1.5; color: #3A3350; margin: 18px 0 0; }

table { border-collapse: collapse; width: 100%%; font-size: 18px; }
td { padding: 13px 0; border-bottom: 1px solid #DDD5C8; }
td.a { font-family: Consolas, monospace; color: %(m)s; width: 70px; font-size: 16px; }
td.r { text-align: right; color: %(m)s; font-size: 14px; }
tr.hoy td { border-bottom: 2px solid %(t)s; font-weight: bold; padding-top: 12px; }
tr.hoy td.a, tr.hoy td.r { color: %(v)s; }

dl { margin: 34px 0 0; display: grid; grid-template-columns: 200px 1fr; }
dt, dd { padding: 24px 0; border-top: 1px solid #CFC6B8; margin: 0; }
dt { font-family: Consolas, monospace; font-size: 15px; letter-spacing: .12em; color: %(v)s; text-transform: uppercase; padding-top: 29px; }
dd { font-size: 21px; line-height: 1.5; color: #3A3350; }
.cierre { margin-top: auto; display: flex; justify-content: space-between; align-items: flex-end; border-top: 2px solid %(t)s; padding-top: 28px; }
.cierre img { height: 52px; }
.cierre div { text-align: right; font-size: 16px; color: %(m)s; line-height: 1.6; }
.cierre div b { color: %(t)s; font-size: 18px; }
""" % {"p": PAPEL, "t": TINTA, "m": MUTED, "v": VIO}


def lamina(n, cuerpo, clase=""):
    return (f'<section class="l {clase}"><div class="top"><img src="{LOGO.as_uri()}">'
            f'<span class="folio">{n:02d} / {TOTAL:02d}</span></div>{cuerpo}</section>')


def armar_html(conteo, res, bt, esp, mun_esp, mun):
    BUILD.mkdir(parents=True, exist_ok=True)
    paginas = []
    nac = conteo["proyeccion_pct"]
    secc = f1(conteo["pct_secciones_contadas"])

    # 1 · portada
    mapa_png(mun, colores_voto(mun["lula_2026"]), "portada.png", 1520)
    paginas.append(lamina(1, f"""
      <div class="kicker">Brasil · elección presidencial 2026</div>
      <h1>Lo que el <em>promedio</em> no muestra</h1>
      <p class="sub">Notas de datos sobre la primera vuelta: encuestas, territorio y margen de error.</p>
      <img class="mapa" src="portada.png">
      <div class="firma"><span>Atlas Analytics · 5 de octubre de 2026</span>
        <span class="ley">Flávio<span class="grad" style="background:linear-gradient(90deg,{FLAVIO},#EDE6DA,{LULA})"></span>Lula</span></div>
    """, "portada"))

    # 2 · encuestas
    fig = fig_encuestas(bt, conteo, res)
    agr = res["agregado_1v_pct"]
    s_base = res["prob_presidente"]["flavio_bolsonaro"]
    s_corr = res["sensibilidad_con_correccion_de_sesgo"]["prob_presidente"]["flavio_bolsonaro"]
    paginas.append(lamina(2, f"""
      <div class="kicker">Encuestas</div>
      <h1>Tres elecciones seguidas, el mismo error</h1>
      <p class="sub">Resultado de la primera vuelta menos el promedio de encuestas, en puntos.</p>
      <div class="fig"><img src="{fig}"></div>
      <p class="txt">El promedio del 1 de octubre daba a Lula {f1(agr['lula'])}% y a Flávio Bolsonaro {f1(agr['flavio_bolsonaro'])}%.
      Lula sacó {f1(nac['lula'])}% y Flávio, {f1(nac['flavio_bolsonaro'])}%. Como en 2018 y 2022, el voto bolsonarista
      quedó subrepresentado. Corrigiendo ese sesgo, el modelo le daba a Flávio <b>{round(s_corr * 100)}%</b> de probabilidad
      de ganar el balotaje; sin corregirlo, {round(s_base * 100)}%.</p>
      <div class="fuente">Promedio ponderado de encuestas publicadas, con ajuste por encuestadora (Atlas). 2026: proyección con el {secc}% de las secciones contadas (TSE). Candidato del PT en 2018: Haddad.</div>
    """))

    # 3 · estados
    fig, filas = fig_estados(conteo)
    lo, hi = min(filas, key=lambda f: f[1]), max(filas, key=lambda f: f[1])
    sd = statistics.pstdev([l for _, l, _ in filas])
    gana_f = sum(f > l for _, l, f in filas)
    ap = conteo["por_uf"]["ap"]["votos"]
    paginas.append(lamina(3, f"""
      <div class="kicker">Estado por estado</div>
      <h1>Lula sacó {f1(lo[1])}% en Roraima y {f1(hi[1])}% en Piauí</h1>
      <p class="sub">El país terminó {f1(nac['flavio_bolsonaro'])} a {f1(nac['lula'])}. Muy pocos estados quedaron cerca de ese número.</p>
      <div class="fig"><img src="{fig}"></div>
      <div class="ley"><span><i style="background:{LULA};border-radius:50%"></i>Lula</span>
        <span><i style="background:{FLAVIO};border-radius:50%"></i>Flávio Bolsonaro</span>
        <span style="color:{MUTED}">Líneas punteadas: resultado nacional</span></div>
      <div class="cifras">
        <div><b>{gana_f} – {len(filas) - gana_f}</b><span>estados para Flávio y para Lula; Amapá se definió por {f0(ap['lula'] - ap['flavio_bolsonaro'])} votos</span></div>
        <div><b>{f1(sd)} pp</b><span>desvío estándar del voto a Lula entre estados</span></div>
      </div>
      <div class="fuente">% de votos válidos por estado, sin exterior. TSE, {secc}% de las secciones. Ordenado por margen.</div>
    """))

    # 4 · LISA
    col = mun_esp["lisa_lula"].map({"High-High": LULA, "Low-Low": FLAVIO}).fillna(GRIS_MAPA)
    mapa_png(mun_esp, col, "lisa.png", 1300)
    mg = esp["moran_municipios"]
    cl = mg["clusters"]
    paginas.append(lamina(4, f"""
      <div class="kicker">Geografía del voto</div>
      <h1>{f0(cl['High-High'] + cl['Low-Low'])} municipios forman bloques de voto homogéneo</h1>
      <p class="sub">Focos de voto a Lula en el segundo turno de 2022, medidos contra los municipios vecinos.</p>
      <div class="duo">
        <div class="izq">
          <div class="dato"><b>{f2(mg['I'])}</b><span>índice de Moran; 0 sería una distribución al azar y 1, agrupamiento total</span></div>
          <div class="dato"><b style="color:{LULA}">{f0(cl['High-High'])}</b><span>municipios en focos de voto a Lula</span></div>
          <div class="dato"><b style="color:{FLAVIO}">{f0(cl['Low-Low'])}</b><span>en focos de voto a Bolsonaro</span></div>
          <p class="nota">Un foco es un municipio que vota como sus vecinos y forma con ellos un bloque que el azar no explica.</p>
        </div>
        <div class="der"><img src="lisa.png"></div>
      </div>
      <div class="fuente">LISA (Moran local) sobre el % de Lula, 999 permutaciones, p &lt; 0,01. En gris, municipios sin patrón significativo. TSE 2022; cálculo en R (rgeoda, spdep).</div>
    """))

    # 5 · GWR
    gw = esp["gwr"]
    cu = gw["coef_por_uf"]["alfabetizacion"]
    cmap = LinearSegmentedColormap.from_list("gw", [VIO, "#B9A8D6", "#EDE6DA", "#E6C78E", OCRE])
    norm = TwoSlopeNorm(vcenter=0, vmin=-14, vmax=6)
    col = [GRIS_MAPA if pd.isna(x) else to_hex(cmap(norm(np.clip(x, -14, 6)))) for x in mun_esp["gwr_alfabetizacion"]]
    mapa_png(mun_esp, col, "gwr.png", 1300)
    paginas.append(lamina(5, f"""
      <div class="kicker">Territorio y Censo</div>
      <h1>La alfabetización no pesa igual en todo Brasil</h1>
      <p class="sub">Cuánto cambia el voto a Lula por cada desvío estándar más de alfabetización, según el lugar (2022).</p>
      <div class="duo">
        <div class="izq">
          <div class="dato"><b style="color:{VIO}">{sig(cu['SC'])}</b><span>puntos en Santa Catarina</span></div>
          <div class="dato"><b style="color:{VIO}">{sig(cu['RJ'])}</b><span>en Rio de Janeiro</span></div>
          <div class="dato"><b style="color:{OCRE}">{sig(cu['AM'])}</b><span>en Amazonas</span></div>
          <p class="nota">Un modelo único para todo el país da {sig(gw['coef_ols']['z_alfabetizacion'])} puntos y explica el {round(gw['r2_ols'] * 100)}% de la variación.
          Si el efecto puede cambiar de un lugar a otro (GWR), explica el {round(gw['r2_gwr'] * 100)}%.</p>
        </div>
        <div class="der"><img src="gwr.png"></div>
      </div>
      <div class="ley" style="justify-content:flex-end">Resta votos a Lula<span class="grad" style="background:linear-gradient(90deg,{VIO},#EDE6DA,{OCRE})"></span>Suma</div>
      <div class="fuente">Regresión geográficamente ponderada, kernel bisquare adaptativo ({gw['vecinos']} vecinos), {f0(gw['n'])} municipios. Controles: población negra y parda, baños, mayores de 60 y urbanización. Cifras por estado: promedio de los coeficientes locales. TSE 2022, IBGE Censo 2022.</div>
    """))

    # 6 · Minas
    pf_mg, pl_mg = pct_uf(conteo, "mg")
    mg_g = mun[mun.uf == "MG"]
    mapa_png(mg_g, colores_voto(mg_g["lula_2026"]), "minas.png", 1100, borde_uf=False)
    filas_t = "".join(f'<tr><td class="a">{a}</td><td>{n}</td><td class="r">presidente</td></tr>' for a, n in MINAS_HISTORIA)
    paginas.append(lamina(6, f"""
      <div class="kicker">Minas Gerais</div>
      <h1>Desde 1989, quien ganó Minas en primera vuelta llegó a la presidencia</h1>
      <p class="sub">Nueve de nueve. El 4 de octubre Minas votó a Flávio Bolsonaro: {f1(pf_mg)}% contra {f1(pl_mg)}% de Lula.</p>
      <div class="duo">
        <div class="izq" style="width:370px">
          <table>{filas_t}<tr class="hoy"><td class="a">2026</td><td>Flávio</td><td class="r">balotaje 25/10</td></tr></table>
          <p class="nota">El norte de Minas vota como el Nordeste; el sur, como São Paulo. Nueve casos son pocos: la regularidad puede romperse.</p>
        </div>
        <div class="der"><img src="minas.png"></div>
      </div>
      <div class="fuente">Ganador en Minas en la 1ª vuelta; 1994 y 1998 se definieron en vuelta única. TSE por sección 2018-2026; Wikipedia y Gazeta do Povo para 1989-2014. Mapa: 1ª vuelta 2026 por municipio.</div>
    """))

    # 7 · método
    secciones = sum(r["secciones"] for r in conteo["por_uf"].values())
    paginas.append(lamina(7, f"""
      <div class="kicker">Cómo se hizo</div>
      <h1>Datos públicos, métodos conocidos, todo reproducible</h1>
      <dl>
        <dt>Resultados</dt><dd>TSE: {f0(secciones)} secciones electorales en 2026, leídas durante el conteo, y resultados por sección de 2018 y 2022.</dd>
        <dt>Territorio</dt><dd>IBGE, Censo 2022 por setor censitário, cruzado con cada local de votación.</dd>
        <dt>Encuestas</dt><dd>Promedio ponderado por tamaño de muestra, fecha y desempeño histórico de cada encuestadora; 10.000 simulaciones Montecarlo.</dd>
        <dt>Espacial</dt><dd>Autocorrelación (Moran, LISA, Getis-Ord Gi*), regresión geográficamente ponderada y regionalización SKATER.</dd>
        <dt>Herramientas</dt><dd>Python (pandas, geopandas) y R (spdep, rgeoda, GWmodel).</dd>
        <dt>Próximo</dt><dd>Balotaje del 25 de octubre: el modelo se recalibra con el resultado de la primera vuelta.</dd>
      </dl>
      <div class="cierre"><img src="{LOGO_V.as_uri()}">
        <div><b>Atlas Analytics</b><br>Análisis electoral y territorial<br>atlas-analytics.site</div></div>
    """))

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil 2026</title>'
            f'<style>{CSS}</style></head><body>{"".join(paginas)}</body></html>')
    out = BUILD / "carrusel.html"
    out.write_text(html, encoding="utf-8")
    return out


def imprimir(html):
    chrome = next((c for c in CHROME if Path(c).exists()), None)
    if chrome is None:
        raise FileNotFoundError("No se encontró Chrome/Edge para imprimir el PDF")
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--allow-file-access-from-files", f"--print-to-pdf={PDF}", html.as_uri()],
                       capture_output=True, text=True)
    if r.returncode != 0 or not PDF.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    JPG.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    for i, p in enumerate(doc, 1):
        z = 1080 / p.rect.width
        out = JPG / f"{i:02d}.jpg"
        p.get_pixmap(matrix=fitz.Matrix(z, z)).save(out, jpg_quality=94)
        print(out)
    print(PDF, f"({doc.page_count} páginas)")


def main():
    imprimir(armar_html(*cargar()))


if __name__ == "__main__":
    main()
