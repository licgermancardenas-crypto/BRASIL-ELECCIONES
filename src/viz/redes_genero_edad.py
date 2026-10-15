# -*- coding: utf-8 -*-
"""Post de Instagram "Sexo y edad en el balotaje" (marca neón, 1080x1350, PIL), a
partir de la última corrida de src/models/genero_edad_balotaje_2026.py.

Salida: reports/figures/redes/post_genero_edad_<fecha>.jpg y el texto en .txt.

    python -m src.viz.redes_genero_edad [--fecha 2026-10-15]
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from PIL import ImageDraw

import src.viz.carrusel_linkedin as cl
from src.models.genero_edad_balotaje_2026 import SALIDA_DIR
from src.viz.post_pronostico import (BLANCO, BOLSO, F_DATOS, F_DISPLAY, F_TEXTO, LULA, NEON, SAFE_X, SALIDA, TEXTO, W,
                                     _f, fondo, grano, track)
from src.viz.redes_balotaje import GRIS_TXT, cabecera, pie, titular

f1 = cl.f1
pc = lambda x: f1(x * 100) + "%"


def cargar() -> dict:
    corrida = sorted(p.parent for p in SALIDA_DIR.glob("*/resumen.json"))[-1]
    return json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))


def barra(d, y, etiqueta, lula):
    """Barra partida Lula | Flávio sobre votos válidos."""
    x0, x1, alto = SAFE_X, W - SAFE_X, 64
    xm = x0 + (x1 - x0) * lula / 100
    d.text((x0, y), etiqueta, font=_f(F_DATOS, 22), fill=BLANCO, anchor="la")
    yb = y + 36
    d.rectangle([x0, yb, xm - 2, yb + alto], fill=LULA)
    d.rectangle([xm + 2, yb, x1, yb + alto], fill=BOLSO)
    d.text((x0 + 18, yb + alto / 2), f"LULA {f1(lula)}%", font=_f(F_DATOS, 26), fill=BLANCO, anchor="lm")
    d.text((x1 - 18, yb + alto / 2), f"FLÁVIO {f1(100 - lula)}%", font=_f(F_DATOS, 26), fill=BLANCO, anchor="rm")
    return yb + alto


def post(R, salida):
    B, P, p22, p26 = R["encuestas"], R["participacion"], R["padron"]["2022"], R["padron"]["2026"]
    jov = B["por_casa"]["Indexa/Broadcast"]["e_16_24"]
    im = grano(fondo(), 6).convert("RGBA")
    d = ImageDraw.Draw(im, "RGBA")
    cabecera(im, d, "BRASIL 2026 · BALOTAJE 25/10")
    y = titular(d, ["SEXO Y EDAD", "EN EL BALOTAJE"],
                ["Mujeres con Lula, hombres con Flávio: qué dicen", "las encuestas y los datos del TSE a diez días del 25/10."], y=168)
    y += 30
    y = barra(d, y, "MUJERES", B["mujeres_media"])
    y = barra(d, y + 26, "HOMBRES", B["hombres_media"])
    d.text((SAFE_X, y + 14), "Promedio de Indexa, Palver y Nexus (10–14/10), votos válidos.",
           font=_f(F_TEXTO, 19), fill=GRIS_TXT, anchor="la")
    items = [
        (f"+{f1(B['brecha_genero_media_pp'])}", NEON, "pts de brecha de género.",
         f"En 2022 era de +{B['brecha_genero_2022_pp']} (Datafolha): se triplicó."),
        (f"{jov:.0f}%", LULA, "Lula entre los de 16 a 24 (válidos).",
         "En las demás edades, parejo (Indexa, 13–14/10)."),
        (pc(p26["60+"]), BLANCO, "del padrón tiene 60 o más.",
         f"En 2022: {pc(p22['60+'])}. Votaron {pc(P['2022_1v']['60+'])} → {pc(P['2026_1v']['60+'])} (1ª vuelta)."),
    ]
    y += 96
    for v, col, l1, l2 in items:
        d.line([(SAFE_X, y - 20), (W - SAFE_X, y - 20)], fill=(0xC4, 0x0B, 0xFF, 60))
        track(d, (SAFE_X, y + 46), v, _f(F_DISPLAY, 64), col, -0.02, "s")
        d.text((SAFE_X + 300, y + 8), l1, font=_f(F_TEXTO, 25), fill=BLANCO, anchor="la")
        d.text((SAFE_X + 300, y + 42), l2, font=_f(F_TEXTO, 22), fill=TEXTO, anchor="la")
        y += 112
    pie(d, ["El voto es secreto: no hay votos oficiales por sexo o edad. Preferencias: encuestas.",
            "Padrón y participación: TSE, perfil del electorado y comparecencia por perfil."])
    im.convert("RGB").save(salida, quality=95, subsampling=0)
    return salida


def texto(R) -> str:
    B, P, p22, p26 = R["encuestas"], R["participacion"], R["padron"]["2022"], R["padron"]["2026"]
    jov = B["por_casa"]["Indexa/Broadcast"]["e_16_24"]
    lo, hi = B["brecha_genero_rango_pp"]
    return f"""Sexo y edad en el balotaje de Brasil.

Las encuestas coinciden: Lula gana entre las mujeres ({f1(B['mujeres_media'])}% de los válidos) y Flávio Bolsonaro entre los hombres ({f1(100 - B['hombres_media'])}%).

+{f1(B['brecha_genero_media_pp'])} pts: la brecha de género en promedio (entre {f1(lo)} y {f1(hi)} según la encuesta). En 2022 era de +{B['brecha_genero_2022_pp']}.
{jov:.0f}%: Lula entre los de 16 a 24 años. En las demás edades la elección está pareja.
{pc(p26['60+'])}: los mayores de 60 en el padrón (en 2022, {pc(p22['60+'])}). Su participación subió de {pc(P['2022_1v']['60+'])} a {pc(P['2026_1v']['60+'])}.

Las mujeres son el {pc(p26['mujeres'])} del padrón y votan más que los hombres ({pc(P['2026_1v']['mujeres'])} contra {pc(P['2026_1v']['hombres'])} el 4/10).

El voto es secreto: no hay datos oficiales de cómo vota cada grupo. Las preferencias son de Indexa, Palver y Nexus; padrón y participación, del TSE.

#AtlasAnalytics #Brasil2026 #EleiçõesBrasil #Elecciones #DataViz"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    fecha = ap.parse_args(argv).fecha
    R = cargar()
    SALIDA.mkdir(parents=True, exist_ok=True)
    out = SALIDA / f"post_genero_edad_{fecha}.jpg"
    post(R, out)
    out.with_suffix(".txt").write_text(texto(R), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
