"""
src/viz/informe_genero_edad_pdf.py

Informe "Sexo y edad en el balotaje" con la identidad de Atlas Analytics, a partir
de la última corrida de src/models/genero_edad_balotaje_2026.py.

Output: reports/briefs/ATLAS_Brasil_Genero_Edad_<fecha>.pdf

Uso:
    python -m src.viz.informe_genero_edad_pdf [--fecha 2026-10-15]
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

from src.models.genero_edad_balotaje_2026 import EDADES, SALIDA_DIR
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.brief_pdf import (BRIEFS, C_FLAVIO, C_LULA, CHROME, CSS_MARCA, INK, MUTED, PORTADA, VIO, Documento, f0,
                               f1, fig, fuente, insight, kpi, limpiar, tabla)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_genero_edad"
GRIS, GRIS_CLARO = "#8A8983", "#CFCBD6"
C_MUJER, C_HOMBRE = "#B5179E", "#3A0CA3"
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))
pc = lambda x: f1(x * 100) + " %"
sg2 = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.2f}".replace(".", ",")
plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none", "axes.edgecolor": "#BBBBBB",
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})


def guardar(f, nombre):
    f.savefig(BUILD / "figs" / nombre, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(f)


def fig_padron(R):
    p22, p26 = R["padron"]["2022"], R["padron"]["2026"]
    x = np.arange(len(EDADES))
    f, ax = plt.subplots(figsize=(6.2, 3.3))
    ax.bar(x - 0.2, [p22[e] * 100 for e in EDADES], 0.38, color=GRIS_CLARO, label="2022")
    ax.bar(x + 0.2, [p26[e] * 100 for e in EDADES], 0.38, color=VIO, label="2026")
    for i, e in enumerate(EDADES):
        ax.text(i + 0.2, p26[e] * 100 + 0.4, f1(p26[e] * 100), ha="center", fontsize=8, color=INK, weight="bold")
    ax.set_xticks(x, [e.replace("-", " a ").replace("+", " o más") for e in EDADES], fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.legend(frameon=False, fontsize=8.5)
    limpiar(ax)
    guardar(f, "padron.svg")


def fig_participacion(R):
    P = R["participacion"]
    grupos = ["mujeres", "hombres"] + EDADES
    etiq = ["Mujeres", "Hombres"] + [e.replace("-", "–").replace("+", " +") for e in EDADES]
    series = [("2022 · 1ª vuelta", "2022_1v", GRIS_CLARO), ("2022 · 2ª vuelta", "2022_2v", GRIS),
              ("2026 · 1ª vuelta", "2026_1v", VIO)]
    x = np.arange(len(grupos))
    f, ax = plt.subplots(figsize=(7.4, 3.5))
    for k, (lab, key, c) in enumerate(series):
        ax.bar(x + (k - 1) * 0.27, [P[key][g] * 100 for g in grupos], 0.26, color=c, label=lab)
    for i, g in enumerate(grupos):
        ax.text(i + 0.27, P["2026_1v"][g] * 100 + 0.8, f"{P['2026_1v'][g] * 100:.0f}", ha="center", fontsize=7.5,
                color=INK, weight="bold")
    ax.axvline(1.5, color="#DDDDDD", lw=1)
    ax.set_xticks(x, etiq, fontsize=8.8)
    ax.set_ylim(50, 92)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    limpiar(ax)
    guardar(f, "participacion.svg")


def fig_genero(R):
    pc_ = R["encuestas"]["por_casa"]
    casas = [c for c, v in pc_.items() if "mujeres" in v and "hombres" in v]
    ref = R["referencia_2022"]["lula"]
    filas = [("Datafolha 2022 (víspera)", ref["mujeres"], ref["hombres"])] + [(c, pc_[c]["mujeres"], pc_[c]["hombres"]) for c in casas]
    f, ax = plt.subplots(figsize=(6.6, 2.9))
    for i, (n, m, h) in enumerate(filas):
        ax.plot([h, m], [i, i], color="#DDDDDD", lw=3, zorder=1)
        ax.scatter([m], [i], s=70, color=C_MUJER, zorder=3)
        ax.scatter([h], [i], s=70, color=C_HOMBRE, zorder=3)
        ax.text(max(m, h) + 0.8, i, f"{sg(m - h)} pts", va="center", fontsize=8.5, color=INK, weight="bold")
    ax.axvline(50, color=INK, lw=0.8)
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=9)
    ax.set_ylim(len(filas) - 0.5, -0.7)
    ax.set_xlim(34, 66)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.scatter([], [], color=C_MUJER, label="Mujeres")
    ax.scatter([], [], color=C_HOMBRE, label="Hombres")
    ax.legend(frameon=False, fontsize=8.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    limpiar(ax, grid="x")
    guardar(f, "genero.svg")


def fig_edad(R):
    ref = R["referencia_2022"]["lula"]
    ix = R["encuestas"]["por_casa"].get("Indexa/Broadcast", {})
    keys = ["e_16_24", "e_25_34", "e_35_44", "e_45_59", "e_60"]
    etiq = ["16–24", "25–34", "35–44", "45–59", "60 +"]
    f, ax = plt.subplots(figsize=(6.2, 3.1))
    ax.plot(etiq, [ref[k] for k in keys], color=GRIS, lw=2, marker="o", label="Datafolha 2022 (Lula vs Bolsonaro)")
    ax.plot(etiq, [ix.get(k, np.nan) for k in keys], color=C_LULA, lw=2.5, marker="o", label="Indexa 13–14/10/2026 (Lula vs Flávio)")
    for i, (k, e) in enumerate(zip(keys, etiq)):
        if k in ix:  # extremos arriba; el resto debajo, para no pisar la línea de 2022 ni el punto de Palver
            ax.text(e, ix[k] + (1.0 if i in (0, 4) else -2.4), f1(ix[k]), ha="center", fontsize=8, color=C_LULA, weight="bold")
    otras = {"Datafolha 6–7/10 (60 +)": ("60 +", R["encuestas"]["por_casa"].get("Datafolha", {}).get("e_60")),
             "Palver 10–13/10 (60 +)": ("60 +", R["encuestas"]["por_casa"].get("Palver", {}).get("e_60"))}
    for n, (e, v) in otras.items():
        if v:
            ax.scatter([e], [v], s=40, color=VIO, zorder=3)
            ax.annotate(n, (e, v), xytext=(7, 0), textcoords="offset points", ha="left", va="center", fontsize=7.5, color=VIO)
    ax.set_xlim(-0.3, 5.6)
    ax.axhline(50, color=INK, lw=0.8)
    ax.set_ylim(40, 68)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f} %")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    limpiar(ax)
    guardar(f, "edad.svg")


CSS_EXTRA = """
.kpis { margin-bottom:.7cm; } .kpis .kpi-v { font-size:21pt; }
.kpi-l { font-size:9pt; } .kpi-n { font-size:8pt; }
.tesis { gap:.6cm 1cm; }
.t h3 { font-size:11pt; } .t p { font-size:9.4pt; line-height:1.42; } .t-n { font-size:18pt; }
.insight { font-size:9.3pt; line-height:1.4; padding:.26cm .34cm; margin:.2cm 0; }
table { font-size:9pt; } th { font-size:7.6pt; } td { padding:.12cm .2cm; white-space:nowrap; }
.fuente { font-size:7.6pt; }
h3.sub { font-size:10.5pt; margin:0 0 .2cm; }
.nota-metodo h3 { font-size:10pt; } .nota-metodo p { font-size:9pt; line-height:1.45; }
.fig-a { max-height:6.4cm; } .fig-b { max-height:7cm; } .fig-c { max-height:6cm; }
"""


def construir(fecha: date) -> Path:
    (BUILD / "figs").mkdir(parents=True, exist_ok=True)
    corrida = sorted(p.parent for p in SALIDA_DIR.glob("*/resumen.json"))[-1]
    R = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    enc = pd.read_csv(corrida / "encuestas.csv")
    for fn in (fig_padron, fig_participacion, fig_genero, fig_edad):
        fn(R)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")

    B, P, E, S, ref = R["encuestas"], R["participacion"], R["ecologico"], R["escenarios"], R["referencia_2022"]
    p26, p22, v26 = R["padron"]["2026"], R["padron"]["2022"], R["votantes_1v_2026"]
    ix = B["por_casa"].get("Indexa/Broadcast", {})
    D = Documento("Atlas Analytics · Brasil 2026")
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"
    pie = "Voto secreto: no hay votos oficiales por sexo o edad. Preferencias: encuestas. Padrón y participación: TSE."

    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Sexo y edad en el balotaje de Brasil</h1>
    <div class="p-sub">Quiénes son los electores, quiénes fueron a votar el 4 de octubre y qué dicen las encuestas y los
      resultados sobre cómo votan mujeres, hombres, jóvenes y mayores.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Padrón</span> TSE, perfil del electorado 2022 y 2026, por município y zona</div>
      <div><span>Participación</span> TSE, comparecencia oficial por sexo y edad, 1ª y 2ª vuelta 2022 y 1ª vuelta 2026</div>
      <div><span>Encuestas</span> {enc['casa'].nunique()} encuestas de 2ª vuelta con cortes por sexo o edad, del 7 al 14/10</div>
      <div><span>Corte</span> {fecha:%d/%m/%Y}</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    gen_ref = B["brecha_genero_2022_pp"]
    lo, hi = B["brecha_genero_rango_pp"]
    m_ap, h_ap = B["mujeres_media"], B["hombres_media"]
    tm, th = P["2026_1v"]["mujeres"], P["2026_1v"]["hombres"]
    hallazgos = [
        ("La brecha de género se multiplicó",
         f"En 2022 Lula sacaba {gen_ref} pts más entre mujeres que entre hombres (Datafolha). En 2026 las encuestas "
         f"que publican ambos datos la ubican entre {f1(lo)} y {f1(hi)} pts: Lula gana entre mujeres "
         f"({f1(m_ap)} % de los válidos, en promedio) y Flávio entre hombres ({f1(100 - h_ap)} %)."),
        ("Las mujeres son mayoría y votan más",
         f"Son el {pc(p26['mujeres'])} del padrón y el {pc(v26['mujeres'])} de los que votaron el 4/10: "
         f"participaron {pc(tm)} contra {pc(th)} de los hombres. Con las brechas de las encuestas, esa composición "
         f"deja a Lula en {f1(B['lula_implicito_por_genero'])} %, cerca del promedio general."),
        ("Los jóvenes, con Lula; el resto, parejo o con Flávio",
         f"Indexa (13–14/10) da a Lula {f1(ix.get('e_16_24', float('nan')))} % entre los de 16 a 24 y alrededor de 48–50 % "
         "en las otras franjas. Entre los mayores de 60 las casas no coinciden: Datafolha da a Lula adelante, Palver e Indexa a Flávio."),
        ("El electorado envejece y los mayores votan más",
         f"Los de 60 o más pasaron del {pc(p22['60+'])} al {pc(p26['60+'])} del padrón y los de 16 a 24 bajaron del "
         f"{pc(p22['16-24'])} al {pc(p26['16-24'])}. La participación de los mayores subió de {pc(P['2022_1v']['60+'])} "
         f"(1ª vuelta 2022) a {pc(P['2026_1v']['60+'])}: son el grupo que las encuestas no logran leer."),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(f"{sg(B['brecha_genero_media_pp'])} pts", "brecha de género 2026", f"encuestas; en 2022: +{gen_ref}")
              + kpi(f"{f1(m_ap)} %", "Lula entre mujeres", "promedio, votos válidos")
              + kpi(f"{f1(100 - h_ap)} %", "Flávio entre hombres", "promedio, votos válidos")
              + kpi(pc(v26["mujeres"]), "mujeres entre los votantes", "1ª vuelta, TSE")
              + kpi(pc(p26["60+"]), "mayores de 60 en el padrón", f"2022: {pc(p22['60+'])}")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(hallazgos))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="El balotaje se divide por género como nunca antes en Brasil",
             bajada="Cuatro hallazgos: tres de encuestas y datos oficiales, uno solo de datos oficiales.", pie=pie)

    # padrón y participación
    filas_p = [[g_n, pc(p22[g]), pc(p26[g]), pc(v26[g])] for g, g_n in
               (("mujeres", "Mujeres"), ("hombres", "Hombres"), ("16-24", "16 a 24"), ("25-34", "25 a 34"),
                ("35-44", "35 a 44"), ("45-59", "45 a 59"), ("60+", "60 o más"), ("superior", "Con superior"))]
    d22 = {g: (P["2022_2v"][g] - P["2022_1v"][g]) * 100 for g in ["mujeres", "hombres"] + EDADES}
    cuerpo = ('<div class="dos-col"><div>'
              + '<h3 class="sub">Padrón por edad</h3>' + fig("padron.svg", "fig fig-a")
              + tabla(["Grupo", "Padrón 2022", "Padrón 2026", "Votaron el 4/10"], filas_p, num=(1, 2, 3))
              + fuente(f"TSE, perfil del electorado. Padrón 2026: {f0(p26['total'])} electores en Brasil (sin exterior).")
              + "</div><div>"
              + '<h3 class="sub">Participación oficial por grupo</h3>' + fig("participacion.svg", "fig fig-b")
              + fuente("TSE, comparecencia por perfil. Votaron / aptos, por turno.")
              + insight(f"<b>Entre vueltas, en 2022 cambió poco la participación:</b> mujeres {sg(d22['mujeres'])} pts, hombres "
                        f"{sg(d22['hombres'])}, jóvenes de 16 a 24 {sg(d22['16-24'])}, mayores de 60 {sg(d22['60+'])}.")
              + insight(f"<b>Las mujeres votan más que los hombres</b> ({pc(tm)} contra {pc(th)} el 4/10). Con la brecha de las "
                        f"encuestas, un punto más de participación femenina ({f0(S.get('mujeres_extra_votantes', 0))} votantes) "
                        f"mueve a Lula apenas {sg2(S.get('mujeres_+1pt_participacion_pp', 0) * 100)} pts.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="1 · QUIÉNES VOTAN", titulo="Más mujeres y más mayores en el padrón; las mujeres votan más",
             bajada="Composición del padrón y participación por sexo y edad: datos oficiales del TSE.", pie=pie)

    # encuestas
    filas_e = []
    for casa, g in enc.groupby("casa", sort=False):
        r = g.set_index("grupo")
        val = lambda k: f1(r.loc[k, "lula_validos"]) + " %" if k in r.index and pd.notna(r.loc[k, "lula_validos"]) else "—"
        filas_e.append([casa, "/".join(str(g["fecha_fin"].iloc[0]).split("-")[:0:-1]), f0(g["muestra"].iloc[0]),
                        val("total"), val("mujeres"), val("hombres")])
    cuerpo = ('<div class="dos-col"><div>'
              + '<h3 class="sub">Lula entre mujeres y hombres, % de válidos</h3>' + fig("genero.svg", "fig fig-c")
              + fuente("Solo encuestas que publican los dos números. Datafolha 2022: votos válidos de la víspera (BR-08297/2022).")
              + '<h3 class="sub">Lula por edad, % de válidos</h3>' + fig("edad.svg", "fig fig-c")
              + "</div><div>"
              + tabla(["Encuesta", "Fin", "Muestra", "Lula total", "Mujeres", "Hombres"], filas_e, num=(2, 3, 4, 5))
              + fuente("Votos válidos calculados sobre Lula + Flávio. AtlasIntel y Datafolha 2026 publicaron solo el puntero de "
                       "cada sexo: Flávio 57,7 % y 53 % entre hombres; Lula 53,6 % y 50 % entre mujeres (votos totales).")
              + insight(f"<b>Todas las casas coinciden en la dirección:</b> Lula adelante entre mujeres, Flávio entre hombres. "
                        f"La brecha va de {f1(lo)} pts (Indexa, telefónica) a {f1(hi)} pts (Nexus y Palver), contra {gen_ref} pts en 2022.")
              + insight("<b>La edad divide menos y las casas no coinciden.</b> Los más jóvenes se inclinan por Lula en Indexa y Nexus, "
                        "pero Palver los muestra empatados (16 a 34). Entre los mayores de 60, Datafolha da a Lula adelante y "
                        "Palver e Indexa a Flávio. En 2022 Lula ganaba en todas las franjas.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="2 · LO QUE DICEN LAS ENCUESTAS", titulo="Lula gana entre mujeres, Flávio entre hombres",
             bajada="Cortes por sexo y edad publicados por las encuestadoras o la prensa, del 7 al 14 de octubre.",
             pie="Fuentes en config/encuestas_segmentos_2026.yaml: Indexa/Broadcast, Palver, Nexus/BTG, AtlasIntel/Bloomberg, Datafolha.")

    # ecológico (prueba fallida) y escenarios
    e22, e26 = E["2022_2v"], E["2026_1v"]
    medio = lambda r: (r["e_25_34"] + r["e_35_44"]) / 2
    filas_k = [["Mujeres − hombres", sg(gen_ref),
                f"{sg(e22['brecha_genero_pp'])} ± {f0(1.96 * e22['brecha_genero_se'])}",
                f"{sg(e26['brecha_genero_pp'])} ± {f0(1.96 * e26['brecha_genero_se'])}"],
               ["16–24 − 25–44", sg(ref["lula"]["e_16_24"] - medio(ref["lula"])),
                f"{sg(e22['jovenes_vs_25_44_pp'])} ± {f0(1.96 * e22['jovenes_se'])}",
                f"{sg(e26['jovenes_vs_25_44_pp'])} ± {f0(1.96 * e26['jovenes_se'])}"],
               ["60 + − 25–44", sg(ref["lula"]["e_60"] - medio(ref["lula"])),
                f"{sg(e22['mayores_vs_25_44_pp'])} ± {f0(1.96 * e22['mayores_se'])}",
                f"{sg(e26['mayores_vs_25_44_pp'])} ± {f0(1.96 * e26['mayores_se'])}"]]
    cuerpo = ('<div class="dos-col"><div>'
              + '<h3 class="sub">Diferencia de apoyo a Lula entre grupos, pts</h3>'
              + tabla(["Grupos", "Datafolha 2022", "Por município 2022", "Por município 2026"], filas_k, num=(1, 2, 3))
              + fuente(f"Regresión ponderada del voto de Lula por município ({f0(e26['n'])}) contra la composición de los que "
                       "votaron (TSE), con efectos fijos de UF y educación superior. Intervalos de 95 %.")
              + insight(f"<b>La prueba contra 2022 falla.</b> Con el balotaje de 2022 el método da una brecha de género de "
                        f"{sg(e22['brecha_genero_pp'])} pts, cuando la encuesta de la víspera medía {sg(gen_ref)} y el resultado "
                        f"la confirmó. Entre jóvenes y adultos da {sg(e22['jovenes_vs_25_44_pp'])} pts: un valor imposible.")
              + insight(f"<b>Por qué:</b> el % de mujeres entre los votantes casi no cambia de un município a otro (desvío de "
                        f"{f1(e22['sd_mujeres_entre_municipios_pp'])} pts), y el peso de jóvenes y mayores va de la mano de la "
                        "región y del ingreso. La regresión atribuye a la edad y al sexo lo que es geografía.")
              + "</div><div>"
              + '<h3 class="sub">Cuánto pesa quién vaya a votar el 25/10</h3>'
              + (insight(f"<b>Si la participación cambia entre vueltas como en 2022</b> (mayores de 60 "
                         f"{sg(S['edad']['cambio_tasa_2022_pp']['60+'])} pts, jóvenes {sg(S['edad']['cambio_tasa_2022_pp']['16-24'])}), "
                         f"con las preferencias de las encuestas Lula se mueve {sg2(S['edad']['efecto_pp'] * 100)} pts por edad y "
                         f"{sg2(S['genero']['efecto_pp'] * 100)} pts por sexo.") if "genero" in S and "edad" in S else "")
              + insight("<b>La composición no define el balotaje.</b> Los grupos van a votar en proporciones parecidas en las dos "
                        "vueltas; lo que puede decidir es que alguien cambie de voto o de abstenerse a votar, no quién se presenta.")
              + insight("<b>Conclusión:</b> el voto por sexo y edad solo se conoce por encuestas. Los datos oficiales dicen quién "
                        "vota, no a quién. Las cifras de este informe sobre preferencias son de las encuestadoras, con márgenes "
                        "de 3 a 5 pts por subgrupo.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="3 · LO QUE DICEN LOS RESULTADOS", titulo="Los resultados por município no permiten medir el voto por sexo o edad",
             bajada="Se probó estimar el voto de cada grupo con los resultados de los 5.571 municípios. No pasó la prueba contra 2022.",
             pie=pie)

    cuerpo = ('<div class="dos-col"><div class="nota-metodo">'
              '<h3>Qué se puede saber y qué no</h3>'
              '<p><b>El voto es secreto.</b> El TSE publica cuántos votos tuvo cada candidato en cada sección y, aparte, '
              'cuántas personas de cada sexo y edad fueron a votar. Nunca cómo votó cada grupo.</p>'
              '<p><b>Lo oficial:</b> padrón y participación por sexo y edad. <b>Lo estimado:</b> el voto por grupo. Se '
              'intentó de dos maneras: encuestas (lo que la gente dice) e inferencia ecológica (cómo votan los lugares '
              'según quién vota ahí). Solo la primera resultó utilizable.</p>'
              '<h3>Inferencia ecológica</h3>'
              '<p>Regresión del voto de Lula (sobre Lula + Flávio) en cada município contra el % de mujeres, de 16 a 24, de 45 '
              'a 59, de 60 o más y con educación superior entre los que votaron, con efectos fijos de UF, ponderada por votos '
              'y con errores robustos. El coeficiente de cada proporción se lee como la diferencia de apoyo del grupo '
              '(Goodman). Se probó contra el balotaje de 2022 y la encuesta Datafolha de la víspera, y no pasó: da brechas '
              'imposibles. Se informa como resultado negativo y no se usa para ninguna cifra.</p>'
              '</div><div class="nota-metodo">'
              '<h3>Encuestas</h3>'
              '<p>Se cargan a mano los cortes publicados (config/encuestas_segmentos_2026.yaml), en votos totales; los válidos se '
              'calculan sobre Lula + Flávio. Como en el resto del análisis, son control: el pronóstico no las usa.</p>'
              '<h3>Fuentes</h3>'
              '<p>TSE: perfil del electorado 2022 y 2026, comparecencia y abstención por perfil 2022 y 2026, resultados 2022 y '
              '1ª vuelta 2026. Datafolha (BR-08297/2022; BR-02949/2026), Indexa/Broadcast (BR-04629/2026), Palver, Nexus/BTG '
              '(BR-07997/2026), AtlasIntel/Bloomberg (BR-03663/2026), vía Poder360, Exame, BNews, DC Mais, UNITV y TVT News.</p>'
              '<h3>Alcance</h3>'
              '<p>Las encuestas por subgrupo tienen márgenes de 3 a 5 pts y difieren por método (telefónica, online, '
              'presencial). Padrón y participación son datos oficiales completos.</p></div></div>')
    D.pagina(cuerpo, kicker="MÉTODO Y FUENTES", titulo="Cómo se hizo este informe",
             pie=f"Atlas Analytics · {fecha_txt} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Sexo y edad</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "informe.html").write_text(html, encoding="utf-8")
    chrome = next((c for c in CHROME if Path(c).exists()), None)
    pdf = BRIEFS / f"ATLAS_Brasil_Genero_Edad_{fecha:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "informe.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas) · corrida %s", pdf.relative_to(ROOT).as_posix(), len(D.paginas), corrida.name)
    return pdf


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    construir(parser.parse_args(argv).fecha)


if __name__ == "__main__":
    main()
