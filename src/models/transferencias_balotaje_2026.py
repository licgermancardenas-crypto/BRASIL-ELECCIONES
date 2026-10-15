"""
src/models/transferencias_balotaje_2026.py

Transferencias del balotaje con datos de encuesta: ¿qué pasa con el
pronóstico (balotaje_2026, método R) si los terceros, los abstencionistas y
la retención se comportan como dicen los entrevistados de BTG/Nexus (10–12/10,
2.002 casos por teléfono)? Y los caminos de Lula al 50 %.

El voto de 2ª vuelta es lineal en cada proporción, así que el pronóstico se
descompone una vez en bloques de votos válidos por grupo de la 1ª vuelta (con
la matriz 2022 por UF del modelo) y después se recombina sin volver a correr
la regresión:

    Lula = Σ_grupo  válidos_grupo × proporción_a_Lula_grupo

  1. Bayes por subgrupo: a priori Beta centrada en la proporción del modelo
     (R) con `K_PRIOR` casos de peso; los datos son el subgrupo de Nexus con
     su n estimado (participación del grupo en el padrón × 2.002 / efecto de
     diseño). El resultado es una distribución, no un número: los subgrupos
     tienen entre 5 y 60 casos.
  2. Cascada: del modelo al escenario Nexus, un bloque por vez (terceros,
     abstencionistas, retención).
  3. Caminos al 50 %: grilla proporción uniforme de terceros a Lula ×
     movilización neta extra (votos), y cuántos votos hacen falta.

Salida: data/processed/electoral/transferencias_balotaje_2026/<fecha_utc>/
    resumen.json, grilla.csv, posteriores.csv

Uso:
    python -m src.models.transferencias_balotaje_2026
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.models.balotaje_2026 import (SALIDA_DIR as BALOTAJE_DIR, estimar, exterior_2026, municipios_2026,
                                      nacional, predecir)
from src.models.conteo_2026 import SALIDA_FINAL as RESULTADO_2026
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("src.models.balotaje_2026").setLevel(logging.WARNING)

SALIDA_DIR = ELECTORAL_DIR / "transferencias_balotaje_2026"
TERCEROS = ["cury", "renan_santos", "caiado", "otros"]

# BTG/Nexus, campo 10–12/10/2026, telefónica, 2.002 casos, BR-07997/2026.
# % de 2ª vuelta por voto de la 1ª (Flávio, Lula, blanco-nulo, no sabe).
# Zema: el informe no da Lula (80 + 12 + 8 = 100): se toma 0.
NEXUS = {
    "fuente": "BTG Pactual/Nexus, 10-12/10/2026, telefónica, n=2.002 (BR-07997/2026)",
    "grupos": {
        "cury": {"flavio": 43, "lula": 41, "bn": 13, "ns": 4},
        "renan_santos": {"flavio": 37, "lula": 30, "bn": 33, "ns": 0},
        "caiado": {"flavio": 55, "lula": 27, "bn": 11, "ns": 7},
        "zema": {"flavio": 80, "lula": 0, "bn": 12, "ns": 8},
        "abstencion": {"flavio": 49, "lula": 41, "bn": 6, "ns": 3},
    },
    "retencion": {"lula": 0.98, "flavio": 0.98},
    "n": 2002,
}
K_PRIOR = 20          # casos de peso de la proporción del modelo
EFECTO_DISENO = 1.5
# En encuestas, quien no votó lo declara menos: se supone que la mitad de los
# abstencionistas reales aparece como tal en la muestra.
DECLARA_ABSTENCION = 0.5
N_SIM = 20000


def bloques(act: pd.DataFrame, T: dict, analogia: dict, ext: dict) -> dict:
    """Votos válidos de 2ª vuelta por grupo de la 1ª (nacional, con exterior) y su proporción a Lula del modelo."""
    b = {g: {"validos": 0.0, "lula": 0.0} for g in ["pt", "bolsonaro", "blanco_nulo", "abstencion"] + TERCEROS}
    for u, x in act.groupby("uf"):
        t = T[u]
        for g in ("pt", "bolsonaro", "blanco_nulo", "abstencion"):
            n = x[f"{g}_1"].sum()
            b[g]["validos"] += n * (t.loc[g, "pt"] + t.loc[g, "bolsonaro"])
            b[g]["lula"] += n * t.loc[g, "pt"]
        for g in TERCEROS:
            fila = t.loc[analogia[g]]
            b[g]["validos"] += x[f"{g}_1"].sum() * (fila["pt"] + fila["bolsonaro"])
    b["pt"]["validos"] += ext["pt_1"]
    b["pt"]["lula"] += ext["pt_1"]
    b["bolsonaro"]["validos"] += ext["bolsonaro_1"]
    for g in TERCEROS:
        b[g]["validos"] += ext[f"{g}_1"]
    return b


def lula_pct(b: dict, a: dict) -> np.ndarray | float:
    """% Lula con proporciones `a` por grupo (escalares o vectores de simulación)."""
    lula = sum(b[g]["validos"] * a[g] for g in b)
    tot = sum(b[g]["validos"] for g in b)
    return lula / tot * 100


def posterior(prior: float, d: dict, n_grupo: float, rng, n: int) -> tuple[np.ndarray, dict]:
    """Beta(prior·K + éxitos, (1−prior)·K + fracasos), con éxitos = Lula entre los que eligen Lula o Flávio."""
    validos = n_grupo * (d["lula"] + d["flavio"]) / 100
    exitos = validos * d["lula"] / (d["lula"] + d["flavio"])
    al, be = prior * K_PRIOR + exitos, (1 - prior) * K_PRIOR + validos - exitos
    draws = rng.beta(al, be, n)
    return draws, {"prior": prior, "nexus": d["lula"] / (d["lula"] + d["flavio"]), "n_efectivo": n_grupo,
                   "n_validos": validos, "posterior_media": al / (al + be),
                   "posterior_p5": float(np.quantile(draws, 0.05)), "posterior_p95": float(np.quantile(draws, 0.95))}


def main() -> None:
    cfg_all = cargar_config()
    cfg = {**cfg_all["seccion"], **cfg_all["balotaje"]}
    rng = np.random.default_rng(cfg["random_seed"])
    corrida = sorted(p.parent for p in BALOTAJE_DIR.glob("*/meta.json"))[-1]
    res_mod = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))

    act = municipios_2026()
    ext = exterior_2026()
    log.info("reestimando matrices 2022 -> 2026 (método R)")
    est = estimar(2022, 2026, cfg["analogia"], cfg, act=act)
    a_mod = res_mod["a_lula_terceros"]["R"]
    b = bloques(act, est["T"], cfg["analogia"], ext)
    a_base = {g: (b[g]["lula"] / b[g]["validos"] if g not in TERCEROS else a_mod[g]) for g in b}
    base = lula_pct(b, a_base)
    # control: los bloques reproducen el pronóstico R
    p_r = predecir(act, est["T"], cfg["analogia"], "R", est["celdas"], est["terceros"])
    log.info("bloques %.3f vs pronóstico R %.3f (con exterior: %.3f)", base, nacional(p_r),
             res_mod["lula_2v"]["R_origen"])

    # 1 · Posteriores
    r = pd.read_parquet(RESULTADO_2026)
    aptos = float(r["aptos"].sum())
    votos = {"cury": r["cury"].sum(), "renan_santos": r["renan_santos"].sum(), "caiado": r["caiado"].sum(),
             "zema": r["zema"].sum(), "otros_resto": r["otros"].sum(), "abstencion": r["abstencion"].sum()}
    n_g = {g: NEXUS["n"] * votos[g] / aptos / EFECTO_DISENO for g in ("cury", "renan_santos", "caiado", "zema")}
    n_g["abstencion"] = NEXUS["n"] * votos["abstencion"] / aptos * DECLARA_ABSTENCION / EFECTO_DISENO
    priors = {**{g: a_mod[g] for g in ("cury", "renan_santos", "caiado")}, "zema": a_mod["otros"],
              "abstencion": a_base["abstencion"]}
    draws, post = {}, {}
    for g in ("cury", "renan_santos", "caiado", "zema", "abstencion"):
        draws[g], post[g] = posterior(priors[g], NEXUS["grupos"][g], n_g[g], rng, N_SIM)
    peso_zema = votos["zema"] / (votos["zema"] + votos["otros_resto"])
    draws["otros"] = peso_zema * draws["zema"] + (1 - peso_zema) * a_mod["otros"]

    # 2 · Cascada (medias posteriores) y Montecarlo del escenario completo
    def con(**cambios):
        return {**a_base, **cambios}
    media = {g: float(np.mean(v)) for g, v in draws.items()}
    pasos = [("Modelo (método R)", con())]
    a_terc = con(**{g: media[g] for g in TERCEROS})
    pasos.append(("+ terceros como Nexus", a_terc))
    a_abs = {**a_terc, "abstencion": media["abstencion"]}
    pasos.append(("+ abstencionistas como Nexus", a_abs))
    # Retención: Lula y Flávio retienen lo mismo (Nexus: 98 % y 98 %). En el
    # modelo, 2022 da Lula 97,4 % y Bolsonaro 99,9 % (el resto, abstención).
    b_ret = {g: dict(v) for g, v in b.items()}
    ret_mod = {g: b[g]["validos"] / (act[f"{g}_1"].sum() + ext[f"{g}_1"]) for g in ("pt", "bolsonaro")}
    for g, k in (("pt", "lula"), ("bolsonaro", "flavio")):
        tot = act[f"{g}_1"].sum() + ext[f"{g}_1"]
        b_ret[g]["validos"] = tot * NEXUS["retencion"][k]
    a_ret = {**a_abs}
    cascada = [{"paso": n, "lula_pct": float(lula_pct(b, a))} for n, a in pasos]
    cascada.append({"paso": "+ retención igual (98 / 98)", "lula_pct": float(lula_pct(b_ret, a_ret))})
    # retención sola, sin lo demás
    solo_ret = float(lula_pct(b_ret, a_base))

    sim_a = {**a_base, **{g: draws[g] for g in TERCEROS}, "abstencion": draws["abstencion"]}
    sim_nexus = lula_pct(b, sim_a)
    sim_nexus_ret = lula_pct(b_ret, sim_a)
    # incertidumbre de modelo/campaña (shock nacional del Montecarlo) además de la de las proporciones
    sd_nac = res_mod["montecarlo"]["sd_nacional_pp"]
    gl = cfg["grados_libertad_t"]
    shock = rng.standard_t(gl, N_SIM) * sd_nac / np.sqrt(gl / (gl - 2))

    def dist(x):
        return {"media": float(np.mean(x)), "p5_50_95": [float(v) for v in np.percentile(x, [5, 50, 95])],
                "prob_lula": float((x > 50).mean())}

    # 3 · Caminos al 50 %
    tot_validos = sum(b[g]["validos"] for g in b)
    lula_votos = sum(b[g]["validos"] * a_base[g] for g in b)
    brecha = tot_validos - 2 * lula_votos   # Flávio − Lula, votos
    V_terc = sum(b[g]["validos"] for g in TERCEROS)
    filas = []
    for a_u in np.round(np.arange(0.0, 1.0001, 0.05), 2):
        for m in np.arange(-1_000_000, 8_000_001, 250_000):
            a = {**a_base, **{g: a_u for g in TERCEROS}}
            L = sum(b[g]["validos"] * a[g] for g in b) + m
            filas.append({"a_lula_terceros": a_u, "movilizacion_neta": int(m), "lula_pct": L / (tot_validos + m) * 100})
    grilla = pd.DataFrame(filas)
    # movilización neta que hace falta con cada proporción de terceros (L + m = (T + m)/2 -> m = T − 2L)
    necesaria = []
    for a_u in np.round(np.arange(0.0, 1.0001, 0.05), 2):
        L = lula_votos - sum(b[g]["validos"] * a_base[g] for g in TERCEROS) + V_terc * a_u
        necesaria.append({"a_lula_terceros": float(a_u), "movilizacion_neta_necesaria": float(tot_validos - 2 * L)})
    # conversión: votos que tienen que pasar de Flávio a Lula (cada uno cuenta doble)
    conversion = brecha / 2

    resumen = {
        "fuente_encuesta": NEXUS["fuente"],
        "modelo_corrida": corrida.name,
        "bloques_validos": {g: {"validos": v["validos"], "a_lula_modelo": a_base[g]} for g, v in b.items()},
        "retencion_modelo_2022": ret_mod,
        "posteriores": post,
        "cascada": cascada,
        "solo_retencion_igual": solo_ret,
        "escenario_nexus": dist(sim_nexus), "escenario_nexus_con_shock": dist(sim_nexus + shock),
        "escenario_nexus_retencion": dist(sim_nexus_ret),
        "escenario_nexus_retencion_con_shock": dist(sim_nexus_ret + shock),
        "votos": {"validos_2v": tot_validos, "lula": lula_votos, "brecha_flavio_menos_lula": brecha,
                  "conversion_necesaria": conversion, "validos_terceros": V_terc},
        "movilizacion_necesaria": necesaria,
        "supuestos": {"K_prior": K_PRIOR, "efecto_diseno": EFECTO_DISENO, "declara_abstencion": DECLARA_ABSTENCION,
                      "zema_lula": "0 (el informe no lo da)"},
    }
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    grilla.to_csv(out / "grilla.csv", index=False)
    pd.DataFrame(post).T.to_csv(out / "posteriores.csv")
    log.info("cascada: %s", [(c["paso"], round(c["lula_pct"], 2)) for c in cascada])
    log.info("Nexus: %s · con retención: %s · brecha %.2f M votos · %s", resumen["escenario_nexus_con_shock"],
             resumen["escenario_nexus_retencion_con_shock"], brecha / 1e6, out)


if __name__ == "__main__":
    main()
