"""
src/viz/tendencia_presidencial.py

Figura del brief: encuestas de 1ª vuelta 2026 (votos válidos, cada punto una
encuesta) y la tendencia del agregador (src/models/agregacion_encuestas.py)
recalculada día por día, para Lula y Flávio Bolsonaro.

Output: reports/figures/presidencial_1v_tendencia_<corte>.png

Uso:
    python -m src.viz.tendencia_presidencial [--corte 2026-10-01]
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from src.etl.transform.encuestas_resultados import SALIDA as ENCUESTAS
from src.models.agregacion_encuestas import (a_validos, agregar, errores_finales, escenario_principal,
                                             fechas_eleccion, track_record)
from src.models.montecarlo.proyeccion_bancas import ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FIGURAS = ROOT / "reports" / "figures"
# Paleta categórica validada (slots 1-2, superficie clara): ver skill dataviz
SERIES = {"lula": ("Lula (PT)", "#2a78d6"), "flavio_bolsonaro": ("Flávio Bolsonaro (PL)", "#eb6834")}
SUPERFICIE, TEXTO, TEXTO_2, GRILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def corte_por_defecto() -> date:
    ano = cargar_config()["encuestas"]["ano_objetivo"]
    return min(date.today(), fechas_eleccion(ano)[1] - timedelta(days=1))


def calcular(corte: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(meta y % válidos de cada encuesta de 1ª vuelta hasta `corte`, agregado día por día)."""
    cfg = cargar_config()["encuestas"]
    largo = pd.read_parquet(ENCUESTAS)
    errs = pd.concat([errores_finales(largo, a, cfg["ventana_final_dias"]) for a in cfg["anos_historicos"]])
    tr, _ = track_record(errs, cfg["shrink_track_record"])
    pesos = dict(zip(tr["casa"], tr["peso_calidad"]))
    meta, val = a_validos(escenario_principal(largo, cfg["ano_objetivo"], 1))
    dentro = meta["fecha_fin"].dt.date <= corte
    meta, val = meta[dentro], val[dentro]
    dias = pd.date_range(meta["fecha_fin"].min() + pd.Timedelta(days=7), pd.Timestamp(corte))
    tendencia = pd.DataFrame([agregar(meta, val, d.date(), pesos, cfg)["estimacion"] for d in dias], index=dias)
    return meta, val, tendencia


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corte", type=date.fromisoformat)
    args = parser.parse_args(argv)

    corte = args.corte or corte_por_defecto()
    meta, val, tendencia = calcular(corte)


    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(9, 5.2), facecolor=SUPERFICIE)
    ax.set_facecolor(SUPERFICIE)
    for cand, (nombre, color) in SERIES.items():
        ax.scatter(meta["fecha_fin"], val[cand] * 100, s=22, color=color, alpha=0.35, linewidths=0, zorder=2)
        ax.plot(tendencia.index, tendencia[cand] * 100, color=color, lw=2, zorder=3, label=nombre)
        ult = tendencia[cand].iloc[-1] * 100
        ax.scatter([tendencia.index[-1]], [ult], s=64, color=color, edgecolors=SUPERFICIE, linewidths=2, zorder=4)
        ax.annotate(f"{nombre}  {ult:.1f}%".replace(".", ","), (tendencia.index[-1], ult), xytext=(8, 0),
                    textcoords="offset points", va="center", color=TEXTO, fontsize=9.5)

    ax.set_ylim(30, 50)
    ax.yaxis.set_major_locator(plt.MultipleLocator(4))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    lunes = pd.date_range(meta["fecha_fin"].min(), pd.Timestamp(corte), freq="W-MON")
    ax.set_xticks(lunes)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.grid(axis="y", color=GRILLA, lw=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRILLA)
    ax.tick_params(colors=TEXTO_2, length=0)
    ax.legend(loc="lower left", frameon=False, labelcolor=TEXTO)
    ax.set_xlim(right=tendencia.index[-1] + pd.Timedelta(days=11))
    fig.suptitle("1ª vuelta presidencial 2026: intención de voto (votos válidos)",
                 x=0.06, ha="left", color=TEXTO, fontsize=13, fontweight="bold")
    ax.set_title(f"Puntos: encuestas individuales · Línea: agregado ATLAS (house effects, recencia, "
                 f"track record) · corte {corte:%d/%m/%Y}", loc="left", color=TEXTO_2, fontsize=9)
    fig.text(0.06, 0.012, "Fuente: encuestas publicadas (Wikipedia); track record contra resultados TSE 2018/2022.\n"
             "En 2018 y 2022 las encuestas subestimaron al candidato bolsonarista 4-6 pp antes de la 1ª vuelta.",
             color=TEXTO_2, fontsize=8, va="bottom")
    fig.tight_layout(rect=(0, 0.06, 1, 1))

    FIGURAS.mkdir(parents=True, exist_ok=True)
    salida = FIGURAS / f"presidencial_1v_tendencia_{corte:%Y-%m-%d}.png"
    fig.savefig(salida, dpi=160, facecolor=SUPERFICIE)
    tendencia.mul(100).round(2).to_csv(salida.with_suffix(".csv"), index_label="fecha")
    log.info("Guardado %s", salida.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
