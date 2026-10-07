"""
src/viz/brief_congreso_pdf.py

Brief "El Congreso que viene" en PDF con la identidad de Atlas Analytics
(mismo formato que src/viz/brief_pdf.py). Lee la última corrida de
src/models/congreso_2026.py.

Output: reports/briefs/ATLAS_Brasil_Congreso_<fecha>.pdf
        (HTML y figuras en reports/briefs/_build_congreso/, fuera de git)

Uso:
    python -m src.viz.brief_congreso_pdf [--fecha 2026-10-07]
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

from src.models.congreso_2026 import SALIDA_DIR as CONGRESO_DIR
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.brief_pdf import (BRIEFS, CHROME, COL, CSS_MARCA, FAM, INK, MUTED, PORTADA, Documento, f0, fig, fuente,
                               insight, kpi, limpiar, pe, tabla, ultima)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_congreso"
ORDEN = ["direita_bolsonarista", "centrao", "centro_liberal", "gobierno_lula", "sin_alineamiento"]
UMB_ET = {"mayoria": "Mayoría", "pec_3_5": "3/5 (enmienda)", "dos_tercios": "2/3"}


def guardar(f, nombre):
    f.savefig(BUILD / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(f)


def fig_pronostico(C: dict, casa: str, nombre: str, tope: int) -> None:
    pv = C["pronostico_vs_resultado"]
    fams = [f for f in ORDEN if f in pv]
    f, ax = plt.subplots(figsize=(6.6, 3.2))
    for i, fa in enumerate(fams):
        d = pv[fa][casa]
        ax.plot([d["p10"], d["p90"]], [i, i], color=COL[fa], lw=7, alpha=0.25, solid_capstyle="round", zorder=1)
        ax.plot([d["mediana"]] * 2, [i - 0.22, i + 0.22], color=COL[fa], lw=2, zorder=2)
        ax.scatter(d["real"], i, s=70, color=COL[fa], edgecolors="white", linewidths=1.2, zorder=3)
        ax.text(max(d["real"], d["p90"]) + tope * 0.015, i, f"{d['real']}", va="center", fontsize=9, weight="bold", color=INK)
    ax.set_yticks(range(len(fams)), [FAM[f] for f in fams], fontsize=8.5)
    ax.set_ylim(len(fams) - 0.5, -0.6)
    ax.set_xlim(0, tope)
    limpiar(ax, grid="x")
    guardar(f, nombre)


def fig_gobernabilidad(C: dict) -> None:
    U = C["umbrales"]
    f, axes = plt.subplots(1, 2, figsize=(10.4, 3.6))
    filas = [(pres, c) for pres in ("flavio", "lula") for c in C["gobernabilidad"][pres]]
    etq = [("Flávio · " if p == "flavio" else "Lula · ") + c["coalicion"] for p, c in filas]
    for ax, casa in zip(axes, ("camara", "senado")):
        y = np.arange(len(filas))
        for i, (p, c) in enumerate(filas):
            fams = c["familias"]
            x0 = 0
            for fa in fams:
                n = C["bancas"][casa].get(fa, 0)
                ax.barh(i, n, left=x0, color=COL[fa], height=0.6, edgecolor="white", linewidth=0.8)
                x0 += n
            ax.text(x0 + U[casa]["total"] * 0.01, i, str(x0), va="center", fontsize=8.5, weight="bold", color=INK)
        for k, ls, ha, dx in (("mayoria", "--", "right", -0.008), ("pec_3_5", "-", "left", 0.008)):
            ax.axvline(U[casa][k], color=INK, lw=1, ls=ls)
            ax.text(U[casa][k] + dx * U[casa]["total"], -0.95, f"{UMB_ET[k]}: {U[casa][k]}", ha=ha, fontsize=7.5, color=INK)
        ax.set_yticks(y, etq if casa == "camara" else [""] * len(y), fontsize=8.5)
        ax.set_ylim(len(filas) - 0.5, -1.3)
        ax.set_xlim(0, U[casa]["total"])
        ax.axhline(2.5, color="#DDDDDD", lw=1)
        ax.set_title("Câmara dos Deputados (513)" if casa == "camara" else "Senado Federal (81)", fontsize=9,
                     loc="left", weight="bold", color=INK, pad=14)
        limpiar(ax, grid="x")
    f.tight_layout()
    guardar(f, "gobernabilidad.svg")


CSS_EXTRA = """
.kpis { margin-bottom:.8cm; } .kpis .kpi-v { font-size:22pt; }
.kpi-l { font-size:9pt; } .kpi-n { font-size:8pt; }
.tesis { gap:.75cm 1cm; }
.t h3 { font-size:11.5pt; } .t p { font-size:9.8pt; line-height:1.42; } .t-n { font-size:19pt; }
.insight { font-size:9.6pt; line-height:1.4; padding:.28cm .36cm; margin:.24cm 0; }
table { font-size:9.2pt; } th { font-size:7.8pt; } td { padding:.15cm .2cm; }
.fuente { font-size:7.6pt; }
.nota-metodo h3 { font-size:10pt; } .nota-metodo p { font-size:9.2pt; line-height:1.45; }
h3.sub { font-size:10.5pt; margin:0 0 .2cm; }
.reco { margin-bottom:.6cm; } .reco h3 { font-size:11pt; } .reco p { font-size:9.6pt; line-height:1.42; }
.fig-prono { max-height:7.6cm; } .fig-gob { max-height:8.6cm; }
"""


def construir(fecha: date) -> Path:
    run = ultima(CONGRESO_DIR)
    C = json.loads((run / "resumen.json").read_text(encoding="utf-8"))
    partidos = pd.read_csv(run / "bancas_partido.csv", index_col=0)
    B, pv, U = C["bancas"], C["pronostico_vs_resultado"], C["umbrales"]
    gf, gl = C["gobernabilidad"]["flavio"], C["gobernabilidad"]["lula"]
    pl_c, pl_s = int(partidos.loc["PL", "camara"]), B["senado"]["direita_bolsonarista"]
    pl_sen_elect = int(partidos.loc["PL", "senado_electos"])
    pt_c = int(partidos.loc["PT", "camara"])
    fc, fs = gf[1]["camara"]["bancas"], gf[1]["senado"]["bancas"]
    lc, ls_ = gl[1]["camara"]["bancas"], gl[1]["senado"]["bancas"]
    lc3, ls3 = gl[2]["camara"]["bancas"], gl[2]["senado"]["bancas"]
    dir_c, dir_s = pv["direita_bolsonarista"]["camara"], pv["direita_bolsonarista"]["senado"]
    cen_c, cen_s = pv["centrao"]["camara"], pv["centrao"]["senado"]
    gob_c, gob_s = pv["gobierno_lula"]["camara"], pv["gobierno_lula"]["senado"]

    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "figs").mkdir(parents=True)
    fig_pronostico(C, "camara", "camara.svg", 300)
    fig_pronostico(C, "senado", "senado.svg", 45)
    fig_gobernabilidad(C)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")
    D = Documento("Atlas Analytics · Brasil 2026")
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"

    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>El Congreso que viene</h1>
    <div class="p-sub">Câmara y Senado después del 4 de octubre: quién ganó bancas, cuánto acertó nuestro modelo y con qué
      mayorías gobernaría cada candidato a partir de 2027.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Datos</span> resultado oficial del TSE: 513 diputados y 54 senadores electos el 4/10</div>
      <div><span>Senado</span> 27 senadores que siguen hasta 2031, por partido (API del Senado al 1/10)</div>
      <div><span>Modelo</span> Montecarlo de bancas del 1/10, 10.000 simulaciones, sin encuestas</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    tesis = [
        ("El PL es la primera fuerza en las dos cámaras",
         f"{pl_c} diputados y {pl_s} senadores. En la Câmara el segundo partido es el PT, con {pt_c}. En el Senado ganó "
         f"{pl_sen_elect} de las 54 bancas en juego."),
        ("Flávio + Centrão alcanza para reformar la Constitución",
         f"Juntos suman {fc} diputados y {fs} senadores: por encima de los 3/5 que pide una enmienda en las dos cámaras "
         f"({U['camara']['pec_3_5']} y {U['senado']['pec_3_5']})."),
        ("Lula necesitaría al Centrão y al centro para lo mismo",
         f"Con el Centrão tendría {lc} diputados pero {ls_} senadores: mayoría simple en el Senado, no los 3/5. Sumando al "
         f"centro liberal llega a {ls3}."),
        ("El Centrão sigue decidiendo, pero pesa menos",
         f"{cen_c['real']} diputados y {cen_s['real']} senadores, menos de lo que esperábamos ({cen_c['mediana']:.0f} y "
         f"{cen_s['mediana']:.0f}). Sin él, ningún presidente llega a la mayoría."),
        ("Nuestro modelo subestimó al bolsonarismo, como las encuestas",
         f"Le dábamos al PL {dir_c['mediana']:.0f} diputados (sacó {dir_c['real']}) y {dir_s['mediana']:.0f} senadores "
         f"(llegó a {dir_s['real']}, más que en cualquiera de las 10.000 simulaciones)."),
        ("Acertó la base de Lula y el centro",
         f"Gobierno Lula: {gob_c['real']} diputados contra {gob_c['mediana']:.0f} pronosticados. Centro liberal: "
         f"{pv['centro_liberal']['camara']['real']} contra {pv['centro_liberal']['camara']['mediana']:.0f}."),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(str(pl_c), "diputados del PL", f"PT: {pt_c}")
              + kpi(str(pl_s), "senadores del PL", f"{pl_sen_elect} electos el 4/10")
              + kpi(f"{fc} · {fs}", "Flávio + Centrão", "diputados · senadores")
              + kpi(f"{lc} · {ls_}", "Lula + Centrão", "diputados · senadores")
              + kpi(f"{U['camara']['pec_3_5']} · {U['senado']['pec_3_5']}", "para una enmienda", "3/5 de cada cámara")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(tesis))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="El bolsonarismo sale del 4/10 como primera fuerza del Congreso",
             bajada="Los seis hallazgos del brief.",
             pie="Bancas por família política (config/familias_partidarias.yaml): partidos agrupados como estaban en 2026.")

    # Câmara
    top = partidos.sort_values("camara", ascending=False).head(12)
    filas = [[p, FAM.get(r.familia, r.familia), str(r.camara)] for p, r in top.iterrows()]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("camara.svg", "fig fig-prono")
              + fuente("Punto: diputados electos. Barra: rango p10–p90 del Montecarlo del 1/10. Raya: mediana pronosticada.")
              + insight(f"<b>El PL sacó {dir_c['real']} bancas, {dir_c['real'] - dir_c['mediana']:.0f} más que la mediana del "
                        f"modelo</b>, aunque dentro de su rango ({dir_c['p10']:.0f}–{dir_c['p90']:.0f}). El modelo partía del voto "
                        "de 2022 y no podía ver el crecimiento del 4/10.")
              + insight(f"<b>El Centrão quedó en {cen_c['real']}</b>, {cen_c['mediana'] - cen_c['real']:.0f} menos que la mediana "
                        f"del modelo ({cen_c['mediana']:.0f}): casi lo mismo que el PL sacó de más.")
              + "</div><div>"
              + '<h3 class="sub">Las 12 bancadas más grandes</h3>' + tabla(["Partido", "Família", "Diputados"], filas, num=(2,))
              + "</div></div>")
    D.pagina(cuerpo, kicker="1 · CÂMARA DOS DEPUTADOS", titulo=f"El PL tendrá la bancada más grande: {pl_c} de 513 diputados",
             bajada="Diputados electos por família contra el pronóstico del 1/10, y las mayores bancadas por partido.",
             pie="TSE, resultado oficial por UF (elección 6259, cargo Deputado Federal). Bancadas al día de la elección: cambian con "
                 "las migraciones de partido.")

    # Senado
    filas = [[FAM[f], str(B["senado_en_juego"].get(f, 0)), str(B["senado_siguen"].get(f, 0)), f"<b>{B['senado'].get(f, 0)}</b>"]
             for f in ORDEN if B["senado"].get(f, 0) or B["senado_en_juego"].get(f, 0)]
    sen = pd.DataFrame(C["senado_electos"])
    pl_ufs = ", ".join(sorted(sen[sen["partido"] == "PL"]["uf"].unique()))
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("senado.svg", "fig fig-prono")
              + fuente("Total del Senado (81): electos el 4/10 más los 27 que siguen. Punto: resultado. Barra: p10–p90 del modelo.")
              + insight(f"<b>El PL ganó {pl_sen_elect} de las 54 bancas</b> y llega a {pl_s} senadores. El modelo le daba "
                        f"{dir_s['mediana']:.0f} (rango {dir_s['p10']:.0f}–{dir_s['p90']:.0f}): el resultado quedó por encima de "
                        "todas las simulaciones.")
              + "</div><div>"
              + tabla(["Família", "Electos 4/10", "Siguen", "Total"], filas, num=(1, 2, 3))
              + insight(f"<b>Dónde ganó el PL:</b> {pl_ufs}.")
              + insight(f"<b>{pl_s} senadores alcanzan para bloquear un juicio político</b> (hacen falta "
                        f"{U['senado']['dos_tercios']} votos para condenar a un presidente). Para frenar una enmienda hacen "
                        f"falta {U['senado']['bloqueo_pec']}.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="2 · SENADO FEDERAL", titulo=f"En el Senado, el PL ganó {pl_sen_elect} de las 54 bancas en juego",
             bajada="Senadores por família: electos el 4/10, los que siguen hasta 2031 y el total contra el pronóstico.",
             pie="Los que siguen: partido según la API del Senado al 1/10. Si un senador gana una gobernación el 25/10, asume "
                 "su suplente (Alan Rick, AC, está en el balotaje).")

    # Gobernabilidad
    def fila_g(pres, c):
        cc, ss = c["camara"], c["senado"]
        si = lambda b: "sí" if b else "no"
        return [("Flávio" if pres == "flavio" else "Lula"), c["coalicion"], str(cc["bancas"]), si(cc["mayoria"]), si(cc["pec_3_5"]),
                str(ss["bancas"]), si(ss["mayoria"]), si(ss["pec_3_5"])]
    filas = [fila_g(p, c) for p in ("flavio", "lula") for c in C["gobernabilidad"][p]]
    cuerpo = (fig("gobernabilidad.svg", "fig fig-gob")
              + fuente("Bancas de cada coalición por família. Línea punteada: mayoría absoluta. Línea llena: 3/5, lo que pide una "
                       "enmienda constitucional en dos votaciones en cada cámara.")
              + '<div class="dos-col"><div>'
              + tabla(["Presidente", "Coalición", "Câmara", "Mayoría", "3/5", "Senado", "Mayoría", "3/5"], filas, num=(2, 5))
              + "</div><div>"
              + insight(f"<b>Con Flávio, el Centrão completa una supermayoría:</b> {fc} diputados y {fs} senadores, por encima "
                        "de los 3/5 en las dos cámaras sin necesitar al centro liberal.")
              + insight(f"<b>Con Lula, el Senado es el límite:</b> aun con el Centrão tendría {ls_} senadores, mayoría simple "
                        f"pero no los {U['senado']['pec_3_5']} de una enmienda.")
              + insight(f"<b>Y el Centrão tendría la llave de un juicio político:</b> con el PL suma {fs} senadores (condenar pide "
                        f"{U['senado']['dos_tercios']}) y {fc} diputados (admitirlo pide {U['camara']['dos_tercios']}; con el "
                        "centro liberal se supera).")
              + "</div></div>")
    D.pagina(cuerpo, kicker="3 · GOBERNABILIDAD", titulo="Flávio con el Centrão tendría supermayoría; Lula, solo mayoría simple en el Senado",
             bajada="Bancas de cada coalición posible del próximo gobierno contra los umbrales de cada cámara.",
             pie="Coaliciones por família: supuesto de que cada família vota en bloque. El Centrão históricamente vota con quien "
                 "gobierna, pero cobra por cada votación.")

    # Método
    cuerpo = ('<div class="dos-col"><div class="nota-metodo">'
              '<h3>De dónde sale cada cosa</h3>'
              '<p><b>Electos.</b> Divulgación oficial del TSE del 4/10 por UF (elección estadual 6259), Deputado Federal y Senador, '
              'al 100 % de las secciones.</p>'
              '<p><b>Famílias.</b> Los partidos se agrupan como en los modelos del 1/10 (config/familias_partidarias.yaml, año '
              '2026, validada el 1/10): base de gobierno, Centrão, derecha bolsonarista, centro liberal.</p>'
              '<p><b>Pronóstico.</b> Montecarlo de bancas del 1/10 sobre el voto de 2022 con los partidos agrupados como hoy, '
              'sin encuestas. Câmara: reparto proporcional por UF con cláusula de barrera. Senado: 54 bancas en juego y 27 '
              'que siguen.</p></div><div class="nota-metodo">'
              '<h3>Límites</h3>'
              '<p>Las bancadas cambian después de la elección: migraciones de partido, federaciones y la ventana partidaria. '
              'Una família no vota en bloque, y el Centrão menos que ninguna.</p>'
              '<p>El modelo del 1/10 no usaba el resultado del 4/10: el error en el PL es el mismo que tuvieron las encuestas '
              'presidenciales, el bolsonarismo creció más de lo que mostraba la base 2022.</p></div></div>')
    D.pagina(cuerpo, kicker="MÉTODO", titulo="Cómo se hizo",
             pie=f"Atlas Analytics · {fecha_txt} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · El Congreso que viene</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "brief.html").write_text(html, encoding="utf-8")
    chrome = next((c for c in CHROME if Path(c).exists()), None)
    pdf = BRIEFS / f"ATLAS_Brasil_Congreso_{fecha:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "brief.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas)", pdf.relative_to(ROOT).as_posix(), len(D.paginas))
    return pdf


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    construir(ap.parse_args(argv).fecha)


if __name__ == "__main__":
    main()
