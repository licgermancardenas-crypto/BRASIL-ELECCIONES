# -*- coding: utf-8 -*-
"""Piezas para redes con los hallazgos del balotaje al 15/10 (modelo, encuestas como
control, transferencias declaradas, territorio y municípios).

  · Instagram (marca neón, 1080x1350, PIL):  post_hallazgos_<fecha>.jpg
  · LinkedIn (línea marfil, HTML + Chrome):  carrusel_hallazgos_<fecha>/NN.jpg y
                                             ATLAS_carrusel_hallazgos_<fecha>.pdf
  · Textos de posteo: un .txt junto a cada pieza.

`cargar()` junta las cifras de todas las corridas; también la usa
src/viz/informe_hallazgos_pdf.py.

    python -m src.viz.redes_hallazgos_balotaje [--fecha 2026-10-15]
"""
import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from PIL import ImageDraw

import src.viz.carrusel_linkedin as cl
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.encuestas_balotaje_2026 import SALIDA_DIR as ENCUESTAS_2V_DIR
from src.models.territorio_balotaje_2026 import SALIDA_DIR as TERRITORIO_DIR
from src.models.transferencias_balotaje_2026 import SALIDA_DIR as TRANSFERENCIAS_DIR
from src.viz.anexo_municipios_pdf import UF_NOMBRE, tabla_municipios
from src.viz.post_pronostico import (BLANCO, BOLSO, F_DATOS, F_DISPLAY, F_TEXTO, H, LULA, NEON, SAFE_X, SALIDA, TEXTO,
                                     W, _f, cargar_municipios, fondo, grano, track)
from src.viz.brief_pdf import ultima
from src.viz.redes_balotaje import GRIS_TXT, cabecera, pie, titular

f1, f0 = cl.f1, cl.f0
mill = lambda x: f1(x / 1e6) + " M"
sg = lambda x: ("+" if x > 0 else "−" if x < 0 else "") + f1(abs(x))
CLARO_LULA, CLARO_FLAVIO = "#EBB7B2", "#B5C9E2"


# --------------------------------------------------------------------------- datos
def cargar() -> dict:
    ult = lambda d: sorted(p.parent for p in d.glob("*/resumen.json"))[-1]
    bal = ultima(BALOTAJE_DIR)
    enc, tra, ter = (ult(d) for d in (ENCUESTAS_2V_DIR, TRANSFERENCIAS_DIR, TERRITORIO_DIR))
    leer = lambda p: json.loads((p / "resumen.json").read_text(encoding="utf-8"))
    R, E, Tr, Tt = leer(bal), leer(enc), leer(tra), leer(ter)
    uf = pd.read_csv(ter / "por_uf.csv", index_col="uf")
    clave = pd.read_csv(ter / "municipios_clave.csv", index_col="codigo")
    t = tabla_municipios()

    terc = {k: v for k, v in Tr["bloques_validos"].items() if k in ("cury", "renan_santos", "caiado", "otros")}
    a_mod = sum(v["validos"] * v["a_lula_modelo"] for v in terc.values()) / sum(v["validos"] for v in terc.values())
    mn = pd.DataFrame(Tr["movilizacion_necesaria"])
    casc = Tr["cascada"]
    a_fl = (t["ganador_1v"] == "Flávio") & (t["ganador_2v_2022"] == "Lula")
    a_lu = (t["ganador_1v"] == "Lula") & (t["ganador_2v_2022"] == "Bolsonaro")
    mg = Tt["termometros"]["MG"]
    tam = Tt["por_tamano"]
    return {
        "R": R, "E": E, "Tr": Tr, "Tt": Tt, "uf": uf, "clave": clave, "t": t,
        "enc": pd.read_csv(enc / "encuestas.csv", parse_dates=["fecha_fin"]),
        "lula": R["montecarlo"]["lula_media"], "p_lula": R["montecarlo"]["prob_lula"],
        "p_flavio": R["montecarlo"]["prob_flavio"],
        "brecha": Tr["votos"]["brecha_flavio_menos_lula"],
        "a_mod": a_mod,
        "mov_necesaria": float(pd.Series(mn["movilizacion_neta_necesaria"].values,
                                         mn["a_lula_terceros"].values).sort_index().pipe(
            lambda s: s.reindex(s.index.union([a_mod])).interpolate("index")[a_mod])),
        "reserva_neta": Tt["totales"]["reserva_lula"] - Tt["totales"]["reserva_bolsonaro"],
        "terceros_neto": casc[1]["lula_pct"] - casc[0]["lula_pct"],
        "retencion_vale": Tr["solo_retencion_igual"] - casc[0]["lula_pct"],
        "perdida_pt_2022": 1 - Tr["retencion_modelo_2022"]["pt"],
        "perdida_bol_2022": 1 - Tr["retencion_modelo_2022"]["bolsonaro"],
        "techo": Tr["escenario_nexus_retencion_con_shock"],
        "n_lula": int((t["ganador_1v"] == "Lula").sum()), "n_flavio": int((t["ganador_1v"] == "Flávio").sum()),
        "padron_lula": t.loc[t["ganador_1v"] == "Lula", "electores"].sum() / t["electores"].sum(),
        "a_flavio": int(a_fl.sum()), "a_lula": int(a_lu.sum()),
        "grandes_a_flavio": t[a_fl].nlargest(6, "electores"),
        "cambios_uf": t.groupby("uf")["cambio_vs_2022"].sum().sort_values(ascending=False),
        "ajustados": t[t["margen_1v_pts"] < 2],
        "sp_juego": uf.loc["SP", "pct_en_juego"], "sp_margen": uf.loc["SP", "pct_margen_flavio"]
        if "pct_margen_flavio" in uf else uf.loc["SP", "pct_margen"],
        "sp_margen_votos": uf.loc["SP", "margen_flavio"],
        "pa": uf.loc["PA", "lula_pct"], "sp_capital": clave.loc[3550308, "lula_pct"],
        "mg": mg, "mg_umbral": 50 + mg["dif_nac_2026_1v"],
        "medianas": tam["100-500 mil"], "chicos": tam["< 20 mil"],
        "medianas_pct_margen": tam["100-500 mil"]["margen"] / Tt["totales"]["margen_flavio"],
        "capitales": Tt["capitales_vs_interior"]["capitales"],
        "giro_2018": E["movimiento_ultimos_dias_pp"]["2018"],
    }


# --------------------------------------------------------------------------- Instagram
def post(D, salida):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    cabecera(im, d, "BRASIL 2026 · BALOTAJE 25/10")
    y = titular(d, ["5 DATOS PARA", "ENTENDER EL", "BALOTAJE"],
                ["Qué dicen los resultados del 4/10, las encuestas y el mapa", "a diez días de la elección."], y=168)
    items = [
        (f"{f1(D['lula'])}%", LULA, "Lula en el pronóstico Atlas.",
         f"Las encuestas, aparte, dan {f1(D['E']['agregado_lula_validos'])}%. Flávio gana en el {D['p_flavio'] * 100:.0f}%."),
        (f"{D['a_flavio']}", BOLSO, "municipios pasaron de Lula a Flávio",
         "desde 2022. En sentido contrario, uno solo."),
        (f"{D['medianas_pct_margen'] * 100:.0f}%", BOLSO, "de la ventaja de Flávio sale de",
         "ciudades de 100 a 500 mil electores."),
        (f"+{f1(D['retencion_vale'])}", NEON, "pts vale que Lula retenga a sus",
         "votantes como Flávio. Más que los terceros."),
        (f"{f1(D['mg_umbral'])}%", BLANCO, "el número a mirar en Minas Gerais:",
         "si Lula lo supera, la elección está abierta."),
    ]
    y += 40
    for v, col, l1, l2 in items:
        d.line([(SAFE_X, y - 20), (W - SAFE_X, y - 20)], fill=(0xC4, 0x0B, 0xFF, 60))
        track(d, (SAFE_X, y + 46), v, _f(F_DISPLAY, 64), col, -0.02, "s")
        d.text((SAFE_X + 330, y + 8), l1, font=_f(F_TEXTO, 25), fill=BLANCO, anchor="la")
        d.text((SAFE_X + 330, y + 42), l2, font=_f(F_TEXTO, 22), fill=TEXTO, anchor="la")
        y += 118
    pie(d, ["Modelo Atlas sin encuestas: resultados del TSE por municipio, 2018, 2022 y 1ª vuelta 2026.",
            "Encuestas de 2ª vuelta y BTG/Nexus (10–12/10) solo como control. Válidos, sin blancos ni nulos."])
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


# --------------------------------------------------------------------------- figuras LinkedIn
def _barh(filas, xlim, fmt, nombre, alto=4.8, tam=14):
    fig, ax = plt.subplots(figsize=(8.6, alto))
    for i, (n, v, c) in enumerate(filas):
        ax.barh(i, v, color=c, height=0.62)
        ax.text(v + xlim * 0.012, i, fmt(v), va="center", fontsize=tam, color=cl.TINTA, weight="bold")
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=tam, color=cl.TINTA)
    ax.set_ylim(len(filas) - 0.4, -0.6)
    ax.set_xlim(0, xlim)
    ax.set_xticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, nombre)


def fig_encuestas(D):
    e = D["enc"].sort_values("fecha_fin")
    m, sd = D["lula"], D["E"]["modelo"]["sd"]
    fig, ax = plt.subplots(figsize=(8.6, 6.8))
    ax.axvspan(m - sd, m + sd, color="#DCD3EC", zorder=0)
    ax.axvline(m, color=cl.VIO, lw=2.5, zorder=1)
    ax.axvline(D["E"]["agregado_lula_validos"], color=cl.LULA, lw=2, ls=(0, (4, 3)), zorder=1)
    ax.axvline(50, color=cl.TINTA, lw=1)
    for i, r in enumerate(e.itertuples()):
        ax.scatter(r.lula_validos, i, s=90, color=cl.LULA, edgecolors=cl.PAPEL, linewidths=1.5, zorder=3)
    ax.set_yticks(range(len(e)), [f"{r.encuestadora_wiki} · {r.fecha_fin:%d/%m}" for r in e.itertuples()],
                  fontsize=12.5, color=cl.TINTA)
    ax.set_ylim(len(e) - 0.4, -1.6)
    ax.text(m, -1.25, f"Modelo {f1(m)}%", ha="right", fontsize=13, color=cl.VIO, weight="bold")
    ax.text(D["E"]["agregado_lula_validos"] + 0.1, -1.25, f"Encuestas {f1(D['E']['agregado_lula_validos'])}%",
            ha="left", fontsize=13, color=cl.LULA, weight="bold")
    ax.set_xlim(44, 52)
    ax.set_xticks([44, 46, 48, 50, 52], ["44%", "46%", "48%", "50%", "52%"], fontsize=12)
    ax.grid(axis="x", color="#E2DACD", lw=0.8, zorder=0)
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "encuestas.svg")


def fig_cambios(D):
    c = D["cambios_uf"].head(9)
    return _barh([(UF_NOMBRE[u], v, cl.FLAVIO) for u, v in c.items()], c.max() * 1.15, lambda v: f"{v:.0f}",
                 "cambios.svg", 5.2)


def fig_cascada(D):
    casc = D["Tr"]["cascada"]
    nombres = ["Modelo", "Terceros como\ndeclaran", "Abstencionistas\ncomo declaran", "Lula retiene\ncomo Flávio"]
    v = [p["lula_pct"] for p in casc]
    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    for i, x in enumerate(v):
        base = v[i - 1] if i else 46.8
        ax.bar(i, x - base, bottom=base, color=cl.VIO if i in (0, 3) else "#A79F92", width=0.6)
        ax.text(i, x + 0.07, f1(x) + "%" + (f"\n({sg(x - v[i - 1])})" if i else ""), ha="center", va="bottom",
                fontsize=13.5, color=cl.TINTA, weight="bold")
    ax.set_xticks(range(len(v)), nombres, fontsize=12.5, color=cl.TINTA)
    ax.set_ylim(46.8, 48.6)
    ax.set_yticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "cascada.svg")


def fig_tamano(D):
    tam = D["Tt"]["por_tamano"]
    filas = [(f"{k} electores\n({f0(v['municipios'])} municipios)", v["lula_pct"],
              cl.LULA if v["lula_pct"] > 50 else cl.FLAVIO) for k, v in tam.items()]
    return _barh(filas, 62, lambda x: f"{f1(x)}%", "tamano.svg", 4.6)


def fig_concentracion(D):
    u = D["uf"].sort_values("pct_en_juego", ascending=False).head(8)
    filas = [(UF_NOMBRE[k], r.pct_en_juego, cl.VIO if k == "SP" else "#A79F92") for k, r in u.iterrows()]
    return _barh(filas, 30, lambda x: f"{f1(x)}%", "concentracion.svg", 5.0)


def fig_variantes(D):
    E = D["E"]
    v = E["variantes_encuestas"]
    filas = [("Si se equivocan como en 2018", v["como_2018"]["media"], cl.LULA),
             ("Encuestas sin corregir", v["sin_corregir"]["media"], "#A79F92"),
             ("Modelo Atlas (sin encuestas)", D["lula"], cl.VIO),
             ("Si se equivocan como en 2022", v["como_2022"]["media"], cl.FLAVIO)]
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    for i, (n, x, c) in enumerate(filas):
        ax.plot([44, x], [i, i], color=c, lw=3, solid_capstyle="butt")
        ax.scatter(x, i, s=160, color=c, zorder=3, edgecolors=cl.PAPEL, linewidths=2)
        ax.text(x + 0.25, i, f"{f1(x)}%", va="center", fontsize=15, color=cl.TINTA, weight="bold")
    ax.axvline(50, color=cl.TINTA, lw=1)
    ax.text(50, -0.75, "50%", ha="center", fontsize=12, color=cl.MUTED)
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=13.5, color=cl.TINTA)
    ax.set_ylim(len(filas) - 0.4, -0.9)
    ax.set_xlim(44, 54.5)
    ax.set_xticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "variantes.svg")


def fig_termometros(D):
    t = D["Tt"]["termometros"]
    filas = [(UF_NOMBRE[k], v["termometro_mad"], cl.VIO if k == "MG" else "#A79F92") for k, v in t.items()]
    return _barh(filas, 10, lambda x: f"{f1(x)} pts", "termometros.svg", 3.9)


def mapa_cambios(D, nombre, ancho):
    t = D["t"]
    mun = cargar_municipios()
    mun["codigo"] = mun["codigo"].astype(int)
    g = t.reindex(mun["codigo"])
    col = []
    for a, b in zip(g["ganador_1v"], g["ganador_2v_2022"]):
        if a == "Flávio" and b == "Lula":
            col.append(cl.FLAVIO)
        elif a == "Lula" and b == "Bolsonaro":
            col.append(cl.LULA)
        elif a == "Lula":
            col.append(CLARO_LULA)
        elif a == "Flávio":
            col.append(CLARO_FLAVIO)
        else:
            col.append(cl.GRIS_MAPA)
    return cl.mapa_png(mun, col, nombre, ancho)


LEYENDA = (f'<span class="ley"><span><i style="background:{cl.FLAVIO}"></i>Pasó de Lula a Flávio</span>'
           f'<span><i style="background:{CLARO_FLAVIO}"></i>Sigue con el bolsonarismo</span>'
           f'<span><i style="background:{CLARO_LULA}"></i>Sigue con Lula</span></span>')


# --------------------------------------------------------------------------- carrusel
def carrusel(D, fecha, build, pdf, jpg_dir):
    cl.BUILD = build
    build.mkdir(parents=True, exist_ok=True)
    total = 9
    E, Tr = D["E"], D["Tr"]
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"

    def lamina(n, cuerpo, clase=""):
        return (f'<section class="l {clase}"><div class="top"><img src="{cl.LOGO.as_uri()}">'
                f'<span class="folio">{n:02d} / {total:02d}</span></div>{cuerpo}</section>')

    p = []
    mapa_cambios(D, "portada.png", 1520)
    p.append(lamina(1, f"""
      <div class="kicker">Brasil · balotaje del 25 de octubre</div>
      <h1>Dónde se decide el <em>balotaje</em></h1>
      <p class="sub">Siete hallazgos a diez días de la elección: el pronóstico, las encuestas, los votantes y el mapa.</p>
      <img class="mapa" src="portada.png">
      <div class="firma"><span>Atlas Analytics · {fecha_txt}</span>{LEYENDA}</div>
    """, "portada"))

    p.append(lamina(2, f"""
      <div class="kicker">1 · El pronóstico</div>
      <h1>Dos métodos independientes dan lo mismo: Flávio favorito</h1>
      <p class="sub">Lula en la 2ª vuelta, % de votos válidos. Cada punto es una encuesta publicada después del 4/10.</p>
      <div class="fig"><img src="{fig_encuestas(D)}"></div>
      <div class="cifras">
        <div><b style="color:{cl.VIO}">{f1(D['lula'])}%</b><span>Lula según el modelo, que no usa encuestas</span></div>
        <div><b style="color:{cl.LULA}">{f1(E['agregado_lula_validos'])}%</b><span>promedio de las encuestas, ajustado por casa</span></div>
        <div><b style="color:{cl.FLAVIO}">{D['p_flavio'] * 100:.0f}%</b><span>de las simulaciones gana Flávio</span></div>
      </div>
      <div class="fuente">Banda: ±1 desvío del modelo. {E['encuestas_con_flavio_adelante']} de {E['encuestas_post_1v']} encuestas dan a Flávio adelante; sin tendencia desde el 4/10.</div>
    """))

    p.append(lamina(3, f"""
      <div class="kicker">2 · Las encuestas no tienen un sesgo fijo</div>
      <h1>En 2018 subestimaron al PT, en 2022 lo sobreestimaron</h1>
      <p class="sub">Error del promedio de encuestas diez días antes del balotaje, en puntos para el candidato del PT.</p>
      <div class="cifras" style="margin-top:34px">
        <div><b style="color:{cl.FLAVIO}">{sg(E['track_record_horizonte'][0]['error_pp'])}</b><span>2018: Haddad terminó mejor de lo que decían</span></div>
        <div><b style="color:{cl.LULA}">{sg(E['track_record_horizonte'][1]['error_pp'])}</b><span>2022: Lula terminó peor de lo que decían</span></div>
        <div><b>{sg(D['giro_2018'])}</b><span>subió Haddad en los últimos diez días de 2018</span></div>
      </div>
      <div class="fig"><img src="{fig_variantes(D)}"></div>
      <p class="txt">Como el error cambia de signo, no se puede corregir: entra como incertidumbre. Con ese margen,
      las encuestas solas le dan a Lula <b>{E['encuestas']['prob_lula'] * 100:.0f}%</b> de chances. Si se repitiera el giro de 2018,
      llegaría a <b>{f1(E['variantes_encuestas']['como_2018']['media'])}%</b>: es lo único con precedente que le alcanza.</p>
      <div class="fuente">Lula en la 2ª vuelta, % de válidos, según cómo se equivoquen las encuestas. Promedio de encuestas publicadas en Wikipedia, mismo método para 2018, 2022 y 2026. Resultado oficial del TSE.</div>
    """))

    p.append(lamina(4, f"""
      <div class="kicker">3 · El mapa se corrió</div>
      <h1>{D['a_flavio']} municipios pasaron de Lula a Flávio desde 2022</h1>
      <p class="sub">Municipios que cambiaron de ganador entre la 2ª vuelta de 2022 y la 1ª de 2026, por estado.</p>
      <div class="fig"><img src="{fig_cambios(D)}"></div>
      <div class="cifras">
        <div><b>{D['a_lula']}</b><span>municipio hizo el camino inverso</span></div>
        <div><b>{f0(D['n_flavio'])}</b><span>municipios ganó Flávio el 4/10; Lula, {f0(D['n_lula'])}</span></div>
        <div><b>{D['padron_lula'] * 100:.0f}%</b><span>del padrón vive en los municipios que ganó Lula</span></div>
      </div>
      <div class="fuente">Los más grandes que cambiaron: {", ".join(f"{r.municipio} ({r.uf})" for r in D['grandes_a_flavio'].itertuples())}.</div>
    """))

    p.append(lamina(5, f"""
      <div class="kicker">4 · Los votantes</div>
      <h1>Los terceros se compensan. Lo que mueve es la retención de Lula</h1>
      <p class="sub">Lula en la 2ª vuelta, % de válidos, sumando lo que declaran los votantes (BTG/Nexus, 10–12/10).</p>
      <div class="fig"><img src="{fig_cascada(D)}"></div>
      <p class="txt">En 2022, el <b>{f1(D['perdida_pt_2022'] * 100)}%</b> de los votantes de Lula de la 1ª vuelta no fue al balotaje;
      de los de Bolsonaro, el {f1(D['perdida_bol_2022'] * 100)}%. Si esta vez Lula retiene como Flávio, suma
      <b>{sg(D['retencion_vale'])} pts</b>, más que todos los terceros juntos.</p>
      <div class="fuente">Encuesta combinada con el modelo según su tamaño (beta-binomial): los subgrupos tienen entre 2 y 125 casos.</div>
    """))

    m, ch = D["medianas"], D["chicos"]
    p.append(lamina(6, f"""
      <div class="kicker">5 · El tamaño de la ciudad</div>
      <h1>Flávio construye su ventaja en las ciudades medianas</h1>
      <p class="sub">Lula en la 2ª vuelta según el modelo, por tamaño de municipio (electores).</p>
      <div class="fig"><img src="{fig_tamano(D)}"></div>
      <div class="cifras">
        <div><b style="color:{cl.FLAVIO}">{D['medianas_pct_margen'] * 100:.0f}%</b><span>del margen de Flávio sale de las ciudades de 100 a 500 mil</span></div>
        <div><b style="color:{cl.FLAVIO}">{mill(m['margen'])}</b><span>de ventaja en esas {m['municipios']} ciudades</span></div>
        <div><b style="color:{cl.LULA}">{f1(ch['lula_pct'])}%</b><span>Lula en los {f0(ch['municipios'])} municipios de menos de 20 mil</span></div>
      </div>
      <div class="fuente">Pronóstico municipal del modelo Atlas para el 25/10, agregado por tamaño de padrón.</div>
    """))

    p.append(lamina(7, f"""
      <div class="kicker">6 · São Paulo</div>
      <h1>Uno de cada cuatro votos en juego está en São Paulo</h1>
      <p class="sub">Parte de los votos en juego (terceros y votantes de 2022 que no fueron el 4/10), por estado.</p>
      <div class="fig"><img src="{fig_concentracion(D)}"></div>
      <div class="cifras">
        <div><b style="color:{cl.FLAVIO}">{mill(D['sp_margen_votos'])}</b><span>de ventaja de Flávio en SP, el {D['sp_margen']:.0f}% de su margen nacional</span></div>
        <div><b>{D['Tt']['concentracion']['top5_pct']:.0f}%</b><span>de lo que está en juego, en SP, MG, BA, RJ y PR</span></div>
        <div><b>{f1(D['sp_capital'])}%</b><span>Lula en São Paulo capital: empate</span></div>
      </div>
      <div class="fuente">Modelo Atlas. Votos en juego: votos de terceros más la reserva de abstencionistas de 2022 de cada lado.</div>
    """))

    mg = D["mg"]
    p.append(lamina(8, f"""
      <div class="kicker">7 · La noche del 25</div>
      <h1>Minas Gerais es el termómetro: mirar el {f1(D['mg_umbral'])}%</h1>
      <p class="sub">Diferencia entre Lula en Minas Gerais y Lula en todo Brasil, en puntos.</p>
      <table style="margin-top:34px">
        <tr><td class="a">2018</td><td>Balotaje Haddad–Bolsonaro</td><td class="r">{sg(mg['dif_nac_2018'])} pts</td></tr>
        <tr><td class="a">2022</td><td>Balotaje Lula–Bolsonaro</td><td class="r">{sg(mg['dif_nac_2022'])} pts</td></tr>
        <tr class="hoy"><td class="a">2026</td><td>1ª vuelta, Lula vs. el bolsonarismo</td><td class="r">{sg(mg['dif_nac_2026_1v'])} pts</td></tr>
      </table>
      <p class="txt" style="margin-top:30px">Es el estado que mejor siguió al resultado nacional en las tres últimas votaciones
      (desvío medio de {f1(mg['termometro_mad'])} pts). Si en el conteo de MG Lula pasa del <b>{f1(D['mg_umbral'])}%</b>, la elección está abierta.
      Otros dos datos para esa noche: <b>Pará</b> está en {f1(D['pa'])}% y <b>São Paulo capital</b> en {f1(D['sp_capital'])}%.</p>
      <div class="fig"><img src="{fig_termometros(D)}"></div>
      <div class="fuente" style="margin-top:0">Desvío medio de cada estado respecto del resultado nacional de Lula, 2018, 2022 y 2026.</div>
      <div class="cifras">
        <div><b>{len(D['ajustados'])}</b><span>municipios se definieron el 4/10 por menos de 2 puntos</span></div>
        <div><b>{mill(D['brecha'])}</b><span>votos de brecha a cerrar para Lula</span></div>
        <div><b>{f1(D['techo']['media'])}%</b><span>Lula si todo sale como declaran los votantes</span></div>
      </div>
    """))

    p.append(lamina(9, f"""
      <div class="kicker">Cómo se hizo</div>
      <h1>Resultados oficiales para pronosticar; encuestas solo para controlar</h1>
      <dl>
        <dt>Pronóstico</dt><dd>Resultados del TSE por municipio de 2018, 2022 y la 1ª vuelta de 2026. Regresión ecológica y {f0(D['R']['montecarlo']['n'])} simulaciones.</dd>
        <dt>Control</dt><dd>{E['encuestas_post_1v']} encuestas de 2ª vuelta, ajustadas por casa y comparadas con su error en 2018 y 2022.</dd>
        <dt>Votantes</dt><dd>Transferencias declaradas de BTG/Nexus (10–12/10), combinadas con el modelo según el tamaño de cada subgrupo.</dd>
        <dt>Territorio</dt><dd>5.571 municipios: votos en juego, tamaño de ciudad, estados termómetro y cambios de ganador desde 2022.</dd>
      </dl>
      <div class="cierre"><img src="{cl.LOGO_V.as_uri()}">
        <div><b>Atlas Analytics</b><br>Análisis electoral y territorial<br>atlas-analytics.site</div></div>
    """))

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Hallazgos balotaje</title>'
            f'<style>{cl.CSS}.portada .mapa {{ bottom: 150px; }} .portada .ley {{ gap: 16px; font-size: 13.5px; }}</style>'
            f'</head><body>{"".join(p)}</body></html>')
    out = build / "carrusel.html"
    out.write_text(html, encoding="utf-8")
    chrome = next((c for c in cl.CHROME if Path(c).exists()), None)
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--allow-file-access-from-files", f"--print-to-pdf={pdf}", out.as_uri()],
                       capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")
    jpg_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    for i, pg in enumerate(doc, 1):
        z = 1080 / pg.rect.width
        pg.get_pixmap(matrix=fitz.Matrix(z, z)).save(jpg_dir / f"{i:02d}.jpg", jpg_quality=94)
    return doc.page_count


# --------------------------------------------------------------------------- textos
def textos(D) -> dict:
    E = D["E"]
    linkedin = f"""A diez días del balotaje en Brasil, junté todo lo que analizamos en Atlas en siete hallazgos.

1. Dos métodos independientes dan lo mismo. Nuestro modelo, que solo usa resultados oficiales del TSE, deja a Lula en {f1(D['lula'])}% de los votos válidos. El promedio de las {E['encuestas_post_1v']} encuestas publicadas después del 4/10, que el modelo no usa, da {f1(E['agregado_lula_validos'])}%. Flávio Bolsonaro gana en el {D['p_flavio'] * 100:.0f}% de las simulaciones.

2. Las encuestas de balotaje no tienen un sesgo fijo. A diez días de la elección, en 2018 subestimaban al PT por {f1(abs(E['track_record_horizonte'][0]['error_pp']))} puntos y en 2022 lo sobreestimaban por {f1(E['track_record_horizonte'][1]['error_pp'])}. No se corrige: es incertidumbre.

3. El mapa se corrió. {D['a_flavio']} municipios pasaron de Lula a Flávio desde 2022; en sentido contrario, uno solo. Lula ganó {f0(D['n_lula'])} municipios el 4/10, pero ahí vive solo el {D['padron_lula'] * 100:.0f}% del padrón.

4. Los terceros se compensan entre sí. Lo que más mueve es la retención: en 2022, el {f1(D['perdida_pt_2022'] * 100)}% de los votantes de Lula de la 1ª vuelta no fue al balotaje, contra el {f1(D['perdida_bol_2022'] * 100)}% de los de Bolsonaro. Retener como Flávio vale {sg(D['retencion_vale'])} puntos.

5. Flávio construye su ventaja en las ciudades medianas: las de 100 a 500 mil electores le dan el {D['medianas_pct_margen'] * 100:.0f}% de su margen. Lula gana en los pueblos chicos.

6. Uno de cada cuatro votos en juego está en São Paulo, y ahí Flávio saca {mill(D['sp_margen_votos'])} de ventaja.

7. La noche del 25, mirar Minas Gerais. Si Lula pasa del {f1(D['mg_umbral'])}% en MG, la elección está abierta.

En el carrusel están los gráficos y el método.

#Brasil2026 #AnálisisElectoral #DatosAbiertos #Elecciones"""
    ig = f"""5 datos para entender el balotaje de Brasil a diez días del 25/10.

{f1(D['lula'])}%: Lula en el pronóstico Atlas, que no usa encuestas. Las encuestas, aparte, dan {f1(E['agregado_lula_validos'])}%.
{D['a_flavio']}: municipios que pasaron de Lula a Flávio desde 2022. Al revés, uno solo.
{D['medianas_pct_margen'] * 100:.0f}%: la parte de la ventaja de Flávio que sale de ciudades de 100 a 500 mil electores.
{sg(D['retencion_vale'])} pts: lo que vale que Lula retenga a sus votantes como Flávio. Más que todos los terceros.
{f1(D['mg_umbral'])}%: el número a mirar en Minas Gerais la noche del 25.

Resultados del TSE por municipio; encuestas y BTG/Nexus solo como control.

#AtlasAnalytics #Brasil2026 #EleiçõesBrasil #Elecciones #DataViz"""
    return {"linkedin": linkedin, "ig": ig}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    fecha = ap.parse_args(argv).fecha
    D = cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    T = textos(D)
    out = SALIDA / f"post_hallazgos_{fecha}.jpg"
    post(D, out)
    out.with_suffix(".txt").write_text(T["ig"], encoding="utf-8")
    print(out)
    pdf = SALIDA / f"ATLAS_carrusel_hallazgos_{fecha}.pdf"
    n = carrusel(D, fecha, SALIDA / "_build_carrusel_hallazgos", pdf, SALIDA / f"carrusel_hallazgos_{fecha}")
    pdf.with_suffix(".txt").write_text(T["linkedin"], encoding="utf-8")
    print(pdf, f"({n} láminas)")


if __name__ == "__main__":
    main()
