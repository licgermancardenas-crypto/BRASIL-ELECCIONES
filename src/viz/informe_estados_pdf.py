"""
src/viz/informe_estados_pdf.py

Informe "Brasil, estado por estado": un capítulo por UF (presidente y
gobernador, mesa por mesa) con la identidad de Atlas Analytics. Lee la última
corrida de src/models/analisis_estados.py; no recalcula nada.

Output: reports/briefs/ATLAS_Brasil_Estado_por_Estado_<fecha>.pdf

Uso:
    python -m src.viz.informe_estados_pdf
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path

from src.geo.divisiones import GEO_DIR
from src.models.analisis_estados import ESTADOS_DIR, NOMBRE_UF
from src.models.analisis_seccion import CENSO
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.brief_pdf import BRIEFS, CHROME, CSS_EXTRA, CSS_MARCA, FAM, Documento, fig, fuente, insight, kpi, tabla
from src.viz.informe_seccion_pdf import nombre_tipo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_estados"
PORTADA = Path(r"E:/ATLAS CONTENIDO/ATLAS ANALYTICS INSTAGRAM/CONCEPTOS DE EJEMPLO (IMAGENES)/ESTILO ATLAS/duotono/13-8ef596a2cbb7.jpg")
f1 = lambda x: f"{x:.1f}".replace(".", ",")
f0 = lambda x: f"{x:,.0f}".replace(",", ".")
pe = lambda x: f"{x * 100:.0f} %"
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))
CLAB = dict(CENSO)

CSS_ESTADOS = """
.fig-uf { max-height:13.4cm; max-width:100%; }
.fig-cruz { max-height:6.2cm; }
.divisor-uf { display:flex; align-items:baseline; gap:.5cm; }
.sigla { font-size:44pt; font-weight:bold; color:#C9BEE4; line-height:1; }
td.wrap { white-space:normal; }
.idx td { white-space:nowrap; font-size:8.2pt; padding:.08cm .16cm; }
.idx th { font-size:7pt; }
.fig-div { max-height:5.6cm; }
.fig-cap { max-height:7.4cm; }
.pag-div table { font-size:8.4pt; } .pag-div td { padding:.09cm .16cm; }
.pag-div .insight { font-size:8.6pt; line-height:1.34; padding:.18cm .28cm; margin:.16cm 0; }
.pag-div h3.sub { margin-top:.1cm; }
.pag-gob table { font-size:8.4pt; } .pag-gob td { padding:.09cm .16cm; }
.pag-gob .insight { font-size:8.7pt; line-height:1.34; padding:.18cm .28cm; margin:.16cm 0; }
.pag-gob .fig-uf { max-height:12.8cm; }
.pag-gob .cruz { gap:.35cm; align-items:center; }
.pag-gob .cruz > div:first-child { flex:.8; }
.pag-gob .fig-cruz { max-height:4.9cm; }
"""


def nombre(s: str) -> str:
    t = str(s).title()
    for x in (" De ", " Da ", " Do ", " Dos ", " Das ", " E "):
        t = t.replace(x, x.lower())
    return t


def titulo_panorama(d: dict) -> str:
    l = d["lula_2v"]
    if l >= 60:
        return f"{d['nombre']}, bastión de Lula"
    if l >= 52:
        return f"{d['nombre']}: Lula gana, sin holgura"
    if l > 48:
        return f"{d['nombre']}, un estado partido al medio"
    if l > 40:
        return f"{d['nombre']}: Bolsonaro gana, sin holgura"
    return f"{d['nombre']}, territorio bolsonarista"


def construir() -> Path:
    corrida = sorted(p.parent for p in ESTADOS_DIR.glob("*/datos.json"))[-1]
    D_ = json.loads((corrida / "datos.json").read_text(encoding="utf-8"))
    nac = D_.pop("_nacional")
    tipos = {int(k): v for k, v in nac["tipos"].items()}
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(corrida / "figs", BUILD / "figs")
    geo = {}
    for uf in D_:
        r = GEO_DIR / uf / "resumen.json"
        if r.exists():
            geo[uf] = json.loads(r.read_text(encoding="utf-8"))
            for f in ("divisiones", "capital"):
                shutil.copy(GEO_DIR / uf / "figs" / f"{f}.svg", BUILD / "figs" / f"{uf}_{f}.svg")
        else:
            log.warning("%s: sin capas geoespaciales (correr src.geo.divisiones)", uf)
    if PORTADA.exists():
        shutil.copy(PORTADA, BUILD / "portada.jpg")
    ufs = sorted(D_, key=lambda u: -D_[u]["electores"])
    D = Documento("Atlas Analytics · Brasil 2026")
    hoy = date.today()

    # ================================================================ portada
    D.paginas.append(f"""<section class="page portada">
  <div class="p-izq">
    <div class="p-marca">ATLAS ANALYTICS</div>
    <h1>Brasil, estado por estado</h1>
    <div class="p-sub">Presidente y gobernador, mesa por mesa, en las 27 unidades de la federación: dónde se gana, qué tan
      cruzado es el voto y qué territorios definen cada estado.</div>
    <div class="p-linea"></div>
    <div class="p-meta">
      <div><span>Voto</span> secciones electorales de presidente y gobernador · 2018 y 2022 · TSE</div>
      <div><span>Unidad</span> {f0(sum(d['locales'] for d in D_.values()))} locales de votación con 100 electores o más</div>
      <div><span>Contexto</span> Censo 2022 (IBGE) por setor censitário</div>
    </div>
    <div class="p-conf">Documento de circulación restringida</div>
  </div>
  <div class="p-der">{'<img src="portada.jpg" alt="">' if PORTADA.exists() else ''}</div>
</section>""")

    # ================================================================ índice comparativo
    filas = []
    for u in ufs:
        d = D_[u]; g = d["gob"]; w = g["ganador"]
        g26 = d["gob_2026"][0] if d["gob_2026"] else None
        filas.append([u, d["nombre"], f0(d["electores"]), f1(d["lula_2v"]) + " %", sg(d["cambio"]),
                      f"{nombre(w['nombre'])} ({w['partido']})" + (" · 2ª v." if g["segunda_vuelta"] else ""),
                      ("—" if g["locales_voto_cruzado_pct"] is None else f1(g["locales_voto_cruzado_pct"]) + " %"),
                      (f"{g26['nombre'].split(' / ')[0]} {pe(g26['prob'])}" if g26 else "—")])
    cuerpo = (f'<div class="idx">{tabla(["UF", "Estado", "Electores", "Lula 2ª v. 2022", "vs 2018", "Gobernador 2022", "Voto cruzado", "Favorito gob. 2026"], filas, num=(2, 3, 4, 6))}</div>'
              + fuente("Ordenado por electores. Voto cruzado: % de escuelas donde el bando que gana a presidente no es el que gana a "
                       "gobernador (— : los dos primeros a gobernador no se reparten los bandos presidenciales). Favorito 2026: modelo estructural de gobernadores (sin encuestas), probabilidad de ganar."))
    D.pagina(cuerpo, kicker="LOS 27 ESTADOS DE UN VISTAZO", titulo="Cómo votó cada estado en 2022 y quién gobierna",
             bajada="Presidencial 2022 y elección de gobernador. Cada estado se desarrolla en su capítulo, en este mismo orden.",
             pie="Escrutinio oficial del TSE por sección. Votos válidos.")

    # ================================================================ cómo leer
    filas_t = [[nombre_tipo(t), f1(t["lula"]) + " %", f1(t["alfabetizacion"]) + " %", f1(t["banos_2mas"]) + " %",
                f1(t["urbano"]) + " %"] for t in sorted(tipos.values(), key=lambda t: t["lula"])]
    cuerpo = ('<div class="dos-col"><div class="nota-metodo">'
              '<h3>Qué tiene cada capítulo</h3>'
              '<p><b>Panorama.</b> El mapa del estado escuela por escuela (2ª vuelta presidencial 2022), los municípios con más '
              'electores, el cambio respecto de 2018 y a dónde fueron los votantes de Ciro y Tebet entre vueltas.</p>'
              '<p><b>Gobernador.</b> El resultado de 2022, el mapa de los dos primeros por escuela y el voto cruzado: cuánto se '
              'parece el voto a gobernador al voto a presidente en cada escuela. Si hubo segunda vuelta, a dónde fueron los '
              'votantes de los demás candidatos. Y el favorito para 2026 según el modelo estructural.</p>'
              '<p><b>Divisiones y jurisdicciones.</b> El voto por município, região imediata, zona eleitoral y, en la capital, '
              'por el área de cada escuela. Cada capa se entrega también en GeoJSON para usar en cualquier mapa.</p>'
              '<p><b>Territorio y mesas.</b> Qué tipos de territorio pesan en el estado, qué explica el voto dentro de él, y las '
              'mesas atípicas: secciones cuyo resultado se aparta mucho del resto de su escuela.</p>'
              '<h3>Mesas atípicas</h3>'
              f'<p>Se compara cada sección con las demás de su misma escuela. Es atípica si la diferencia supera 4 veces lo esperable '
              f'por azar más la variación normal entre mesas de una escuela ({f1(nac["tau_pp"])} puntos). En todo el país son '
              f'{f0(nac["atipicas"])} de {f0(nac["secciones_analizadas_atipicas"])}. Atípica no quiere decir irregular: suelen ser '
              'secciones especiales (cárceles, hospitales, comunidades) o urnas muy chicas.</p>'
              '</div><div>'
              '<h3 class="sub">Los cuatro tipos de territorio (tipología nacional)</h3>'
              + tabla(["Tipo", "Lula 2022", "Alfabetizados", "2+ baños", "Urbano"], filas_t, num=(1, 2, 3, 4))
              + fuente("Locales agrupados por el perfil censal de su área de influencia (k-medias). Cada capítulo muestra cuánto "
                       "pesa cada tipo en el estado y cómo votó ahí.")
              + "</div></div>")
    D.pagina(cuerpo, kicker="CÓMO LEER LOS CAPÍTULOS", titulo="Cuatro páginas por estado, con la escuela como unidad",
             pie="Unidad: local de votación (escuela). La sección (mesa) se usa para detectar urnas atípicas.")

    # ================================================================ capítulos
    for u in ufs:
        d = D_[u]; g = d["gob"]; tr = d["transfer"]
        sig = f'<span class="sigla">{u}</span>'
        # ---- A · panorama
        mc = d["municipios_clave"]
        filas_m = [[x["municipio"], f0(x["electores"]), f1(x["lula"]) + " %", sg(x["cambio"])] for x in mc]
        sube = max(mc, key=lambda x: x["cambio"]); baja = min(mc, key=lambda x: x["cambio"])
        ins = [insight(f"<b>Lula {f1(d['lula_2v'])} % en la 2ª vuelta</b> ({sg(d['cambio'])} puntos respecto de Haddad 2018). "
                       f"Ganó en el {f1(d['lula_gana_locales'])} % de las {f0(d['locales'])} escuelas del estado. En la 1ª vuelta: "
                       f"Lula {f1(d['lula_1v'])} %, Bolsonaro {f1(d['bolsonaro_1v'])} %.")]
        if sube["municipio"] != baja["municipio"]:
            ins.append(insight(f"<b>Entre las grandes ciudades,</b> donde más creció Lula fue {sube['municipio']} ({sg(sube['cambio'])}) "
                               f"y donde menos, {baja['municipio']} ({sg(baja['cambio'])})."))
        def tercero(n, pct, a):
            return f"{n} ({f1(pct)} % en la 1ª) fue {pe(a)} a Lula" + (" (poco preciso: pocos votos)" if pct < 3 else "")
        ins.append(insight("<b>Los terceros entre vueltas,</b> entre quienes eligieron a un finalista: "
                           + tercero("Ciro", tr["ciro_pct_1v"], tr["ciro_a_lula"]) + "; "
                           + tercero("Tebet", tr["tebet_pct_1v"], tr["tebet_a_lula"]) + "."))
        cuerpo = ('<div class="dos-col dos-col-55"><div>' + fig(f"{u}_mapa.svg", "fig fig-uf") + "</div><div>"
                  + '<div class="kpis">' + kpi(f0(d["electores"]), "electores", f"{f0(d['secciones'])} mesas")
                  + kpi(f1(d["lula_2v"]) + " %", "Lula, 2ª vuelta 2022", f"Haddad 2018: {f1(d['haddad_2v_2018'])} %")
                  + kpi(f1(d["abst_2"]) + " %", "abstención", "2ª vuelta 2022") + "</div>"
                  + tabla(["Município", "Electores", "Lula", "vs 2018"], filas_m, num=(1, 2, 3))
                  + "".join(ins) + "</div></div>")
        D.pagina(cuerpo, kicker=f"{u} · {d['nombre'].upper()} · PANORAMA", titulo=titulo_panorama(d),
                 bajada="Segunda vuelta presidencial 2022: % de Lula en cada escuela.",
                 pie=f"Municípios con más electores del estado. vs 2018: puntos de Lula 2022 respecto de Haddad 2018.")

        # ---- B · gobernador
        c1 = g["candidatos_1v"]; w = g["ganador"]
        filas_g = [[nombre(c["nombre"]), c["partido"], FAM.get(c["familia"], c["familia"]), f1(c["pct"]) + " %",
                    next((f1(x["pct"]) + " %" for x in g["candidatos_2v"] if x["nr"] == c["nr"]), "—")] for c in c1]
        alineado = c1[0] if g["corr_g1_lula"] >= g["corr_g2_lula"] else c1[1]
        otro = c1[1] if alineado is c1[0] else c1[0]
        w1 = next((c for c in c1 if c["nr"] == w["nr"]), None)
        w2 = next((c for c in g["candidatos_2v"] if c["nr"] == w["nr"]), None)
        ins = [insight(f"<b>Ganó {nombre(w['nombre'])} ({w['partido']})</b>"
                       + (f" en segunda vuelta con {f1(w2['pct'])} %" if g["segunda_vuelta"] and w2 else " en primera vuelta")
                       + (f"; en la 1ª había sacado {f1(w1['pct'])} %." if w1 else ".")
                       + f" En la 1ª vuelta, {nombre(c1[0]['nombre'])} superó a {nombre(c1[1]['nombre'])} en el "
                       f"{f1(g['g1_gana_locales_pct'])} % de las escuelas.")]
        ca, co = max(g["corr_g1_lula"], g["corr_g2_lula"]), min(g["corr_g1_lula"], g["corr_g2_lula"])
        if g["locales_voto_cruzado_pct"] is not None:
            ins.append(insight(f"<b>Voto cruzado: {f1(g['locales_voto_cruzado_pct'])} % de las escuelas</b> eligen un bando a "
                               f"presidente y el otro a gobernador. El voto a {nombre(alineado['nombre'])} se superpone con el de Lula "
                               f"escuela por escuela (correlación {f1(ca * 100)} %); el de {nombre(otro['nombre'])}, con el de "
                               f"Bolsonaro ({f1(co * 100)} %)."))
        else:
            pares = [(c1[0], g["corr_g1_lula"]), (c1[1], g["corr_g2_lula"])]
            fuerte = max(pares, key=lambda x: abs(x[1]))
            debil = pares[1] if fuerte is pares[0] else pares[0]
            if abs(fuerte[1]) >= 0.3 and abs(debil[1]) < 0.2:
                texto = (f"El voto a {nombre(fuerte[0]['nombre'])} se superpone con el de {'Lula' if fuerte[1] > 0 else 'Bolsonaro'} "
                         f"(correlación con Lula {f1(fuerte[1] * 100)} %); el de {nombre(debil[0]['nombre'])} no se alinea con "
                         f"ningún bando presidencial ({f1(debil[1] * 100)} %), así que el voto cruzado no se puede medir.")
            else:
                texto = (f"Los dos primeros no se reparten los bandos de Lula y Bolsonaro (correlaciones con Lula: "
                         f"{nombre(c1[0]['nombre'])} {f1(g['corr_g1_lula'] * 100)} %, {nombre(c1[1]['nombre'])} "
                         f"{f1(g['corr_g2_lula'] * 100)} %): la disputa estadual tiene su propia lógica.")
            ins.append(insight("<b>El voto a gobernador no replica la grieta presidencial.</b> " + texto))
        if g.get("transfer_otros"):
            t = g["transfer_otros"]
            ins.append(insight(f"<b>En la 2ª vuelta,</b> los votantes de los demás candidatos fueron {pe(t['g1'])} a "
                               f"{nombre(c1[0]['nombre'])} y {pe(t['g2'])} a {nombre(c1[1]['nombre'])}; {pe(t['blanco_nulo'])} votó en "
                               "blanco o nulo."))
        partes = []
        if g.get("ganador_2018"):
            w18 = g["ganador_2018"]
            partes.append(f"<b>2018:</b> ganó {nombre(w18['nombre'])} ({w18['partido']})"
                          + ("; reelecto en 2022." if w18["nombre"] == w["nombre"] else "."))
        if d["gob_2026"]:
            f26 = d["gob_2026"]
            partes.append(f"<b>2026</b> (modelo estructural, sin encuestas): favorito {f26[0]['nombre']} "
                          f"({FAM.get(f26[0]['familia'], f26[0]['familia'])}{', en ejercicio' if f26[0]['incumbente'] else ''}) "
                          f"con {pe(f26[0]['prob'])}; balotaje {pe(d['gob_2026_balotaje'] or 0)}.")
        if partes:
            ins.append(insight(" ".join(partes)))
        cuerpo = ('<div class="dos-col pag-gob"><div>' + fig(f"{u}_gobernador.svg", "fig fig-uf") + "</div><div>"
                  + tabla(["Candidato", "Partido", "Família", "1ª vuelta", "2ª vuelta"], filas_g, num=(3, 4))
                  + '<div class="dos-col cruz"><div>' + fig(f"{u}_cruzado.svg", "fig fig-cruz") + "</div><div>"
                  + ins[0] + "</div></div>" + "".join(ins[1:]) + "</div></div>")
        D.pagina(cuerpo, kicker=f"{u} · {d['nombre'].upper()} · GOBERNADOR",
                 titulo=f"{nombre(w['nombre'])} y el mapa del voto a gobernador",
                 bajada=f"Margen entre {nombre(c1[0]['nombre'])} y {nombre(c1[1]['nombre'])} en cada escuela (1ª vuelta 2022).",
                 pie="Voto cruzado: escuelas donde el bando que gana a presidente no es el que gana a gobernador.")

        # ---- C · territorio y mesas
        tp = d["tipos"]
        filas_tp = [[nombre_tipo(tipos[int(t)]), f1(x["electores_pct"]) + " %", f1(x["lula"]) + " %",
                     f1(tipos[int(t)]["lula"]) + " %"] for t, x in sorted(tp.items(), key=lambda kv: -kv[1]["electores_pct"])]
        reg = d.get("reg")
        ins = []
        if reg:
            top = sorted(reg["beta"].items(), key=lambda kv: -abs(kv[1]))[:2]
            ins.append(insight(f"<b>El Censo explica el {pe(reg['r2'])} del voto de cada escuela del estado.</b> Lo que más pesa: "
                               + "; ".join(f"{CLAB[v].lower()} ({'más' if b > 0 else 'menos'} voto a Lula)" for v, b in top) + "."))
        dom = max(tp.items(), key=lambda kv: kv[1]["electores_pct"])
        ins.append(insight(f"<b>El territorio dominante es {nombre_tipo(tipos[int(dom[0])]).lower()}</b> "
                           f"({f1(dom[1]['electores_pct'])} % de los electores), donde Lula sacó {f1(dom[1]['lula'])} % "
                           f"(promedio nacional de ese tipo: {f1(tipos[int(dom[0])]['lula'])} %)."))
        dif = d["abst_2"] - nac["abst_2"]
        ins.append(insight(f"<b>Abstención: {f1(d['abst_2'])} %</b> en la 2ª vuelta, {f1(abs(dif))} puntos "
                           f"{'por encima' if dif > 0 else 'por debajo'} del promedio nacional ({f1(nac['abst_2'])} %)."
                           + (f" Los ausentes de la 1ª vuelta siguieron ausentes en un {pe(tr['abst_se_queda'])}." if tr.get('abst_se_queda') else "")))
        at = d["atipicas"]
        ins.append(insight(f"<b>Mesas atípicas: {at['n']}</b> ({f1(at['por_mil'])} cada mil secciones; promedio nacional "
                           f"{f1(nac['atipicas'] / nac['secciones_analizadas_atipicas'] * 1000)}). Atípica no quiere decir irregular."))
        filas_a = [[x["municipio"], f"{x['zona']}/{x['seccion']}", x["local"][:38], f0(x["votos"]), f1(x["lula_seccion"]) + " %",
                    f1(x["lula_resto"]) + " %"] for x in at["top"]]
        cuerpo = ('<div class="dos-col"><div>'
                  + '<h3 class="sub">Tipos de territorio en el estado</h3>'
                  + tabla(["Tipo", "Electores", "Lula en el estado", "Lula en el país"], filas_tp, num=(1, 2, 3))
                  + "".join(ins[:-1]) + "</div><div>"
                  + '<h3 class="sub">Mesas más atípicas</h3>'
                  + (f'<div class="td-wrap">{tabla(["Município", "Zona/sec.", "Escuela", "Votos", "Lula mesa", "Resto escuela"], filas_a, num=(3, 4, 5))}</div>'
                     if filas_a else "<p class='fuente'>No hay mesas atípicas en el estado.</p>")
                  + ins[-1] + "</div></div>")
        D.pagina(cuerpo, kicker=f"{u} · {d['nombre'].upper()} · TERRITORIO Y MESAS",
                 titulo="Qué territorio define el voto y qué mesas se apartan",
                 bajada="Tipología nacional de territorios aplicada al estado, y secciones que votan muy distinto que el resto de su escuela.",
                 pie="Mesa atípica: |z| > 4 frente a las demás secciones de la misma escuela (2ª vuelta presidencial 2022).")

        # ---- D · divisiones y jurisdicciones
        if u in geo:
            gz = geo[u]; cp = gz["capas"]
            ri = gz["regioes_intermediarias"][:6]
            filas_r = [[str(x["nombre"]), f0(x["electores"]), f1(x["lula_2v"]) + " %",
                        (f1(x["gob_1_pct"]) + " %") if x.get("gob_1_pct") is not None else "—"] for x in ri]
            ins = []
            bc = gz.get("bairros_capital")
            if bc and bc["mas_lula"] and bc["menos_lula"]:
                ins.append(insight("<b>Barrios de la capital:</b> donde más vota a Lula, "
                                   + ", ".join(f"{x['nombre']} ({f1(x['lula_2v'])} %)" for x in bc["mas_lula"][:3])
                                   + "; donde menos, " + ", ".join(f"{x['nombre']} ({f1(x['lula_2v'])} %)" for x in bc["menos_lula"][:3])
                                   + ". Barrios con 2.000 electores o más."))
            ins.append(insight("<b>Capas entregadas (GeoJSON y GeoPackage):</b> "
                               + f"{cp['regioes_intermediarias']['n']} regiões intermediárias, {cp['regioes_imediatas']['n']} imediatas, "
                               + f"{cp['municipios']['n']} municípios, {cp['distritos']['n']} distritos, "
                               + (f"{cp['bairros']['n']} barrios, " if 'bairros' in cp else "")
                               + f"{cp['zonas_eleitorais']['n']} zonas eleitorais (aprox.), {f0(cp['areas_escuelas']['n'])} áreas de escuela, "
                               + f"{f0(cp['locales']['n'])} escuelas y {f0(gz['secciones'])} mesas con coordenadas."))
            cuerpo = ('<div class="pag-div">' + fig(f"{u}_divisiones.svg", "fig fig-div")
                      + '<div class="dos-col"><div>' + fig(f"{u}_capital.svg", "fig fig-cap") + "</div><div>"
                      + '<h3 class="sub">Regiões intermediárias</h3>'
                      + tabla(["Región", "Electores", "Lula 2ª v.", f"{nombre(d['gob']['candidatos_1v'][0]['nombre'])} (gob.)"], filas_r,
                              num=(1, 2, 3))
                      + "".join(ins) + "</div></div></div>")
            D.pagina(cuerpo, kicker=f"{u} · {d['nombre'].upper()} · DIVISIONES Y JURISDICCIONES",
                     titulo="El voto por cada división del estado",
                     bajada="Lula, 2ª vuelta 2022, por município, região imediata y zona eleitoral; abajo, la capital por área de cada escuela.",
                     pie="Divisiones del IBGE (malla de setores 2022). Zonas eleitorais y áreas de escuela: aproximadas por cercanía a la escuela.")

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Brasil, estado por estado</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}{CSS_ESTADOS}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "informe.html").write_text(html, encoding="utf-8")
    chrome = next(c for c in CHROME if Path(c).exists())
    pdf = BRIEFS / f"ATLAS_Brasil_Estado_por_Estado_{hoy:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "informe.html").as_uri()], capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    log.info("PDF %s (%d páginas) desde %s", pdf.relative_to(ROOT).as_posix(), len(D.paginas), corrida.name)
    return pdf


if __name__ == "__main__":
    construir()
