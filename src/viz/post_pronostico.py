# -*- coding: utf-8 -*-
"""Pieza para redes: pronóstico presidencial 2026 sobre el mapa del 2º turno 2022.

Formato 1080x1350 (4:5) con el sistema de marca de los posteos de Atlas
(banda de encabezado, Consolas para datos, Arial para titular, pie).

Las cifras salen de resumen_presidencial_encuestas_2026.json; el mapa, de los
municipios.geojson por UF (lula_2v = % Lula en votos válidos, 2º turno 2022).

    python -m src.viz.post_pronostico              # pronóstico
    python -m src.viz.post_pronostico --resultado  # pronóstico vs. conteo TSE
"""
import io
import json
import os
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parents[2]
GEO = RAIZ / "data" / "processed" / "geo"
RESUMEN = RAIZ / "data" / "processed" / "electoral" / "resumen_presidencial_encuestas_2026.json"
SALIDA = RAIZ / "reports" / "figures" / "redes"

BRAND = r"C:\Users\corra\Desktop\ANALISIS POLITICO\SERVICIOS PRESENTACIONES\brandkit"
LOGO_H = os.path.join(BRAND, "logo-horizontal", "png", "atlas-horizontal-blanco-1200.png")

F_DISPLAY = r"C:\Windows\Fonts\arialbd.ttf"
F_TEXTO = r"C:\Windows\Fonts\arial.ttf"
F_DATOS = r"C:\Windows\Fonts\consola.ttf"
F_DATOS_B = r"C:\Windows\Fonts\consolab.ttf"

TINTA = (0x12, 0x00, 0x2A)
NEON = (0xEF, 0xBF, 0xF8)
VIOLETA = (0xC4, 0x0B, 0xFF)
LILA = (0xD2, 0x7C, 0xDF)
TEXTO = (0xE6, 0xD6, 0xF2)
BLANCO = (0xFF, 0xFF, 0xFF)
LULA = (0xFF, 0x4D, 0x6D)
BOLSO = (0x2B, 0xB3, 0xFF)

W, H = 1080, 1350
SAFE_X, SAFE_B = 64, 96


def _f(path, size):
    return ImageFont.truetype(path, size)


def track(d, xy, texto, font, fill, tracking=0.0, anchor_y="a"):
    x, y = xy
    extra = tracking * font.size
    for ch in texto:
        d.text((x, y), ch, font=font, fill=fill, anchor="l" + anchor_y)
        x += d.textlength(ch, font=font) + extra
    return x - xy[0] - (extra if texto else 0)


def track_w(d, texto, font, tracking=0.0):
    extra = tracking * font.size
    return sum(d.textlength(c, font=font) for c in texto) + extra * max(len(texto) - 1, 0)


def pct(x, dec=0):
    return f"{x:.{dec}f}".replace(".", ",")


# --------------------------------------------------------------------------- fondo
def fondo():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # halo violeta detrás del mapa, cae a tinta hacia los bordes
    r = np.sqrt(((xx - W * 0.55) / W) ** 2 + ((yy - H * 0.50) / H) ** 2)
    k = np.clip(1 - r / 0.62, 0, 1) ** 2.2
    base = np.array(TINTA, np.float32)
    halo = np.array((0x3A, 0x06, 0x62), np.float32)
    a = base + (halo - base) * k[:, :, None]
    # grilla tenue de coordenadas
    im = Image.fromarray(a.astype(np.uint8), "RGB")
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(0, W, 54):
        d.line([(x, 0), (x, H)], fill=(0xC4, 0x0B, 0xFF, 14))
    for y in range(0, H, 54):
        d.line([(0, y), (W, y)], fill=(0xC4, 0x0B, 0xFF, 14))
    return im


def grano(im, fuerza=7):
    a = np.asarray(im, dtype=np.float32)
    n = np.random.default_rng(7).normal(0, fuerza, a.shape[:2])[:, :, None]
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8), "RGB")


# --------------------------------------------------------------------------- mapa
def cargar_municipios():
    capas = []
    for uf in sorted(p.name for p in GEO.iterdir() if len(p.name) == 2):
        g = gpd.read_file(GEO / uf / "municipios.geojson", columns=["codigo", "lula_2v", "geometry"])
        g["uf"] = uf
        capas.append(g)
    return gpd.GeoDataFrame(pd.concat(capas, ignore_index=True), crs=capas[0].crs)


def render_mapa(mun, ancho_px, columna="lula_2v"):
    """Devuelve (RGBA del mapa, RGBA del contorno para el resplandor).

    columna: % Lula (0-100). Los municipios sin dato quedan en tinta apagada."""
    mun = mun.to_crs("ESRI:102033")  # Albers América del Sur: área fiel
    ufs = mun.dissolve("uf")
    pais = ufs.dissolve()
    x0, y0, x1, y1 = pais.total_bounds
    aspecto = (y1 - y0) / (x1 - x0)
    dpi = 200
    fig_w = ancho_px / dpi
    fig_h = fig_w * aspecto

    def hex_(c):
        return "#%02x%02x%02x" % c

    cmap = LinearSegmentedColormap.from_list(
        "lb", [hex_(BOLSO), "#1E6FB0", "#3B1C66", "#A8325A", hex_(LULA)])

    def figura():
        fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_axis_off()
        fig.patch.set_alpha(0)
        return fig, ax

    def a_img(fig):
        buf = io.BytesIO()
        fig.savefig(buf, dpi=dpi, transparent=True)
        plt.close(fig)
        buf.seek(0)
        return Image.open(buf).convert("RGBA")

    fig, ax = figura()
    # 30% → azul pleno, 70% → coral pleno: la mitad del país está en ese rango
    mun.plot(ax=ax, color="#22103A", linewidth=0.05, edgecolor=(0.07, 0, 0.16, 0.35))
    con = mun[mun[columna].notna()]
    con.assign(v=con[columna].clip(25, 75)).plot(
        ax=ax, column="v", cmap=cmap, vmin=25, vmax=75,
        linewidth=0.05, edgecolor=(0.07, 0, 0.16, 0.35))
    ufs.boundary.plot(ax=ax, linewidth=0.55, color=(0.94, 0.75, 0.97, 0.55))
    pais.boundary.plot(ax=ax, linewidth=1.1, color=(0.94, 0.75, 0.97, 0.95))
    mapa = a_img(fig)

    fig, ax = figura()
    pais.boundary.plot(ax=ax, linewidth=5, color=(0.77, 0.04, 1.0, 1.0))
    glow = a_img(fig)
    return mapa, glow


# --------------------------------------------------------------------------- pieza
def armar(res, mun, salida):
    im = fondo().convert("RGBA")

    # mapa a la derecha, sangrando un poco hacia el borde
    mapa, glow = render_mapa(mun, 610)
    mx, my = W - SAFE_X - mapa.width + 30, 893 - mapa.height
    # el resplandor necesita margen o el desenfoque se corta en el borde del lienzo
    m = 80
    lienzo = Image.new("RGBA", (glow.width + 2 * m, glow.height + 2 * m), (0, 0, 0, 0))
    lienzo.alpha_composite(glow, (m, m))
    halo = lienzo.filter(ImageFilter.GaussianBlur(20))
    for _ in range(2):
        im.alpha_composite(halo, (mx - m, my - m))
    im.alpha_composite(mapa, (mx, my))

    # velo de tinta a la izquierda para que las cifras lean sobre el mapa
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    velo = np.clip((520 - xx) / 300, 0, 1) ** 1.3 * 0.80
    velo = np.maximum(velo, np.clip((yy - (H - 450)) / 120, 0, 1) ** 1.4 * 0.95)
    capa = Image.new("RGBA", (W, H), TINTA + (0,))
    capa.putalpha(Image.fromarray((velo * 255).astype(np.uint8), "L"))
    im.alpha_composite(capa)

    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")

    # --- banda de encabezado
    yb = 92
    d.rectangle([SAFE_X, yb - 13, SAFE_X + 3, yb + 13], fill=VIOLETA)
    track(d, (SAFE_X + 20, yb), "BRASIL 2026 · PRONÓSTICO", _f(F_DATOS, 21), NEON, 0.22, "m")
    lg = Image.open(LOGO_H).convert("RGBA")
    lg = lg.resize((round(lg.width * 34 / lg.height), 34), Image.LANCZOS)
    im.alpha_composite(lg, (W - SAFE_X - lg.width, yb - lg.height // 2))
    d.line([(SAFE_X, yb + 40), (W - SAFE_X, yb + 40)], fill=(0xC4, 0x0B, 0xFF, 70))

    # --- titular
    y = 200
    for ln in ("EMPATE", "TÉCNICO"):
        track(d, (SAFE_X, y), ln, _f(F_DISPLAY, 104), BLANCO, -0.02, "a")
        y += 110
    d.line([(SAFE_X, y + 14), (SAFE_X + 46, y + 14)], fill=VIOLETA, width=3)
    d.text((SAFE_X, y + 34), "1ª vuelta · 4 de octubre", font=_f(F_TEXTO, 28), fill=TEXTO, anchor="la")
    d.text((SAFE_X, y + 70), "% de votos válidos (estimado)", font=_f(F_TEXTO, 22), fill=LILA, anchor="la")

    # --- primera vuelta: dos cifras
    a1 = res["agregado_1v_pct"]
    y = 545
    for nombre, val, col in (("LULA", a1["lula"], LULA), ("FLÁVIO", a1["flavio_bolsonaro"], BOLSO)):
        d.rectangle([SAFE_X, y + 8, SAFE_X + 6, y + 92], fill=col)
        track(d, (SAFE_X + 24, y), nombre, _f(F_DATOS_B, 22), col, 0.22, "a")
        w = track(d, (SAFE_X + 22, y + 26), pct(val, 1), _f(F_DISPLAY, 76), BLANCO, -0.02, "a")
        d.text((SAFE_X + 30 + w, y + 40), "%", font=_f(F_DISPLAY, 38), fill=BLANCO, anchor="la")
        y += 124
    brecha = a1["lula"] - a1["flavio_bolsonaro"]
    sig = res["incertidumbre_pp"]["sigma_1v"]
    d.text((SAFE_X, y + 4), f"Brecha {pct(brecha, 1)} pp: menor", font=_f(F_TEXTO, 22), fill=TEXTO, anchor="la")
    d.text((SAFE_X, y + 34), f"que el error típico (±{pct(sig, 1)} pp)", font=_f(F_TEXTO, 22), fill=TEXTO, anchor="la")

    # --- banda inferior: balotaje y probabilidad
    y0 = 904
    d.line([(SAFE_X, y0), (W - SAFE_X, y0)], fill=(0xC4, 0x0B, 0xFF, 110))
    col_w = (W - 2 * SAFE_X) // 2
    # izq: probabilidad de balotaje
    p2v = round(res["prob_hay_segunda_vuelta"] * 100)
    track(d, (SAFE_X, y0 + 30), "PROB. DE BALOTAJE", _f(F_DATOS, 19), LILA, 0.20, "a")
    w = track(d, (SAFE_X - 4, y0 + 60), str(p2v), _f(F_DISPLAY, 110), NEON, -0.02, "a")
    d.text((SAFE_X + w + 6, y0 + 78), "%", font=_f(F_DISPLAY, 52), fill=NEON, anchor="la")
    d.text((SAFE_X, y0 + 186), "Lula vs. Flávio · 25 de octubre", font=_f(F_TEXTO, 21), fill=TEXTO, anchor="la")

    # der: quién gana el balotaje
    xr = SAFE_X + col_w + 30
    d.line([(xr - 30, y0 + 28), (xr - 30, y0 + 216)], fill=(0xC4, 0x0B, 0xFF, 90))
    pp = res["prob_presidente"]
    pf, pl = round(pp["flavio_bolsonaro"] * 100), round(pp["lula"] * 100)
    track(d, (xr, y0 + 30), "PROB. DE SER PRESIDENTE", _f(F_DATOS, 19), LILA, 0.20, "a")
    ancho = W - SAFE_X - xr
    yb2 = y0 + 70
    for nombre, val, col in (("Flávio", pf, BOLSO), ("Lula", pl, LULA)):
        d.text((xr, yb2), nombre, font=_f(F_TEXTO, 26), fill=BLANCO, anchor="la")
        t = f"{val}%"
        d.text((W - SAFE_X, yb2), t, font=_f(F_DISPLAY, 30), fill=col, anchor="ra")
        d.rectangle([xr, yb2 + 40, xr + ancho, yb2 + 48], fill=(0x2C, 0x00, 0x56))
        d.rectangle([xr, yb2 + 40, xr + ancho * val / 100, yb2 + 48], fill=col)
        yb2 += 64
    d.text((xr, yb2 + 2), "Moneda al aire, con leve ventaja de Flávio",
           font=_f(F_TEXTO, 19), fill=TEXTO, anchor="la")

    # --- nota de método
    s = res["sensibilidad_con_correccion_de_sesgo"]["prob_presidente"]["flavio_bolsonaro"]
    nota = ("Agregador de encuestas + 10.000 simulaciones (corte 1/10). Si se repite el sesgo "
            f"de 2018/22, Flávio sube a {round(s * 100)}%.",
            "Mapa: 2º turno 2022 por municipio, % Lula (rojo) vs. Bolsonaro (azul).")
    yn = H - SAFE_B - 8 - 34 - 10 - 26 * len(nota)
    for ln in nota:
        d.text((SAFE_X, yn), ln, font=_f(F_TEXTO, 17), fill=(0xB8, 0xA4, 0xCC), anchor="la")
        yn += 26

    # --- pie
    yp = H - SAFE_B - 8
    d.line([(SAFE_X, yp - 34), (W - SAFE_X, yp - 34)], fill=(0xC4, 0x0B, 0xFF, 70))
    track(d, (SAFE_X, yp), "ATLAS ANALYTICS · ATLAS-ANALYTICS.SITE", _f(F_DATOS, 17), LILA, 0.18, "s")

    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


def _halo(im, glow, xy, m=90, radio=22, veces=2):
    lienzo = Image.new("RGBA", (glow.width + 2 * m, glow.height + 2 * m), (0, 0, 0, 0))
    lienzo.alpha_composite(glow, (m, m))
    halo = lienzo.filter(ImageFilter.GaussianBlur(radio))
    for _ in range(veces):
        im.alpha_composite(halo, (xy[0] - m, xy[1] - m))


def armar_mapa(res, mun, salida, ancho=900):
    """Variante con el mapa de protagonista: ocupa casi todo el lienzo y las
    cifras flotan en los vacíos (Atlántico y sur del continente)."""
    im = fondo().convert("RGBA")
    mapa, glow = render_mapa(mun, ancho)
    mx, my = W - mapa.width - 20, 262
    _halo(im, glow, (mx, my))
    im.alpha_composite(mapa, (mx, my))
    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")

    # --- banda de encabezado
    yb = 92
    d.rectangle([SAFE_X, yb - 13, SAFE_X + 3, yb + 13], fill=VIOLETA)
    track(d, (SAFE_X + 20, yb), "BRASIL 2026 · PRONÓSTICO", _f(F_DATOS, 21), NEON, 0.22, "m")
    lg = Image.open(LOGO_H).convert("RGBA")
    lg = lg.resize((round(lg.width * 34 / lg.height), 34), Image.LANCZOS)
    im.alpha_composite(lg, (W - SAFE_X - lg.width, yb - lg.height // 2))
    d.line([(SAFE_X, yb + 40), (W - SAFE_X, yb + 40)], fill=(0xC4, 0x0B, 0xFF, 70))

    # --- titular en una línea
    track(d, (SAFE_X, 168), "EMPATE TÉCNICO", _f(F_DISPLAY, 92), BLANCO, -0.02, "a")
    d.text((SAFE_X, 272), "1ª vuelta · 4 de octubre", font=_f(F_TEXTO, 26), fill=TEXTO, anchor="la")

    # --- arriba a la derecha (Atlántico norte): balotaje
    xr = W - SAFE_X
    p2v = round(res["prob_hay_segunda_vuelta"] * 100)
    f_k = _f(F_DATOS, 18)
    t = "PROB. DE BALOTAJE · 25/10"
    track(d, (xr - track_w(d, t, f_k, 0.2), 290), t, f_k, LILA, 0.20, "a")
    f_g = _f(F_DISPLAY, 112)
    f_p = _f(F_DISPLAY, 50)
    wp = d.textlength("%", font=f_p)
    d.text((xr, 322), "%", font=f_p, fill=NEON, anchor="ra")
    d.text((xr - wp - 4, 316), str(p2v), font=f_g, fill=NEON, anchor="ra")

    # --- abajo a la izquierda (sur del continente): 1ª vuelta
    a1 = res["agregado_1v_pct"]
    y = 830
    track(d, (SAFE_X, y), "VOTOS VÁLIDOS (EST.)", f_k, LILA, 0.20, "a")
    y += 36
    for nombre, val, col in (("LULA", a1["lula"], LULA), ("FLÁVIO", a1["flavio_bolsonaro"], BOLSO)):
        d.rectangle([SAFE_X, y + 6, SAFE_X + 6, y + 88], fill=col)
        track(d, (SAFE_X + 22, y), nombre, _f(F_DATOS_B, 21), col, 0.22, "a")
        w = track(d, (SAFE_X + 20, y + 24), pct(val, 1), _f(F_DISPLAY, 72), BLANCO, -0.02, "a")
        d.text((SAFE_X + 28 + w, y + 36), "%", font=_f(F_DISPLAY, 34), fill=BLANCO, anchor="la")
        y += 112
    brecha = a1["lula"] - a1["flavio_bolsonaro"]
    sig = res["incertidumbre_pp"]["sigma_1v"]
    d.text((SAFE_X, y + 2), f"Brecha {pct(brecha, 1)} pp < error ±{pct(sig, 1)} pp",
           font=_f(F_TEXTO, 20), fill=TEXTO, anchor="la")

    # --- abajo a la derecha (Atlántico sur): quién gana
    pp = res["prob_presidente"]
    pf, pl = round(pp["flavio_bolsonaro"] * 100), round(pp["lula"] * 100)
    ancho_c = 250
    xl = xr - ancho_c
    y = 940
    track(d, (xl, y), "PROB. DE GANAR", f_k, LILA, 0.20, "a")
    y += 38
    for nombre, val, col in (("Flávio", pf, BOLSO), ("Lula", pl, LULA)):
        d.text((xl, y), nombre, font=_f(F_TEXTO, 25), fill=BLANCO, anchor="la")
        d.text((xr, y - 4), f"{val}%", font=_f(F_DISPLAY, 34), fill=col, anchor="ra")
        d.rectangle([xl, y + 40, xr, y + 47], fill=(0x2C, 0x00, 0x56))
        d.rectangle([xl, y + 40, xl + ancho_c * val / 100, y + 47], fill=col)
        y += 70

    # --- nota de método
    s = res["sensibilidad_con_correccion_de_sesgo"]["prob_presidente"]["flavio_bolsonaro"]
    nota = ("10.000 simulaciones sobre el agregado de encuestas (corte 1/10). Con el sesgo de 2018/22, "
            f"Flávio {round(s * 100)}%.",
            "Mapa: 2º turno 2022 por municipio · rojo Lula, azul Bolsonaro.")
    yn = H - SAFE_B - 8 - 34 - 10 - 24 * len(nota)
    for ln in nota:
        d.text((SAFE_X, yn), ln, font=_f(F_TEXTO, 16), fill=(0xB8, 0xA4, 0xCC), anchor="la")
        yn += 24

    yp = H - SAFE_B - 8
    d.line([(SAFE_X, yp - 34), (W - SAFE_X, yp - 34)], fill=(0xC4, 0x0B, 0xFF, 70))
    track(d, (SAFE_X, yp), "ATLAS ANALYTICS · ATLAS-ANALYTICS.SITE", _f(F_DATOS, 17), LILA, 0.18, "s")
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


CONTEO = RAIZ / "data" / "processed" / "electoral" / "conteo_presidencial_2026_1v.json"
CONTEO_MUN = RAIZ / "data" / "processed" / "electoral" / "conteo_presidencial_2026_1v_municipios.parquet"


def armar_resultado(res, conteo, mun, salida, ancho=860):
    """Pronóstico (corte 1/10) contra la proyección del conteo del TSE.
    El mapa es 2026: % Lula sobre Lula + Flávio por municipio, conteo parcial."""
    im = fondo().convert("RGBA")
    mapa, glow = render_mapa(mun, ancho, columna="lula_2026")
    mx, my = W - mapa.width - 30, 300
    _halo(im, glow, (mx, my))
    im.alpha_composite(mapa, (mx, my))
    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")

    yb = 92
    d.rectangle([SAFE_X, yb - 13, SAFE_X + 3, yb + 13], fill=VIOLETA)
    track(d, (SAFE_X + 20, yb), "BRASIL 2026 · PRONÓSTICO VS. RESULTADO", _f(F_DATOS, 21), NEON, 0.22, "m")
    lg = Image.open(LOGO_H).convert("RGBA")
    lg = lg.resize((round(lg.width * 34 / lg.height), 34), Image.LANCZOS)
    im.alpha_composite(lg, (W - SAFE_X - lg.width, yb - lg.height // 2))
    d.line([(SAFE_X, yb + 40), (W - SAFE_X, yb + 40)], fill=(0xC4, 0x0B, 0xFF, 70))

    pron, proy = res["agregado_1v_pct"], conteo["proyeccion_pct"]
    hay_balotaje = max(proy.values()) < 50
    track(d, (SAFE_X, 168), "HAY BALOTAJE" if hay_balotaje else "SIN BALOTAJE",
          _f(F_DISPLAY, 92), BLANCO, -0.02, "a")
    dF = proy["flavio_bolsonaro"] - pron["flavio_bolsonaro"]
    d.text((SAFE_X, 272), f"Flávio rinde {pct(dF, 0)} puntos más que las encuestas",
           font=_f(F_TEXTO, 25), fill=TEXTO, anchor="la")

    # --- arriba a la derecha: el error con Flávio
    xr = W - SAFE_X
    f_k = _f(F_DATOS, 18)
    t = "ERROR CON FLÁVIO"
    track(d, (xr - track_w(d, t, f_k, 0.2), 312), t, f_k, LILA, 0.20, "a")
    f_g, f_p = _f(F_DISPLAY, 80), _f(F_DISPLAY, 34)
    wp = d.textlength("pp", font=f_p)
    d.text((xr, 350), "pp", font=f_p, fill=BOLSO, anchor="ra")
    d.text((xr - wp - 8, 340), "+" + pct(dF, 1), font=f_g, fill=BOLSO, anchor="ra")

    # --- abajo a la izquierda: pronóstico → proyección
    y = 810
    f_col = _f(F_DATOS, 17)
    track(d, (SAFE_X, y), "% VÁLIDOS", f_k, LILA, 0.20, "a")
    xa, xb = SAFE_X + 150, SAFE_X + 300
    track(d, (xa, y + 34), "PRONÓST.", f_col, (0xB8, 0xA4, 0xCC), 0.12, "a")
    track(d, (xb, y + 34), "RESULTADO*", f_col, NEON, 0.12, "a")
    y += 68
    for nombre, k, col in (("FLÁVIO", "flavio_bolsonaro", BOLSO), ("LULA", "lula", LULA)):
        d.rectangle([SAFE_X, y + 4, SAFE_X + 6, y + 70], fill=col)
        track(d, (SAFE_X + 20, y + 24), nombre, _f(F_DATOS_B, 21), col, 0.18, "a")
        d.text((xa, y + 12), pct(pron[k], 1), font=_f(F_DISPLAY, 46), fill=(0xB8, 0xA4, 0xCC), anchor="la")
        d.text((xb, y + 2), pct(proy[k], 1), font=_f(F_DISPLAY, 62), fill=BLANCO, anchor="la")
        y += 96

    # --- abajo a la derecha: qué sigue
    ancho_c = 290
    xl = xr - ancho_c
    y = 950
    track(d, (xl, y), "BALOTAJE · 25/10", f_k, LILA, 0.20, "a")
    s = res["sensibilidad_con_correccion_de_sesgo"]["prob_presidente"]["flavio_bolsonaro"]
    for i, ln in enumerate(("Se cumplió nuestro escenario", "con el sesgo de 2018/22.",
                            "En ese escenario, Flávio")):
        d.text((xl, y + 36 + 30 * i), ln, font=_f(F_TEXTO, 22), fill=TEXTO, anchor="la")
    d.text((xl, y + 130), f"tenía {round(s * 100)}% de ganar.", font=_f(F_DISPLAY, 24), fill=NEON, anchor="la")

    hora = max(r["hora_tse"] for r in conteo["por_uf"].values()).split(" ")[1][:5]
    nota = (f"*Proyección Atlas con {pct(conteo['pct_secciones_contadas'], 1)}% de las secciones contadas "
            f"(TSE, {hora}): cada estado se completa como viene votando.",
            "Pronóstico: agregador de encuestas, corte 1/10. Mapa: % Lula vs. Flávio por municipio, conteo parcial.")
    yn = H - SAFE_B - 8 - 34 - 10 - 24 * len(nota)
    for ln in nota:
        d.text((SAFE_X, yn), ln, font=_f(F_TEXTO, 16), fill=(0xB8, 0xA4, 0xCC), anchor="la")
        yn += 24

    yp = H - SAFE_B - 8
    d.line([(SAFE_X, yp - 34), (W - SAFE_X, yp - 34)], fill=(0xC4, 0x0B, 0xFF, 70))
    track(d, (SAFE_X, yp), "ATLAS ANALYTICS · ATLAS-ANALYTICS.SITE", _f(F_DATOS, 17), LILA, 0.18, "s")
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


def main_resultado():
    res = json.loads(RESUMEN.read_text(encoding="utf-8"))
    conteo = json.loads(CONTEO.read_text(encoding="utf-8"))
    mun = cargar_municipios()
    m = pd.read_parquet(CONTEO_MUN)
    m = m[(m.flavio + m.lula) > 0]
    m["lula_2026"] = 100 * m.lula / (m.lula + m.flavio)
    mun = mun.assign(codigo=mun.codigo.astype(int)).merge(
        m[["codigo", "lula_2026"]].astype({"codigo": int}), on="codigo", how="left")
    SALIDA.mkdir(parents=True, exist_ok=True)
    out = SALIDA / f"post_resultado_1v_{conteo['descarga_utc'][:10]}.jpg"
    armar_resultado(res, conteo, mun, out)
    print(out)


def main():
    res = json.loads(RESUMEN.read_text(encoding="utf-8"))
    SALIDA.mkdir(parents=True, exist_ok=True)
    mun = cargar_municipios()
    out = SALIDA / f"post_pronostico_{res['fecha_corte_encuestas']}.jpg"
    armar(res, mun, out)
    print(out)
    out = SALIDA / f"post_pronostico_mapa_{res['fecha_corte_encuestas']}.jpg"
    armar_mapa(res, mun, out)
    print(out)


if __name__ == "__main__":
    import sys
    main_resultado() if "--resultado" in sys.argv else main()
