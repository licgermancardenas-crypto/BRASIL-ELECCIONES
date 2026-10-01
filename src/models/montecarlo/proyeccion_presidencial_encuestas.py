"""
src/models/montecarlo/proyeccion_presidencial_encuestas.py

Fase 5 — Montecarlo presidencial 2026 sobre el agregado de encuestas
(src/models/agregacion_encuestas.py). Reemplaza como pronóstico al escenario
base-2022 (proyeccion_presidencial.py), que queda como referencia estructural.

Incertidumbre = error del AGREGADOR en el backtest 2018/2022 (backtest.csv de
la última corrida de agregación), no el margen de error muestral: lo que
falló en 2018 y 2022 fue sistemático (toda la industria en la misma
dirección), y eso es lo que hay que simular.

  1ª vuelta, 2 principales (família gobierno_lula y direita_bolsonarista):
      x = m + sigma_1v · z_familia                 z ~ N(0, 1), una por família
  resto de candidatos y "otros":
      x = m · (1 + sigma_rel · N(0, 1))            error relativo de los menores
  -> recorte en 0 y renormalización a 100% de válidos.
  2ª vuelta (cruce agregado de Lula contra el rival que pasa):
      % Lula = m2 + sigma_2v · (z_lula − z_rival) / √2
  El mismo z en las dos vueltas: si las encuestas subestiman a la derecha
  en la 1ª, también la subestiman en el cruce (pasó en 2018 y 2022).

Con `encuestas.corregir_sesgo_historico: true` se suma además el sesgo medio
del backtest. Se corren SIEMPRE las dos variantes: la del config es la
principal y la otra queda en el resumen como sensibilidad.

Salidas en data/processed/electoral/presidencial_encuestas_sim/<fecha_utc>/:
  resumen.json, distribucion_1v.parquet, meta.json

Uso:
    python -m src.models.montecarlo.proyeccion_presidencial_encuestas
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl.extract.versionado import sha256
from src.etl.transform.encuestas_resultados import SALIDA as ENCUESTAS
from src.models.agregacion_encuestas import SALIDA_DIR as AGREGADAS_DIR
from src.models.montecarlo.proyeccion_bancas import CONFIG_MODELO, ELECTORAL_DIR, ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "presidencial_encuestas_sim"
FAMILIAS_PRINCIPALES = ("gobierno_lula", "direita_bolsonarista")


def ultima_agregacion() -> Path:
    corridas = sorted(p.parent for p in AGREGADAS_DIR.glob("*/meta.json"))
    if not corridas:
        raise FileNotFoundError("No hay corridas de agregación: correr src.models.agregacion_encuestas")
    return corridas[-1]


def incertidumbre(backtest: pd.DataFrame, familias: dict[tuple[int, str], str]) -> dict:
    """Sesgo medio y RMS del error del agregador en el backtest, en fracción de válidos."""
    bt = backtest.copy()
    bt["familia"] = [familias.get((a, c)) for a, c in zip(bt["ano"], bt["candidato"])]
    e = bt["error_agregado_pp"] / 100
    v1 = bt["vuelta"].eq(1)
    princ = v1 & bt["familia"].isin(FAMILIAS_PRINCIPALES) & bt["top2"]
    menores = v1 & ~bt["top2"]
    rel = (bt.loc[menores, "agregado_pct"] - bt.loc[menores, "real_pct"]) / bt.loc[menores, "agregado_pct"]
    pre = bt["cruce_antes_1v"] & bt["familia"].eq("gobierno_lula")
    rms = lambda s: float(np.sqrt((s ** 2).mean()))
    return {
        "sigma_1v": rms(e[princ]),
        "sesgo_1v": {f: float(e[princ & bt["familia"].eq(f)].mean()) for f in FAMILIAS_PRINCIPALES},
        "sigma_rel_menores": rms(rel),
        "sesgo_rel_menores": float(rel.mean()),
        "sigma_2v": rms(e[pre]),
        "sesgo_2v_lula": float(e[pre].mean()),
        "observaciones": {"1v_principales": int(princ.sum()), "1v_menores": int(menores.sum()),
                          "2v_cruce_antes_1v": int(pre.sum())},
    }


def simular(m1: pd.Series, cruces: dict[str, float], principales: dict[str, str], inc: dict,
            corregir: bool, n_sim: int, seed: int) -> tuple[dict, pd.DataFrame]:
    """m1: % válidos 1ª vuelta (fracción) por candidato; cruces: rival -> % Lula en el cruce;
    principales: família -> candidato (uno por família de FAMILIAS_PRINCIPALES)."""
    rng = np.random.default_rng(seed)
    cands = m1.index.tolist()
    if set(principales) != set(FAMILIAS_PRINCIPALES) or not set(principales.values()) <= set(cands):
        raise ValueError(f"Principales {principales} no están en la 1ª vuelta {cands}")
    lula = principales["gobierno_lula"]
    fam_de = {c: f for f, c in principales.items()}

    z = {c: rng.normal(0, 1, n_sim) for c in principales.values()}
    x = np.empty((n_sim, len(cands)))
    for j, c in enumerate(cands):
        if c in z:
            sesgo = inc["sesgo_1v"][fam_de[c]] if corregir else 0.0
            # error = encuesta − real  =>  real = encuesta − error
            x[:, j] = m1[c] - sesgo + inc["sigma_1v"] * z[c]
        else:
            sesgo = inc["sesgo_rel_menores"] if corregir else 0.0
            # el sesgo relativo es (encuesta − real)/encuesta: se descuenta
            x[:, j] = m1[c] * (1 - sesgo + inc["sigma_rel_menores"] * rng.normal(0, 1, n_sim))
    x = np.clip(x, 0, None)
    x /= x.sum(axis=1, keepdims=True)
    elegibles = [j for j, c in enumerate(cands) if c != "otros"]
    xe = x[:, elegibles]
    nombres = np.array([cands[j] for j in elegibles])
    orden = np.argsort(-xe, axis=1)
    primero, segundo = nombres[orden[:, 0]], nombres[orden[:, 1]]
    gana_1v = xe.max(axis=1) > 0.5

    presidente = np.where(gana_1v, primero, "")
    pares = pd.Series(["|".join(sorted(p)) for p in zip(primero, segundo)])
    # rival sin z propio (no es de las famílias principales): shock independiente
    z_rival_comun = rng.normal(0, 1, n_sim)
    for rival, m2 in cruces.items():
        en_juego = ~gana_1v & (pares.to_numpy() == "|".join(sorted([lula, rival])))
        if not en_juego.any():
            continue
        z_r = z[rival] if rival in z else z_rival_comun
        sesgo = inc["sesgo_2v_lula"] if corregir else 0.0
        p = m2 - sesgo + inc["sigma_2v"] * (z[lula] - z_r) / np.sqrt(2)
        presidente = np.where(en_juego, np.where(p > 0.5, lula, rival), presidente)
    sin_cruce = presidente == ""

    rival_principal = principales["direita_bolsonarista"]
    m2_princ = cruces.get(rival_principal)
    resumen = {
        "prob_hay_segunda_vuelta": round(float((~gana_1v).mean()), 3),
        "prob_gana_en_1v": {c: round(float((gana_1v & (primero == c)).mean()), 3) for c in nombres
                            if (gana_1v & (primero == c)).any()},
        "prob_pares_segunda_vuelta": {k: round(float(v), 3) for k, v in
                                      pares[~gana_1v].value_counts(normalize=True).head(5).items()},
        "pct_validos_1v": {c: {"p10": round(float(np.quantile(x[:, j], 0.1)) * 100, 1),
                               "mediana": round(float(np.median(x[:, j])) * 100, 1),
                               "p90": round(float(np.quantile(x[:, j], 0.9)) * 100, 1)}
                           for j, c in enumerate(cands)},
        f"prob_gana_cruce_{lula}_vs_{rival_principal}": None,
        "prob_presidente": {c: round(float((presidente == c).mean()), 3) for c in np.unique(presidente) if c},
        "prob_sin_cruce_agregado": round(float(sin_cruce.mean()), 3),
    }
    if m2_princ is not None:
        sesgo = inc["sesgo_2v_lula"] if corregir else 0.0
        p = m2_princ - sesgo + inc["sigma_2v"] * (z[lula] - z[rival_principal]) / np.sqrt(2)
        resumen[f"prob_gana_cruce_{lula}_vs_{rival_principal}"] = round(float((p > 0.5).mean()), 3)
        resumen[f"pct_{lula}_cruce_vs_{rival_principal}"] = {
            "p10": round(float(np.quantile(p, 0.1)) * 100, 1), "mediana": round(float(np.median(p)) * 100, 1),
            "p90": round(float(np.quantile(p, 0.9)) * 100, 1)}
    return resumen, pd.DataFrame(x * 100, columns=cands)


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-sim", type=int)
    args = parser.parse_args(argv)

    cfg = cargar_config()
    n_sim = args.n_sim or cfg["simulacion"]["n_simulaciones"]
    seed = cfg["simulacion"]["random_seed"]
    corregir = cfg["encuestas"]["corregir_sesgo_historico"]
    ano = cfg["encuestas"]["ano_objetivo"]

    corrida = ultima_agregacion()
    agregado = pd.read_csv(corrida / "agregado.csv")
    backtest = pd.read_csv(corrida / "backtest.csv")
    meta_agr = json.loads((corrida / "meta.json").read_text(encoding="utf-8"))
    largo = pd.read_parquet(ENCUESTAS)
    familias = largo.dropna(subset=["familia"]).drop_duplicates(["ano", "candidato"]).set_index(
        ["ano", "candidato"])["familia"].to_dict()
    # Principal de cada família = candidato del partido de presidencial.partido_candidato
    # (gobierno_lula tiene dos: Lula/PT y Cury/AVANTE).
    partido_de = largo[largo["ano"] == ano].dropna(subset=["partido"]).drop_duplicates("candidato").set_index(
        "candidato")["partido"]
    principales = {f: partido_de.index[partido_de == p][0] for f, p in cfg["presidencial"]["partido_candidato"].items()}

    inc = incertidumbre(backtest, familias)
    a1 = agregado[agregado["vuelta"] == 1]
    m1 = a1.set_index("candidato")["pct_validos"] / 100
    lula = principales["gobierno_lula"]
    cruces = {}
    for esc, g in agregado[agregado["vuelta"] == 2].groupby("escenario"):
        if lula in g["candidato"].values:
            rival = next(c for c in g["candidato"] if c != lula)
            cruces[rival] = float(g.loc[g["candidato"] == lula, "pct_validos"].iloc[0]) / 100

    principal, dist = simular(m1, cruces, principales, inc, corregir, n_sim, seed)
    alternativa, _ = simular(m1, cruces, principales, inc, not corregir, n_sim, seed)
    resumen = {
        "tipo": "PRONÓSTICO sobre agregado de encuestas (votos válidos, nacional)",
        "fecha_corte_encuestas": meta_agr["fecha_corte_encuestas"],
        "corrige_sesgo_historico": corregir,
        "agregado_1v_pct": (m1 * 100).round(1).to_dict(),
        "agregado_cruces_pct_lula": {r: round(v * 100, 1) for r, v in cruces.items()},
        **principal,
        "incertidumbre_pp": {"sigma_1v": round(inc["sigma_1v"] * 100, 2),
                             "sesgo_1v": {f: round(v * 100, 2) for f, v in inc["sesgo_1v"].items()},
                             "sigma_rel_menores": round(inc["sigma_rel_menores"], 2),
                             "sigma_2v": round(inc["sigma_2v"] * 100, 2),
                             "sesgo_2v_lula": round(inc["sesgo_2v_lula"] * 100, 2)},
        ("sensibilidad_sin_correccion_de_sesgo" if corregir else "sensibilidad_con_correccion_de_sesgo"): {
            k: v for k, v in alternativa.items()
            if k in ("prob_hay_segunda_vuelta", "prob_gana_en_1v", "prob_presidente")
            or k.startswith(("prob_gana_cruce_", f"pct_{lula}_cruce_"))},
    }

    ahora = datetime.now(timezone.utc)
    out = SALIDA_DIR / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    dist.to_parquet(out / "distribucion_1v.parquet", index=False)
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "random_seed": seed, "n_simulaciones": n_sim,
        "fecha_corte_encuestas": meta_agr["fecha_corte_encuestas"],
        "agregacion_usada": corrida.relative_to(ROOT).as_posix(),
        "incertidumbre": inc,
        "limitaciones": [
            f"Incertidumbre medida con {inc['observaciones']} errores del agregador (2 elecciones).",
            "En 2018 y 2022 las encuestas subestimaron a la derecha bolsonarista antes de la 1ª vuelta; "
            "sin corrección ese sesgo entra solo como varianza.",
            "Cruces de 2ª vuelta medidos antes de la 1ª: no incorporan la reconfiguración de la campaña de balotaje.",
            "Nacional: no hay distribución por UF.",
        ],
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in
                           [corrida / "agregado.csv", corrida / "backtest.csv", ENCUESTAS, CONFIG_MODELO]},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(out / "resumen.json", ELECTORAL_DIR / "resumen_presidencial_encuestas_2026.json")

    log.info("Presidencial 2026 con encuestas (%d simulaciones, semilla %d):\n%s",
             n_sim, seed, json.dumps(resumen, ensure_ascii=False, indent=1))
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
