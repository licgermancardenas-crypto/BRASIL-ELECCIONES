"""
src/viz/informe_espacial_pdf.py

Informe "Brasil: el voto en el espacio" (focos LISA, focos de cambio Gi*, GWR,
regionalización SKATER y accesibilidad), con la identidad de Atlas. Lee la
última corrida de R/analisis_espacial.R y sus mapas (src.viz.mapas_espaciales).

Output: reports/briefs/ATLAS_Brasil_Analisis_Espacial_<fecha>.pdf

Uso:
    python -m src.viz.informe_espacial_pdf
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

from src.models.analisis_estados import NOMBRE_UF
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.brief_pdf import BRIEFS, CHROME, CSS_EXTRA, CSS_MARCA, Documento, fig, fuente, insight, kpi, tabla
from src.viz.mapas_espaciales import ESPACIAL, VAR_ETQ

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_espacial"
PORTADA = Path(r"E:/ATLAS CONTENIDO/ATLAS ANALYTICS INSTAGRAM/CONCEPTOS DE EJEMPLO (IMAGENES)/ESTILO ATLAS/duotono/36-c3a8a4b6e51c.jpg")
f1 = lambda x: f"{x:.1f}".replace(".", ",")
f2 = lambda x: f"{x:.2f}".replace(".", ",")
f0 = lambda x: f"{x:,.0f}".replace(",", ".")
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))

CSS = """
.fig-grande { max-height:15.2cm; max-width:100%; margin:0 auto; }
.fig-media { max-height:12.6cm; }
.fig-chica { max-height:7.4cm; }
"""


def construir() -> Path:
    corrida = sorted(p.parent for p in ESPACIAL.glob("*/resumen.json"))[-1]
    R = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(corrida / "figs", BUILD / "figs")
    portada = next((p for p in PORTADA.parent.glob("36-*.jpg")), None) if PORTADA.parent.exists() else None
    if portada:
        shutil.copy(portada, BUILD / "portada.jpg")
    mg, gi, gw, am, ae = R["moran_municipios"], R["gi_cambio"], R["gwr"], R["accesibilidad_municipios"], R["accesibilidad_escuelas"]
    dec = pd.read_csv(corrida / "accesibilidad_deciles.csv")
    cuf = pd.DataFrame(gw["coef_por_uf"])
    D = Documento("Atlas Analytics · Brasil 2026")
    hoy = date.today()
    dup_esc, dup_mun = ae["coef_logdist"] * 0.693, am["sem"]["log(dist_km)"] * 0.693

    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil: el voto en el espacio</h1>
    <div class="p-sub">Dónde se concentra el voto, dónde se movió entre 2018 y 2022, por qué el mismo factor social pesa distinto
      según el lugar, qué regiones votan parecido y cuánto cuesta en participación estar lejos de la escuela.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Unidades</span> {f0(sum(R['moran_municipios']['clusters'].values()))} municípios · {f0(ae['n'])} áreas de escuela</div>
      <div><span>Métodos</span> LISA, Getis-Ord Gi*, GWR, SKATER y modelo de error espacial (R: spdep, GWmodel, rgeoda)</div>
      <div><span>Datos</span> TSE (sección electoral) · IBGE (Censo 2022 por setor)</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if portada else ''}</div>
</section>""")

    c = mg["clusters"]
    tesis = [
        ("El voto brasileño está muy agrupado en el territorio",
         f"El índice de Moran es {f2(mg['I'])} (1 sería agrupamiento perfecto). {f0(c.get('High-High', 0))} municípios forman focos "
         f"lulistas y {f0(c.get('Low-Low', 0))} focos bolsonaristas; casi no hay islas de un bando dentro del otro."),
        ("El cambio de 2022 también tuvo geografía",
         f"Lula creció en focos que abarcan {f0(gi.get('Foco de suba de Lula', 0))} municípios y perdió en focos de "
         f"{f0(gi.get('Foco de baja de Lula', 0))}. No fue un desplazamiento parejo: hubo territorios en movimiento."),
        ("El mismo factor social pesa distinto según el lugar",
         f"Un modelo único explica el {f1(gw['r2_ols'] * 100)} % del voto por município; dejando que los efectos varíen en el "
         f"espacio (GWR), el {f1(gw['r2_gwr'] * 100)} %. La educación pesa mucho contra Lula en el Sul y Rio, y casi nada en el Nordeste."),
        ("Las regiones que votan parecido no son las administrativas",
         "La regionalización SKATER arma, en cada estado, tantas regiones como regiões imediatas tiene el IBGE, pero agrupando "
         "municípios por cómo votan. Es un mapa electoral alternativo para planificar territorio."),
        ("Estar lejos de la escuela cuesta participación",
         f"La abstención sube de {f1(dec['abstencion'].iloc[0])} % en las escuelas más cercanas a {f1(dec['abstencion'].iloc[-1])} % "
         f"en las más lejanas. Controlando por urbanización y perfil social, duplicar la distancia suma entre {f1(dup_esc)} y "
         f"{f1(dup_mun)} puntos de abstención."),
    ]
    cuerpo = ('<div class="kpis">' + kpi(f2(mg["I"]), "índice de Moran", "voto a Lula por município")
              + kpi(f0(c.get("High-High", 0)), "municípios en focos lulistas", f"{f0(c.get('Low-Low', 0))} bolsonaristas")
              + kpi(f0(gi.get("Foco de suba de Lula", 0)), "en focos de suba de Lula", "2018 → 2022")
              + kpi(f"{f1(gw['r2_gwr'] * 100)} %", "explica la GWR", f"modelo único: {f1(gw['r2_ols'] * 100)} %")
              + kpi(f"+{f1(dup_esc)} a {f1(dup_mun)}", "puntos de abstención", "al duplicar la distancia")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>' for i, (t, x) in enumerate(tesis))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="El mapa del voto tiene focos, movimientos y reglas propias por región",
             pie="Análisis en R (spdep, rgeoda, GWmodel, spatialreg) sobre la base mesa por mesa del TSE y el Censo 2022.")

    # 1 · focos
    D.pagina(fig("lisa_municipios.svg", "fig fig-grande"), kicker="1 · DÓNDE SE CONCENTRA EL VOTO",
             titulo="Focos lulistas y bolsonaristas, município por município",
             bajada=f"LISA (Moran local) sobre el % de Lula en la 2ª vuelta 2022. Moran global: {f2(mg['I'])}. Significancia p < 0,01 "
                    "con 999 permutaciones.", pie="Vecindad: municípios que comparten borde (reina).", clase="pag-mapa")
    cuerpo = (fig("lisa_metropolis.svg", "fig fig-media")
              + '<div class="dos-col">'
              + insight("<b>Un foco no es un lugar donde un candidato gana:</b> es un lugar donde gana y además está rodeado de lugares "
                        "donde también gana, más de lo que daría el azar. Es la geografía del voto consolidado.")
              + insight("<b>Dentro de las ciudades se repite el patrón:</b> en São Paulo los focos lulistas son las periferias sur y "
                        "norte; en Rio, el foco lulista está en el este de la ciudad y los focos bolsonaristas, hacia el oeste. Cada estado tiene "
                        "su mapa de focos por escuela en el informe por estado.")
              + "</div>")
    D.pagina(cuerpo, kicker="1 · DÓNDE SE CONCENTRA EL VOTO", titulo="Los focos dentro de las grandes ciudades, escuela por escuela",
             bajada="LISA calculado sobre todas las escuelas de cada estado; acá, las dos capitales más grandes.",
             pie="Unidad: área de influencia de cada escuela (setores más cercanos). Escuelas con 100 electores o más.")

    # 2 · cambio
    D.pagina(fig("gi_cambio.svg", "fig fig-grande"), kicker="2 · DÓNDE SE MOVIÓ EL VOTO",
             titulo="Focos de suba y de baja de Lula entre 2018 y 2022",
             bajada="Getis-Ord Gi* sobre el cambio del voto PT en la 2ª vuelta (Lula 2022 − Haddad 2018), por município. p < 0,01.",
             pie="Un foco de suba es un grupo de municípios vecinos donde Lula creció más que el promedio, todos juntos.", clase="pag-mapa")

    # 3 · GWR
    filas = []
    for v in ["alfabetizacion", "preta_parda", "banos_2mas", "mayores_60"]:
        s = cuf[v].sort_values()
        filas.append([VAR_ETQ[v], sg(gw["coef_ols"][f"z_{v}"]), f"{sg(gw['coef_local'][v]['10%'])} a {sg(gw['coef_local'][v]['90%'])}",
                      f"{s.index[0]} ({sg(s.iloc[0])})", f"{s.index[-1]} ({sg(s.iloc[-1])})"])
    cuerpo = (fig("gwr_coeficientes.svg", "fig fig-media")
              + tabla(["Variable", "Efecto único (MCO)", "Rango local (p10–p90)", "Más negativo (UF)", "Más positivo (UF)"], filas,
                      num=(1, 2)))
    D.pagina(cuerpo, kicker="3 · EL MISMO FACTOR, OTRO EFECTO",
             titulo="Cuánto pesa cada rasgo social en el voto, según dónde",
             bajada=f"Regresión geográficamente ponderada (GWR) del % de Lula por município sobre el Censo 2022: cada município tiene "
                    f"sus propios coeficientes, estimados con sus {gw['vecinos']} vecinos más cercanos. Rojo: más voto a Lula; azul: menos.",
             pie="Variables estandarizadas: el coeficiente es puntos de Lula por un desvío estándar de la variable.")
    cuerpo = ('<div class="dos-col"><div>' + fig("gwr_r2.svg", "fig fig-media") + "</div><div>"
              + insight(f"<b>El modelo con efectos variables explica el {f1(gw['r2_gwr'] * 100)} % del voto por município</b>, contra "
                        f"{f1(gw['r2_ols'] * 100)} % de un modelo único para todo el país (AICc {f0(gw['aicc_ols'])} → {f0(gw['aicc_gwr'])}).")
              + insight("<b>La educación es la gran divisoria del Sul y del Sudeste:</b> en Rio, Santa Catarina y Rio Grande do Sul, "
                        f"cada desvío de alfabetización resta más de 10 puntos a Lula; en el Nordeste el efecto casi desaparece.")
              + insight("<b>El color de piel pesa más en São Paulo, Espírito Santo y Pará:</b> más de 11 puntos de Lula por desvío. "
                        "En Acre el efecto es negativo.")
              + insight("<b>Lectura para campaña:</b> el mismo perfil social no vota igual en todo el país. Un mensaje segmentado por "
                        "nivel educativo rinde en el Sul y en Rio; en el Nordeste, el voto es más transversal.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="3 · EL MISMO FACTOR, OTRO EFECTO", titulo="Dónde el modelo social explica bien el voto",
             bajada="R² local de la GWR: qué parte del voto de cada zona explican las cinco variables del Censo.",
             pie="GWR con kernel bisquare adaptativo; ancho de banda por AICc (GWmodel).")

    # 4 · SKATER
    sk = R["skater"]
    filas = [[uf, NOMBRE_UF[uf], v["regioes_imediatas"], v["k"], f"{v['ratio_entre_total'] * 100:.0f} %"]
             for uf, v in sorted(sk.items(), key=lambda kv: -kv[1]["ratio_entre_total"])[:10]]
    cuerpo = ('<div class="dos-col dos-col-60"><div>' + fig("skater_4.svg", "fig fig-media") + "</div><div>"
              + tabla(["UF", "Estado", "Regiões IBGE", "Regiones SKATER", "Varianza explicada"], filas, num=(2, 3, 4))
              + insight("<b>Regiones contiguas que votan parecido.</b> SKATER corta el árbol de vecindad de los municípios para que "
                        "cada región sea lo más homogénea posible en su voto (Lula 1ª y 2ª vuelta, cambio 2018-2022 y abstención).")
              + insight("<b>Varianza explicada:</b> qué parte de las diferencias entre municípios queda entre regiones. Con el mismo "
                        "número de regiones que el IBGE, las regiones SKATER resumen el voto del estado con una sola cifra por región.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="4 · REGIONES ELECTORALES", titulo="Un mapa electoral alternativo al administrativo",
             bajada="Regionalización SKATER por estado; el número dentro de cada región es su % de Lula en la 2ª vuelta 2022.",
             pie="Cada estado tiene su mapa SKATER en el informe por estado. Islas sin vecinos (Fernando de Noronha, Ilhabela) quedan fuera.")

    # 5 · accesibilidad
    cuerpo = ('<div class="dos-col"><div>' + fig("acceso_deciles.svg", "fig fig-chica") + fig("acceso_mapa.svg", "fig fig-chica")
              + "</div><div>"
              + insight(f"<b>Lejos de la escuela se vota menos.</b> En el 10 % de escuelas más cercanas a su población "
                        f"({dec['dist_km_mediana'].iloc[0] * 1000:.0f} m de mediana) la abstención fue {f1(dec['abstencion'].iloc[0])} %; "
                        f"en el 10 % más lejano ({f1(dec['dist_km_mediana'].iloc[-1])} km), {f1(dec['abstencion'].iloc[-1])} %.")
              + insight(f"<b>No es solo que lo rural vote menos.</b> Controlando por urbanización, educación, edad y nivel socioeconómico, "
                        f"y por el estado, duplicar la distancia suma {f2(dup_esc)} puntos de abstención por escuela "
                        f"({f0(ae['n'])} escuelas) y {f2(dup_mun)} por município en un modelo que corrige la dependencia espacial "
                        f"(λ = {f2(am['lambda'])}).")
              + insight("<b>Lectura para el balotaje:</b> el transporte el día de la elección es un factor de participación medible. "
                        "Los territorios rurales del Norte y del Nordeste, con escuelas a varios kilómetros, son donde más rinde.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="5 · ACCESIBILIDAD", titulo="Cada kilómetro hasta la escuela resta participación",
             bajada="Distancia en línea recta desde cada setor censitário a su escuela, promedio por habitante, contra la abstención de la 2ª vuelta 2022.",
             pie="Distancia mínima posible (escuela más cercana): la real suele ser mayor. Modelo de error espacial con spatialreg.")

    # metodología
    cuerpo = ('<div class="dos-col"><div class="nota-metodo">'
              '<h3>Métodos</h3>'
              f'<p><b>LISA (Moran local).</b> Compara el voto de cada unidad con el de sus vecinas; foco = alto rodeado de alto o bajo '
              f'rodeado de bajo, con p &lt; 0,01 por 999 permutaciones (rgeoda). Vecindad: comparten borde.</p>'
              '<p><b>Getis-Ord Gi*.</b> Busca grupos de municípios vecinos con cambios 2018-2022 más altos o más bajos que el promedio.</p>'
              f'<p><b>GWR.</b> Una regresión por município, con sus {gw["vecinos"]} vecinos más cercanos ponderados por distancia '
              '(kernel bisquare adaptativo, ancho de banda por AICc; GWmodel). Variables del Censo 2022 estandarizadas.</p>'
              '<p><b>SKATER.</b> Corta el árbol de expansión mínima de la vecindad para formar k regiones contiguas homogéneas '
              '(rgeoda). k = número de regiões imediatas del IBGE en el estado.</p>'
              '<p><b>Accesibilidad.</b> Modelo de error espacial (spatialreg) en municípios y mínimos cuadrados con efectos fijos de '
              'estado en escuelas, ponderados por electores.</p>'
              '</div><div class="nota-metodo">'
              '<h3>Cómo leer los resultados</h3>'
              '<p>Todos los análisis comparan territorios, no personas. Que la educación pese contra Lula en un município no dice '
              'cómo vota cada persona educada.</p>'
              '<p>Las áreas de escuela y la distancia son aproximadas: se asume que cada setor vota en la escuela más cercana de su '
              'município. Las escuelas sin coordenadas (3,4 % del padrón, sobre todo en Bahia y Sergipe) no entran en los análisis '
              'por escuela.</p>'
              '<h3>Reproducibilidad</h3>'
              f'<p>Script R/analisis_espacial.R (semilla 2026, {R["parametros"]["r"]}). Insumos: src/geo/insumos_espaciales.py.</p>'
              "</div></div>")
    D.pagina(cuerpo, kicker="METODOLOGÍA", titulo="Cómo se hizo cada análisis", pie=f"Atlas Analytics · {hoy:%d/%m/%Y} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil: el voto en el espacio</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}{CSS}.pag-mapa .cuerpo {{ display:flex; align-items:center; justify-content:center; }}</style>'
            f'</head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "informe.html").write_text(html, encoding="utf-8")
    chrome = next(c for c in CHROME if Path(c).exists())
    pdf = BRIEFS / f"ATLAS_Brasil_Analisis_Espacial_{hoy:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "informe.html").as_uri()], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas)", pdf.relative_to(ROOT).as_posix(), len(D.paginas))
    return pdf


if __name__ == "__main__":
    construir()
