"""
src/models/montecarlo/proyeccion_presidencial.py

ESCENARIO de segunda vuelta presidencial 2026 — no es un pronóstico.

Sin encuestas (decisión del 2026-10-01), lo único que los datos permiten es
responder: "si la 2ª vuelta es entre el candidato de gobierno_lula y el de
direita_bolsonarista, y cada uno parte del voto de su família en la 2ª vuelta
2022, ¿qué tan probable es cada resultado con el nivel de cambio que hubo
entre 2018 y 2022?"

Premisas (quedan en meta.json):
  - Quién pasa la 1ª vuelta NO se modela: con 14 candidatos y sin encuestas
    no hay base para estimar si un tercero (Caiado, Zema, Marçal, ...) entra.
  - El candidato 2026 de cada família hereda el voto de la família en 2022
    (Lula 2022 -> Lula 2026; Bolsonaro 2022 -> Flávio Bolsonaro 2026).
  - Balotaje presidencial = UNA elección nacional (gana quien suma más votos
    válidos en todo el país). Nada que ver con los balotajes por UF de
    gobernador.

Ruido por simulación, sobre el % de la família de gobierno_lula en cada UF:
  shock nacional ~ N(0, |cambio nacional 2018->2022|)    (una sola observación)
  shock por UF   ~ N(0, desvío entre UF de (cambio_UF - cambio nacional))
El total nacional pondera cada UF por sus votos válidos de la base (incluye
el exterior, ZZ).

Salidas versionadas en data/processed/electoral/presidencial_sim/<fecha_utc>/:
  resumen.json, por_uf.csv, distribucion_nacional.parquet, meta.json

Uso:
    python -m src.models.montecarlo.proyeccion_presidencial
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

from src.etl.extract.tse_extractor import ultima_version
from src.etl.extract.versionado import sha256
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import familia, tabla_ano
from src.models.montecarlo.proyeccion_bancas import CONFIG_MODELO, ELECTORAL_DIR, ROOT, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "presidencial_sim"
FILTRO_PRES = {"NM_TIPO_ELEICAO": {"Eleição Ordinária"}, "DS_CARGO": {"PRESIDENTE"}}


def segunda_vuelta(ano: int, familias: list[str]) -> pd.DataFrame:
    """% de la primera família de `familias` y votos válidos, por UF, en la 2ª vuelta de `ano`."""
    if tabla_ano(ano)[0] != "vigente":
        raise ValueError(f"La clasificación {ano} no está vigente")
    d = leer_zip_tse(ultima_version("resultados", ano),
                     columnas=["SG_UF", "NR_TURNO", "SG_PARTIDO", "NM_URNA_CANDIDATO", "QT_VOTOS_NOMINAIS_VALIDOS"],
                     filtro=FILTRO_PRES)
    d = d[d["NR_TURNO"] == "2"]
    if d.empty:
        raise ValueError(f"{ano} no tuvo 2ª vuelta presidencial")
    d["votos"] = pd.to_numeric(d["QT_VOTOS_NOMINAIS_VALIDOS"])
    d["familia"] = [familia(p, ano) for p in d["SG_PARTIDO"]]
    if set(d["familia"]) != set(familias):
        raise ValueError(f"{ano}: la 2ª vuelta fue entre {sorted(set(d['familia']))}, no {familias}")
    t = d.pivot_table(index="SG_UF", columns="familia", values="votos", aggfunc="sum")
    candidatos = d.groupby("familia")["NM_URNA_CANDIDATO"].first().to_dict()
    return pd.DataFrame({"pct": t[familias[0]] / t.sum(axis=1), "validos": t.sum(axis=1)}), candidatos


def nacional(pct: pd.Series | np.ndarray, validos: pd.Series) -> float:
    return float((np.asarray(pct) * validos.to_numpy()).sum() / validos.sum())


def candidatos_2026(ano: int, partido_por_familia: dict[str, str]) -> dict[str, str]:
    """Candidato presidencial `ano` del partido indicado para cada família (debe haber uno)."""
    c = leer_zip_tse(ultima_version("candidatos", ano), columnas=["NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"],
                     filtro=FILTRO_PRES).drop_duplicates(["NR_CANDIDATO", "NM_URNA_CANDIDATO"])
    salida = {}
    for fam, partido in partido_por_familia.items():
        if familia(partido, ano) != fam:
            raise ValueError(f"{partido} no es de {fam} en {ano}")
        nombres = c.loc[c["SG_PARTIDO"] == partido, "NM_URNA_CANDIDATO"].tolist()
        if len(nombres) != 1:
            raise ValueError(f"{partido} tiene {len(nombres)} candidatos presidenciales en {ano}: {nombres}")
        salida[fam] = f"{nombres[0]} ({partido})"
    return salida


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-sim", type=int)
    args = parser.parse_args(argv)

    cfg = cargar_config()
    c = cfg["presidencial"]
    n_sim = args.n_sim or cfg["simulacion"]["n_simulaciones"]
    seed = cfg["simulacion"]["random_seed"]
    fams = c["familias_balotaje"]

    base, cand_base = segunda_vuelta(c["ano_base"], fams)
    ref, cand_ref = segunda_vuelta(c["ano_referencia_cambio"], fams)
    ufs = base.index
    cambio_nac = nacional(base["pct"], base["validos"]) - nacional(ref["pct"].reindex(ufs), ref["validos"].reindex(ufs))
    desvio = (base["pct"] - ref["pct"].reindex(ufs)) - cambio_nac
    desvio = desvio.drop(c["excluir_del_desvio"], errors="ignore")
    sigma_nac, sigma_uf = abs(cambio_nac), float(desvio.std())
    log.info("Cambio nacional %d->%d: %+.2f pp | desvío entre UF: %.2f pp | correlación por UF: %.3f",
             c["ano_referencia_cambio"], c["ano_base"], cambio_nac * 100, sigma_uf * 100,
             base["pct"].corr(ref["pct"].reindex(ufs)))

    rng = np.random.default_rng(seed)
    pct = np.clip(base["pct"].to_numpy()[None, :]
                  + rng.normal(0, sigma_nac, (n_sim, 1))
                  + rng.normal(0, sigma_uf, (n_sim, len(ufs))), 0, 1)
    nac = (pct * base["validos"].to_numpy()).sum(axis=1) / base["validos"].sum()

    cand26 = candidatos_2026(cfg["gobernadores"]["ano_objetivo"], c["partido_candidato"])
    resumen = {
        "escenario": f"2ª vuelta {fams[0]} vs {fams[1]}, base {c['ano_base']}",
        "candidatos_2026": cand26,
        "base_pct_nacional": round(nacional(base["pct"], base["validos"]) * 100, 2),
        f"prob_gana_{fams[0]}": round(float((nac > 0.5).mean()), 3),
        f"pct_{fams[0]}_p10": round(float(np.quantile(nac, 0.10)) * 100, 1),
        f"pct_{fams[0]}_mediana": round(float(np.median(nac)) * 100, 1),
        f"pct_{fams[0]}_p90": round(float(np.quantile(nac, 0.90)) * 100, 1),
        "sigma_nacional_pp": round(sigma_nac * 100, 2),
        "sigma_uf_pp": round(sigma_uf * 100, 2),
    }
    por_uf = pd.DataFrame({
        "uf": ufs, f"pct_{fams[0]}_base": (base["pct"] * 100).round(1).to_numpy(),
        f"prob_gana_uf_{fams[0]}": (pct > 0.5).mean(axis=0).round(3),
        "validos_base": base["validos"].astype(int).to_numpy(),
    })

    ahora = datetime.now(timezone.utc)
    out = SALIDA_DIR / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    por_uf.to_csv(out / "por_uf.csv", index=False)
    pd.DataFrame({f"pct_{fams[0]}": nac}).to_parquet(out / "distribucion_nacional.parquet", index=False)
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "random_seed": seed, "n_simulaciones": n_sim, "fecha_corte_encuestas": None,
        "tipo": "ESCENARIO, no pronóstico",
        "premisas": [
            f"2ª vuelta entre {fams[0]} y {fams[1]}; no se modela quién pasa la 1ª vuelta.",
            f"Cada candidato 2026 hereda el voto de su família en la 2ª vuelta {c['ano_base']} "
            f"({cand_base} -> {cand26}).",
            "Balotaje nacional: un solo proceso, independiente de los balotajes de gobernador.",
        ],
        "ruido": {"cambio_referencia": f"{c['ano_referencia_cambio']}->{c['ano_base']}",
                  "candidatos_referencia": cand_ref, "sigma_nacional_pp": resumen["sigma_nacional_pp"],
                  "sigma_uf_pp": resumen["sigma_uf_pp"], "excluido_del_desvio": c["excluir_del_desvio"]},
        "limitaciones": [
            "Una sola transición (2018->2022) para medir el ruido.",
            "No incluye efecto de incumbencia presidencial (Lula) por falta de casos comparables en los datos.",
            "Sin encuestas: ignora todo lo que cambió desde 2022.",
        ],
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in [
            ultima_version("resultados", c["ano_base"]), ultima_version("resultados", c["ano_referencia_cambio"]),
            ultima_version("candidatos", cfg["gobernadores"]["ano_objetivo"]), CONFIG_MODELO,
            ROOT / "config" / "familias_partidarias.yaml"]},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(out / "resumen.json", ELECTORAL_DIR / "resumen_presidencial_2026.json")

    log.info("ESCENARIO presidencial 2026 (%d simulaciones, semilla %d):\n%s",
             n_sim, seed, json.dumps(resumen, ensure_ascii=False, indent=1))
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
