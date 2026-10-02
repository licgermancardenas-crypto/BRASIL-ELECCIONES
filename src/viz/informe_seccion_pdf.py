"""
src/viz/informe_seccion_pdf.py

Informe "Brasil, mesa por mesa" en PDF con la identidad de Atlas Analytics
(mismo formato que el brief y que los informes CABA). No recalcula nada: lee
la última corrida de src/models/analisis_seccion.py (datos.json + figs/).

Output: reports/briefs/ATLAS_Brasil_Mesa_por_Mesa_<fecha>.pdf

Uso:
    python -m src.viz.informe_seccion_pdf
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

from src.models.analisis_seccion import ANALISIS_DIR, CENSO, ETQ
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, ROOT
from src.viz.brief_pdf import (BRIEFS, CHROME, CSS_EXTRA, CSS_MARCA, Documento, fig, fuente, insight, kpi, tabla, ultima)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_seccion"
PORTADA = Path(r"E:/ATLAS CONTENIDO/ATLAS ANALYTICS INSTAGRAM/CONCEPTOS DE EJEMPLO (IMAGENES)/ESTILO ATLAS/duotono/03-31d34d954fcf.jpg")

f1 = lambda x: f"{x:.1f}".replace(".", ",")
f0 = lambda x: f"{x:,.0f}".replace(",", ".")
pe = lambda x: f"{x * 100:.0f} %"
ps = lambda x: f"{x:.0f} %"
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))
CLAB = dict(CENSO)

CSS_SECCION = """
.fig-mapa { max-height:14.2cm; }
.fig-metro { max-height:7.4cm; }
.fig-chica { max-height:7.2cm; }
.fig-media { max-height:9.4cm; }
.fig-heat { max-height:6.6cm; }
"""


def nombre_tipo(t: dict) -> str:
    zona = "urbano" if t["urbano"] >= 70 else "rural" if t["urbano"] < 35 else "mixto"
    nivel = "acomodado" if t["banos_2mas"] >= 40 else "intermedio" if t["banos_2mas"] >= 18 else "popular"
    if zona == "rural" and t["preta_parda"] < 45 and t["alfabetizacion"] < 85:
        return "Rural, comunidades indígenas"
    return f"{zona.capitalize()} {nivel}"


def construir() -> Path:
    corrida = ultima(ANALISIS_DIR) if any(ANALISIS_DIR.glob("*/meta.json")) else sorted(
        p.parent for p in ANALISIS_DIR.glob("*/datos.json"))[-1]
    D_ = json.loads((corrida / "datos.json").read_text(encoding="utf-8"))
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(corrida / "figs", BUILD / "figs")
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")

    dist, cam, tr, coh, ab = D_["dist"], D_["cambio"], D_["transfer"], D_["cohortes"], D_["abstencion"]
    var = dist["varianza"]
    t22, t18 = tr["t22"], tr["t18"]
    reg, tipos, proy = D_.get("reg"), D_.get("tipos"), D_.get("proy_2026")
    a_l = lambda t, o: t[o]["pt"] / (t[o]["pt"] + t[o]["bolsonaro"])

    D = Documento("Atlas Analytics · Brasil 2026")
    hoy = date.today()

    # ================================================================ portada
    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil, mesa por mesa</h1>
    <div class="p-sub">Cómo votó cada escuela del país en las presidenciales de 2018 y 2022, qué explica ese voto y qué
      anticipa para la segunda vuelta de 2026.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Voto</span> {f0(dist['secciones'])} secciones electorales · {f0(dist['locales'])} locales de votación · 2018 y 2022</div>
      <div><span>Padrón</span> {f0(dist['electores'])} electores con su local ubicado por coordenadas (TSE)</div>
      <div><span>Contexto</span> Censo 2022 (IBGE) por setor censitário</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    # ================================================================ resumen
    tesis = [
        ("Brasil vota partido en dos, y la línea pasa por el mapa",
         f"Lula ganó en {f0(dist['lula_gana_locales'])} de {f0(dist['locales_analizados'])} locales de votación en 2022. "
         f"En el Nordeste sacó {f1(dist['por_region']['Nordeste'])} %; en el Sul, {f1(dist['por_region']['Sul'])} %."),
        ("El estado explica más que el barrio",
         f"El {pe(var['entre_uf'])} de las diferencias entre locales se explica por la UF y el {pe(var['entre_municipios'])} por el "
         f"município. Solo el {pe(var['dentro_municipio'])} se juega dentro de cada ciudad."),
        ("El mapa casi no se mueve; el nivel sí",
         f"El voto PT por município de 2018 y 2022 tiene una correlación de {f1(cam['corr_18_22'] * 100)} %. Lula creció "
         f"{f1(cam['media_ponderada'])} puntos sobre Haddad, sobre todo en el Sudeste (+{f1(cam['por_region']['Sudeste'])})."),
        ("Lula creció donde el PT era débil",
         f"En los municípios más bolsonaristas de 2018, Lula sumó {f1(cam['por_quintil_2018']['0'])} puntos; en los bastiones "
         f"petistas perdió {f1(abs(cam['por_quintil_2018']['4']))}. La elección se ganó en territorio ajeno."),
        ("Los votos de los terceros se reparten, no se trasladan",
         f"En 2022 el votante de Ciro fue {pe(a_l(t22, 'ciro'))} a Lula entre los dos finalistas, el de Tebet {pe(a_l(t22, 'tebet'))}. "
         f"En 2018 el de Ciro había ido {pe(a_l(t18, 'ciro'))} a Haddad."),
        ("Con los votantes de 2022, el balotaje 2026 es parejo",
         (f"Si los votantes de los terceros de 2026 se comportan como sus pares de 2022, Lula sacaría "
          f"{f1(list(proy['escenarios'].values())[-1]['lula_2v'])} % en la segunda vuelta." if proy else
          "Sin agregado de encuestas 2026 disponible.")),
    ]
    cuerpo = ('<div class="kpis">'
              + kpi(f0(dist["secciones"]), "secciones electorales", "presidente 2022")
              + kpi(f0(dist["locales_analizados"]), "locales analizados", "con 100 electores o más")
              + kpi(pe(var["entre_uf"] + var["entre_municipios"]), "de la variación es territorial", "UF y município")
              + kpi(f"+{f1(cam['media_ponderada'])}", "puntos de Lula sobre Haddad", "2ª vuelta, 2018 → 2022")
              + kpi(pe(a_l(t22, "ciro")), "de los votantes de Ciro eligió a Lula", "entre quienes votaron a un finalista")
              + (kpi(pe(reg["r2"]), "del voto lo anticipa el Censo", "por local de votación") if reg else "")
              + '</div><div class="tesis">'
              + "".join(f'<div class="t"><div class="t-n">{i + 1}</div><div><h3>{t}</h3><p>{x}</p></div></div>'
                        for i, (t, x) in enumerate(tesis))
              + "</div>")
    D.pagina(cuerpo, kicker="RESUMEN", titulo="Un país dividido por el mapa, que se mueve en bloque",
             bajada="Los seis hallazgos del análisis. Cada uno se desarrolla en las páginas siguientes.",
             pie="Escrutinio oficial del TSE por sección electoral. Votos válidos salvo que se indique.")

    # ================================================================ 1 · mapa
    reg_ord = sorted(dist["por_region"].items(), key=lambda kv: -kv[1])
    cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("mapa_brasil.svg", "fig fig-mapa") + "</div><div>"
              + tabla(["Región", "Lula, 2ª vuelta 2022"], [[r, f1(v) + " %"] for r, v in reg_ord], num=(1,))
              + insight(f"<b>Cada punto es una escuela.</b> Son {f0(D_['mapa']['locales_con_coordenadas'])} locales de votación "
                        "ubicados con las coordenadas que publica el TSE, coloreados según quién ganó y por cuánto.")
              + insight(f"<b>Dos países.</b> El Nordeste votó {f1(dist['por_region']['Nordeste'])} % a Lula; el Sul y el "
                        f"Centro-Oeste, menos del 40 %. {f0(dist['locales_80_lula'])} locales le dieron a Lula 80 % o más; "
                        f"solo {f0(dist['locales_80_bolsonaro'])} hicieron lo mismo con Bolsonaro.")
              + insight(f"<b>Lula gana en más escuelas y por más margen.</b> Ganó en {pe(dist['lula_gana_locales'] / dist['locales_analizados'])} "
                        "de los locales; los triunfos aplastantes son casi todos suyos, mientras que Bolsonaro gana por márgenes "
                        "más moderados en el Sul, el Centro-Oeste y el interior del Sudeste.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="1 · EL MAPA DEL VOTO", titulo="El Nordeste contra el Sul, escuela por escuela",
             bajada="Segunda vuelta 2022: % de Lula en cada local de votación.",
             pie="Locales con 100 electores o más y coordenadas válidas en el padrón del TSE.")

    # ================================================================ 2 · dentro de las ciudades
    m = D_["mapa"]
    sp, rj = m["São Paulo (región metropolitana)"], m["Rio de Janeiro (región metropolitana)"]
    cuerpo = (fig("mapa_metropolis.svg", "fig fig-metro")
              + '<div class="dos-col"><div>' + fig("distribucion.svg", "fig fig-chica")
              + fuente("Votos válidos de la 2ª vuelta 2022 según el % de Lula en su local de votación.")
              + "</div><div>"
              + insight(f"<b>La UF explica el {pe(var['entre_uf'])} de las diferencias entre locales</b>, el município otro "
                        f"{pe(var['entre_municipios'])}, y lo que pasa dentro de cada ciudad apenas el {pe(var['dentro_municipio'])}. "
                        "Conocer el estado y la ciudad dice casi todo del voto de una escuela.")
              + insight(f"<b>Pero dentro de las metrópolis la ciudad se parte.</b> En la región metropolitana de São Paulo Lula sacó "
                        f"{f1(sp['lula_pct'])} % y en la de Rio {f1(rj['lula_pct'])} %, pero los mapas muestran barrios enteros que votan "
                        "en bloque hacia uno u otro lado a pocos kilómetros de distancia.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="2 · ENTRE ESTADOS Y DENTRO DE LAS CIUDADES", titulo="El estado define casi todo, salvo en las metrópolis",
             bajada="Arriba: los locales de las dos regiones metropolitanas más grandes. Abajo: cuántos votos hubo en locales de cada nivel de voto.",
             pie="Descomposición de la varianza del % de Lula por local, ponderada por votos válidos.")

    # ================================================================ 3 · qué explica el voto
    if reg and tipos:
        filas = [[nombre_tipo(t), f0(t["locales"]), f0(t["electores"]), f1(t["lula"]) + " %", f1(t["alfabetizacion"]) + " %",
                  f1(t["preta_parda"]) + " %", f1(t["banos_2mas"]) + " %", f1(t["urbano"]) + " %"] for t in tipos]
        top = sorted(reg["beta"].items(), key=lambda kv: -abs(kv[1]))[:3]
        cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig("betas.svg", "fig fig-chica")
                  + fuente("Efecto de cada variable del Censo sobre el % de Lula en el local, en desvíos estándar, controlando "
                           "por las demás. Barra: intervalo de confianza del 95 %.")
                  + tabla(["Tipo de territorio", "Locales", "Electores", "Lula", "Alfab.", "Preta/parda", "2+ baños", "Urbano"],
                          filas, num=(1, 2, 3, 4, 5, 6, 7))
                  + "</div><div>"
                  + insight(f"<b>Siete datos del Censo anticipan el {pe(reg['r2'])} del voto de cada local.</b> Sumando la UF, el "
                            f"ajuste llega al {pe(reg['r2_con_uf'])}: el voto está anclado en quién vive alrededor de cada escuela.")
                  + insight("<b>Lo que más pesa:</b> " + "; ".join(
                      f"{CLAB[v].lower()} ({'más' if b > 0 else 'menos'} voto a Lula)" for v, b in top) + ".")
                  + insight("<b>Cuatro tipos de territorio.</b> Agrupando los locales por su perfil censal aparecen cuatro "
                            "Brasiles que votan distinto. El voto a Lula sube a medida que baja el nivel socioeconómico.")
                  + "</div></div>")
        D.pagina(cuerpo, kicker="3 · QUÉ EXPLICA EL VOTO", titulo="El perfil social del barrio anticipa el voto de la escuela",
                 bajada="Regresión del % de Lula por local sobre el Censo 2022 de su área de influencia, y tipología de territorios.",
                 pie="Área de influencia: setores censitários más cercanos a cada local dentro de su município. Aproximación.")

    # ================================================================ 4 · cambio
    sub = cam["mayores_subas"]
    cuerpo = ('<div class="dos-col"><div>' + fig("cambio_municipios.svg", "fig fig-media")
              + fuente("Cada punto es un município; el tamaño, sus electores. Sobre la diagonal, Lula 2022 sacó más que Haddad 2018.")
              + "</div><div>" + fig("cohortes.svg", "fig fig-chica")
              + fuente("Municípios agrupados en quintiles según el voto a Haddad en la 2ª vuelta 2018 (Q1: el más bolsonarista).")
              + insight(f"<b>Lula creció en {f0(cam['subio'])} de {f0(cam['municipios'])} municípios.</b> El salto vino del Sudeste "
                        f"(+{f1(cam['por_region']['Sudeste'])}) y del Sul (+{f1(cam['por_region']['Sul'])}); en el Nordeste, donde ya "
                        f"ganaba por amplio margen, quedó igual ({sg(cam['por_region']['Nordeste'])}).")
              + insight("<b>Las mayores subas, en el Gran São Paulo:</b> " + ", ".join(
                  f"{s['municipio']} ({sg(s['cambio'])})" for s in sub[:4]) + ".")
              + "</div></div>")
    D.pagina(cuerpo, kicker="4 · DE 2018 A 2022", titulo="El mapa quedó igual; Lula ganó terreno en territorio ajeno",
             pie="Comparación por município (los números de local cambian entre elecciones).")

    # ================================================================ 5 · transferencias
    val = tr["validacion"]
    cuerpo = ('<div class="dos-col"><div><h3 class="sub">2022: de la 1ª a la 2ª vuelta</h3>' + fig("transfer22.svg", "fig fig-heat")
              + "</div><div><h3 class='sub'>2018: de la 1ª a la 2ª vuelta</h3>" + fig("transfer18.svg", "fig fig-heat")
              + "</div></div>"
              + fuente("Cada fila es lo que se votó en la 1ª vuelta; cada columna, lo que hizo esa misma gente en la 2ª (% de la fila). "
                       "Estimado comparando los mismos locales, UF por UF.")
              + '<div class="dos-col">'
              + insight(f"<b>Ciro 2022 se partió:</b> {pe(t22['ciro']['pt'])} a Lula, {pe(t22['ciro']['bolsonaro'])} a Bolsonaro y "
                        f"{pe(t22['ciro']['blanco_nulo'])} en blanco o nulo. En 2018 había ido {pe(t18['ciro']['pt'])} a Haddad.")
              + insight(f"<b>Tebet empujó a Bolsonaro:</b> {pe(t22['tebet']['bolsonaro'])} de sus votantes lo eligió, contra "
                        f"{pe(t22['tebet']['pt'])} que fue a Lula, pese al apoyo público de Tebet a Lula.")
              + insight(f"<b>La estimación cierra:</b> aplicada a la 1ª vuelta reproduce la 2ª con Lula {f1(val['lula_predicho'])} % "
                        f"(real: {f1(val['lula_real'])} %); el error típico por local es de {f1(val['error_mediano_local_pp'])} puntos.")
              + "</div>")
    D.pagina(cuerpo, kicker="5 · A DÓNDE VAN LOS VOTOS", titulo="Los votos de los terceros se reparten; los ausentes no vuelven",
             pie="Regresión ecológica con restricciones (proporciones entre 0 y 1 que suman 100 %). Compara locales, no personas.")

    # ================================================================ 6 · abstención
    q = ab["por_quintil_lula"]
    cuerpo = ('<div class="dos-col"><div>' + fig("abstencion.svg", "fig fig-chica") + "</div><div>"
              + insight(f"<b>Uno de cada cinco no vota.</b> La abstención fue {f1(ab['nacional_1'])} % en la 1ª vuelta de 2022 y "
                        f"{f1(ab['nacional_2'])} % en la 2ª, pese a que el voto es obligatorio.")
              + insight(f"<b>Se abstienen más los locales lulistas:</b> {f1(q['4']['abst_2'])} % en el quintil más lulista contra "
                        f"{f1(q['0']['abst_2'])} % en el más bolsonarista. Cada punto de participación en esos territorios vale votos "
                        "para el PT.")
              + insight(f"<b>Quien no votó en la 1ª, no votó en la 2ª:</b> el {pe(t22['abstencion']['abstencion'])} de los ausentes "
                        "de la 1ª vuelta siguió ausente. La movilización entre vueltas casi no cambia el padrón efectivo.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="6 · ABSTENCIÓN", titulo="El ausente es estable, y es un poco más lulista",
             pie="Abstención = padrón de la sección − comparecencia, sumada por local.")

    # ================================================================ 7 · 2026
    if proy:
        esc = proy["escenarios"]
        filas = [[k[0].upper() + k[1:], pe(v["a_lula"]), f1(v["lula_2v"]) + " %"] for k, v in esc.items()]
        cruce = proy.get("cruce_encuestas_lula")
        analog = list(esc.values())[-1]["lula_2v"]
        a1 = proy["agregado_1v"]
        cuerpo = ('<div class="dos-col"><div>'
                  + tabla(["Si los votantes de los terceros se comportan…", "Van a Lula", "Lula, 2ª vuelta"], filas, num=(1, 2))
                  + fuente(f"Agregado ATLAS de 1ª vuelta: Lula {f1(a1['lula'])} %, Flávio {f1(a1['flavio_bolsonaro'])} %, terceros "
                           f"{f1(proy['terceros'])} %. Sobre los que eligen entre los dos finalistas.")
                  + "</div><div>"
                  + insight(f"<b>Con el comportamiento de 2022, la 2ª vuelta queda entre {f1(min(v['lula_2v'] for v in esc.values()))} "
                            f"y {f1(max(v['lula_2v'] for v in esc.values()))} % para Lula.</b> Es una elección de centímetros: depende de "
                            "a quién se parezcan los votantes de Santos, Caiado y Zema.")
                  + (insight(f"<b>Las dos vías coinciden.</b> El cruce directo de las encuestas da a Lula {f1(cruce)} % contra "
                             f"Flávio; el cálculo por analogía con 2022, {f1(analog)} %. La diferencia es de {f1(abs(cruce - analog))} "
                             "puntos: el balotaje está empatado se lo mire por donde se lo mire.") if cruce else "")
                  + insight(f"<b>Los votantes de los finalistas no se mueven.</b> En 2022, el {pe(t22['bolsonaro']['bolsonaro'])} del "
                            f"votante de Bolsonaro en 1ª vuelta lo repitió en la 2ª, y el {pe(t22['pt']['pt'])} del de Lula. "
                            "El terreno en disputa son los terceros, el voto en blanco y la abstención.")
                  + "</div></div>")
        D.pagina(cuerpo, kicker="7 · QUÉ ANTICIPA PARA 2026", titulo="Una segunda vuelta que se decide en los votantes de los terceros",
                 bajada="Matriz de transferencias 2022 aplicada al agregado de encuestas de 1ª vuelta 2026.",
                 pie="Supuesto de analogía (no dato): Cury como Ciro; Caiado como Tebet; Zema y Santos como los 'otros' de 2022.")

    # ================================================================ metodología
    cuerpo = ('<div class="dos-col"><div class="nota-metodo">'
              '<h3>De dónde sale cada cosa</h3>'
              f'<p><b>El voto.</b> Escrutinio oficial del TSE por sección electoral para presidente, 2018 y 2022: '
              f'{f0(dist["secciones"])} secciones en 2022. Los totales coinciden con el resultado oficial al centésimo.</p>'
              '<p><b>El padrón y la ubicación.</b> Archivo de locales de votación del TSE: electores por sección y coordenadas de '
              'cada escuela. Las secciones agregadas el día de la elección se suman a su sección principal.</p>'
              '<p><b>El contexto.</b> Censo 2022 (IBGE) por setor censitário. Cada setor se asigna al local de votación más '
              'cercano de su município, y se suman sus datos: es el área de influencia de la escuela.</p>'
              '</div><div class="nota-metodo">'
              '<h3>Cómo leer los números</h3>'
              '<p>Los resultados son el escrutinio real: no tienen margen de error. Las transferencias y la regresión comparan '
              'territorios, no personas: que una escuela con más votantes de Ciro haya dado más votos a Lula no dice qué hizo cada '
              'votante de Ciro.</p>'
              '<p>El Censo 2022 no publica ingreso por setor: el nivel socioeconómico se aproxima con la cantidad de baños del '
              'hogar y el acceso a cloacas.</p>'
              '<h3>Alcance</h3>'
              '<p>Solo la elección presidencial. Se excluyen el exterior y los locales con menos de 100 electores (cárceles, aldeas '
              'muy chicas), cuyo porcentaje es demasiado ruidoso.</p></div></div>')
    D.pagina(cuerpo, kicker="METODOLOGÍA", titulo="De dónde sale cada número y cómo leerlo",
             pie=f"Atlas Analytics · {hoy:%d/%m/%Y} · documento de circulación restringida.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil, mesa por mesa</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}{CSS_SECCION}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "informe.html").write_text(html, encoding="utf-8")
    chrome = next(c for c in CHROME if Path(c).exists())
    pdf = BRIEFS / f"ATLAS_Brasil_Mesa_por_Mesa_{hoy:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "informe.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas) desde %s", pdf.relative_to(ROOT).as_posix(), len(D.paginas), corrida.name)
    return pdf


if __name__ == "__main__":
    construir()
