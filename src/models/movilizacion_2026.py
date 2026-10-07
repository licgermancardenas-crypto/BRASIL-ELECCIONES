"""
src/models/movilizacion_2026.py

Movilización para el balotaje 2026: ¿le alcanza a Lula con traer de vuelta a
quienes no votaron el 4/10? Sin encuestas: TSE por município y la matriz de
origen del modelo de balotaje.

  1. Participación 2022 -> 2026 en la 1ª vuelta, por quintil de voto a Lula
     en 2022 y por región, y cambio de votos de Lula y del bolsonarismo.
  2. Historia: cambio de abstención entre 1ª y 2ª vuelta en 2018 y 2022, por
     quintil (qué movilización es realista entre vueltas).
  3. Reserva: votantes de Lula y de Bolsonaro en la 2ª vuelta de 2022 que no
     votaron el 4/10 (regresión ecológica 2022 -> 2026 por UF, ajustada a lo
     observado en cada município, la misma de balotaje_2026).
  4. Lo que hace falta: brecha del pronóstico de balotaje contra la reserva
     neta, y cuánta baja de la abstención haría falta en los municípios
     donde gana Lula.

Salida: data/processed/electoral/movilizacion_2026/<fecha_utc>/
    resumen.json, municipios.parquet

Uso:
    python -m src.models.movilizacion_2026
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.etl.transform.base_locales import salida as salida_locales
from src.models.analisis_seccion import REGION
from src.models.balotaje_2026 import (GRUPOS_1V, ORIGEN, SALIDA_DIR as BALOTAJE_DIR, celdas_origen, matriz_origen,
                                      municipios_2026, municipios_previos)
from src.models.conteo_2026 import SALIDA as CONTEO_UF
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "movilizacion_2026"


def ultima_corrida_balotaje():
    return sorted(p.parent for p in BALOTAJE_DIR.glob("*/meta.json"))[-1]


def por_quintil(j: pd.DataFrame) -> list[dict]:
    q = pd.qcut(j["lula22"], 5, labels=False)
    out = []
    for k, x in j.groupby(q):
        out.append({"quintil": int(k) + 1, "lula_2v_2022": x["pt_2"].sum() / (x["pt_2"] + x["bolsonaro_2"]).sum() * 100,
                    "abst_1v_2022": x["abstencion_1"].sum() / x["aptos"].sum() * 100,
                    "abst_1v_2026": x["abstencion_1_26"].sum() / x["aptos_26"].sum() * 100,
                    "lula_1v_2022": x["pt_1"].sum(), "lula_1v_2026": x["pt_1_26"].sum(),
                    "bolsonaro_1v_2022": x["bolsonaro_1"].sum(), "flavio_1v_2026": x["bolsonaro_1_26"].sum()})
    return out


def historia_entre_vueltas(m: pd.DataFrame) -> list[float]:
    """Cambio de abstención 1ª -> 2ª vuelta (pp del padrón) por quintil de Lula/PT en la 2ª vuelta."""
    q = pd.qcut(m["pt_2"] / (m["pt_2"] + m["bolsonaro_2"]), 5, labels=False)
    return [float((x["abstencion_2"].sum() - x["abstencion_1"].sum()) / x["aptos"].sum() * 100) for _, x in m.groupby(q)]


def main() -> None:
    cfg = cargar_config()["balotaje"]
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)

    m18, m22, m26 = municipios_previos(2018), municipios_previos(2022), municipios_2026()
    nombres = pd.read_parquet(salida_locales(2022), columns=["cd_ibge", "nm_municipio"]).drop_duplicates("cd_ibge") \
        .set_index("cd_ibge")["nm_municipio"]

    # 1 · participación 2022 -> 2026
    j = m22.join(m26.drop(columns="uf"), rsuffix="_26", how="inner")
    j["lula22"] = j["pt_2"] / (j["pt_2"] + j["bolsonaro_2"])
    j["region"] = j["uf"].map(REGION)
    reg = {r: {"abst_1v_2022": x["abstencion_1"].sum() / x["aptos"].sum() * 100,
               "abst_1v_2026": x["abstencion_1_26"].sum() / x["aptos_26"].sum() * 100,
               "lula_cambio": x["pt_1_26"].sum() - x["pt_1"].sum(),
               "bolsonarismo_cambio": x["bolsonaro_1_26"].sum() - x["bolsonaro_1"].sum()}
           for r, x in j.groupby("region")}

    # 2 · historia entre vueltas
    hist = {"2018": historia_entre_vueltas(m18), "2022": historia_entre_vueltas(m22),
            "nacional": {str(a): {"abst_1v": m["abstencion_1"].sum() / m["aptos"].sum() * 100,
                                  "abst_2v": m["abstencion_2"].sum() / m["aptos"].sum() * 100}
                         for a, m in ((2018, m18), (2022, m22))}}

    # 3 · reserva: origen 2022 de quienes no votaron (y de blanco-nulo) el 4/10
    B, _ = matriz_origen(m22, m26, GRUPOS_1V[2026], cfg["min_municipios_uf"])
    celdas = celdas_origen(m26, m22, B, GRUPOS_1V[2026], ["abstencion", "blanco_nulo"])
    ab = celdas[celdas["tercero"] == "abstencion"][ORIGEN].add_suffix("_abst")
    bn = celdas[celdas["tercero"] == "blanco_nulo"][ORIGEN].add_suffix("_bn")
    mun = m26[["uf", "aptos", "pt_1", "bolsonaro_1", "abstencion_1"]].join(ab).join(bn)
    mun["nombre"] = nombres.reindex(mun.index)
    mun["lula22"] = j["lula22"].reindex(mun.index)
    mun["region"] = mun["uf"].map(REGION)
    mun["reserva_neta"] = mun["pt_abst"] - mun["bolsonaro_abst"]
    mun.to_parquet(out / "municipios.parquet")

    # 4 · brecha del pronóstico y lo que hace falta
    bal = ultima_corrida_balotaje()
    R = json.loads((bal / "resumen.json").read_text(encoding="utf-8"))
    uf = pd.read_csv(bal / "por_uf.csv", index_col=0)
    zz = json.loads(CONTEO_UF.read_text(encoding="utf-8"))["por_uf"]["zz"]["validos_contados"]
    p = R["lula_2v"]["R_origen"] / 100
    v2 = uf["pt"].sum() + uf["bolsonaro"].sum() + zz
    brecha = (1 - 2 * p) * v2
    lula_abst, bol_abst = mun["pt_abst"].sum(), mun["bolsonaro_abst"].sum()
    # Si vuelve una fracción f de los votantes de Lula 2022 que no votaron y vota a Lula:
    f_empate = brecha / lula_abst
    # Baja uniforme de la abstención (pp del padrón) en los municípios donde gana Lula,
    # con los nuevos votantes repartidos como el voto a Lula de 2022 en ese município.
    fav = mun[mun["lula22"] > 0.5]
    neto_por_pp = float((fav["aptos"] / 100 * (2 * fav["lula22"] - 1)).sum())
    pp_empate = brecha / neto_por_pp
    top = mun.sort_values("reserva_neta", ascending=False).head(25)

    por_uf = mun.groupby("uf")[["pt_abst", "bolsonaro_abst", "reserva_neta", "aptos", "abstencion_1"]].sum()
    por_uf["brecha_balotaje"] = uf["bolsonaro"] - uf["pt"]
    resumen = {
        "participacion": {"abst_1v_2022": m22["abstencion_1"].sum() / m22["aptos"].sum() * 100,
                          "abst_1v_2026": m26["abstencion_1"].sum() / m26["aptos"].sum() * 100,
                          "aptos_2022": m22["aptos"].sum(), "aptos_2026": m26["aptos"].sum(),
                          "por_quintil_lula_2022": por_quintil(j), "por_region": reg},
        "entre_vueltas_historia": hist,
        "reserva": {"no_votaron_2026": m26["abstencion_1"].sum(), "de_lula_2022": lula_abst,
                    "de_bolsonaro_2022": bol_abst, "neta_lula": lula_abst - bol_abst,
                    "por_region": mun.groupby("region")[["pt_abst", "bolsonaro_abst", "reserva_neta"]].sum()
                    .to_dict(orient="index"),
                    "blanco_nulo_de_lula_2022": mun["pt_bn"].sum(), "blanco_nulo_de_bolsonaro_2022": mun["bolsonaro_bn"].sum()},
        "lo_que_hace_falta": {"lula_2v_pronostico": p * 100, "validos_2v": v2, "brecha_votos": brecha,
                              "fraccion_reserva_lula_para_empatar": f_empate,
                              "municipios_lula_gana_2022": int(len(fav)), "aptos_en_esos": float(fav["aptos"].sum()),
                              "neto_lula_por_pp_menos_abstencion": neto_por_pp, "pp_menos_abstencion_para_empatar": pp_empate,
                              "mayor_baja_historica_entre_vueltas_pp": -min(min(hist["2018"]), min(hist["2022"]))},
        "por_uf": por_uf.to_dict(orient="index"),
        "top_municipios_reserva_neta": top[["nombre", "uf", "aptos", "pt_abst", "bolsonaro_abst", "reserva_neta"]]
        .reset_index().to_dict(orient="records"),
        "balotaje_corrida": bal.name,
    }
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello, "balotaje": bal.name}), encoding="utf-8")
    log.info("reserva: %.2f M de Lula 2022 y %.2f M de Bolsonaro 2022 no votaron; brecha %.2f M; "
             "empate si vuelve %.0f%% de la reserva de Lula o la abstención baja %.1f pp donde gana Lula",
             lula_abst / 1e6, bol_abst / 1e6, brecha / 1e6, 100 * f_empate, pp_empate)


if __name__ == "__main__":
    main()
