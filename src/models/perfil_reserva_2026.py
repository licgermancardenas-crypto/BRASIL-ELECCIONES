"""
src/models/perfil_reserva_2026.py

Perfil territorial de la reserva de Lula: los votantes de Lula en la 2ª vuelta
de 2022 que no votaron el 4/10/2026 (estimación por município de
movilizacion_2026), cruzados con el Censo 2022.

Es un perfil de TERRITORIOS, no de personas: dice en qué tipo de municípios
está la reserva, no quiénes son los que no votaron (falacia ecológica).

  1. Perfil comparado: promedios del Censo (por município, ponderados por
     población) pesados por cada electorado: reserva de Lula, reserva de
     Bolsonaro, votantes de Lula y de Flávio del 4/10 y el padrón.
  2. Concentración: reparto de la reserva y del voto a Lula por tamaño de
     município y por región.
  3. Abandono: qué parte de los votantes de Lula (y de Bolsonaro) en la 2ª
     vuelta de 2022 no votó el 4/10, por región y tamaño de município.
  4. Regresiones por município (MCO ponderado, efectos fijos de UF, errores
     robustos HC1, variables del Censo estandarizadas):
       a. abandono de Lula (ponderado por sus votos de 2022)
       b. abandono de Bolsonaro (ídem)
       c. cambio de la abstención 2022 -> 2026 (pp, ponderado por padrón)

Insumos: última corrida de movilizacion_2026, locales_censo_2022 (Censo por
local de votación) y locales_2022 (código IBGE), resultados por município.
Salida: data/processed/electoral/perfil_reserva_2026/<fecha_utc>/
    resumen.json, municipios.parquet

Uso:
    python -m src.models.perfil_reserva_2026
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.etl.transform.base_locales import salida as salida_locales
from src.etl.transform.votacion_seccion import SALIDA_DIR as SECCION_DIR
from src.models.balotaje_2026 import municipios_previos
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR
from src.models.movilizacion_2026 import SALIDA_DIR as MOVILIZACION_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "perfil_reserva_2026"
CENSO = {"jovenes_15_29": "15 a 29 años", "mayores_60": "60 años o más", "preta_parda": "Población negra o parda",
         "alfabetizacion": "Alfabetización (15+)", "banos_2mas": "Hogares con 2 baños o más",
         "cloaca_red": "Cloaca a red", "urbano": "Población urbana"}
TAMANO = [0, 20_000, 100_000, 500_000, np.inf]
TAMANO_ET = ["Menos de 20 mil electores", "20 a 100 mil", "100 a 500 mil", "Más de 500 mil"]
GRUPOS = {"reserva_lula": "Reserva de Lula", "reserva_bolsonaro": "Reserva de Bolsonaro",
          "lula_1v": "Votó Lula el 4/10", "flavio_1v": "Votó Flávio el 4/10", "padron": "Padrón"}


def censo_municipal() -> pd.DataFrame:
    c = pd.read_parquet(SECCION_DIR / "locales_censo_2022.parquet")
    l = pd.read_parquet(salida_locales(2022), columns=["uf", "cd_municipio", "nr_zona", "nr_local", "cd_ibge"])
    c = c.merge(l, on=["uf", "cd_municipio", "nr_zona", "nr_local"], how="inner")
    v = list(CENSO)
    c = c[(c["pop"] > 0)].dropna(subset=v)
    g = c.groupby("cd_ibge").apply(lambda x: pd.Series({**{k: np.average(x[k], weights=x["pop"]) for k in v},
                                                         "pop_censo": x["pop"].sum()}), include_groups=False)
    return g


def regresion(df: pd.DataFrame, y: str, peso: str = "aptos") -> dict:
    X = df[list(CENSO)]
    X = (X - X.mean()) / X.std()
    X["log_padron"] = np.log(df["aptos"])
    X = X.join(pd.get_dummies(df["uf"], prefix="uf", drop_first=True, dtype=float))
    X = sm.add_constant(X)
    m = sm.WLS(df[y], X, weights=df[peso]).fit(cov_type="HC1")
    return {"n": int(m.nobs), "r2": float(m.rsquared),
            "coef": {k: {"b": float(m.params[k]), "se": float(m.bse[k]), "p": float(m.pvalues[k])}
                     for k in [*CENSO, "log_padron"]}}


def main() -> None:
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)
    mov_dir = sorted(p.parent for p in MOVILIZACION_DIR.glob("*/meta.json"))[-1]
    mv = pd.read_parquet(mov_dir / "municipios.parquet")
    m22 = municipios_previos(2022)
    cz = censo_municipal()
    df = mv.join(cz, how="inner").join(m22[["abstencion_1", "aptos", "pt_2", "bolsonaro_2"]].rename(
        columns={"abstencion_1": "abst_22", "aptos": "aptos_22"}), how="inner")
    df = df[(df["aptos"] > 0) & (df["aptos_22"] > 0) & (df["pt_2"] > 0) & (df["bolsonaro_2"] > 0)].dropna(subset=list(CENSO))
    log.info("%d municípios con reserva, Censo y 2022 (de %d)", len(df), len(mv))
    df["reserva_por_elector"] = df["pt_abst"] / df["aptos"] * 100
    # abandono: parte de los votantes de cada uno en la 2ª vuelta de 2022 que no votó el 4/10
    df["abandono_lula"] = df["pt_abst"] / df["pt_2"] * 100
    df["abandono_bolsonaro"] = df["bolsonaro_abst"] / df["bolsonaro_2"] * 100
    df["cambio_abst"] = df["abstencion_1"] / df["aptos"] * 100 - df["abst_22"] / df["aptos_22"] * 100
    pesos = {"reserva_lula": df["pt_abst"], "reserva_bolsonaro": df["bolsonaro_abst"], "lula_1v": df["pt_1"],
             "flavio_1v": df["bolsonaro_1"], "padron": df["aptos"]}

    perfil = {g: {k: float(np.average(df[k], weights=w) * 100) for k in CENSO} for g, w in pesos.items()}
    df["tamano"] = pd.cut(df["aptos"], TAMANO, labels=TAMANO_ET, right=False)
    conc = {}
    for nombre, col in (("tamano", "tamano"), ("region", "region")):
        t = df.groupby(col, observed=True)[["pt_abst", "bolsonaro_abst", "pt_1", "aptos"]].sum()
        conc[nombre] = (t / t.sum() * 100).to_dict(orient="index")
    # capitales: municípios con más de 500 mil electores son casi todos capitales o grandes metrópolis
    reg = {"abandono_lula": regresion(df, "abandono_lula", "pt_2"),
           "abandono_bolsonaro": regresion(df, "abandono_bolsonaro", "bolsonaro_2"),
           "cambio_abstencion": regresion(df, "cambio_abst")}
    q = pd.qcut(df["abandono_lula"], 5, labels=False)
    quint = df.groupby(q).apply(lambda x: pd.Series({
        "abandono_lula": np.average(x["abandono_lula"], weights=x["pt_2"]),
        "abandono_bolsonaro": np.average(x["abandono_bolsonaro"], weights=x["bolsonaro_2"]),
        "electores_m": x["aptos"].sum() / 1e6, "reserva_m": x["pt_abst"].sum() / 1e6,
        **{k: np.average(x[k], weights=x["aptos"]) * 100 for k in CENSO}}), include_groups=False)

    abandono = {"lula": float(df["pt_abst"].sum() / df["pt_2"].sum() * 100),
                "bolsonaro": float(df["bolsonaro_abst"].sum() / df["bolsonaro_2"].sum() * 100),
                "lula_por_region": (df.groupby("region")["pt_abst"].sum() / df.groupby("region")["pt_2"].sum() * 100).to_dict(),
                "bolsonaro_por_region": (df.groupby("region")["bolsonaro_abst"].sum()
                                         / df.groupby("region")["bolsonaro_2"].sum() * 100).to_dict(),
                "lula_por_tamano": (df.groupby("tamano", observed=True)["pt_abst"].sum()
                                    / df.groupby("tamano", observed=True)["pt_2"].sum() * 100).to_dict(),
                "bolsonaro_por_tamano": (df.groupby("tamano", observed=True)["bolsonaro_abst"].sum()
                                         / df.groupby("tamano", observed=True)["bolsonaro_2"].sum() * 100).to_dict()}
    resumen = {"municipios": len(df), "abandono": abandono, "cobertura_reserva": float(df["pt_abst"].sum() / mv["pt_abst"].sum()),
               "perfil": perfil, "etiquetas": {"censo": CENSO, "grupos": GRUPOS}, "concentracion": conc,
               "regresiones": reg, "quintiles_reserva": quint.reset_index(drop=True).to_dict(orient="records"),
               "movilizacion_corrida": mov_dir.name}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    df.drop(columns="tamano").to_parquet(out / "municipios.parquet")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello}), encoding="utf-8")
    d = pd.DataFrame(perfil).T.round(1)
    log.info("perfil (%%):\n%s", d.to_string())
    for y, r in reg.items():
        log.info("%s (R² %.2f): %s", y, r["r2"], ", ".join(f"{k} {v['b']:+.2f}{'*' if v['p'] < 0.05 else ''}"
                                                        for k, v in r["coef"].items()))
    log.info("concentración por tamaño:\n%s", pd.DataFrame(conc["tamano"]).T.round(1).to_string())
    log.info("salida %s", out)


if __name__ == "__main__":
    main()
