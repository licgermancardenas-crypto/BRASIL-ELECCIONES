# -*- coding: utf-8 -*-
"""Piezas para la noche del balotaje (25/10/2026): pronóstico Atlas contra resultado.

Lee una foto del tablero (src/models/tablero_2v_2026.py, estado.json) y arma
tres posts de Instagram (marca neón, 1080x1350) con su texto:

  post_noche_presidente_<sello>.jpg   Lula y Flávio: pronóstico vs. resultado (o proyección)
  post_noche_estados_<sello>.jpg      27 UF: pronóstico vs. resultado
  post_noche_gobernadores_<sello>.jpg los 7 balotajes estaduales

Mientras el conteo no llega al 100 % las piezas dicen "proyección" y muestran
el % contado; con el 100 % dicen "resultado". No proclaman ganador antes del
99,5 % contado.

    python -m src.viz.redes_noche_balotaje                     # última foto real del tablero
    python -m src.viz.redes_noche_balotaje --estado <ruta>     # una foto en particular
    python -m src.viz.redes_noche_balotaje --demo [--parcial]  # noche simulada 2022, con marca DEMO
"""
import argparse
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from src.models.tablero_2v_2026 import SALIDA_DIR as TABLERO_DIR
from src.viz.post_pronostico import (BLANCO, BOLSO, F_DATOS, F_DATOS_B, F_DISPLAY, F_TEXTO, H, LILA, LULA, NEON, SAFE_X,
                                     SALIDA, TEXTO, W, _f, fondo, grano, pct, track)
from src.viz.redes_balotaje import FONDO_BARRA, GRIS_TXT, cabecera, cifras, pie, titular

FINAL = 99.5   # % contado a partir del cual se habla de resultado


# --------------------------------------------------------------------------- datos
def cargar(ruta: Path | None, demo: bool, parcial: bool) -> tuple[dict, str]:
    if demo:
        ruta = TABLERO_DIR / ("simulacion-paso-06" if parcial else "simulacion-paso-12") / "estado.json"
    elif ruta is None:
        fotos = sorted(p for p in TABLERO_DIR.glob("*/estado.json") if not p.parent.name.startswith("simulacion"))
        if not fotos:
            raise FileNotFoundError("Todavía no hay fotos reales del tablero: correr src.models.tablero_2v_2026")
        ruta = fotos[-1]
    E = json.loads(ruta.read_text(encoding="utf-8"))
    if demo and not E.get("gobernadores"):
        # Gobernadores inventados para probar el diseño: pronóstico 2026 con ruido. Solo en --demo, con marca DEMO.
        from src.models.balotaje_gobernadores_2026 import SALIDA_DIR as GOB_DIR
        g = pd.read_csv(sorted(p.parent for p in GOB_DIR.glob("*/meta.json"))[-1] / "por_uf.csv")
        rng = np.random.default_rng(25)
        E["gobernadores"] = [{"uf": r.uf, "A": r.A, "B": r.B, "pronostico_A": r.pct_A_2v, "prob_A": r.prob_A,
                              "pct_secciones": 100.0 if not parcial else 60.0,
                              "A_contado": float(np.clip(r.pct_A_2v + rng.normal(0, 6), 30, 70))} for r in g.itertuples()]
    return E, ruta.parent.name


def es_final(E: dict) -> bool:
    return E["votos_contados_pct"] >= FINAL


def lula_final(E: dict) -> float:
    return E["lula_contado"] if es_final(E) else E["lula_proyectado"]


def nombre(s: str) -> str:
    t = s.title()
    for p in (" De ", " Da ", " Do ", " Dos ", " Das "):
        t = t.replace(p, p.lower())
    return t


def demo_marca(im):
    capa = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    f = _f(F_DISPLAY, 150)
    d.text((W / 2, H / 2), "DEMO", font=f, fill=(255, 255, 255, 46), anchor="mm")
    d.text((W / 2, H / 2 + 110), "DATOS SIMULADOS · NO PUBLICAR", font=_f(F_DATOS_B, 34), fill=(255, 255, 255, 70), anchor="mm")
    im.alpha_composite(capa.rotate(28, center=(W / 2, H / 2)))


def kicker(E: dict) -> str:
    return "BALOTAJE 25/10 · RESULTADO" if es_final(E) else f"BALOTAJE 25/10 · {pct(E['votos_contados_pct'], 0)}% CONTADO"


# --------------------------------------------------------------------------- posts
def post_presidente(E, salida, demo):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    cabecera(im, d, kicker(E))
    lu = lula_final(E)
    fl = 100 - lu
    pron = E["lula_pronostico"]
    if es_final(E):
        gana = "LULA" if lu > 50 else "FLÁVIO BOLSONARO"
        lineas = [gana, "GANA EL", "BALOTAJE"] if len(gana) < 10 else ["FLÁVIO", "BOLSONARO", "GANA EL BALOTAJE"]
        sub = [f"Atlas pronosticó Lula {pct(pron, 1)}% el 7 de octubre, sin encuestas.",
               f"Resultado: {pct(lu, 1)}%. Diferencia: {'+' if lu - pron >= 0 else '−'}{pct(abs(lu - pron), 1)} puntos."]
    else:
        lineas = ["PROYECCIÓN", "ATLAS"]
        sub = [f"Con el {pct(E['votos_contados_pct'], 0)}% de los votos contados, Lula rinde "
               f"{pct(abs(E['desvio_nacional_pp']), 1)} pts {'más' if E['desvio_nacional_pp'] > 0 else 'menos'}",
               "de lo que esperaba el pronóstico en esos mismos municipios."]
    y = titular(d, lineas, sub)

    x0, x1 = SAFE_X, W - SAFE_X
    yb = max(y + 70, 690)
    for nombre_c, v, col in (("FLÁVIO BOLSONARO", fl, BOLSO), ("LULA", lu, LULA)):
        track(d, (x0, yb), nombre_c, _f(F_DATOS, 22), GRIS_TXT, 0.14, "a")
        d.text((x1, yb - 14), f"{pct(v, 1)}%", font=_f(F_DISPLAY, 58), fill=col, anchor="ra")
        d.rectangle([x0, yb + 50, x1, yb + 74], fill=FONDO_BARRA)
        d.rectangle([x0, yb + 50, x0 + (x1 - x0) * v / 100, yb + 74], fill=col)
        yb += 130
    xm = x0 + (x1 - x0) * 0.5
    for yy in range(yb - 260 + 44, yb - 40, 12):
        d.line([(xm, yy), (xm, yy + 6)], fill=(255, 255, 255, 150), width=2)
    # marca del pronóstico sobre la barra de Lula
    xp = x0 + (x1 - x0) * pron / 100
    d.polygon([(xp, yb - 130 + 46), (xp - 9, yb - 130 + 32), (xp + 9, yb - 130 + 32)], fill=NEON)
    d.text((xp, yb - 130 + 26), f"pronóstico {pct(pron, 1)}%", font=_f(F_DATOS, 17), fill=NEON, anchor="ms")

    if es_final(E):
        cifras(d, 1000, [(f"{pct(pron, 1)}%", NEON, "Lula, pronóstico", "Atlas del 7/10"),
                         (f"{pct(lu, 1)}%", LULA, "Lula, resultado", "oficial del TSE"),
                         (f"{'+' if lu - pron >= 0 else '−'}{pct(abs(lu - pron), 1)}", BLANCO, "puntos de diferencia", "con el pronóstico")])
    else:
        lo, hi = lu - 1.645 * E["sd_pp"], lu + 1.645 * E["sd_pp"]
        cifras(d, 1000, [(f"{pct(E['lula_contado'], 1)}%", GRIS_TXT, "Lula en lo contado", "(engaña: depende de qué entró)"),
                         (f"{pct(lu, 1)}%", LULA, "Lula proyectado", f"rango {pct(lo, 1)}–{pct(hi, 1)}%"),
                         (f"{round(E['prob_lula'] * 100)}%", NEON, "probabilidad", "de que gane Lula")])
    pie(d, [f"TSE, divulgación oficial · {E.get('hora_tse', '')}. Votos válidos.",
            "Pronóstico y proyección: modelo Atlas sin encuestas, municipio por municipio."])
    if demo:
        demo_marca(im)
    im.convert("RGB").save(salida, quality=95, subsampling=0)


def grafico_estados(E) -> tuple[Image.Image, dict]:
    u = pd.DataFrame(E["por_uf"])
    u["res"] = np.where(u["pct_contado"] >= FINAL, u["lula_contado"], u["lula_proj"])
    u = u.sort_values("res")
    fig, ax = plt.subplots(figsize=(9.6, 6.6), dpi=110)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    y = np.arange(len(u))
    neon, lula, bolso, txt = [tuple(c / 255 for c in x) for x in (NEON, LULA, BOLSO, TEXTO)]
    ax.axvline(50, color=(1, 1, 1, 0.45), lw=1)
    for i, r in enumerate(u.itertuples()):
        ax.plot([r.pronostico, r.res], [i, i], color=(0.77, 0.04, 1, 0.45), lw=2.4, zorder=1)
        ax.scatter(r.pronostico, i, s=46, facecolors="none", edgecolors=neon, linewidths=1.6, zorder=2)
        ax.scatter(r.res, i, s=58, color=lula if r.res > 50 else bolso, zorder=3)
    ax.set_yticks(y, u["uf"], fontsize=13, color=txt, fontfamily="Consolas")
    ax.set_xlim(10, 90)
    ax.set_xticks([20, 35, 50, 65, 80], ["20%", "35%", "50%", "65%", "80%"], fontsize=13, color=txt)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=(1, 1, 1, 0.08))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight")
    plt.close(fig)
    err = (u["res"] - u["pronostico"])
    stats = {"mae": float(err.abs().mean()), "aciertos": int(((u["res"] > 50) == (u["pronostico"] > 50)).sum()),
             "n": len(u), "max_uf": u.loc[err.abs().idxmax(), "uf"], "max_err": float(err.loc[err.abs().idxmax()])}
    return Image.open(buf).convert("RGBA"), stats


def post_estados(E, salida, demo):
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    cabecera(im, d, kicker(E))
    g, st = grafico_estados(E)
    palabra = "RESULTADO" if es_final(E) else "PROYECCIÓN"
    titular(d, ["ESTADO POR ESTADO"], [f"Lula: pronóstico Atlas (○) contra {palabra.lower()} (●).",
                                        f"Ganador correcto en {st['aciertos']} de {st['n']} estados."], y=168)
    g = g.resize((W - 2 * SAFE_X + 20, round(g.height * (W - 2 * SAFE_X + 20) / g.width)), Image.LANCZOS)
    if g.height > 600:
        g = g.resize((round(g.width * 600 / g.height), 600), Image.LANCZOS)
    im.alpha_composite(g, (SAFE_X - 20, 350))
    d = ImageDraw.Draw(im, "RGBA")
    cifras(d, 1000, [(f"{pct(st['mae'], 1)} pts", NEON, "error medio", "por estado"),
                     (f"{st['aciertos']}/{st['n']}", BLANCO, "estados con el", "ganador correcto"),
                     (f"{'+' if st['max_err'] > 0 else '−'}{pct(abs(st['max_err']), 1)}", LULA if st["max_err"] > 0 else BOLSO,
                      f"mayor desvío: {st['max_uf']}", "(pts de Lula)")])
    pie(d, [f"TSE · {E.get('hora_tse', '')}. Votos válidos. Sin exterior. Rojo: gana Lula; azul: gana Flávio.",
            "Estados sin terminar de contar: proyección del tablero Atlas."])
    if demo:
        demo_marca(im)
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return st


def post_gobernadores(E, salida, demo):
    gob = [g for g in E.get("gobernadores", []) if g.get("A_contado") is not None]
    if not gob:
        return None
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    cabecera(im, d, "BALOTAJE 25/10 · GOBERNADORES")
    ok = sum((g["A_contado"] > 50) == (g["pronostico_A"] > 50) for g in gob)
    titular(d, ["SIETE BALOTAJES", "ESTADUALES"], [f"Pronóstico Atlas contra conteo del TSE. Ganador correcto en {ok} de {len(gob)}."])
    y = 520
    x0, x1 = SAFE_X, W - SAFE_X
    for g in sorted(gob, key=lambda g: -g["prob_A"]):
        a, b = nombre(g["A"]), nombre(g["B"])
        acierto = (g["A_contado"] > 50) == (g["pronostico_A"] > 50)
        track(d, (x0, y), g["uf"], _f(F_DATOS_B, 26), NEON, 0.1, "a")
        d.text((x0 + 70, y), f"{a} vs {b}", font=_f(F_TEXTO, 23), fill=BLANCO, anchor="la")
        d.text((x1, y), "✓" if acierto else "✗", font=_f(r"C:\Windows\Fonts\seguisym.ttf", 28),
               fill=NEON if acierto else LULA, anchor="ra")
        txt = (f"pronóstico {pct(g['pronostico_A'], 1)}% · {'resultado' if g['pct_secciones'] >= FINAL else 'contado'} "
               f"{pct(g['A_contado'], 1)}%" + ("" if g["pct_secciones"] >= FINAL else f" ({pct(g['pct_secciones'], 0)}% secc.)"))
        d.text((x0 + 70, y + 34), txt, font=_f(F_DATOS, 19), fill=GRIS_TXT, anchor="la")
        y += 82
    pie(d, [f"% del primero de la 1ª vuelta sobre los votos de los dos finalistas. TSE · {E.get('hora_tse', '')}.",
            "Pronóstico: cada finalista conserva su proporción de la 1ª vuelta (mejor método en 2018-2022)."])
    if demo:
        demo_marca(im)
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return ok, len(gob)


# --------------------------------------------------------------------------- textos
def textos(E, st, gob) -> dict:
    lu, pron = lula_final(E), E["lula_pronostico"]
    dif = lu - pron
    if es_final(E):
        abre = (f"Lula ganó el balotaje en Brasil con {pct(lu, 1)}% de los votos válidos." if lu > 50 else
                f"Flávio Bolsonaro ganó el balotaje en Brasil con {pct(100 - lu, 1)}% de los votos válidos.")
        pres = (f"{abre}\n\nEl 7 de octubre, sin usar encuestas, pronosticamos Lula {pct(pron, 1)}%. El resultado le dio "
                f"{pct(abs(dif), 1)} puntos {'más' if dif > 0 else 'menos'} de lo pronosticado. El modelo partía del resultado de la "
                "primera vuelta, municipio por municipio, y de cómo se habían movido los votos entre vueltas en 2022.")
    else:
        pres = (f"Con el {pct(E['votos_contados_pct'], 0)}% de los votos contados, Lula tiene {pct(E['lula_contado'], 1)}%. "
                f"Nuestra proyección: {pct(lu, 1)}%.\n\nEl número contado engaña porque no todo el país cuenta al mismo ritmo. "
                "Comparamos cada municipio ya contado con lo que esperábamos de él y proyectamos lo que falta. "
                f"Lula rinde {pct(abs(E['desvio_nacional_pp']), 1)} puntos {'más' if E['desvio_nacional_pp'] > 0 else 'menos'} "
                "de lo previsto.")
    est = (f"Estado por estado, el pronóstico erró en promedio {pct(st['mae'], 1)} puntos y acertó el ganador en "
           f"{st['aciertos']} de {st['n']} estados. El mayor desvío fue en {st['max_uf']} "
           f"({'+' if st['max_err'] > 0 else '−'}{pct(abs(st['max_err']), 1)} puntos de Lula).")
    gtxt = "" if gob is None else (f"En los siete balotajes de gobernador, el pronóstico acertó el ganador en {gob[0]} de {gob[1]}. "
                                   "Usamos el método más simple: cada finalista conserva su proporción de la primera vuelta, "
                                   "el que mejor funcionó en 2018 y 2022.")
    tags = "\n\n#AtlasAnalytics #Brasil2026 #EleiçõesBrasil #Elecciones #DataViz"
    return {"presidente": pres + tags, "estados": est + tags, "gobernadores": (gtxt + tags) if gtxt else ""}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--estado", type=Path)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--parcial", action="store_true", help="con --demo: noche a medio contar")
    a = ap.parse_args(argv)
    E, sello = cargar(a.estado, a.demo, a.parcial)
    tag = ("demo-" + ("parcial" if a.parcial else "final")) if a.demo else sello
    out = SALIDA / "noche_25-10"
    out.mkdir(parents=True, exist_ok=True)
    post_presidente(E, out / f"post_noche_presidente_{tag}.jpg", a.demo)
    st = post_estados(E, out / f"post_noche_estados_{tag}.jpg", a.demo)
    gob = post_gobernadores(E, out / f"post_noche_gobernadores_{tag}.jpg", a.demo)
    for k, t in textos(E, st, gob).items():
        if t:
            (out / f"post_noche_{k}_{tag}.txt").write_text(t, encoding="utf-8")
    print(out, tag)


if __name__ == "__main__":
    main()
