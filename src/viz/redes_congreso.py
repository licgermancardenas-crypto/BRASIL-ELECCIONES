# -*- coding: utf-8 -*-
"""Piezas para redes: el Congreso que sale del 4/10/2026.

  · LinkedIn (línea editorial marfil, como carrusel_linkedin.py): 6 láminas
      carrusel_congreso_<fecha>/NN.jpg y ATLAS_carrusel_congreso_<fecha>.pdf (+ .txt)
  · Instagram (marca neón, como post_pronostico.py):
      post_congreso_<fecha>.jpg (+ .txt)

Lee la última corrida de src/models/congreso_2026.py.

    python -m src.viz.redes_congreso [--fecha 2026-10-07]
"""
import argparse
import io
import json
import subprocess
from datetime import date
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import src.viz.carrusel_linkedin as cl
from src.models.congreso_2026 import SALIDA_DIR as CONGRESO_DIR
from src.viz.brief_pdf import COL, FAM
from src.viz.post_pronostico import BLANCO, BOLSO, H, LULA, NEON, SAFE_X, SALIDA, TEXTO, W, _f, fondo, grano
from src.viz.redes_balotaje import cabecera, cifras, pie, titular

# de izquierda a derecha en el hemiciclo
ORDEN = ["gobierno_lula", "esquerda_independente", "sin_alineamiento", "centro_liberal", "centrao", "direita_bolsonarista"]
CORTO = {"gobierno_lula": "Base de Lula", "centro_liberal": "Centro liberal", "centrao": "Centrão",
         "direita_bolsonarista": "PL y aliados", "sin_alineamiento": "Sin alineamiento", "esquerda_independente": "Otra izquierda"}
f1, f0 = cl.f1, cl.f0


def cargar() -> dict:
    run = sorted(p.parent for p in CONGRESO_DIR.glob("*/meta.json"))[-1]
    C = json.loads((run / "resumen.json").read_text(encoding="utf-8"))
    C["partidos"] = pd.read_csv(run / "bancas_partido.csv", index_col=0)
    return C


# --------------------------------------------------------------------------- hemiciclo
def asientos(n: int, filas: int, r0: float = 0.42) -> np.ndarray:
    """Coordenadas (x, y) de n bancas en semicírculos concéntricos, ordenadas de izquierda a derecha."""
    radios = np.linspace(r0, 1, filas)
    cap = radios / radios.sum() * n
    por_fila = np.floor(cap).astype(int)
    for i in np.argsort(-(cap - por_fila))[: n - por_fila.sum()]:
        por_fila[i] += 1
    pts = []
    for r, k in zip(radios, por_fila):
        ang = np.linspace(np.pi, 0, k) if k > 1 else np.array([np.pi / 2])
        pts += [(a, r * np.cos(a), r * np.sin(a)) for a in ang]
    pts.sort(key=lambda t: -t[0])
    return np.array([(x, y) for _, x, y in pts])


def hemiciclo(bancas: dict, total: int, filas: int, ax, tam: float, fondo_claro: bool, umbrales=()):
    pos = asientos(total, filas)
    colores = [COL[f] for f in ORDEN for _ in range(int(bancas.get(f, 0)))]
    colores += ["#BBBBBB"] * (total - len(colores))
    ax.scatter(pos[:, 0], pos[:, 1], s=tam, c=colores, linewidths=0)
    ax.set_aspect("equal")
    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-0.08, 1.05)
    ax.axis("off")
    for u in umbrales:   # marca radial de la banca número u (desde la izquierda)
        x, y = pos[u - 1]
        ang = np.arctan2(y, x)
        ax.plot([0.36 * np.cos(ang), 1.05 * np.cos(ang)], [0.36 * np.sin(ang), 1.05 * np.sin(ang)],
                color="#1D1631" if fondo_claro else "white", lw=1, ls=(0, (3, 2)))


# --------------------------------------------------------------------------- LinkedIn
def fig_hemiciclo_svg(C, casa, nombre, total, filas, tam, umbrales=()):
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    hemiciclo(C["bancas"][casa], total, filas, ax, tam, True, umbrales)
    return cl.guardar_svg(fig, nombre)


def fig_partidos(C):
    p = C["partidos"].sort_values("camara", ascending=False).head(10)[::-1]
    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    for i, (sig, r) in enumerate(p.iterrows()):
        ax.barh(i, r.camara, color=COL.get(r.familia, "#999999"), height=0.66)
        ax.text(r.camara + 2, i, str(r.camara), va="center", fontsize=14, weight="bold", color=cl.TINTA)
    ax.set_yticks(range(len(p)), p.index, fontsize=14, color=cl.TINTA)
    ax.set_xticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "partidos.svg")


def fig_coaliciones(C):
    U = C["umbrales"]
    filas = [("Flávio + Centrão", C["gobernabilidad"]["flavio"][1]), ("Lula + Centrão", C["gobernabilidad"]["lula"][1]),
             ("Lula + Centrão + centro", C["gobernabilidad"]["lula"][2])]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.4))
    for ax, casa, tit in zip(axes, ("camara", "senado"), ("Câmara (513)", "Senado (81)")):
        for i, (et, c) in enumerate(filas):
            x0 = 0
            for fa in c["familias"]:
                n = C["bancas"][casa].get(fa, 0)
                ax.barh(i, n, left=x0, color=COL[fa], height=0.6, edgecolor=cl.PAPEL, linewidth=1)
                x0 += n
            ax.text(x0 + U[casa]["total"] * 0.02, i, str(x0), va="center", fontsize=14, weight="bold", color=cl.TINTA)
        ax.axvline(U[casa]["pec_3_5"], color=cl.TINTA, lw=1.4)
        ax.text(U[casa]["pec_3_5"], -0.75, f"3/5: {U[casa]['pec_3_5']}", ha="center", fontsize=12, color=cl.TINTA, weight="bold")
        ax.set_yticks(range(len(filas)), [et for et, _ in filas] if casa == "camara" else [""] * 3, fontsize=13, color=cl.TINTA)
        ax.set_ylim(len(filas) - 0.5, -1.1)
        ax.set_xlim(0, U[casa]["total"] * 1.12)
        ax.set_xticks([])
        ax.set_title(tit, fontsize=13, color=cl.MUTED, loc="left", pad=24)
        cl.limpiar(ax)
    fig.tight_layout()
    return cl.guardar_svg(fig, "coaliciones.svg")


def fig_pronostico(C):
    pv = C["pronostico_vs_resultado"]
    fams = ["direita_bolsonarista", "centrao", "gobierno_lula", "centro_liberal"]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.4))
    for ax, casa, tope, tit in zip(axes, ("camara", "senado"), (300, 45), ("Câmara", "Senado")):
        for i, fa in enumerate(fams):
            d = pv[fa][casa]
            ax.plot([d["p10"], d["p90"]], [i, i], color=COL[fa], lw=9, alpha=0.25, solid_capstyle="round")
            ax.plot([d["mediana"]] * 2, [i - 0.25, i + 0.25], color=COL[fa], lw=2.5)
            ax.scatter(d["real"], i, s=110, color=COL[fa], edgecolors=cl.PAPEL, linewidths=1.5, zorder=3)
            ax.text(max(d["real"], d["p90"]) + tope * 0.03, i, str(d["real"]), va="center", fontsize=13, weight="bold",
                    color=cl.TINTA)
        ax.set_yticks(range(len(fams)), [CORTO[f] for f in fams] if casa == "camara" else [""] * len(fams), fontsize=13,
                      color=cl.TINTA)
        ax.set_ylim(len(fams) - 0.5, -0.7)
        ax.set_xlim(0, tope * 1.1)
        ax.tick_params(axis="x", labelsize=11)
        ax.set_title(tit, fontsize=13, color=cl.MUTED, loc="left")
        cl.limpiar(ax)
    fig.tight_layout()
    return cl.guardar_svg(fig, "pronostico.svg")


def ley_familias(fams):
    return '<div class="ley">' + "".join(f'<span><i style="background:{COL[f]};border-radius:50%"></i>{CORTO[f]}</span>'
                                         for f in fams) + "</div>"


def carrusel(C, fecha, build, pdf, jpg_dir):
    cl.BUILD = build
    build.mkdir(parents=True, exist_ok=True)
    total = 6
    lam = lambda n, cuerpo, clase="": (f'<section class="l {clase}"><div class="top"><img src="{cl.LOGO.as_uri()}">'
                                       f'<span class="folio">{n:02d} / {total:02d}</span></div>{cuerpo}</section>')
    B, U, pv = C["bancas"], C["umbrales"], C["pronostico_vs_resultado"]
    P = C["partidos"]
    pl_c, pt_c = int(P.loc["PL", "camara"]), int(P.loc["PT", "camara"])
    pl_s, pl_se = B["senado"]["direita_bolsonarista"], int(P.loc["PL", "senado_electos"])
    gf, gl = C["gobernabilidad"]["flavio"], C["gobernabilidad"]["lula"]
    fams_cam = [f for f in ORDEN if B["camara"].get(f, 0)]
    fams_sen = [f for f in ORDEN if B["senado"].get(f, 0)]
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"
    pag = []

    hemi = fig_hemiciclo_svg(C, "camara", "hemi_camara.svg", 513, 12, 40)
    pag.append(lam(1, f"""
      <div class="kicker">Brasil · Congreso 2027-2031</div>
      <h1>El Congreso que <em>viene</em></h1>
      <p class="sub">Quién ganó bancas el 4 de octubre y con qué mayorías gobernaría cada candidato.</p>
      <div class="fig"><img src="{hemi}"></div>
      {ley_familias(fams_cam)}
      <div class="fuente">Câmara dos Deputados, 513 bancas por família política. TSE, resultado oficial · Atlas Analytics, {fecha_txt}.</div>
    """))
    pag.append(lam(2, f"""
      <div class="kicker">Câmara dos Deputados</div>
      <h1>El PL tendrá la bancada más grande: {pl_c} diputados</h1>
      <p class="sub">Las diez bancadas más grandes que salen de la elección.</p>
      <div class="fig"><img src="{fig_partidos(C)}"></div>
      <div class="cifras">
        <div><b>{pl_c}</b><span>diputados del PL; el PT, segundo, tiene {pt_c}</span></div>
        <div><b>{B['camara']['centrao']}</b><span>diputados del Centrão (UNIÃO, PSD, PP, Republicanos, MDB y otros)</span></div>
      </div>
      <div class="fuente">TSE, Deputado Federal por UF. Bancadas al día de la elección: cambian con las migraciones de partido.</div>
    """))
    hemi_s = fig_hemiciclo_svg(C, "senado", "hemi_senado.svg", 81, 5, 190)
    pag.append(lam(3, f"""
      <div class="kicker">Senado Federal</div>
      <h1>En el Senado, el PL ganó {pl_se} de las 54 bancas en juego</h1>
      <p class="sub">Con los 27 senadores que siguen hasta 2031, queda con {pl_s} de 81.</p>
      <div class="fig"><img src="{hemi_s}"></div>
      {ley_familias(fams_sen)}
      <div class="cifras">
        <div><b>{pl_s}</b><span>senadores del PL: alcanzan para frenar un juicio político (condenar pide {U['senado']['dos_tercios']})</span></div>
        <div><b>{B['senado']['centrao']}</b><span>senadores del Centrão</span></div>
        <div><b>{B['senado']['gobierno_lula']}</b><span>de la base de Lula</span></div>
      </div>
      <div class="fuente">TSE, Senador por UF; senadores que siguen según la API del Senado al 1/10.</div>
    """))
    pag.append(lam(4, f"""
      <div class="kicker">Gobernabilidad</div>
      <h1>Con el Centrão, Flávio tendría 3/5 en las dos cámaras. Lula, no</h1>
      <p class="sub">Bancas de cada coalición contra los 3/5 que pide una enmienda constitucional.</p>
      <div class="fig"><img src="{fig_coaliciones(C)}"></div>
      <p class="txt">Flávio y el Centrão suman <b>{gf[1]['camara']['bancas']} diputados y {gf[1]['senado']['bancas']} senadores</b>.
      Lula con el Centrão llegaría a {gl[1]['camara']['bancas']} diputados pero a {gl[1]['senado']['bancas']} senadores: mayoría
      simple en el Senado, no los {U['senado']['pec_3_5']} de una enmienda. Supone que cada bloque vota unido, y el Centrão
      no lo hace gratis.</p>
      <div class="fuente">Coaliciones por família política. Umbrales: Constitución Federal, art. 60 (enmiendas) y art. 52 (juicio político).</div>
    """))
    dc, ds = pv["direita_bolsonarista"]["camara"], pv["direita_bolsonarista"]["senado"]
    pag.append(lam(5, f"""
      <div class="kicker">Nuestro pronóstico</div>
      <h1>Nuestro modelo también subestimó al PL</h1>
      <p class="sub">Bancas por família: resultado (●) contra el pronóstico del 1 de octubre (rango y mediana).</p>
      <div class="fig"><img src="{fig_pronostico(C)}"></div>
      <p class="txt">Le dábamos al PL {dc['mediana']:.0f} diputados y sacó <b>{dc['real']}</b>; {ds['mediana']:.0f} senadores y llegó a
      <b>{ds['real']}</b>, más que en cualquiera de las 10.000 simulaciones. La base de Lula y el centro salieron casi exactos.
      El modelo partía del voto de 2022 y no podía ver el crecimiento del bolsonarismo, el mismo que no vieron las encuestas.</p>
      <div class="fuente">Montecarlo de bancas del 1/10/2026, sin encuestas: voto 2022 con los partidos agrupados como en 2026.</div>
    """))
    pag.append(lam(6, f"""
      <div class="kicker">Cómo se hizo</div>
      <h1>Resultados oficiales y una vara fija para agrupar partidos</h1>
      <dl>
        <dt>Electos</dt><dd>TSE: 513 diputados y 54 senadores electos el 4/10, por estado, al 100% de las secciones.</dd>
        <dt>Senado</dt><dd>27 senadores que siguen hasta 2031, con su partido según la API del Senado.</dd>
        <dt>Famílias</dt><dd>Los partidos se agrupan como en nuestros modelos del 1/10: base de Lula, Centrão, PL y aliados, centro liberal.</dd>
        <dt>Pronóstico</dt><dd>Montecarlo de bancas sobre el voto de 2022, publicado antes de la elección.</dd>
      </dl>
      <div class="cierre"><img src="{cl.LOGO_V.as_uri()}">
        <div><b>Atlas Analytics</b><br>Análisis electoral y territorial<br>atlas-analytics.site</div></div>
    """))
    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Congreso Brasil 2027</title>'
            f'<style>{cl.CSS}</style></head><body>{"".join(pag)}</body></html>')
    out = build / "carrusel.html"
    out.write_text(html, encoding="utf-8")
    chrome = next((c for c in cl.CHROME if Path(c).exists()), None)
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                        f"--print-to-pdf={pdf}", out.as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    jpg_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    for i, p in enumerate(doc, 1):
        z = 1080 / p.rect.width
        p.get_pixmap(matrix=fitz.Matrix(z, z)).save(jpg_dir / f"{i:02d}.jpg", jpg_quality=94)
    return doc.page_count


# --------------------------------------------------------------------------- Instagram
def post_instagram(C, salida):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    B, U = C["bancas"], C["umbrales"]
    P = C["partidos"]
    gf, gl = C["gobernabilidad"]["flavio"], C["gobernabilidad"]["lula"]
    cabecera(im, d, "BRASIL · CONGRESO 2027-2031")
    titular(d, ["EL PL, PRIMERA", "FUERZA DEL", "CONGRESO"],
            [f"{int(P.loc['PL', 'camara'])} diputados y {B['senado']['direita_bolsonarista']} senadores. Con el Centrão,",
             "Flávio tendría los 3/5 para reformar la Constitución."])
    fig, ax = plt.subplots(figsize=(9, 4.7), dpi=120)
    fig.patch.set_alpha(0)
    # 3/5 contado desde la derecha: lo que suman PL + Centrão
    hemiciclo(B["camara"], 513, 12, ax, 30, False, umbrales=(U["camara"]["total"] - U["camara"]["pec_3_5"] + 1,))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight")
    plt.close(fig)
    h = Image.open(buf).convert("RGBA")
    h = h.resize((820, round(h.height * 820 / h.width)), Image.LANCZOS)
    im.alpha_composite(h, ((W - 820) // 2, 512))
    d = ImageDraw.Draw(im, "RGBA")
    fams = [f for f in ORDEN if B["camara"].get(f, 0)]
    x = SAFE_X
    for f in fams:
        c = tuple(int(COL[f][i:i + 2], 16) for i in (1, 3, 5))
        d.ellipse([x, 946, x + 16, 962], fill=c)
        t = f"{CORTO[f]} {B['camara'][f]}"
        d.text((x + 24, 954), t, font=_f(r"C:\Windows\Fonts\arial.ttf", 19), fill=TEXTO, anchor="lm")
        x += 24 + d.textlength(t, font=_f(r"C:\Windows\Fonts\arial.ttf", 19)) + 26
    cifras(d, 1016, [(f"{gf[1]['camara']['bancas']} · {gf[1]['senado']['bancas']}", BOLSO, "Flávio + Centrão", "diputados · senadores"),
                     (f"{gl[1]['camara']['bancas']} · {gl[1]['senado']['bancas']}", LULA, "Lula + Centrão", "diputados · senadores"),
                     (f"{U['camara']['pec_3_5']} · {U['senado']['pec_3_5']}", NEON, "3/5 para una", "enmienda constitucional")])
    pie(d, ["Hemiciclo: Câmara dos Deputados, 513 bancas por família. Línea: 308 bancas desde la derecha (3/5).",
            "TSE, resultado oficial del 4/10; Senado con los 27 que siguen hasta 2031."])
    im.convert("RGB").save(salida, quality=95, subsampling=0)


def textos(C) -> tuple[str, str]:
    B, U, pv = C["bancas"], C["umbrales"], C["pronostico_vs_resultado"]
    P = C["partidos"]
    gf, gl = C["gobernabilidad"]["flavio"], C["gobernabilidad"]["lula"]
    dc, ds = pv["direita_bolsonarista"]["camara"], pv["direita_bolsonarista"]["senado"]
    li = f"""El 25 de octubre Brasil elige presidente, pero el Congreso con el que va a gobernar ya está definido.

El PL sale del 4 de octubre como primera fuerza en las dos cámaras: {int(P.loc['PL', 'camara'])} diputados, contra {int(P.loc['PT', 'camara'])} del PT, y {B['senado']['direita_bolsonarista']} senadores después de ganar {int(P.loc['PL', 'senado_electos'])} de las 54 bancas en juego.

La diferencia entre los dos candidatos se ve en el Senado. Flávio Bolsonaro con el Centrão sumaría {gf[1]['camara']['bancas']} diputados y {gf[1]['senado']['bancas']} senadores, por encima de los 3/5 que pide una enmienda constitucional en las dos cámaras. Lula con el Centrão llegaría a {gl[1]['camara']['bancas']} diputados pero a {gl[1]['senado']['bancas']} senadores: mayoría simple, no los {U['senado']['pec_3_5']} de una enmienda.

Una autocrítica: nuestro modelo del 1 de octubre le daba al PL {dc['mediana']:.0f} diputados y {ds['mediana']:.0f} senadores. Sacó {dc['real']} y {ds['real']}. Partía del voto de 2022 y no vio el crecimiento del bolsonarismo, el mismo error que tuvieron las encuestas. La base de Lula y el centro, en cambio, salieron casi exactos.

En el carrusel están los hemiciclos, las coaliciones y el método.

#Brasil2026 #CongresoNacional #AnálisisElectoral #DatosAbiertos"""
    ig = f"""El PL sale del 4 de octubre como primera fuerza del Congreso de Brasil: {int(P.loc['PL', 'camara'])} diputados y {B['senado']['direita_bolsonarista']} senadores.

Si gana Flávio Bolsonaro, con el Centrão tendría {gf[1]['camara']['bancas']} diputados y {gf[1]['senado']['bancas']} senadores: los 3/5 que pide una reforma constitucional en las dos cámaras. Si gana Lula, con el Centrão llegaría a {gl[1]['camara']['bancas']} diputados pero solo a {gl[1]['senado']['bancas']} senadores.

Fuente: TSE, resultado oficial.

#AtlasAnalytics #Brasil2026 #CongressoNacional #Elecciones #DataViz"""
    return li, ig


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    fecha = ap.parse_args(argv).fecha
    C = cargar()
    li, ig = textos(C)
    post = SALIDA / f"post_congreso_{fecha}.jpg"
    post_instagram(C, post)
    post.with_suffix(".txt").write_text(ig, encoding="utf-8")
    pdf = SALIDA / f"ATLAS_carrusel_congreso_{fecha}.pdf"
    n = carrusel(C, fecha, SALIDA / "_build_carrusel_congreso", pdf, SALIDA / f"carrusel_congreso_{fecha}")
    pdf.with_suffix(".txt").write_text(li, encoding="utf-8")
    print(post, pdf, n)


if __name__ == "__main__":
    main()
