"""
src/models/montecarlo/proyeccion_gobernadores.py

Simulación Montecarlo de las 27 elecciones de gobernador 2026.

Cada UF es un proceso INDEPENDIENTE con su propio balotaje (si nadie supera
el 50% de los votos válidos en 1ª vuelta, van los dos primeros a 2ª vuelta
en ESA UF). Nunca se mezcla con la lógica del balotaje presidencial. Lo único
común entre UFs es el shock nacional de cada família (mismo ruido que Câmara
y Senado).

Modelo por UF, sin encuestas (decisión del 2026-10-01):
  fuerza de família S_f   = % de voto a Câmara (año base, famílias del año objetivo)
                            + shocks de família (nacional + UF)
  puntaje del candidato i = S_f(i) × (1 si es el 1º de su família, beta si no)
                            × exp(sigma · z_i + delta · incumbente_i)
  1ª vuelta: % de votos = puntaje / suma. Si el primero supera 50%, gana.
  2ª vuelta: los dos primeros; % × exp(sigma_balotaje · z), gana el mayor.

Orden dentro de una família: incumbente primero, después por número de
candidato (arbitrario: por eso el modelo reporta família e incumbente, no
cada candidato no incumbente por separado).

Incumbente = electo gobernador o vice en el ciclo anterior (también
suplementarias que figuran en consulta_cand), por CPF y misma UF. Un solo
parámetro delta para gobernador y vice (decisión del 2026-10-01).

Calibración: beta, sigma, delta y sigma_balotaje por máxima verosimilitud de
lo que pasó en 2018 y 2022 (54 elecciones): família ganadora, si el ganador
era incumbente y si hubo balotaje, con la fuerza de Câmara del MISMO año.
Falla si un óptimo queda en el borde superior de su grilla.

Salidas versionadas en data/processed/electoral/gobernadores_sim/<fecha_utc>/:
  probabilidad_uf.csv             UF × família × incumbente: prob. de ganar; prob. de balotaje por UF
  gobernadores_familia_simulacion.parquet   simulación × família (cantidad de gobernaciones)
  calibracion.csv, validacion.csv, resumen.csv, meta.json
Y copia del resumen en data/processed/electoral/resumen_gobernadores_2026.csv.

Uso:
    python -m src.models.montecarlo.proyeccion_gobernadores [--n-sim 2000]
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.etl.extract.tse_extractor import ultima_version
from src.etl.extract.versionado import sha256
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import familia, tabla_ano
from src.models.montecarlo.proyeccion_bancas import (
    CONFIG_MODELO, ELECTORAL_DIR, ROOT, cargar_config, cargar_ruido,
)
from src.models.montecarlo.proyeccion_senado import fuerza_familias

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "gobernadores_sim"
FILTRO_GOB = {"DS_CARGO": {"GOVERNADOR"}}
ORDINARIA = {"NM_TIPO_ELEICAO": {"Eleição Ordinária"}}


@dataclass
class Carrera:
    uf: str
    familias: list[str]          # famílias del año (columnas de fuerza)
    fuerza: np.ndarray           # (F,)
    fam_idx: np.ndarray          # (k,) família de cada candidato
    primero: np.ndarray          # (k,) bool, 1º de su família
    incumbente: np.ndarray       # (k,) bool
    nombres: list[str]
    # resultado real (solo años pasados)
    real_familia: str | None = None
    real_incumbente: bool | None = None
    real_balotaje: bool | None = None


# ---------------------------------------------------------------- insumos

def incumbentes(ano: int) -> set[tuple[str, str]]:
    """(UF, CPF) de quienes fueron electos gobernador o vice en el ciclo anterior a `ano`."""
    c = leer_zip_tse(ultima_version("candidatos", ano - 4),
                     columnas=["SG_UF", "NR_CPF_CANDIDATO", "DS_SIT_TOT_TURNO"],
                     filtro={"DS_CARGO": {"GOVERNADOR", "VICE-GOVERNADOR"}})
    e = c[c["DS_SIT_TOT_TURNO"].str.upper().str.startswith("ELEITO", na=False)]
    return set(zip(e["SG_UF"], e["NR_CPF_CANDIDATO"]))


def _ordenar(c: pd.DataFrame) -> pd.DataFrame:
    c = c.sort_values(["uf", "familia", "incumbente", "numero"], ascending=[True, True, False, True])
    c["primero"] = ~c.duplicated(["uf", "familia"])
    return c


def candidatos_pasados(ano: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Candidatos que recibieron votos en 1ª vuelta y resultado real por UF."""
    r = leer_zip_tse(ultima_version("resultados", ano),
                     columnas=["SG_UF", "SQ_CANDIDATO", "NR_CANDIDATO", "NM_URNA_CANDIDATO",
                               "SG_PARTIDO", "NR_TURNO", "DS_SIT_TOT_TURNO"],
                     filtro={**ORDINARIA, **FILTRO_GOB})
    cpf = leer_zip_tse(ultima_version("candidatos", ano), columnas=["SQ_CANDIDATO", "NR_CPF_CANDIDATO"],
                       filtro={**ORDINARIA, **FILTRO_GOB}).drop_duplicates("SQ_CANDIDATO")
    t1 = r[r["NR_TURNO"] == "1"].drop_duplicates(["SG_UF", "SQ_CANDIDATO"]).merge(cpf, on="SQ_CANDIDATO", how="left")
    inc = incumbentes(ano)
    c = pd.DataFrame({
        "uf": t1["SG_UF"], "numero": pd.to_numeric(t1["NR_CANDIDATO"]), "nombre": t1["NM_URNA_CANDIDATO"],
        "partido": t1["SG_PARTIDO"], "sq": t1["SQ_CANDIDATO"],
        "incumbente": [(u, x) in inc for u, x in zip(t1["SG_UF"], t1["NR_CPF_CANDIDATO"])],
    })
    c["familia"] = [familia(p, ano) for p in c["partido"]]

    ganador = r[r["DS_SIT_TOT_TURNO"].str.upper().str.startswith("ELEITO", na=False)].drop_duplicates("SG_UF")
    res = pd.DataFrame({"uf": ganador["SG_UF"], "sq": ganador["SQ_CANDIDATO"]})
    res = res.merge(c[["sq", "familia", "incumbente"]], on="sq", how="left")
    res["balotaje"] = res["uf"].isin(set(r.loc[r["NR_TURNO"] == "2", "SG_UF"]))
    return _ordenar(c), res.set_index("uf")


def candidatos_2026(ano: int) -> pd.DataFrame:
    c = leer_zip_tse(ultima_version("candidatos", ano),
                     columnas=["SG_UF", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "NR_CPF_CANDIDATO"],
                     filtro={**ORDINARIA, **FILTRO_GOB}).drop_duplicates(["SG_UF", "NR_CANDIDATO"])
    inc = incumbentes(ano)
    c = pd.DataFrame({
        "uf": c["SG_UF"], "numero": pd.to_numeric(c["NR_CANDIDATO"]), "nombre": c["NM_URNA_CANDIDATO"],
        "partido": c["SG_PARTIDO"],
        "incumbente": [(u, x) in inc for u, x in zip(c["SG_UF"], c["NR_CPF_CANDIDATO"])],
    })
    c["familia"] = [familia(p, ano) for p in c["partido"]]
    return _ordenar(c)


def armar_carreras(cands: pd.DataFrame, fuerza: pd.DataFrame,
                   resultado: pd.DataFrame | None = None) -> list[Carrera]:
    familias = sorted(set(fuerza.columns) | set(cands["familia"]))
    f = fuerza.reindex(columns=familias, fill_value=0.0)
    carreras = []
    for uf, g in cands.groupby("uf"):
        k = Carrera(uf=uf, familias=familias, fuerza=f.loc[uf].to_numpy(),
                    fam_idx=np.array([familias.index(x) for x in g["familia"]]),
                    primero=g["primero"].to_numpy(), incumbente=g["incumbente"].to_numpy(),
                    nombres=g["nombre"].tolist())
        if resultado is not None and uf in resultado.index:
            k.real_familia = resultado.at[uf, "familia"]
            k.real_incumbente = bool(resultado.at[uf, "incumbente"])
            k.real_balotaje = bool(resultado.at[uf, "balotaje"])
        carreras.append(k)
    return carreras


# ---------------------------------------------------------------- elección

def eleccion(fuerza_sim: np.ndarray, k: Carrera, beta: float, delta: float,
             z_cand: np.ndarray, z_bal: np.ndarray, sigma: float, sigma_bal: float) -> tuple[np.ndarray, np.ndarray]:
    """
    fuerza_sim: (N × F) fuerza de família por simulación.
    z_cand: (N × k) normales estándar del efecto propio; z_bal: (N × 2) del balotaje.
    Devuelve (índice del candidato ganador (N,), hubo balotaje (N,)).
    """
    base = fuerza_sim[:, k.fam_idx] * np.where(k.primero, 1.0, beta)
    puntaje = base * np.exp(sigma * z_cand + delta * k.incumbente)
    total = puntaje.sum(axis=1, keepdims=True)
    votos = np.divide(puntaje, total, out=np.zeros_like(puntaje), where=total > 0)

    orden = np.argsort(-votos, axis=1, kind="stable")
    top2 = orden[:, :2] if votos.shape[1] >= 2 else np.repeat(orden[:, :1], 2, axis=1)
    v_top2 = np.take_along_axis(votos, top2, axis=1)
    balotaje = v_top2[:, 0] <= 0.5
    segunda = v_top2 * np.exp(sigma_bal * z_bal)
    ganador_bal = np.where(segunda[:, 0] >= segunda[:, 1], top2[:, 0], top2[:, 1])
    return np.where(balotaje, ganador_bal, top2[:, 0]), balotaje


# ---------------------------------------------------------------- calibración

def calibrar(carreras: list[Carrera], grillas: dict, n_sim: int, seed: int) -> tuple[dict, pd.DataFrame]:
    """Máxima verosimilitud de (família ganadora, ganador incumbente, hubo balotaje) por carrera.
    Números aleatorios comunes en toda la grilla: la superficie es suave y comparable."""
    rng = np.random.default_rng(seed)
    z = [(rng.standard_normal((n_sim, len(k.fam_idx))), rng.standard_normal((n_sim, 2))) for k in carreras]
    eps = 1 / (2 * n_sim)
    filas = []
    for beta, sigma, delta in itertools.product(grillas["beta"], grillas["sigma_candidato"], grillas["delta_incumbente"]):
        for sigma_bal in grillas["sigma_balotaje"]:
            ll = 0.0
            for k, (zc, zb) in zip(carreras, z):
                f = np.repeat(k.fuerza[None, :], n_sim, axis=0)
                gan, bal = eleccion(f, k, beta, delta, zc, zb, sigma, sigma_bal)
                fam_ok = np.array(k.familias)[k.fam_idx[gan]] == k.real_familia
                ok = fam_ok & (k.incumbente[gan] == k.real_incumbente) & (bal == k.real_balotaje)
                ll += np.log(ok.mean() + eps)
            filas.append({"beta": beta, "sigma_candidato": sigma, "delta_incumbente": delta,
                          "sigma_balotaje": sigma_bal, "log_verosimilitud": round(float(ll), 3)})
    tabla = pd.DataFrame(filas).sort_values("log_verosimilitud", ascending=False).reset_index(drop=True)
    mejor = tabla.iloc[0].to_dict()
    for p in ("sigma_candidato", "delta_incumbente", "sigma_balotaje"):
        if mejor[p] == max(grillas[p]) and max(grillas[p]) > 0:
            raise ValueError(f"Óptimo de {p} en el borde superior de la grilla ({mejor[p]}): ampliarla")
    return {p: float(mejor[p]) for p in ("beta", "sigma_candidato", "delta_incumbente", "sigma_balotaje")}, tabla


def validar(carreras: list[Carrera], params: dict, n_sim: int, seed: int) -> pd.DataFrame:
    """Acierto de la família ganadora más probable del modelo vs reglas ingenuas, por carrera."""
    rng = np.random.default_rng(seed + 1)
    filas = []
    for k in carreras:
        f = np.repeat(k.fuerza[None, :], n_sim, axis=0)
        gan, bal = eleccion(f, k, params["beta"], params["delta_incumbente"],
                            rng.standard_normal((n_sim, len(k.fam_idx))), rng.standard_normal((n_sim, 2)),
                            params["sigma_candidato"], params["sigma_balotaje"])
        fams = pd.Series(np.array(k.familias)[k.fam_idx[gan]])
        modelo = fams.value_counts().idxmax()
        presentes = sorted(set(k.fam_idx))
        mas_fuerte = k.familias[max(presentes, key=lambda j: k.fuerza[j])]
        inc = [k.familias[k.fam_idx[i]] for i in np.flatnonzero(k.incumbente)]
        filas.append({
            "uf": k.uf, "real": k.real_familia,
            "modelo": modelo, "prob_modelo_real": round(float((fams == k.real_familia).mean()), 3),
            "ingenua_mas_fuerte": mas_fuerte,
            "ingenua_incumbente": inc[0] if inc else mas_fuerte,
            "balotaje_real": k.real_balotaje, "prob_balotaje_modelo": round(float(bal.mean()), 3),
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- simulación 2026

def simular(carreras: list[Carrera], ruido: pd.DataFrame, params: dict, n_sim: int, seed: int):
    familias = carreras[0].familias
    sig_uf = ruido["sigma_uf_pp"].reindex(familias).fillna(0).to_numpy() / 100
    sig_nac = ruido["sigma_nacional_pp"].reindex(familias).fillna(0).to_numpy() / 100
    rng = np.random.default_rng(seed)
    shock_nac = rng.normal(0, 1, (n_sim, len(familias))) * sig_nac

    por_uf, conteo = [], np.zeros((n_sim, len(familias)), dtype=int)
    for k in carreras:
        s = np.clip(k.fuerza + shock_nac + rng.normal(0, 1, (n_sim, len(familias))) * sig_uf, 0, None)
        s[:, k.fuerza == 0] = 0
        gan, bal = eleccion(s, k, params["beta"], params["delta_incumbente"],
                            rng.standard_normal((n_sim, len(k.fam_idx))), rng.standard_normal((n_sim, 2)),
                            params["sigma_candidato"], params["sigma_balotaje"])
        fam_gan = k.fam_idx[gan]
        np.add.at(conteo, (np.arange(n_sim), fam_gan), 1)
        d = pd.DataFrame({"familia": np.array(familias)[fam_gan], "incumbente": k.incumbente[gan]})
        p = d.value_counts(normalize=True).rename("prob_ganar").reset_index()
        cands = pd.DataFrame({"familia": np.array(familias)[k.fam_idx], "incumbente": k.incumbente,
                              "nombre": k.nombres})
        nombres = cands.groupby(["familia", "incumbente"])["nombre"].agg(" / ".join).reset_index()
        p = nombres.merge(p, on=["familia", "incumbente"], how="left").fillna({"prob_ganar": 0.0})
        p["uf"] = k.uf
        p["prob_balotaje_uf"] = round(float(bal.mean()), 3)
        por_uf.append(p)
    return pd.concat(por_uf, ignore_index=True), pd.DataFrame(conteo, columns=familias)


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-sim", type=int)
    args = parser.parse_args(argv)

    cfg = cargar_config()
    c = cfg["gobernadores"]
    n_sim = args.n_sim or cfg["simulacion"]["n_simulaciones"]
    seed = cfg["simulacion"]["random_seed"]
    if tabla_ano(c["ano_objetivo"])[0] != "vigente":
        raise ValueError(f"La clasificación {c['ano_objetivo']} no está vigente")

    calib_carreras = []
    for ano in c["anos_calibracion"]:
        cands, res = candidatos_pasados(ano)
        calib_carreras += armar_carreras(cands, fuerza_familias(ano, ano), res)
    params, tabla_calib = calibrar(calib_carreras, c["calibracion"], c["calibracion"]["n_sim"], seed)
    valid = validar(calib_carreras, params, c["calibracion"]["n_sim"], seed)
    aciertos = {r: int((valid[r] == valid["real"]).sum()) for r in ("modelo", "ingenua_mas_fuerte", "ingenua_incumbente")}
    log.info("Calibración %s (%d elecciones): %s\nAciertos de família ganadora: %s",
             c["anos_calibracion"], len(calib_carreras), params, aciertos)

    cands26 = candidatos_2026(c["ano_objetivo"])
    carreras = armar_carreras(cands26, fuerza_familias(c["ano_base"], c["ano_objetivo"]))
    ruido = cargar_ruido(cfg["camara"]["ruido"]["fuente_volatilidad"], cfg["camara"]["ruido"]["componente_nacional"])
    prob_uf, conteo = simular(carreras, ruido, params, n_sim, seed)

    resumen = pd.DataFrame({
        "media": conteo.mean().round(1), "p10": conteo.quantile(0.10),
        "mediana": conteo.median(), "p90": conteo.quantile(0.90),
    }).sort_values("media", ascending=False).rename_axis("familia").reset_index()

    ahora = datetime.now(timezone.utc)
    out = SALIDA_DIR / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    prob_uf = prob_uf[["uf", "familia", "incumbente", "nombre", "prob_ganar", "prob_balotaje_uf"]]
    prob_uf.sort_values(["uf", "prob_ganar"], ascending=[True, False]).to_csv(out / "probabilidad_uf.csv", index=False)
    conteo.rename_axis("simulacion").reset_index().to_parquet(out / "gobernadores_familia_simulacion.parquet", index=False)
    tabla_calib.head(50).to_csv(out / "calibracion.csv", index=False)
    valid.to_csv(out / "validacion.csv", index=False)
    resumen.to_csv(out / "resumen.csv", index=False)

    insumos = [ELECTORAL_DIR / "serie_historica_familias.parquet", ELECTORAL_DIR / "volatilidad_familias.parquet",
               *[ELECTORAL_DIR / f"camara_familia_uf_{a}.parquet" for a in c["anos_calibracion"]],
               ultima_version("candidatos", c["ano_objetivo"]), CONFIG_MODELO,
               ROOT / "config" / "familias_partidarias.yaml"]
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "random_seed": seed, "n_simulaciones": n_sim, "fecha_corte_encuestas": None,
        "base": f"fuerza de família = voto a Câmara {c['ano_base']} por UF, famílias {c['ano_objetivo']} (sin encuestas)",
        "parametros_calibrados": params,
        "aciertos_familia_ganadora_calibracion": {**aciertos, "elecciones": len(calib_carreras)},
        "incumbentes_2026": cands26.loc[cands26["incumbente"], ["uf", "nombre", "partido"]].to_dict(orient="records"),
        "limitaciones": [
            "Sin encuestas: el voto personal entra como ruido calibrado con 2018 y 2022.",
            "Incumbente = electo gobernador o vice en 2022 (CPF). No se sabe por datos TSE quién ejerce hoy.",
            "RR: la suplementaria de gobernador de jun/2026 figura sin electo (votos sub judice): nadie marcado incumbente.",
            "consulta_cand 2026 no publica situación de candidatura: incluye impugnadas.",
            "Candidatos no incumbentes de una misma família no se distinguen entre sí.",
        ],
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in insumos},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(out / "resumen.csv", ELECTORAL_DIR / "resumen_gobernadores_2026.csv")

    log.info("Gobernadores 2026 — %d simulaciones, semilla %d\n%s", n_sim, seed, resumen.to_string(index=False))
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
