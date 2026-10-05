# -*- coding: utf-8 -*-
"""Carrusel para LinkedIn: lo que dejó la 1ª vuelta 2026 en clave de datos.

Siete láminas 1080x1350 con el sistema de marca de los posteos de Atlas
(mismas piezas que src/viz/post_pronostico.py) y un PDF para subir como
documento a LinkedIn:

  1. Portada                      (nueva)
  2. Pronóstico vs. resultado     (post_resultado_1v, ya publicado)
  3. Lección 1: el promedio       (nueva: % por estado, conteo TSE 2026)
  4. Lección 2: geografía         (nueva: LISA y GWR, 2º turno 2022, R/analisis_espacial.R)
  5. La regla de Minas            (post_minas, ya publicado)
  6. Tres lecciones               (nueva)
  7. Cierre                       (nueva)

Antes: python -m src.viz.post_pronostico --resultado  (piezas 2 y 5)

    python -m src.viz.carrusel_linkedin
"""
import json
import statistics
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from src.viz.post_pronostico import (
    BLANCO, BOLSO, CONTEO, CONTEO_MUN, F_DATOS, F_DATOS_B, F_DISPLAY, F_TEXTO, FECHA_1V, H, LILA, LOGO_H,
    LULA, NEON, RAIZ, SAFE_B, SAFE_X, SALIDA, TEXTO, TINTA, VIOLETA, W, _f, _halo, cargar_municipios, fondo,
    grano, pct, render_mapa, track, track_w,
)

ESPACIAL = RAIZ / "data" / "processed" / "geo" / "_espacial"
SALIDA_C = SALIDA / f"carrusel_linkedin_{FECHA_1V}"
GRIS = (0xB8, 0xA4, 0xCC)
APAGADO = (0x2C, 0x00, 0x56)

NOMBRE_UF = {"RR": "Roraima", "PI": "Piauí"}


def f0(x):
    return f"{x:,.0f}".replace(",", ".")


def f2(x):
    return f"{x:.2f}".replace(".", ",")


# --------------------------------------------------------------------------- piezas comunes
def encabezado(im, d, kicker):
    yb = 92
    d.rectangle([SAFE_X, yb - 13, SAFE_X + 3, yb + 13], fill=VIOLETA)
    track(d, (SAFE_X + 20, yb), kicker, _f(F_DATOS, 21), NEON, 0.22, "m")
    lg = Image.open(LOGO_H).convert("RGBA")
    lg = lg.resize((round(lg.width * 34 / lg.height), 34), Image.LANCZOS)
    im.alpha_composite(lg, (W - SAFE_X - lg.width, yb - lg.height // 2))
    d.line([(SAFE_X, yb + 40), (W - SAFE_X, yb + 40)], fill=(0xC4, 0x0B, 0xFF, 70))


def pie(d, nota=(), n=None):
    yn = H - SAFE_B - 8 - 34 - 10 - 24 * len(nota)
    for ln in nota:
        d.text((SAFE_X, yn), ln, font=_f(F_TEXTO, 16), fill=GRIS, anchor="la")
        yn += 24
    yp = H - SAFE_B - 8
    d.line([(SAFE_X, yp - 34), (W - SAFE_X, yp - 34)], fill=(0xC4, 0x0B, 0xFF, 70))
    track(d, (SAFE_X, yp), "ATLAS ANALYTICS · ATLAS-ANALYTICS.SITE", _f(F_DATOS, 17), LILA, 0.18, "s")
    if n:
        f = _f(F_DATOS, 17)
        d.text((W - SAFE_X, yp), f"{n[0]:02d} / {n[1]:02d}", font=f, fill=LILA, anchor="rs")


def titular(d, lineas, y=168, size=84, paso=92):
    for ln in lineas:
        track(d, (SAFE_X, y), ln, _f(F_DISPLAY, size), BLANCO, -0.02, "a")
        y += paso
    return y


def envolver(d, texto, font, ancho):
    lineas, actual = [], ""
    for p in texto.split():
        prueba = (actual + " " + p).strip()
        if d.textlength(prueba, font=font) <= ancho:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    return lineas + [actual]


def parrafo(d, xy, texto, font, fill, ancho, interlinea):
    x, y = xy
    for ln in envolver(d, texto, font, ancho):
        d.text((x, y), ln, font=font, fill=fill, anchor="la")
        y += interlinea
    return y


def velo_izq(im, hasta=520, alfa=0.85):
    xx = np.mgrid[0:H, 0:W][1].astype(np.float32)
    velo = np.clip((hasta - xx) / 300, 0, 1) ** 1.3 * alfa
    capa = Image.new("RGBA", (W, H), TINTA + (0,))
    capa.putalpha(Image.fromarray((velo * 255).astype(np.uint8), "L"))
    im.alpha_composite(capa)


# --------------------------------------------------------------------------- datos
def municipios_2026():
    mun = cargar_municipios()
    m = pd.read_parquet(CONTEO_MUN)
    m = m[(m.flavio + m.lula) > 0]
    m["lula_2026"] = 100 * m.lula / (m.lula + m.flavio)
    return mun.assign(codigo=mun.codigo.astype(int)).merge(
        m[["codigo", "lula_2026"]].astype({"codigo": int}), on="codigo", how="left")


def por_estado(conteo):
    filas = []
    for uf, r in conteo["por_uf"].items():
        if uf == "zz":  # exterior
            continue
        v = r["votos"]
        t = sum(v.values())
        filas.append((uf.upper(), 100 * v["lula"] / t, 100 * v["flavio_bolsonaro"] / t))
    return sorted(filas, key=lambda f: f[1] - f[2])


def espacial():
    d = sorted(p for p in ESPACIAL.iterdir() if (p / "resumen.json").exists())[-1]
    res = json.loads((d / "resumen.json").read_text(encoding="utf-8"))
    mun = gpd.read_file(d / "municipios.gpkg", columns=["codigo", "uf", "lisa_lula", "geometry"])
    return res, mun[mun.codigo != 0]


def render_lisa(mun, ancho_px):
    """Mapa de focos LISA con el mismo encuadre y bordes que render_mapa."""
    import io

    import matplotlib.pyplot as plt

    mun = mun.to_crs("ESRI:102033")
    ufs = mun.dissolve("uf")
    pais = ufs.dissolve()
    x0, y0, x1, y1 = pais.total_bounds
    dpi = 200
    fig_w = ancho_px / dpi
    fig_h = fig_w * (y1 - y0) / (x1 - x0)
    hx = lambda c: "#%02x%02x%02x" % c
    color = {"High-High": hx(LULA), "Low-Low": hx(BOLSO)}

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
    mun.plot(ax=ax, color=mun["lisa_lula"].map(color).fillna("#2A1650"),
             linewidth=0.05, edgecolor=(0.07, 0, 0.16, 0.35))
    ufs.boundary.plot(ax=ax, linewidth=0.55, color=(0.94, 0.75, 0.97, 0.55))
    pais.boundary.plot(ax=ax, linewidth=1.1, color=(0.94, 0.75, 0.97, 0.95))
    mapa = a_img(fig)
    fig, ax = figura()
    pais.boundary.plot(ax=ax, linewidth=5, color=(0.77, 0.04, 1.0, 1.0))
    return mapa, a_img(fig)


# --------------------------------------------------------------------------- láminas
def lamina_portada(mun, n):
    im = fondo().convert("RGBA")
    mapa, glow = render_mapa(mun, 620, columna="lula_2026")
    mx, my = W - mapa.width + 50, 560
    _halo(im, glow, (mx, my))
    im.alpha_composite(mapa, (mx, my))
    velo_izq(im, 560, 0.75)
    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    encabezado(im, d, "BRASIL 2026 · 1ª VUELTA")

    y = titular(d, ("ACERTAR", "NO ES", "ADIVINAR"), y=180, size=108, paso=116)
    d.line([(SAFE_X, y + 18), (SAFE_X + 46, y + 18)], fill=VIOLETA, width=3)
    parrafo(d, (SAFE_X, y + 40), "Pronóstico, resultado y tres lecciones de datos de la elección en Brasil.",
            _f(F_TEXTO, 28), TEXTO, 420, 38)

    y = 880
    for t in ("ESTADÍSTICA DESCRIPTIVA", "ANÁLISIS GEOESPACIAL", "MODELOS PROBABILÍSTICOS"):
        d.rectangle([SAFE_X, y - 2, SAFE_X + 5, y + 26], fill=VIOLETA)
        track(d, (SAFE_X + 20, y), t, _f(F_DATOS_B, 20), NEON, 0.16, "a")
        y += 52
    track(d, (SAFE_X, y + 26), "DESLIZÁ →", _f(F_DATOS_B, 22), LILA, 0.22, "a")
    pie(d, ("Mapa: 1ª vuelta 2026 por municipio, % Lula (rojo) vs. Flávio (azul). Conteo TSE al 99,6% de las secciones.",),
        n)
    return im


def lamina_promedio(conteo, n):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    encabezado(im, d, "LECCIÓN 1 · ESTADÍSTICA DESCRIPTIVA")
    titular(d, ("EL PROMEDIO ESCONDE",), size=76)
    nac = conteo["contado_pct"]
    d.text((SAFE_X, 268), f"Brasil: Flávio {pct(nac['flavio_bolsonaro'], 1)}, Lula {pct(nac['lula'], 1)}. "
           "Estado por estado, es otro país.", font=_f(F_TEXTO, 25), fill=TEXTO, anchor="la")

    filas = por_estado(conteo)
    x0, x1, v0, v1 = 150, W - SAFE_X - 10, 15, 75
    sx = lambda v: x0 + (x1 - x0) * (v - v0) / (v1 - v0)
    ytop, paso = 372, 23
    ybot = ytop + paso * (len(filas) - 1)
    f_ax = _f(F_DATOS, 16)
    for v in range(20, 80, 10):
        d.line([(sx(v), ytop - 14), (sx(v), ybot + 10)], fill=(0xC4, 0x0B, 0xFF, 30))
        d.text((sx(v), ytop - 22), f"{v}%", font=f_ax, fill=GRIS, anchor="ms")
    for v, col in ((nac["lula"], LULA), (nac["flavio_bolsonaro"], BOLSO)):
        for yy in range(ytop - 12, ybot + 10, 8):
            d.line([(sx(v), yy), (sx(v), yy + 4)], fill=col + (150,), width=2)
    xm = (sx(nac["lula"]) + sx(nac["flavio_bolsonaro"])) / 2
    f_n = _f(F_DATOS, 15)
    track(d, (xm - track_w(d, "NACIONAL", f_n, 0.16) / 2, ybot + 20), "NACIONAL", f_n, NEON, 0.16, "a")

    f_uf = _f(F_DATOS_B, 17)
    for i, (uf, l, f) in enumerate(filas):
        y = ytop + i * paso
        gana = BOLSO if f > l else LULA
        d.text((SAFE_X, y), uf, font=f_uf, fill=gana, anchor="lm")
        d.line([(sx(min(l, f)), y), (sx(max(l, f)), y)], fill=gana + (120,), width=3)
        for v, col in ((l, LULA), (f, BOLSO)):
            d.ellipse([sx(v) - 7, y - 7, sx(v) + 7, y + 7], fill=col, outline=TINTA, width=1)

    lulas = [l for _, l, _ in filas]
    sd = statistics.pstdev(lulas)
    lo, hi = min(filas, key=lambda f: f[1]), max(filas, key=lambda f: f[1])
    y = 1032
    d.line([(SAFE_X, y - 14), (W - SAFE_X, y - 14)], fill=(0xC4, 0x0B, 0xFF, 110))
    cols = (
        (f"{pct(lo[1], 0)}–{pct(hi[1], 0)}%", f"Lula entre {NOMBRE_UF[lo[0]]} y {NOMBRE_UF[hi[0]]}"),
        (f"±{pct(sd, 0)} pp", "desvío estándar entre estados"),
        (f"{sum(f > l for _, l, f in filas)} a {sum(l > f for _, l, f in filas)}", "estados: Flávio vs. Lula"),
    )
    cw = (W - 2 * SAFE_X) // 3
    for i, (v, t) in enumerate(cols):
        x = SAFE_X + i * cw
        d.text((x, y + 4), v, font=_f(F_DISPLAY, 50), fill=NEON, anchor="la")
        parrafo(d, (x, y + 70), t, _f(F_TEXTO, 19), TEXTO, cw - 30, 24)
    ap = conteo["por_uf"]["ap"]["votos"]
    nota = ("Conteo TSE al 99,6% de las secciones, % de votos válidos por estado (sin exterior). "
            f"En AP, Lula por {f0(ap['lula'] - ap['flavio_bolsonaro'])} votos.",
            "Ordenado por margen: arriba los estados más bolsonaristas, abajo los más lulistas.")
    pie(d, nota, n)
    return im


def lamina_geografia(res, mun, n):
    im = fondo().convert("RGBA")
    mapa, glow = render_lisa(mun, 700)
    mx, my = W - mapa.width - 24, 396
    _halo(im, glow, (mx, my))
    im.alpha_composite(mapa, (mx, my))
    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    encabezado(im, d, "LECCIÓN 2 · ANÁLISIS GEOESPACIAL")
    y = titular(d, ("EL VOTO TIENE", "GEOGRAFÍA"))
    d.text((SAFE_X, y + 12), "El voto no se reparte al azar: se agrupa en territorios.",
           font=_f(F_TEXTO, 25), fill=TEXTO, anchor="la")

    mg, gw = res["moran_municipios"], res["gwr"]
    f_k = _f(F_DATOS, 17)
    y = 470
    track(d, (SAFE_X, y), "ÍNDICE DE MORAN", f_k, LILA, 0.16, "a")
    d.text((SAFE_X - 4, y + 26), f2(mg["I"]), font=_f(F_DISPLAY, 96), fill=NEON, anchor="la")
    parrafo(d, (SAFE_X, y + 136), "1 sería agrupamiento perfecto; 0, azar.", _f(F_TEXTO, 19), TEXTO, 270, 24)

    y = 680
    track(d, (SAFE_X, y), "FOCOS (LISA)", f_k, LILA, 0.16, "a")
    y += 36
    for k, col, t in (("High-High", LULA, "municipios en focos de Lula"),
                      ("Low-Low", BOLSO, "en focos de Bolsonaro")):
        d.rectangle([SAFE_X, y + 6, SAFE_X + 6, y + 64], fill=col)
        d.text((SAFE_X + 20, y), f0(mg["clusters"][k]), font=_f(F_DISPLAY, 40), fill=BLANCO, anchor="la")
        d.text((SAFE_X + 20, y + 46), t, font=_f(F_TEXTO, 18), fill=TEXTO, anchor="la")
        y += 86

    y = 900
    track(d, (SAFE_X, y), "REGRESIÓN GEOGRÁFICA", f_k, LILA, 0.16, "a")
    track(d, (SAFE_X, y + 26), "(GWR) · R²", f_k, LILA, 0.16, "a")
    d.text((SAFE_X, y + 56), f"{f2(gw['r2_ols'])} → {f2(gw['r2_gwr'])}", font=_f(F_DISPLAY, 40),
           fill=NEON, anchor="la")
    parrafo(d, (SAFE_X, y + 110), "Si el efecto del Censo puede variar según el lugar, el modelo explica mucho más.",
            _f(F_TEXTO, 19), TEXTO, 300, 24)

    nota = (f"2º turno 2022, % Lula por municipio. LISA con 999 permutaciones, p < 0,01; en violeta oscuro, sin foco.",
            "GWR: alfabetización, población negra y parda, baños, mayores de 60 y urbanización (Censo 2022).")
    pie(d, nota, n)
    return im


LECCIONES = (
    ("Desagregá antes de concluir",
     "Un 47 a 45 nacional es un país partido: Lula va de 23% en Roraima a 71% en Piauí. "
     "Una media sin dispersión engaña."),
    ("El dónde explica el por qué",
     "Las mismas variables sociales pesan distinto según la región. Un modelo global no lo ve; el mapa, sí."),
    ("Medí la incertidumbre",
     "No publicamos una cifra sino dos escenarios. Se cumplió el que corregía el sesgo histórico de las "
     "encuestas: estaba sobre la mesa."),
)


def lamina_lecciones(n):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    encabezado(im, d, "LO QUE DEJA LA NOCHE")
    titular(d, ("TRES LECCIONES", "DE DATOS"))
    y = 450
    for i, (t, txt) in enumerate(LECCIONES, 1):
        d.line([(SAFE_X, y - 22), (W - SAFE_X, y - 22)], fill=(0xC4, 0x0B, 0xFF, 80))
        d.text((SAFE_X, y), f"{i:02d}", font=_f(F_DATOS_B, 56), fill=VIOLETA, anchor="la")
        x = SAFE_X + 120
        d.text((x, y + 4), t, font=_f(F_DISPLAY, 36), fill=BLANCO, anchor="la")
        yf = parrafo(d, (x, y + 62), txt, _f(F_TEXTO, 26), TEXTO, W - SAFE_X - x, 36)
        y = yf + 96
    pie(d, ("Fuente: TSE (conteo 2026 y resultados 2018/2022), IBGE (Censo 2022), agregador de encuestas Atlas.",), n)
    return im


def lamina_cierre(mun, n):
    im = fondo().convert("RGBA")
    mapa, glow = render_mapa(mun, 620, columna="lula_2026")
    mapa.putalpha(mapa.getchannel("A").point(lambda a: a * 0.35))
    glow.putalpha(glow.getchannel("A").point(lambda a: a * 0.4))
    mx, my = W - mapa.width + 120, 560
    _halo(im, glow, (mx, my))
    im.alpha_composite(mapa, (mx, my))
    im = grano(im.convert("RGB"), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    encabezado(im, d, "BRASIL 2026 · BALOTAJE 25/10")
    y = titular(d, ("¿CUÁNTAS DECISIONES", "SE TOMAN MIRANDO", "SOLO EL PROMEDIO?"), y=190, size=72, paso=84)
    parrafo(d, (SAFE_X, y + 30), "En política, en empresas y en gestión pública, los datos sirven cuando se "
            "desagregan, se ponen en el mapa y se miden con su incertidumbre.", _f(F_TEXTO, 27), TEXTO, 640, 38)

    y = 760
    track(d, (SAFE_X, y), "ATLAS ANALYTICS", _f(F_DATOS, 18), LILA, 0.2, "a")
    y += 44
    for t in ("ANALÍTICA ELECTORAL", "ESTADÍSTICA APLICADA", "ANÁLISIS GEOESPACIAL"):
        d.rectangle([SAFE_X, y - 2, SAFE_X + 5, y + 26], fill=VIOLETA)
        track(d, (SAFE_X + 20, y), t, _f(F_DATOS_B, 20), NEON, 0.16, "a")
        y += 48
    d.text((SAFE_X, y + 24), "Balotaje: 25 de octubre. Seguimos con los datos.",
           font=_f(F_DISPLAY, 26), fill=BLANCO, anchor="la")
    pie(d, (), n)
    return im


def main():
    conteo = json.loads(CONTEO.read_text(encoding="utf-8"))
    res_esp, mun_esp = espacial()
    mun = municipios_2026()
    SALIDA_C.mkdir(parents=True, exist_ok=True)
    total = 7
    previas = {2: SALIDA / f"post_resultado_1v_{FECHA_1V}.jpg", 5: SALIDA / f"post_minas_{FECHA_1V}.jpg"}
    nuevas = {
        1: lambda: lamina_portada(mun, (1, total)),
        3: lambda: lamina_promedio(conteo, (3, total)),
        4: lambda: lamina_geografia(res_esp, mun_esp, (4, total)),
        6: lambda: lamina_lecciones((6, total)),
        7: lambda: lamina_cierre(mun, (7, total)),
    }
    paginas = []
    for i in range(1, total + 1):
        im = Image.open(previas[i]).convert("RGB") if i in previas else nuevas[i]().convert("RGB")
        out = SALIDA_C / f"{i:02d}.jpg"
        im.save(out, quality=95, subsampling=0)
        paginas.append(im)
        print(out)
    pdf = SALIDA_C.parent / f"ATLAS_carrusel_linkedin_{FECHA_1V}.pdf"
    paginas[0].save(pdf, save_all=True, append_images=paginas[1:], resolution=72, quality=92)
    print(pdf)


if __name__ == "__main__":
    main()
