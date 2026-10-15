"""
src/viz/informe_hallazgos_pdf.py

Informe formal de hallazgos del balotaje (25/10/2026) con la identidad de Atlas
Analytics: síntesis de todo el análisis (pronóstico, encuestas como control,
transferencias declaradas, territorio y municípios) en un documento corto.

Reusa las figuras del brief (correr antes src/viz/brief_balotaje_pdf.py con la
misma fecha) y las cifras de src/viz/redes_hallazgos_balotaje.cargar().

Output: reports/briefs/ATLAS_Brasil_Hallazgos_Balotaje_<fecha>.pdf

Uso:
    python -m src.viz.informe_hallazgos_pdf [--fecha 2026-10-15]
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import src.viz.carrusel_linkedin as cl
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.anexo_municipios_pdf import UF_NOMBRE
from src.viz.brief_balotaje_pdf import BUILD as BUILD_BRIEF, nombre_mun
from src.viz.brief_pdf import (BRIEFS, C_FLAVIO, CHROME, CSS_MARCA, INK, PORTADA, Documento, f0, f1, fig, fuente,
                               insight, kpi, limpiar, pe, tabla)
from src.viz.redes_hallazgos_balotaje import CLARO_FLAVIO, CLARO_LULA, cargar, mapa_cambios, mill, sg

sg2 = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.2f}".replace(".", ",")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_hallazgos"
FIGS_BRIEF = ["encuestas.svg", "horizonte.svg", "cascada.svg", "tamano.svg", "territorio.svg", "caminos.svg"]
plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "none"})


def fig_cambios_uf(D) -> None:
    c = D["cambios_uf"].head(10)[::-1]
    f, ax = plt.subplots(figsize=(5.6, 4.2))
    ax.barh([UF_NOMBRE[u] for u in c.index], c.values, color=C_FLAVIO, height=0.62)
    for i, v in enumerate(c.values):
        ax.text(v + 1.5, i, f"{v:.0f}", va="center", fontsize=9, color=INK, weight="bold")
    ax.set_xticks([])
    ax.tick_params(labelsize=9)
    limpiar(ax, grid=None)
    f.savefig(BUILD / "figs" / "cambios_uf.svg", format="svg", bbox_inches="tight", facecolor="white")
    plt.close(f)


CSS_EXTRA = """
.kpis { margin-bottom:.7cm; } .kpis .kpi-v { font-size:21pt; }
.kpi-l { font-size:9pt; } .kpi-n { font-size:8pt; }
.tesis { gap:.6cm 1cm; }
.t h3 { font-size:11pt; } .t p { font-size:9.4pt; line-height:1.42; } .t-n { font-size:18pt; }
.insight { font-size:9.3pt; line-height:1.4; padding:.26cm .34cm; margin:.2cm 0; }
table { font-size:9pt; } th { font-size:7.6pt; } td { padding:.13cm .2cm; white-space:nowrap; }
.fuente { font-size:7.6pt; }
.reco { margin-bottom:.5cm; } .reco h3 { font-size:10.8pt; } .reco p { font-size:9.4pt; line-height:1.42; }
.nota-metodo h3 { font-size:10pt; } .nota-metodo p { font-size:9pt; line-height:1.45; }
h3.sub { font-size:10.5pt; margin:0 0 .2cm; }
.fig-enc { max-height:7.4cm; } .fig-hz { max-height:5cm; } .fig-casc { max-height:10.5cm; }
.fig-tam { max-height:6.2cm; } .fig-ter { max-height:13cm; } .fig-cam { max-height:11cm; } .fig-cuf { max-height:7.6cm; }
.mapa-c { width:100%; max-height:12.6cm; object-fit:contain; }
.ley-c { display:flex; gap:.45cm; font-size:8pt; color:#6B6480; margin-top:.1cm; }
.ley-c i { display:inline-block; width:.3cm; height:.3cm; margin-right:.12cm; vertical-align:-1px; }
"""


def construir(fecha: date) -> Path:
    for sub in ("figs",):
        (BUILD / sub).mkdir(parents=True, exist_ok=True)
    faltan = [n for n in FIGS_BRIEF if not (BUILD_BRIEF / "figs" / n).exists()]
    if faltan:
        raise FileNotFoundError(f"Faltan figuras del brief {faltan}: correr antes python -m src.viz.brief_balotaje_pdf")
    for n in FIGS_BRIEF:
        shutil.copy(BUILD_BRIEF / "figs" / n, BUILD / "figs" / n)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")

    D = cargar()
    E, Tr, Tt, R = D["E"], D["Tr"], D["Tt"], D["R"]
    cl.BUILD = BUILD / "figs"
    mapa_cambios(D, "mapa_cambios.png", 1400)
    fig_cambios_uf(D)

    Doc = Documento("Atlas Analytics · Brasil 2026")
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"
    pie = "Cifras en votos válidos (sin blancos ni nulos). Pronóstico sin encuestas; encuestas solo como control."

    # ================================================================ portada
    Doc.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil 2026: dónde se decide el balotaje</h1>
    <div class="p-sub">Informe de hallazgos. Qué dicen juntos el pronóstico, las encuestas, lo que declaran los votantes
      y el mapa de los 5.571 municípios, a diez días del 25 de octubre.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Pronóstico</span> resultados oficiales del TSE, 2018, 2022 y 1ª vuelta 2026 · {f0(R['montecarlo']['n'])} simulaciones</div>
      <div><span>Control</span> {E['encuestas_post_1v']} encuestas de 2ª vuelta posteriores al 4/10, contrastadas aparte</div>
      <div><span>Votantes</span> transferencias declaradas, BTG Pactual/Nexus, 10–12/10</div>
      <div><span>Corte</span> {fecha:%d/%m/%Y}</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    # ================================================================ resumen
    hallazgos = [
        ("Flávio es claro favorito, y dos métodos lo confirman",
         f"El modelo, solo con resultados oficiales, deja a Lula en {f1(D['lula'])} % y le da {pe(D['p_lula'])} de chances. "
         f"Las encuestas, que el modelo no usa, dan {f1(E['agregado_lula_validos'])} %: la diferencia (z = {f1(E['contraste']['z'])}) "
         "está dentro del error de ambos."),
        ("Las encuestas de balotaje no tienen un sesgo fijo",
         f"A diez días de la elección, en 2018 subestimaban al PT por {f1(abs(E['track_record_horizonte'][0]['error_pp']))} pts y en 2022 lo "
         f"sobreestimaban por {f1(E['track_record_horizonte'][1]['error_pp'])}. No se corrige: entra como incertidumbre."),
        ("El mapa se corrió hacia el bolsonarismo",
         f"{D['a_flavio']} municípios pasaron de Lula a Flávio respecto de 2022 y uno solo hizo el camino inverso. "
         f"Lula ganó {f0(D['n_lula'])} municípios el 4/10, pero ahí vive el {pe(D['padron_lula'])} del padrón."),
        ("Los terceros se compensan; decide la retención",
         f"Según lo que declaran, los votantes de terceros se reparten casi parejo (efecto neto {sg2(D['terceros_neto'])} pts). "
         f"Que Lula retenga a sus votantes como Flávio vale {sg(D['retencion_vale'])} pts."),
        ("Flávio construye su ventaja en las ciudades medianas",
         f"Las ciudades de 100 a 500 mil electores le dan el {pe(D['medianas_pct_margen'])} de su margen, con Lula en "
         f"{f1(D['medianas']['lula_pct'])} %. Lula gana en los municípios de menos de 20 mil ({f1(D['chicos']['lula_pct'])} %)."),
        ("São Paulo pesa, Minas Gerais avisa",
         f"SP concentra el {f1(D['sp_juego'])} % de los votos en juego y {mill(D['sp_margen_votos'])} de ventaja de Flávio. "
         f"MG es el estado que mejor sigue al nacional: si Lula pasa del {f1(D['mg_umbral'])} % ahí, la elección está abierta."),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(f"{f1(D['lula'])} %", "Lula en la 2ª vuelta", "pronóstico sin encuestas")
              + kpi(pe(D["p_flavio"]), "Flávio presidente", f"Lula {pe(D['p_lula'])}")
              + kpi(f"{f1(E['agregado_lula_validos'])} %", "Lula en las encuestas", f"{E['encuestas_post_1v']} encuestas, control externo")
              + kpi(mill(D["brecha"]), "brecha a cerrar", "votos válidos")
              + kpi(str(D["a_flavio"]), "municípios de Lula a Flávio", "desde la 2ª vuelta de 2022")
              + kpi(f"{f1(D['mg_umbral'])} %", "el número de Minas Gerais", "para la noche del 25")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(hallazgos))
              + "</div>")
    Doc.pagina(cuerpo, kicker="RESUMEN EJECUTIVO", titulo="Flávio llega como favorito y Lula necesita más de lo que tiene a mano",
               bajada="Seis hallazgos del análisis completo. Cada uno se desarrolla en las páginas siguientes.", pie=pie)

    # ================================================================ 1 · pronóstico y control
    v = E["variantes_encuestas"]
    filas_v = [["Modelo Atlas (sin encuestas)", f"{f1(D['lula'])} %", pe(D["p_lula"])],
               ["Encuestas, error como varianza", f"{f1(E['encuestas']['media'])} %", pe(E["encuestas"]["prob_lula"])],
               ["Encuestas si se equivocan como en 2018", f"{f1(v['como_2018']['media'])} %", pe(v["como_2018"]["prob_lula"])],
               ["Encuestas si se equivocan como en 2022", f"{f1(v['como_2022']['media'])} %", pe(v["como_2022"]["prob_lula"])],
               ["<b>Síntesis por precisión</b>", f"<b>{f1(E['sintesis']['media'])} %</b>", f"<b>{pe(E['sintesis']['prob_lula'])}</b>"]]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("encuestas.svg", "fig fig-enc")
              + fuente("Cada punto es una encuesta publicada después del 4/10, en votos válidos. Línea violeta: modelo.")
              + fig("horizonte.svg", "fig fig-hz")
              + fuente("Error del promedio de encuestas según los días que faltaban, 2018 y 2022, en puntos para el PT.")
              + "</div><div>"
              + tabla(["Lectura", "Lula", "P(Lula gana)"], filas_v, num=(1, 2))
              + insight(f"<b>{E['encuestas_con_flavio_adelante']} de {E['encuestas_post_1v']} encuestas dan a Flávio adelante</b> y no hay "
                        f"tendencia desde el 4/10 ({sg2(E['tendencia']['pendiente_pts_por_dia'])} pts por día, t = {sg(E['tendencia']['t'])}).")
              + insight(f"<b>El riesgo es un giro final.</b> En 2018 Haddad subió {f1(D['giro_2018'])} pts en los últimos diez días. "
                        f"Repetirlo llevaría a Lula a {f1(v['como_2018']['media'])} %: es el único escenario con precedente que le alcanza.")
              + insight(f"<b>Implícitamente, las encuestas le dan a Lula el {pe(E['a_lula_terceros_implicita']['principal'])} de los "
                        f"votos de terceros;</b> el modelo, el {pe(D['a_mod'])}. Esa es toda la diferencia entre los dos.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="1 · EL PRONÓSTICO Y SU CONTROL", titulo="Modelo y encuestas, por caminos separados, llegan al mismo lugar",
               bajada="El pronóstico oficial no usa encuestas (decisión del 7/10). Las encuestas se usan solo para contrastarlo.",
               pie="Encuestas: Wikipedia, con ajuste por casa y peso por historial. Modelo: TSE.")

    # ================================================================ 2 · votantes
    P = Tr["posteriores"]
    nom = {"cury": "Cury", "renan_santos": "Renan Santos", "caiado": "Caiado", "zema": "Zema", "abstencion": "No votaron el 4/10"}
    filas_p = [[nom[k], pe(P[k]["prior"]), pe(P[k]["nexus"]), f0(P[k]["n_validos"]),
                f"<b>{pe(P[k]['posterior_media'])}</b>", f"{pe(P[k]['posterior_p5'])} – {pe(P[k]['posterior_p95'])}"] for k in nom]
    cuerpo = ('<div class="dos-col"><div>' + fig("cascada.svg", "fig fig-casc")
              + fuente("Lula en la 2ª vuelta, sumando de a un paso lo que declaran los votantes (BTG/Nexus, 10–12/10).")
              + "</div><div>"
              + '<h3 class="sub">Parte que elige a Lula, entre los que votan a alguien</h3>'
              + tabla(["Grupo", "Modelo", "Encuesta", "Casos", "Combinado", "Rango 90 %"], filas_p, num=(1, 2, 3, 4, 5))
              + fuente("Combinado: beta-binomial con el modelo como punto de partida (peso de 20 casos) y efecto de diseño 1,5.")
              + insight(f"<b>Los terceros se compensan:</b> Caiado empuja hacia Flávio y Cury y Renan Santos hacia Lula. "
                        f"Neto: {sg2(D['terceros_neto'])} pts.")
              + insight(f"<b>La retención es la palanca.</b> En 2022, el {f1(D['perdida_pt_2022'] * 100)} % de los votantes de Lula "
                        f"de la 1ª vuelta no fue al balotaje, contra el {f1(D['perdida_bol_2022'] * 100)} % de los de Bolsonaro. "
                        f"Retener como Flávio vale {sg(D['retencion_vale'])} pts, más que todos los terceros.")
              + insight(f"<b>Con todo lo declarado, Lula llega a {f1(D['techo']['media'])} %</b> y gana en el {pe(D['techo']['prob_lula'])} "
                        "de las simulaciones. Es un techo: la retención declarada suele ser optimista.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="2 · PATRONES DE COMPORTAMIENTO", titulo="Los terceros no definen: lo que pesa es que vuelvan los votantes de Lula",
               bajada="Transferencias declaradas en la encuesta, combinadas con el modelo según cuántos casos tiene cada subgrupo.",
               pie="BTG Pactual/Nexus, 10–12/10/2026, telefónica, n = 2.002. Subgrupos chicos: leer los rangos.")

    # ================================================================ 3 · el mapa
    g = D["grandes_a_flavio"]
    filas_g = [[r.municipio, r.uf, f0(r.electores), f"{f1(r.lula_2v_2022_pct)} %", f"{f1(r.lula_pct)} %"] for r in g.itertuples()]
    ley = (f'<div class="ley-c"><span><i style="background:{C_FLAVIO}"></i>Pasó de Lula a Flávio</span>'
           f'<span><i style="background:{CLARO_FLAVIO}"></i>Sigue con el bolsonarismo</span>'
           f'<span><i style="background:{CLARO_LULA}"></i>Sigue con Lula</span></div>')
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + '<img class="mapa-c" src="figs/mapa_cambios.png">' + ley
              + "</div><div>"
              + '<h3 class="sub">Municípios que cambiaron de ganador, por estado</h3>' + fig("cambios_uf.svg", "fig fig-cuf")
              + '<h3 class="sub">Los más grandes que pasaron a Flávio</h3>'
              + tabla(["Município", "UF", "Electores", "Lula 2022", "Lula 4/10"], filas_g, num=(2, 3, 4))
              + fuente("Lula 2022: 2ª vuelta. Lula 4/10: % de válidos en la 1ª vuelta, con todos los candidatos.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="3 · PATRONES TERRITORIALES", titulo=f"{D['a_flavio']} municípios pasaron de Lula a Flávio; al revés, uno solo",
               bajada=f"Ganador de la 1ª vuelta del 4/10 contra el de la 2ª vuelta de 2022. Flávio ganó {f0(D['n_flavio'])} municípios y Lula {f0(D['n_lula'])}.",
               pie="TSE, 1ª vuelta 2026 al 100 % y 2ª vuelta 2022 por sección. Lista completa en el anexo de municípios.")

    # ================================================================ 4 · tamaño y región
    reg = Tt["por_region"]
    filas_r = [[k, f"{f1(r['lula_pct'])} %", mill(r["margen_flavio"]) if r["margen_flavio"] > 0 else "−" + mill(-r["margen_flavio"]),
                mill(r["en_juego"]), sg2(r["cambio_lula_1v"] / 1e6) + " M", sg2(r["cambio_bolsonarismo_1v"] / 1e6) + " M"]
               for k, r in sorted(reg.items(), key=lambda kv: -kv[1]["en_juego"])]
    cuerpo = ('<div class="dos-col"><div>' + fig("tamano.svg", "fig fig-tam")
              + fuente("Pronóstico municipal del modelo, agregado por tamaño de padrón.")
              + '<h3 class="sub">Por región</h3>'
              + tabla(["Región", "Lula 25/10", "Margen Flávio", "En juego", "Lula vs 2022", "Bolsonarismo vs 2022"], filas_r,
                      num=(1, 2, 3, 4, 5))
              + fuente("Cambios: votos de la 1ª vuelta 2026 contra la 2ª vuelta de 2022. Margen negativo: ventaja de Lula.")
              + "</div><div>"
              + insight(f"<b>El tamaño de la ciudad explica más que la región.</b> En las {D['medianas']['municipios']} ciudades de 100 a 500 mil "
                        f"electores Lula saca {f1(D['medianas']['lula_pct'])} % y Flávio junta {mill(D['medianas']['margen'])} de ventaja, "
                        f"el {pe(D['medianas_pct_margen'])} de su margen nacional.")
              + insight(f"<b>Lula gana en los pueblos chicos</b> ({f1(D['chicos']['lula_pct'])} % en los {f0(D['chicos']['municipios'])} "
                        f"municípios de menos de 20 mil) y las capitales quedan cerca del nacional ({f1(D['capitales']['lula_pct'])} %).")
              + insight(f"<b>El retroceso de Lula es nacional.</b> Desde 2022 perdió {mill(-reg['Sudeste']['cambio_lula_1v'])} en el Sudeste "
                        f"y {mill(-reg['Sul']['cambio_lula_1v'])} en el Sur, y el bolsonarismo creció "
                        f"{mill(reg['Nordeste']['cambio_bolsonarismo_1v'])} en el Nordeste, su territorio.")
              + insight(f"<b>Que vote más gente no alcanza:</b> cinco puntos más de participación en los municípios que Lula ganó en "
                        f"2022 suman {sg(Tt['escenarios_participacion']['municipios_lula_2022_+5']['cambio_pp'])} pts. "
                        "Necesita que vuelvan sus votantes, no cualquier votante.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="4 · CIUDADES Y REGIONES", titulo="Flávio gana el balotaje en las ciudades medianas",
               bajada="Lula proyectado, margen y votos en juego por tamaño de município y por región.", pie=pie)

    # ================================================================ 5 · dónde se decide
    tm = Tt["termometros"]
    filas_t = [[f"{UF_NOMBRE[k]} ({k})", f1(r["termometro_mad"]), sg(r["dif_nac_2018"]), sg(r["dif_nac_2022"]), sg(r["dif_nac_2026_1v"]),
                f"<b>{f1(50 + r['dif_nac_2026_1v'])} %</b>"] for k, r in tm.items()]
    filas_b = [[nombre_mun(b["nombre"]), b["uf"], f0(b["aptos"]), f"{f1(b['lula_pct'])} %"] for b in Tt["bisagra"]["top"][:8]]
    cuerpo = ('<div class="dos-col"><div>' + fig("territorio.svg", "fig fig-ter")
              + fuente("Votos en juego (terceros y abstencionistas de 2022) y margen de Flávio por estado, según el modelo.")
              + "</div><div>"
              + '<h3 class="sub">Termómetros: diferencia con el nacional de Lula, en pts</h3>'
              + tabla(["Estado", "Desvío medio", "2018", "2022", "2026 1ª", "Umbral 25/10"], filas_t, num=(1, 2, 3, 4, 5))
              + fuente("Umbral: Lula en ese estado compatible con un empate nacional, si mantiene la diferencia de la 1ª vuelta.")
              + f'<h3 class="sub">Municípios bisagra: {Tt["bisagra"]["municipios"]} con {mill(Tt["bisagra"]["aptos"])} de electores</h3>'
              + tabla(["Município", "UF", "Electores", "Lula 25/10"], filas_b, num=(2, 3))
              + insight(f"<b>São Paulo concentra el {f1(D['sp_juego'])} % de lo que está en juego</b> y Flávio saca ahí "
                        f"{mill(D['sp_margen_votos'])}, el {D['sp_margen']:.0f} % de su margen. La capital está en empate ({f1(D['sp_capital'])} %), "
                        f"igual que Pará ({f1(D['pa'])} %). {len(D['ajustados'])} municípios se definieron el 4/10 por menos de 2 puntos.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="5 · DÓNDE SE DECIDE", titulo="Cinco estados tienen más de la mitad de lo que está en juego, y Minas avisa",
               bajada=f"SP, MG, BA, RJ y PR concentran el {f1(Tt['concentracion']['top5_pct'])} % de los votos en juego.", pie=pie)

    # ================================================================ 6 · caminos
    ep = Tt["escenarios_participacion"]
    nom_e = {"todo_el_pais_+3": "Todo el país, +3 pts", "nordeste_+5": "Nordeste, +5 pts",
             "municipios_lula_2022_+5": "Municípios que ganó Lula en 2022, +5 pts", "capitales_+5": "Capitales, +5 pts",
             "sur_y_centro_oeste_+5": "Sur y Centro-Oeste, +5 pts"}
    filas_e = [[n, mill(ep[k]["votos_nuevos"]), sg(ep[k]["cambio_pp"]), f"{f1(ep[k]['lula_pct'])} %"] for k, n in nom_e.items()]
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("caminos.svg", "fig fig-cam")
              + fuente("Lula en la 2ª vuelta según qué parte de los terceros elija y cuántos votantes netos sume.")
              + "</div><div>"
              + insight(f"<b>Faltan {mill(D['brecha'])} de votos.</b> Equivale a convertir {mill(Tr['votos']['conversion_necesaria'])} "
                        f"de votantes de Flávio. Con lo que el modelo le da en terceros ({pe(D['a_mod'])}), Lula necesita "
                        f"{mill(D['mov_necesaria'])} de votos netos extra, y su reserva neta es de {mill(D['reserva_neta'])}.")
              + insight("<b>Solo gana combinando dos cosas:</b> que dos de cada tres votantes de terceros lo elijan y que recupere "
                        "más de la mitad de su reserva. Ninguna de las dos tiene precedente en 2018 ni en 2022.")
              + '<h3 class="sub">Más participación, ¿cuánto mueve?</h3>'
              + tabla(["Escenario", "Votos nuevos", "Cambio", "Lula"], filas_e, num=(1, 2, 3))
              + fuente("Los nuevos votantes votan como su município en la 2ª vuelta de 2022.")
              + "</div></div>")
    Doc.pagina(cuerpo, kicker="6 · CAMINOS AL 50 %", titulo="Para ganar, Lula necesita a la vez terceros y movilización",
               bajada="Qué combinaciones de transferencias y participación alcanzan para el empate.", pie=pie)

    # ================================================================ qué mirar + método
    acciones = [
        ("Que vuelvan a votar los votantes de Lula del 4/10",
         f"Es la palanca más grande ({sg(D['retencion_vale'])} pts). Abstención que sube en el Nordeste o en la periferia de "
         "São Paulo cierra la elección."),
        ("São Paulo capital y las ciudades medianas",
         f"La capital está en empate ({f1(D['sp_capital'])} %). Si en las ciudades de 100 a 500 mil electores Lula pasa del "
         f"{f1(D['medianas']['lula_pct'])} %, el pronóstico se queda corto."),
        ("Minas Gerais en la noche del 25",
         f"Si en el conteo de MG Lula pasa del {f1(D['mg_umbral'])} %, la elección está abierta. Pará ({f1(D['pa'])} %) es el "
         "segundo indicador."),
        ("Un giro de última semana en las encuestas",
         f"Si los promedios del 22 al 24/10 muestran a Lula arriba del 49 %, hay que tomarlo en serio: en 2018 el PT subió "
         f"{f1(D['giro_2018'])} pts en los últimos diez días."),
    ]
    cuerpo = ('<div class="dos-col"><div>'
              + "".join(f'<div class="reco"><div class="r-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(acciones))
              + '</div><div class="nota-metodo">'
              '<h3>Método</h3>'
              '<p><b>Pronóstico.</b> Regresión ecológica con restricciones entre la 2ª vuelta de 2022 y la 1ª de 2026 por município, '
              'matriz de retención y movilización de 2022 sobre 92.000 locales de votación, y simulación Montecarlo con shocks '
              'nacional y por estado. Probado contra el balotaje de 2022.</p>'
              '<p><b>Control externo.</b> Promedio de encuestas de 2ª vuelta con ajuste por casa y peso por historial; su error a '
              'diez días en 2018 y 2022 entra como varianza.</p>'
              '<p><b>Votantes.</b> Transferencias declaradas en BTG/Nexus combinadas con el modelo por subgrupo (beta-binomial).</p>'
              '<p><b>Territorio.</b> Votos en juego, tamaño de ciudad, estados termómetro, municípios bisagra y cambios de ganador '
              'en los 5.571 municípios.</p>'
              '<h3>Fuentes</h3>'
              '<p>TSE (resultados 2018, 2022 y 2026). Wikipedia, encuestas de 2ª vuelta. BTG Pactual/Nexus (13/10). Poder360/Quaest. '
              'IBGE (códigos y nombres de municípios).</p>'
              '<h3>Alcance</h3>'
              '<p>Inferencia ecológica: describe territorios, no personas. Los rangos combinan el error del método, la diferencia '
              'entre métodos y un margen por lo que la prueba no ve.</p></div></div>')
    Doc.pagina(cuerpo, kicker="QUÉ MIRAR HASTA EL 25 DE OCTUBRE", titulo="Cuatro señales y cómo se hizo este informe",
               pie=f"Atlas Analytics · {fecha_txt} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Hallazgos del balotaje</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(Doc.paginas)}</body></html>')
    (BUILD / "informe.html").write_text(html, encoding="utf-8")
    chrome = next((c for c in CHROME if Path(c).exists()), None)
    if chrome is None:
        raise FileNotFoundError("No se encontró Chrome/Edge para imprimir el PDF")
    pdf = BRIEFS / f"ATLAS_Brasil_Hallazgos_Balotaje_{fecha:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "informe.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas)", pdf.relative_to(ROOT).as_posix(), len(Doc.paginas))
    return pdf


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    construir(parser.parse_args(argv).fecha)


if __name__ == "__main__":
    main()
