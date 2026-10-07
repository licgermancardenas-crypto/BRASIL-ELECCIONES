# -*- coding: utf-8 -*-
"""Piezas para redes sobre el balotaje del 25/10/2026 (sin encuestas).

  · Instagram (marca neón de Atlas, 1080x1350, PIL, como post_pronostico.py):
      post_balotaje_terceros_<fecha>.jpg   Lula necesita el X % de los terceros
      post_balotaje_reserva_<fecha>.jpg    la reserva de abstencionistas no alcanza
  · LinkedIn (línea editorial marfil, HTML + Chrome, como carrusel_linkedin.py):
      carrusel_balotaje_<fecha>/NN.jpg y ATLAS_carrusel_balotaje_<fecha>.pdf
  · Textos de posteo: un .txt junto a cada pieza.

Insumos: última corrida de src/models/balotaje_2026.py y de
src/models/movilizacion_2026.py, resultado final de la 1ª vuelta por município
y locales 2018/2022 (para lo que hicieron los terceros en esas elecciones).

    python -m src.viz.redes_balotaje [--fecha 2026-10-07]
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
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import src.viz.carrusel_linkedin as cl
from src.etl.transform.base_locales import salida as salida_locales
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.conteo_2026 import SALIDA_FINAL as RESULTADO_2026
from src.models.movilizacion_2026 import SALIDA_DIR as MOVILIZACION_DIR
from src.viz.post_pronostico import (BLANCO, BOLSO, F_DATOS, F_DATOS_B, F_DISPLAY, F_TEXTO, H, LILA, LOGO_H, LULA, NEON,
                                     SAFE_B, SAFE_X, SALIDA, TEXTO, VIOLETA, W, _f, cargar_municipios, fondo, grano,
                                     pct, track)

GRIS_TXT = (0xB8, 0xA4, 0xCC)
FONDO_BARRA = (0x2C, 0x00, 0x56)
TERC = {"cury": "Cury", "renan_santos": "Renan Santos", "caiado": "Caiado", "otros": "Zema y otros"}
f1, f0 = cl.f1, cl.f0
mill = lambda x: f1(x / 1e6) + " M"


# --------------------------------------------------------------------------- datos
def ultima(base: Path) -> Path:
    return sorted(p.parent for p in base.glob("*/meta.json"))[-1]


def terceros_historicos() -> dict:
    """Parte del voto 'del resto' de la 1ª vuelta que ganó el PT en la 2ª (votos válidos, nacional)."""
    out = {}
    for ano in (2018, 2022):
        loc = pd.read_parquet(salida_locales(ano))
        v1 = loc[[c for c in loc.columns if c.endswith("_1") and not c.startswith(("blanco", "abst", "compar"))]].sum().sum()
        v2 = loc["pt_2"].sum() + loc["bolsonaro_2"].sum()
        pt1, bol1 = loc["pt_1"].sum() / v1, loc["bolsonaro_1"].sum() / v1
        pt2 = loc["pt_2"].sum() / v2
        out[ano] = (pt2 - pt1) / (1 - pt1 - bol1)
    return out


def cargar() -> dict:
    bal, mov = ultima(BALOTAJE_DIR), ultima(MOVILIZACION_DIR)
    R = json.loads((bal / "resumen.json").read_text(encoding="utf-8"))
    M = json.loads((mov / "resumen.json").read_text(encoding="utf-8"))
    s = pd.DataFrame(R["sensibilidad"])
    pend, ord0 = np.polyfit(s["a_lula_terceros"], s["lula_pct"], 1)
    pv = R["primera_vuelta"]
    terc = pv["terceros"]
    n_terc = sum(terc.values())
    a_r = R["a_lula_terceros"]["R"]
    return {
        "R": R, "M": M, "bt": pd.read_csv(bal / "backtest.csv"),
        "quiebre": (50 - ord0) / pend, "pend": pend, "ord0": ord0,
        "pv": pv, "terc": terc, "n_terc": n_terc,
        "a_modelo": sum(a_r[k] * terc[k] for k in terc) / n_terc,
        "necesita_simple": (pv["validos"] / 2 - pv["lula"]) / n_terc,
        "brecha_1v": pv["flavio"] - pv["lula"],
        "hist": terceros_historicos(),
    }


# --------------------------------------------------------------------------- Instagram
def cabecera(im, d, kicker):
    yb = 92
    d.rectangle([SAFE_X, yb - 13, SAFE_X + 3, yb + 13], fill=VIOLETA)
    track(d, (SAFE_X + 20, yb), kicker, _f(F_DATOS, 21), NEON, 0.22, "m")
    lg = Image.open(LOGO_H).convert("RGBA")
    lg = lg.resize((round(lg.width * 34 / lg.height), 34), Image.LANCZOS)
    im.alpha_composite(lg, (W - SAFE_X - lg.width, yb - lg.height // 2))
    d.line([(SAFE_X, yb + 40), (W - SAFE_X, yb + 40)], fill=(0xC4, 0x0B, 0xFF, 70))


def titular(d, lineas, sub, y=168):
    for ln in lineas:
        track(d, (SAFE_X, y), ln, _f(F_DISPLAY, 80), BLANCO, -0.02, "a")
        y += 88
    y += 14
    for ln in sub:
        d.text((SAFE_X, y), ln, font=_f(F_TEXTO, 25), fill=TEXTO, anchor="la")
        y += 34
    return y


def cifras(d, y, items):
    """Fila de cifras: (valor, color, línea 1, línea 2)."""
    ancho = (W - 2 * SAFE_X) / len(items)
    d.line([(SAFE_X, y - 26), (W - SAFE_X, y - 26)], fill=(0xC4, 0x0B, 0xFF, 70))
    for i, (v, col, l1, l2) in enumerate(items):
        x = SAFE_X + i * ancho
        if i:
            d.line([(x - 18, y - 6), (x - 18, y + 120)], fill=(0xC4, 0x0B, 0xFF, 60))
        track(d, (x, y), v, _f(F_DISPLAY, 52), col, -0.02, "a")
        d.text((x, y + 70), l1, font=_f(F_TEXTO, 20), fill=TEXTO, anchor="la")
        d.text((x, y + 96), l2, font=_f(F_TEXTO, 20), fill=TEXTO, anchor="la")


def pie(d, notas):
    yp = H - SAFE_B - 8
    yn = yp - 34 - 10 - 24 * len(notas)
    for ln in notas:
        d.text((SAFE_X, yn), ln, font=_f(F_TEXTO, 16), fill=GRIS_TXT, anchor="la")
        yn += 24
    d.line([(SAFE_X, yp - 34), (W - SAFE_X, yp - 34)], fill=(0xC4, 0x0B, 0xFF, 70))
    track(d, (SAFE_X, yp), "ATLAS ANALYTICS · ATLAS-ANALYTICS.SITE", _f(F_DATOS, 17), LILA, 0.18, "s")


def post_terceros(D, salida):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    q = D["quiebre"]
    cabecera(im, d, "BRASIL 2026 · BALOTAJE 25/10")
    titular(d, ["LULA NECESITA", f"EL {q * 100:.0f}% DE LOS", "TERCEROS"],
            [f"Para empatar con Flávio Bolsonaro tendría que llevarse casi {round(q * 10)} de cada 10",
             "votos de Cury, Renan Santos, Caiado y Zema. Ni en 2018 el PT llegó a tanto."])

    # escala 0-100 %
    x0, x1, yb = SAFE_X, W - SAFE_X, 760
    X = lambda p: x0 + (x1 - x0) * p
    d.rectangle([x0, yb - 7, x1, yb + 7], fill=FONDO_BARRA)
    d.rectangle([x0, yb - 7, X(D["a_modelo"]), yb + 7], fill=NEON)
    marcas = [  # (valor, color, etiqueta, arriba)
        (D["hist"][2022], GRIS_TXT, [f"2022: {D['hist'][2022] * 100:.0f}%", "a Lula"], False),
        (D["a_modelo"], NEON, [f"MODELO: {D['a_modelo'] * 100:.0f}%", "lo esperable hoy"], True),
        (D["hist"][2018], GRIS_TXT, [f"2018: {D['hist'][2018] * 100:.0f}%", "a Haddad"], False),
        (q, LULA, [f"NECESITA {q * 100:.0f}%", "para empatar"], True),
    ]
    for v, col, lab, arriba in marcas:
        x = X(v)
        d.line([(x, yb - 30), (x, yb + 30)], fill=col, width=4 if col == LULA else 3)
        ancla = "ra" if v > 0.8 else "la" if v < 0.2 else "ma"
        yy = yb - 104 if arriba else yb + 44
        d.text((x, yy), lab[0], font=_f(F_DATOS_B, 24), fill=col, anchor=ancla)
        d.text((x, yy + 32), lab[1], font=_f(F_TEXTO, 19), fill=TEXTO, anchor=ancla)
    for p in (0, 0.5, 1):
        d.text((X(p), yb + 128), f"{p * 100:.0f}%", font=_f(F_DATOS, 17), fill=GRIS_TXT,
               anchor="la" if p == 0 else "ra" if p == 1 else "ma")
    d.text((SAFE_X, yb + 160), "Parte de los votantes de terceros que elige a Lula (entre los que votan a alguien)",
           font=_f(F_TEXTO, 18), fill=GRIS_TXT, anchor="la")

    R = D["R"]
    cifras(d, 1000, [(mill(D["brecha_1v"]), BOLSO, "de ventaja de Flávio", "en la 1ª vuelta"),
                     (mill(D["n_terc"]), NEON, "votos de terceros", "en juego"),
                     (f"{pct(R['montecarlo']['lula_media'], 1)}%", LULA, "Lula en la 2ª vuelta", "según el modelo")])
    pie(d, [f"Con la retención y la participación de la 2ª vuelta de 2022. Si nadie entrara ni saliera, le alcanzaría con "
            f"{D['necesita_simple'] * 100:.0f}%.",
            "2018 y 2022: lo que el PT sacó del voto de los demás candidatos entre vueltas. TSE; modelo Atlas sin encuestas."])
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


def post_reserva(D, salida):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    M = D["M"]
    res, falta = M["reserva"], M["lo_que_hace_falta"]
    cabecera(im, d, "BRASIL 2026 · BALOTAJE 25/10")
    titular(d, ["LA RESERVA", "DE LULA", "NO ALCANZA"],
            [f"{mill(res['de_lula_2022'])} de votantes de Lula en 2022 no fueron a votar el 4/10.",
             f"Aunque volvieran todos, la brecha a cerrar es de {mill(falta['brecha_votos'])}."])

    filas = [("BRECHA A CERRAR EL 25/10", falta["brecha_votos"], BLANCO),
             ("VOTARON LULA EN 2022, NO VOTARON EL 4/10", res["de_lula_2022"], LULA),
             ("VOTARON BOLSONARO EN 2022, NO VOTARON EL 4/10", res["de_bolsonaro_2022"], BOLSO)]
    y, x0, x1 = 600, SAFE_X, W - SAFE_X - 150
    tope = max(v for _, v, _ in filas) * 1.02
    for et, v, col in filas:
        track(d, (x0, y), et, _f(F_DATOS, 19), GRIS_TXT, 0.12, "a")
        d.rectangle([x0, y + 36, x1, y + 70], fill=FONDO_BARRA)
        d.rectangle([x0, y + 36, x0 + (x1 - x0) * v / tope, y + 70], fill=col)
        d.text((W - SAFE_X, y + 53), mill(v), font=_f(F_DISPLAY, 40), fill=col, anchor="rm")
        y += 118
    xb = x0 + (x1 - x0) * falta["brecha_votos"] / tope
    for yy in range(600 + 36, y - 40, 14):
        d.line([(xb, yy), (xb, yy + 7)], fill=(0xFF, 0xFF, 0xFF, 150), width=2)

    sp = M["top_municipios_reserva_neta"][0]
    cifras(d, 1000, [(f"{falta['pp_menos_abstencion_para_empatar']:.0f} pp", LULA, "debería bajar la abstención",
                      "donde ganó Lula en 2022"),
                     (f"{pct(falta['mayor_baja_historica_entre_vueltas_pp'], 1)} pp", NEON, "mayor cambio entre",
                      "vueltas, 2018 y 2022"),
                     (f"{sp['reserva_neta'] / 1e3:.0f} mil", BLANCO, "reserva neta en", "São Paulo capital")])
    pie(d, ["Estimación ecológica con resultados del TSE por município (2ª vuelta 2022 y 1ª vuelta 2026).",
            f"Brecha: pronóstico Atlas para el balotaje, Lula {pct(D['R']['montecarlo']['lula_media'], 1)}% de los válidos."])
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


# --------------------------------------------------------------------------- LinkedIn
def fig_primera(D):
    pv = D["pv"]
    val = pv["validos"]
    filas = [("Flávio Bolsonaro", pv["flavio"], cl.FLAVIO), ("Lula", pv["lula"], cl.LULA)] + \
            [(TERC[k], v, "#A79F92") for k, v in sorted(D["terc"].items(), key=lambda kv: -kv[1])]
    fig, ax = plt.subplots(figsize=(8.6, 5.0))
    for i, (n, v, c) in enumerate(filas):
        ax.barh(i, v / val * 100, color=c, height=0.62)
        ax.text(v / val * 100 + 0.8, i, f"{f1(v / val * 100)}%", va="center", fontsize=14, color=cl.TINTA, weight="bold")
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=14, color=cl.TINTA)
    ax.set_ylim(len(filas) - 0.4, -0.6)
    ax.set_xlim(0, 58)
    ax.set_xticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "primera.svg")


def fig_origen(D):
    comp = D["R"]["composicion_terceros_por_origen_2022"]
    orden = sorted(comp, key=lambda k: -D["terc"][k])
    cols = {"pt": (cl.LULA, "Lula"), "bolsonaro": (cl.FLAVIO, "Bolsonaro"),
            "blanco_nulo": ("#A79F92", "Blanco o nulo"), "abstencion": ("#D9D1C3", "No votó")}
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    for i, t in enumerate(orden):
        x = 0
        for o, (c, _) in cols.items():
            w = comp[t][o] * 100
            ax.barh(i, w, left=x, color=c, height=0.62, edgecolor=cl.PAPEL, linewidth=1.5)
            if w >= 8:
                ax.text(x + w / 2, i, f"{w:.0f}", ha="center", va="center", fontsize=14, weight="bold",
                        color="white" if o != "abstencion" else cl.TINTA)
            x += w
    ax.set_yticks(range(len(orden)), [TERC[t] for t in orden], fontsize=14, color=cl.TINTA)
    ax.set_ylim(len(orden) - 0.4, -0.6)
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c, _ in cols.values()],
              labels=[e for _, e in cols.values()], ncol=4, frameon=False, fontsize=13,
              loc="upper left", bbox_to_anchor=(0, 1.12), handlelength=1)
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "origen.svg")


def fig_curva(D):
    q, a = D["quiebre"], D["a_modelo"]
    x = np.linspace(0.2, 0.95, 50)
    y = D["pend"] * x + D["ord0"]
    fig, ax = plt.subplots(figsize=(8.6, 5.6))
    ax.axhline(50, color=cl.TINTA, lw=1)
    for ano, c in ((2022, "#D9D1C3"), (2018, "#E9CFC9")):
        h = D["hist"][ano] * 100
        ax.axvspan(h - 2.5, h + 2.5, color=c, zorder=0)
        ax.text(h, 45.25, f"{ano}\n{h:.0f}%", ha="center", fontsize=12, color=cl.MUTED)
    ax.plot(x * 100, y, color=cl.VIO, lw=3, zorder=2)
    yl = D["pend"] * a + D["ord0"]
    ax.scatter([a * 100], [yl], s=110, color=cl.VIO, zorder=3, edgecolors=cl.PAPEL, linewidths=2)
    ax.annotate(f"Modelo: {a * 100:.0f}% → Lula {f1(yl)}%", (a * 100, yl), xytext=(14, -6), textcoords="offset points",
                fontsize=14, color=cl.TINTA, weight="bold", va="top")
    ax.axvline(q * 100, color=cl.LULA, lw=1.5, ls=(0, (4, 3)))
    ax.text(q * 100 - 1.2, 51.3, f"Empate: {q * 100:.0f}%", ha="right", fontsize=14, color=cl.LULA, weight="bold")
    ax.set_xlim(20, 95)
    ax.set_ylim(45, 52)
    ax.set_xticks([20, 40, 60, 80], ["20%", "40%", "60%", "80%"], fontsize=13)
    ax.set_yticks([46, 48, 50, 52], ["46%", "48%", "50%", "52%"], fontsize=13)
    ax.grid(axis="y", color="#E2DACD", lw=0.8, zorder=0)
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "curva.svg")


def fig_reserva(D):
    res, falta = D["M"]["reserva"], D["M"]["lo_que_hace_falta"]
    filas = [("Brecha a cerrar", falta["brecha_votos"], cl.TINTA),
             ("Votaron Lula en 2022,\nno votaron el 4/10", res["de_lula_2022"], cl.LULA),
             ("Votaron Bolsonaro en 2022,\nno votaron el 4/10", res["de_bolsonaro_2022"], cl.FLAVIO)]
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    for i, (n, v, c) in enumerate(filas):
        ax.barh(i, v / 1e6, color=c, height=0.6)
        ax.text(v / 1e6 + 0.12, i, mill(v), va="center", fontsize=16, color=cl.TINTA, weight="bold")
    ax.axvline(falta["brecha_votos"] / 1e6, color=cl.TINTA, lw=1, ls=(0, (3, 3)))
    ax.set_yticks(range(len(filas)), [n for n, _, _ in filas], fontsize=14, color=cl.TINTA)
    ax.set_ylim(len(filas) - 0.4, -0.6)
    ax.set_xlim(0, 7.8)
    ax.set_xticks([])
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "reserva.svg")


def fig_backtest(D):
    b = D["bt"][D["bt"]["metodo"] == "R"]
    fig, ax = plt.subplots(figsize=(7.4, 6.4))
    ax.plot([15, 80], [15, 80], color=cl.MUTED, lw=1, ls=(0, (3, 3)))
    ax.scatter(b["real"], b["predicho"], s=70, color=cl.VIO, edgecolors=cl.PAPEL, linewidths=1.2, zorder=3)
    for r in b.itertuples():
        if r.uf in ("SP", "MG", "RJ", "BA", "SC", "PI"):
            ax.annotate(r.uf, (r.real, r.predicho), xytext=(7, -4), textcoords="offset points", fontsize=12,
                        color=cl.MUTED, fontfamily="Consolas")
    ax.set_xlim(15, 80)
    ax.set_ylim(15, 80)
    ax.set_aspect("equal")
    ax.set_xlabel("Lula real, 2ª vuelta 2022", fontsize=13, color=cl.MUTED)
    ax.set_ylabel("Lula predicho desde la 1ª vuelta", fontsize=13, color=cl.MUTED)
    ax.set_xticks([20, 40, 60, 80], ["20%", "40%", "60%", "80%"], fontsize=12)
    ax.set_yticks([20, 40, 60, 80], ["20%", "40%", "60%", "80%"], fontsize=12)
    ax.grid(color="#E2DACD", lw=0.8, zorder=0)
    cl.limpiar(ax)
    return cl.guardar_svg(fig, "backtest.svg")


def carrusel(D, fecha, build, pdf, jpg_dir):
    cl.BUILD = build          # mapa_png y guardar_svg escriben en cl.BUILD
    build.mkdir(parents=True, exist_ok=True)
    total = 7

    def lamina(n, cuerpo, clase=""):
        return (f'<section class="l {clase}"><div class="top"><img src="{cl.LOGO.as_uri()}">'
                f'<span class="folio">{n:02d} / {total:02d}</span></div>{cuerpo}</section>')

    R, M, pv = D["R"], D["M"], D["pv"]
    mc, bt = R["montecarlo"], R["backtest_2022"]
    res, falta = M["reserva"], M["lo_que_hace_falta"]
    q, a = D["quiebre"], D["a_modelo"]
    fecha_txt = f"{fecha.day} de octubre de {fecha.year}"
    paginas = []

    # 1 · portada
    mun = cargar_municipios()
    r = pd.read_parquet(RESULTADO_2026)
    r["lula_2026"] = 100 * r["lula"] / (r["lula"] + r["flavio_bolsonaro"])
    mun = mun.assign(codigo=mun.codigo.astype(int)).merge(r[["codigo", "lula_2026"]].astype({"codigo": int}),
                                                          on="codigo", how="left")
    cl.mapa_png(mun, cl.colores_voto(mun["lula_2026"]), "portada.png", 1520)
    paginas.append(lamina(1, f"""
      <div class="kicker">Brasil · balotaje del 25 de octubre</div>
      <h1>La cuenta que Lula <em>no logra</em> cerrar</h1>
      <p class="sub">Qué dicen los resultados de la primera vuelta sobre el balotaje, sin una sola encuesta.</p>
      <img class="mapa" src="portada.png">
      <div class="firma"><span>Atlas Analytics · {fecha_txt}</span>
        <span class="ley">Flávio<span class="grad" style="background:linear-gradient(90deg,{cl.FLAVIO},#EDE6DA,{cl.LULA})"></span>Lula</span></div>
    """, "portada"))

    # 2 · punto de partida
    paginas.append(lamina(2, f"""
      <div class="kicker">Primera vuelta</div>
      <h1>Flávio Bolsonaro llega con {mill(D['brecha_1v'])} de votos de ventaja</h1>
      <p class="sub">Resultado del 4 de octubre, en votos válidos.</p>
      <div class="fig"><img src="{fig_primera(D)}"></div>
      <div class="cifras">
        <div><b>{mill(D['n_terc'])}</b><span>votos de los candidatos que quedaron afuera</span></div>
        <div><b>{D['necesita_simple'] * 100:.0f}%</b><span>de esos votos necesita Lula si votan exactamente los mismos</span></div>
      </div>
      <div class="fuente">TSE, divulgación oficial al 100% de las secciones, con el exterior.</div>
    """))

    # 3 · origen de los terceros
    comp = R["composicion_terceros_por_origen_2022"]
    paginas.append(lamina(3, f"""
      <div class="kicker">De dónde vienen los terceros</div>
      <h1>Sus votantes venían más del bolsonarismo que de Lula</h1>
      <p class="sub">Qué votó en la segunda vuelta de 2022 cada electorado de tercero de 2026, de cada 100.</p>
      <div class="fig"><img src="{fig_origen(D)}"></div>
      <p class="txt">De cada 100 votantes de Cury, {comp['cury']['pt'] * 100:.0f} habían votado a Lula en 2022 y
      {comp['cury']['bolsonaro'] * 100:.0f} a Bolsonaro. Si cada uno vuelve a su lado, Lula se lleva
      <b>{a * 100:.0f}%</b> de los votos de terceros.</p>
      <div class="fuente">Regresión ecológica con restricciones entre 5.570 municipios, por estado. Describe territorios, no personas.</div>
    """))

    # 4 · el umbral
    paginas.append(lamina(4, f"""
      <div class="kicker">El umbral</div>
      <h1>Para empatar, Lula necesitaría el {q * 100:.0f}% de esos votos</h1>
      <p class="sub">Voto de Lula en la segunda vuelta según qué parte de los votantes de terceros lo elija.</p>
      <div class="fig"><img src="{fig_curva(D)}"></div>
      <p class="txt">El umbral es más alto que el {D['necesita_simple'] * 100:.0f}% de la cuenta simple porque en 2022 la segunda
      vuelta movilizó más a Bolsonaro que al PT, y el modelo supone que se repite. En 2018, con Ciro viniendo de la
      centroizquierda, el PT se llevó {D['hist'][2018] * 100:.0f}% de los demás votos; en 2022, {D['hist'][2022] * 100:.0f}%.</p>
      <div class="fuente">Bandas: lo que ganó el PT del voto de los demás candidatos entre vueltas, según el resultado oficial (TSE).</div>
    """))

    # 5 · movilización
    sp = M["top_municipios_reserva_neta"][0]
    paginas.append(lamina(5, f"""
      <div class="kicker">Movilización</div>
      <h1>Aunque vuelvan a votar todos sus votantes de 2022, no alcanza</h1>
      <p class="sub">Votantes de la segunda vuelta de 2022 que no fueron a votar el 4 de octubre.</p>
      <div class="fig"><img src="{fig_reserva(D)}"></div>
      <div class="cifras">
        <div><b>{falta['pp_menos_abstencion_para_empatar']:.0f} pp</b><span>tendría que bajar la abstención donde ganó Lula en 2022</span></div>
        <div><b>{f1(falta['mayor_baja_historica_entre_vueltas_pp'])} pp</b><span>el mayor cambio entre vueltas en 2018 y 2022</span></div>
        <div><b>{sp['reserva_neta'] / 1e3:.0f} mil</b><span>reserva neta en São Paulo capital, la más grande</span></div>
      </div>
      <div class="fuente">Misma regresión ecológica, ajustada a la abstención observada en cada municipio. TSE 2022 y 2026.</div>
    """))

    # 6 · el método y el pronóstico
    paginas.append(lamina(6, f"""
      <div class="kicker">El pronóstico</div>
      <h1>Probado contra 2022, el método erró por {f1(abs(bt['R']['error_nacional_pp']))} puntos</h1>
      <p class="sub">Con la segunda vuelta de 2018 y la primera de 2022, predicción del balotaje de 2022 por estado.</p>
      <div class="duo">
        <div class="izq">
          <div class="dato"><b style="color:{cl.LULA}">{f1(mc['lula_media'])}%</b><span>Lula en la segunda vuelta del 25/10</span></div>
          <div class="dato"><b style="color:{cl.FLAVIO}">{mc['prob_flavio'] * 100:.0f}%</b><span>de las simulaciones gana Flávio</span></div>
          <div class="dato"><b>{f1(bt['R']['mae_uf_pp'])} pp</b><span>error medio por estado en la prueba</span></div>
          <p class="nota">Repartir a los terceros por parecido entre candidatos (Cury como Ciro) erró por {f1(bt['A']['error_nacional_pp'])} puntos. Es una sola prueba: la incertidumbre del pronóstico es más amplia.</p>
        </div>
        <div class="der"><img src="{fig_backtest(D)}"></div>
      </div>
      <div class="fuente">Cada punto es un estado. Montecarlo de {f0(mc['n'])} simulaciones con shock nacional t de Student y shock por estado.</div>
    """))

    # 7 · método
    paginas.append(lamina(7, f"""
      <div class="kicker">Cómo se hizo</div>
      <h1>Solo resultados oficiales, ninguna encuesta</h1>
      <dl>
        <dt>Resultados</dt><dd>TSE: primera vuelta 2026 por municipio, con padrón, abstención, blancos y nulos; 2018 y 2022 por local de votación.</dd>
        <dt>Terceros</dt><dd>Regresión ecológica con restricciones entre la segunda vuelta de 2022 y la primera de 2026, por estado.</dd>
        <dt>Resto</dt><dd>Retención y movilización entre vueltas: matriz de la elección de 2022, estimada sobre 92.000 locales de votación.</dd>
        <dt>Prueba</dt><dd>El mismo método, un ciclo atrás, contra el balotaje real de 2022.</dd>
        <dt>Herramientas</dt><dd>Python (pandas, scipy, geopandas).</dd>
      </dl>
      <div class="cierre"><img src="{cl.LOGO_V.as_uri()}">
        <div><b>Atlas Analytics</b><br>Análisis electoral y territorial<br>atlas-analytics.site</div></div>
    """))

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Balotaje Brasil 2026</title>'
            f'<style>{cl.CSS}</style></head><body>{"".join(paginas)}</body></html>')
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
    for i, p in enumerate(doc, 1):
        z = 1080 / p.rect.width
        p.get_pixmap(matrix=fitz.Matrix(z, z)).save(jpg_dir / f"{i:02d}.jpg", jpg_quality=94)
    return doc.page_count


# --------------------------------------------------------------------------- textos
def textos(D) -> dict:
    R, M = D["R"], D["M"]
    mc, bt = R["montecarlo"], R["backtest_2022"]
    res, falta = M["reserva"], M["lo_que_hace_falta"]
    q, a = D["quiebre"], D["a_modelo"]
    comp = R["composicion_terceros_por_origen_2022"]
    linkedin = f"""Después del 4 de octubre me propuse pronosticar el balotaje de Brasil sin mirar una sola encuesta. Solo con los resultados oficiales del TSE, municipio por municipio.

El punto de partida: Flávio Bolsonaro sacó {mill(D['brecha_1v'])} de votos más que Lula. Los candidatos que quedaron afuera suman {mill(D['n_terc'])}. Si votaran exactamente los mismos electores, Lula necesitaría llevarse el {D['necesita_simple'] * 100:.0f}% de esos votos.

Para saber hacia dónde van, crucé dónde creció cada tercero con cómo había votado cada municipio en la segunda vuelta de 2022. De cada 100 votantes de Cury, {comp['cury']['pt'] * 100:.0f} habían votado a Lula y {comp['cury']['bolsonaro'] * 100:.0f} a Bolsonaro. Con Renan Santos y Caiado pasa algo parecido. Si cada uno vuelve a su lado, Lula se lleva el {a * 100:.0f}% de ese voto, y con la movilización que tuvo la segunda vuelta de 2022, el empate exige {q * 100:.0f}%.

La otra salida sería la participación. {mill(res['de_lula_2022'])} de votantes de Lula en 2022 no fueron a votar el 4 de octubre. Aun si volvieran todos, la brecha es de {mill(falta['brecha_votos'])}, y del otro lado hay {mill(res['de_bolsonaro_2022'])} de votantes de Bolsonaro en la misma situación.

Antes de publicarlo probé el método un ciclo atrás: con la segunda vuelta de 2018 y la primera de 2022 predijo el balotaje de 2022 con {f1(abs(bt['R']['error_nacional_pp']))} puntos de error. El resultado para el 25 de octubre: Lula {f1(mc['lula_media'])}%, y Flávio gana en el {mc['prob_flavio'] * 100:.0f}% de las simulaciones.

Es inferencia ecológica: describe territorios, no personas. En el carrusel están los gráficos y el método.

#Brasil2026 #AnálisisElectoral #DatosAbiertos #Elecciones"""
    ig_terceros = f"""Lula necesita el {q * 100:.0f}% de los votos de los terceros para empatar el balotaje. Ni en 2018 el PT llegó a tanto.

Flávio Bolsonaro ganó la primera vuelta por {mill(D['brecha_1v'])} de votos. Cury, Renan Santos, Caiado y Zema suman {mill(D['n_terc'])}. Según nuestro modelo, Lula se llevaría el {a * 100:.0f}% de esos votos: más de esos electores había votado a Bolsonaro que a Lula en 2022.

En 2018 el PT se llevó el {D['hist'][2018] * 100:.0f}% del voto de los demás candidatos entre vueltas; en 2022, el {D['hist'][2022] * 100:.0f}%.

Pronóstico Atlas para el 25/10: Lula {f1(mc['lula_media'])}%. Sin encuestas, solo resultados del TSE.

#AtlasAnalytics #Brasil2026 #EleiçõesBrasil #Elecciones #DataViz"""
    ig_reserva = f"""¿Y si Lula consigue que vuelvan a votar los que se quedaron en casa? Tampoco alcanza.

{mill(res['de_lula_2022'])} de votantes de Lula en 2022 no fueron a votar el 4 de octubre. La brecha a cerrar el 25/10 es de {mill(falta['brecha_votos'])}. Y del otro lado hay {mill(res['de_bolsonaro_2022'])} de votantes de Bolsonaro en la misma situación.

Para empatar, la abstención tendría que bajar {falta['pp_menos_abstencion_para_empatar']:.0f} puntos en los municipios donde ganó Lula en 2022. En 2018 y 2022, el mayor cambio entre vueltas fue de {f1(falta['mayor_baja_historica_entre_vueltas_pp'])} puntos.

Estimación ecológica con resultados del TSE por municipio.

#AtlasAnalytics #Brasil2026 #EleiçõesBrasil #Elecciones #DataViz"""
    return {"linkedin": linkedin, "terceros": ig_terceros, "reserva": ig_reserva}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    fecha = ap.parse_args(argv).fecha
    D = cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    T = textos(D)
    for nombre, fn in (("terceros", post_terceros), ("reserva", post_reserva)):
        out = SALIDA / f"post_balotaje_{nombre}_{fecha}.jpg"
        fn(D, out)
        out.with_suffix(".txt").write_text(T[nombre], encoding="utf-8")
        print(out)
    pdf = SALIDA / f"ATLAS_carrusel_balotaje_{fecha}.pdf"
    n = carrusel(D, fecha, SALIDA / "_build_carrusel_balotaje", pdf, SALIDA / f"carrusel_balotaje_{fecha}")
    pdf.with_suffix(".txt").write_text(T["linkedin"], encoding="utf-8")
    print(pdf, f"({n} láminas)")


if __name__ == "__main__":
    main()
