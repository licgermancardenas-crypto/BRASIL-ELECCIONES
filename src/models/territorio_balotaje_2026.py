"""
src/models/territorio_balotaje_2026.py

¿Dónde se decide el balotaje? Cruza el pronóstico municipal (balotaje_2026,
método R), la reserva de abstencionistas (movilizacion_2026) y el cambio
2022 -> 2026 de la 1ª vuelta, sin encuestas.

  1. Por UF: margen pronosticado en votos (Flávio − Lula), votos en juego
     (válidos de terceros + reserva de Lula y de Bolsonaro 2022 que no votó
     el 4/10), y elasticidad de la participación: votos netos para Lula por
     cada punto más de participación en la UF, si los nuevos votantes votan
     como su município en la 2ª vuelta de 2022.
  2. Dónde perdió Lula desde 2022: cambio de votos de 1ª vuelta del PT y del
     bolsonarismo por UF (la brecha de 2026 se abrió ahí).
  3. Termómetros: UF cuyo % Lula (entre Lula y el bolsonarismo) quedó más
     cerca del nacional en 2018, 2022 y la 1ª de 2026 (lectura temprana de
     la noche).
  4. Municípios: los de más votos en juego, por tamaño y capital/interior,
     y el margen pronosticado por grupo.
  5. Escenarios territoriales de participación: +2 / +5 pts en el Nordeste,
     en los municípios donde Lula ganó en 2022, y en las capitales.

Salida: data/processed/electoral/territorio_balotaje_2026/<fecha_utc>/
    resumen.json, por_uf.csv, municipios_clave.csv

Uso:
    python -m src.models.territorio_balotaje_2026
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.etl.transform.base_locales import salida as salida_locales
from src.models.analisis_seccion import REGION
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR, municipios_2026
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR
from src.models.movilizacion_2026 import SALIDA_DIR as MOVILIZACION_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "territorio_balotaje_2026"
TERCEROS = ["cury", "renan_santos", "caiado", "otros"]
TAMANOS = [0, 20_000, 100_000, 500_000, np.inf]
ETIQ_TAMANO = ["< 20 mil", "20-100 mil", "100-500 mil", "> 500 mil"]


def ultima(d):
    return sorted(p.parent for p in d.glob("*/resumen.json"))[-1]


def share_uf(loc: pd.DataFrame, pt: str, bol: str) -> pd.Series:
    g = loc.groupby("uf")[[pt, bol]].sum()
    return g[pt] / (g[pt] + g[bol]) * 100


def main() -> None:
    corrida = ultima(BALOTAJE_DIR)
    res_mod = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    mun = pd.read_parquet(corrida / "municipios.parquet")
    mov = pd.read_parquet(ultima(MOVILIZACION_DIR) / "municipios.parquet")
    act = municipios_2026()
    loc22 = pd.read_parquet(salida_locales(2022)).query("uf != 'ZZ'")
    loc18 = pd.read_parquet(salida_locales(2018)).query("uf != 'ZZ'")

    # base municipal
    b = mun[["uf", "pt", "bolsonaro", "lula_pct", "aptos"]].join(act[[f"{g}_1" for g in TERCEROS] + ["abstencion_1"]])
    b = b.join(mov[["pt_abst", "bolsonaro_abst", "lula22", "nombre", "region"]])
    b["lula22"] = b["lula22"].fillna(b["lula_pct"] / 100)
    b["region"] = b["region"].fillna(b["uf"].map(REGION))
    b["terceros"] = b[[f"{g}_1" for g in TERCEROS]].sum(axis=1)
    b["margen_flavio"] = b["bolsonaro"] - b["pt"]
    b["en_juego"] = b["terceros"] + b["pt_abst"].fillna(0) + b["bolsonaro_abst"].fillna(0)
    # votos netos para Lula si la participación sube 1 pt del padrón y los nuevos votan como el município en 2022
    b["elasticidad_1pt"] = b["aptos"] * 0.01 * (2 * b["lula22"] - 1)

    # 1 · Por UF
    uf = b.groupby("uf").agg(region=("region", "first"), aptos=("aptos", "sum"), lula_2v=("pt", "sum"),
                             flavio_2v=("bolsonaro", "sum"), terceros=("terceros", "sum"),
                             reserva_lula=("pt_abst", "sum"), reserva_bolsonaro=("bolsonaro_abst", "sum"),
                             en_juego=("en_juego", "sum"), elasticidad_1pt=("elasticidad_1pt", "sum"))
    uf["lula_pct"] = uf["lula_2v"] / (uf["lula_2v"] + uf["flavio_2v"]) * 100
    uf["margen_flavio"] = uf["flavio_2v"] - uf["lula_2v"]
    por_uf_mod = pd.read_csv(corrida / "por_uf.csv", index_col=0)
    uf["prob_lula"] = por_uf_mod["prob_lula"]
    # cambio 1ª vuelta 2022 -> 2026
    v22 = loc22.groupby("uf")[["pt_1", "bolsonaro_1"]].sum()
    v26 = act.groupby("uf")[["pt_1", "bolsonaro_1"]].sum()
    uf["cambio_lula_1v"] = v26["pt_1"] - v22["pt_1"]
    uf["cambio_bolsonarismo_1v"] = v26["bolsonaro_1"] - v22["bolsonaro_1"]
    uf["swing_neto_1v"] = uf["cambio_bolsonarismo_1v"] - uf["cambio_lula_1v"]
    # termómetros
    s18 = share_uf(loc18, "pt_2", "bolsonaro_2")
    s22 = share_uf(loc22, "pt_2", "bolsonaro_2")
    s26 = act.groupby("uf").apply(lambda x: x["pt_1"].sum() / (x["pt_1"].sum() + x["bolsonaro_1"].sum()) * 100)
    nac = {
        2018: loc18["pt_2"].sum() / (loc18["pt_2"] + loc18["bolsonaro_2"]).sum() * 100,
        2022: loc22["pt_2"].sum() / (loc22["pt_2"] + loc22["bolsonaro_2"]).sum() * 100,
        "2026_1v": act["pt_1"].sum() / (act["pt_1"] + act["bolsonaro_1"]).sum() * 100,
    }
    uf["dif_nac_2018"] = s18 - nac[2018]
    uf["dif_nac_2022"] = s22 - nac[2022]
    uf["dif_nac_2026_1v"] = s26 - nac["2026_1v"]
    uf["termometro_mad"] = uf[["dif_nac_2018", "dif_nac_2022", "dif_nac_2026_1v"]].abs().mean(axis=1)
    uf["desvio_estable_sd"] = uf[["dif_nac_2018", "dif_nac_2022", "dif_nac_2026_1v"]].std(axis=1)
    uf = uf.sort_values("en_juego", ascending=False)
    tot = {k: float(uf[k].sum()) for k in ("margen_flavio", "en_juego", "terceros", "reserva_lula",
                                           "reserva_bolsonaro", "cambio_lula_1v", "cambio_bolsonarismo_1v")}
    uf["pct_en_juego"] = uf["en_juego"] / tot["en_juego"] * 100
    uf["pct_margen"] = uf["margen_flavio"] / tot["margen_flavio"] * 100

    # concentración: cuántas UF juntan la mitad / 80 % de los votos en juego
    acum = uf["en_juego"].cumsum() / tot["en_juego"]
    concentracion = {"uf_50": int((acum < 0.5).sum() + 1), "uf_80": int((acum < 0.8).sum() + 1),
                     "top5": uf.index[:5].tolist(), "top5_pct": float(uf["pct_en_juego"].iloc[:5].sum())}

    # 2 · Por región
    reg = uf.groupby("region")[["lula_2v", "flavio_2v", "margen_flavio", "en_juego", "terceros", "reserva_lula",
                                "reserva_bolsonaro", "cambio_lula_1v", "cambio_bolsonarismo_1v",
                                "elasticidad_1pt"]].sum()
    reg["lula_pct"] = reg["lula_2v"] / (reg["lula_2v"] + reg["flavio_2v"]) * 100

    # 4 · Municípios: tamaño y capitales
    b["tamano"] = pd.cut(b["aptos"], TAMANOS, labels=ETIQ_TAMANO, right=False)
    b["capital"] = b.index.isin(CAPITALES)
    por_tam = b.groupby("tamano", observed=True).agg(municipios=("aptos", "size"), aptos=("aptos", "sum"),
                                                     lula=("pt", "sum"), flavio=("bolsonaro", "sum"),
                                                     en_juego=("en_juego", "sum"), margen=("margen_flavio", "sum"))
    por_tam["lula_pct"] = por_tam["lula"] / (por_tam["lula"] + por_tam["flavio"]) * 100
    cap = b.groupby("capital").agg(municipios=("aptos", "size"), lula=("pt", "sum"), flavio=("bolsonaro", "sum"),
                                   en_juego=("en_juego", "sum"), margen=("margen_flavio", "sum"))
    cap["lula_pct"] = cap["lula"] / (cap["lula"] + cap["flavio"]) * 100
    clave = b.sort_values("en_juego", ascending=False).head(40)[
        ["nombre", "uf", "aptos", "lula_pct", "margen_flavio", "terceros", "pt_abst", "bolsonaro_abst", "en_juego",
         "elasticidad_1pt"]]
    # municípios "bisagra": pronóstico entre 45 y 55 % con más de 50 mil electores
    bisagra = b[(b["lula_pct"].between(45, 55)) & (b["aptos"] > 50_000)]

    # 5 · Escenarios de participación (nuevos votantes votan como el município en 2022)
    L0, F0 = float(b["pt"].sum()), float(b["bolsonaro"].sum())
    def escenario(mask, pts):
        nuevos = b.loc[mask, "aptos"] * pts / 100
        L = L0 + float((nuevos * b.loc[mask, "lula22"]).sum())
        F = F0 + float((nuevos * (1 - b.loc[mask, "lula22"])).sum())
        return {"lula_pct": L / (L + F) * 100, "cambio_pp": L / (L + F) * 100 - L0 / (L0 + F0) * 100,
                "votos_nuevos": float(nuevos.sum())}
    lula_gano_22 = b["lula22"] > 0.5
    escenarios = {}
    for pts in (2, 5):
        escenarios[f"nordeste_+{pts}"] = escenario(b["region"] == "Nordeste", pts)
        escenarios[f"municipios_lula_2022_+{pts}"] = escenario(lula_gano_22, pts)
        escenarios[f"capitales_+{pts}"] = escenario(b["capital"], pts)
        escenarios[f"sur_y_centro_oeste_+{pts}"] = escenario(b["region"].isin(["Sul", "Centro-Oeste"]), pts)
    # participación +3 pts parejo en todo el país (cada município vota como en 2022)
    escenarios["todo_el_pais_+3"] = escenario(pd.Series(True, index=b.index), 3)

    resumen = {
        "modelo_corrida": corrida.name,
        "territorio_lula_pct": L0 / (L0 + F0) * 100,
        "totales": tot, "concentracion": concentracion,
        "por_region": reg.round(3).to_dict(orient="index"),
        "termometros": uf.sort_values("termometro_mad")[["termometro_mad", "desvio_estable_sd", "dif_nac_2018",
                                                          "dif_nac_2022", "dif_nac_2026_1v"]].head(6).round(2).to_dict(orient="index"),
        "nacional_lula_vs_bolsonarismo": nac,
        "por_tamano": por_tam.round(3).to_dict(orient="index"),
        "capitales_vs_interior": cap.round(3).rename(index={True: "capitales", False: "interior"}).to_dict(orient="index"),
        "bisagra": {"municipios": int(len(bisagra)), "aptos": float(bisagra["aptos"].sum()),
                    "lula_pct": float(bisagra["pt"].sum() / (bisagra["pt"] + bisagra["bolsonaro"]).sum() * 100),
                    "top": bisagra.sort_values("aptos", ascending=False).head(12)[["nombre", "uf", "aptos", "lula_pct"]]
                    .round(2).to_dict(orient="records")},
        "escenarios_participacion": escenarios,
    }
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    uf.to_csv(out / "por_uf.csv")
    clave.to_csv(out / "municipios_clave.csv")
    log.info("UF por votos en juego:\n%s", uf[["lula_pct", "margen_flavio", "en_juego", "pct_en_juego",
                                               "elasticidad_1pt", "swing_neto_1v", "termometro_mad"]].round(1).to_string())
    log.info("región:\n%s", reg.round(0).to_string())
    log.info("escenarios: %s", json.dumps({k: round(v["cambio_pp"], 2) for k, v in escenarios.items()}))
    log.info("salida %s", out)


# Códigos IBGE de las 27 capitales.
CAPITALES = {1200401, 2704302, 1600303, 1302603, 2927408, 2304400, 5300108, 3205309, 5208707, 2111300, 5103403,
             5002704, 3106200, 1501402, 2507507, 4106902, 2611606, 2211001, 3304557, 2408102, 4314902, 1100205,
             1400100, 4205407, 3550308, 2800308, 1721000}


if __name__ == "__main__":
    main()
