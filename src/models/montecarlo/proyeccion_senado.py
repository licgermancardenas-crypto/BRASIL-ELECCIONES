"""
src/models/montecarlo/proyeccion_senado.py

Simulación Montecarlo de la composición del Senado Federal post-2026.

2026 renueva 2/3: 54 bancas (2 por UF), mayoritario, cada elector vota dos
veces. Las otras 27 (electos en 2022, mandato hasta 2031) se toman con su
partido ACTUAL desde la API del Senado.

QUÉ PUEDE Y QUÉ NO PUEDE DECIR ESTE MODELO: el Senado se decide por
candidato. Sin encuestas, el modelo solo estima cuántas bancas tiene
chance cada FAMÍLIA por UF, a partir de la fuerza de la família (voto a
Câmara) y de cuántos candidatos presenta. No nombra ganadores.

Ruido: (a) shocks de família, iguales a la Câmara (cambio de fuerza entre
elecciones); (b) efecto propio de cada candidatura, multiplicativo: fuerza ×
exp(N(0, sigma)); representa el error del modelo con la fuerza conocida. sigma se calibra por
máxima verosimilitud con los ganadores reales de 2018.

Regla por UF (determinística dado el ruido):
  - Fuerza de la família S_f = % de votos a Câmara en la UF (año base, con
    famílias del año objetivo) + ruido (mismo modelo que la Câmara).
  - Cada família con >= 1 candidato compite con S_f; si tiene >= 2, su
    segundo candidato compite con beta * S_f (dos votos por elector).
  - Las 2 entradas más fuertes ganan.
beta se calibra reproduciendo 2018 (también renovó 2 bancas por UF),
minimizando el error en el total nacional por família, y se compara contra
una regla ingenua: "ganan las 2 famílias más fuertes de la UF".

Salidas versionadas en data/processed/legislativo/senado/<fecha_utc>/:
  bancas_familia_simulacion.parquet   simulación × família (54 en juego y total 81)
  probabilidad_uf_familia.csv         por UF y família: prob. de ganar >= 1 banca, bancas esperadas
  calibracion.csv                     aciertos 2018 por beta y regla ingenua
  resumen.csv, meta.json
Y copia de resumen.csv en data/processed/legislativo/resumen_bancas_senado.csv.

Uso:
    python -m src.models.montecarlo.proyeccion_senado [--n-sim 2000]
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

from src.etl.extract.referencia_extractor import ultima_version as ultima_referencia
from src.etl.extract.tse_extractor import ultima_version
from src.etl.extract.versionado import sha256
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import familia, tabla_ano
from src.models.montecarlo.proyeccion_bancas import (
    CONFIG_MODELO, ELECTORAL_DIR, LEGISLATIVO_DIR, ROOT, cargar_config, cargar_ruido,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FILTRO_SENADO = {"NM_TIPO_ELEICAO": {"Eleição Ordinária"}, "DS_CARGO": {"SENADOR"}}
BANCAS_POR_UF = 2


# ---------------------------------------------------------------- insumos

def fuerza_familias(ano_base: int, ano_clasificacion: int) -> pd.DataFrame:
    """% de votos a Câmara por UF y família. Si los años coinciden, clasificación del año;
    si no, composición fija del año de clasificación (serie histórica)."""
    if ano_base == ano_clasificacion:
        d = pd.read_parquet(ELECTORAL_DIR / f"camara_familia_uf_{ano_base}.parquet")
    else:
        s = pd.read_parquet(ELECTORAL_DIR / "serie_historica_familias.parquet")
        d = s[(s["composicion"] == f"fija_{ano_clasificacion}") & (s["ano"] == ano_base)]
        if d.empty:
            raise ValueError(f"No hay serie con composición fija_{ano_clasificacion} para {ano_base}")
    return d.pivot_table(index="uf", columns="familia", values="pct_votos", fill_value=0.0)


def candidatos(ano: int) -> pd.DataFrame:
    """Candidatos a senador por UF con su família del año. 2026: consulta_cand (sin
    situación de candidatura publicada). Años pasados: los que recibieron votos."""
    if ano >= 2026:
        c = leer_zip_tse(ultima_version("candidatos", ano),
                         columnas=["SG_UF", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"],
                         filtro=FILTRO_SENADO)
        c = c.drop_duplicates(["SG_UF", "NR_CANDIDATO"])  # mismo candidato registrado dos veces
    else:
        c = leer_zip_tse(ultima_version("resultados", ano),
                         columnas=["SG_UF", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "NR_TURNO"],
                         filtro=FILTRO_SENADO)
        c = c[c["NR_TURNO"] == "1"].drop_duplicates(["SG_UF", "SQ_CANDIDATO"])
    c = c.rename(columns={"SG_UF": "uf", "NM_URNA_CANDIDATO": "candidato", "SG_PARTIDO": "partido"})
    c["familia"] = [familia(p, ano) for p in c["partido"]]
    return c[["uf", "candidato", "partido", "familia"]]


def electos(ano: int) -> pd.DataFrame:
    r = leer_zip_tse(ultima_version("resultados", ano),
                     columnas=["SG_UF", "SQ_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"],
                     filtro=FILTRO_SENADO)
    e = r[r["DS_SIT_TOT_TURNO"].str.upper().str.startswith("ELEITO", na=False)]
    e = e.drop_duplicates(["SG_UF", "SQ_CANDIDATO"])
    e = e.assign(familia=[familia(p, ano) for p in e["SG_PARTIDO"]])
    return e.rename(columns={"SG_UF": "uf"})[["uf", "familia"]]


def senadores_que_siguen(ano_objetivo: int) -> pd.DataFrame:
    """Senadores con mandato que sigue después de la elección (2ª legislatura del mandato
    posterior a la actual), con partido actual y família del año objetivo."""
    path = ultima_referencia("senado_en_ejercicio")
    ps = json.loads(path.read_text(encoding="utf-8"))["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    legs = [int(p["Mandato"]["SegundaLegislaturaDoMandato"]["NumeroLegislatura"]) for p in ps]
    ultima = max(legs)
    filas = [(p["IdentificacaoParlamentar"]["NomeParlamentar"],
              p["IdentificacaoParlamentar"]["SiglaPartidoParlamentar"],
              p["Mandato"]["UfParlamentar"])
             for p, leg in zip(ps, legs) if leg == ultima]
    d = pd.DataFrame(filas, columns=["senador", "partido", "uf"])
    d["familia"] = [familia(p, ano_objetivo) for p in d["partido"]]
    if len(d) != 27 or d["uf"].nunique() != 27:
        raise ValueError(f"Se esperaban 27 senadores que siguen (1 por UF); hay {len(d)}")
    return d


# ---------------------------------------------------------------- regla

def ganadores(fuerza: np.ndarray, n_cand: np.ndarray, beta: float,
              bancas: int = BANCAS_POR_UF, efecto_candidato: np.ndarray | None = None) -> np.ndarray:
    """
    fuerza: (simulaciones × famílias) fuerza de cada família en la UF.
    n_cand: (famílias,) cantidad de candidatos de cada família en la UF.
    efecto_candidato: (simulaciones × 2·famílias) shock propio de cada candidatura
        (1º y 2º de cada família), en escala logarítmica: la fuerza de la
        candidatura se multiplica por exp(efecto). Multiplicativo a propósito:
        un candidato puede duplicar o achicar la fuerza de su família, pero un
        partido de 0,5% no salta a 30% (con ruido aditivo sí pasaba).
    Devuelve (simulaciones × famílias) con bancas ganadas.
    """
    fuerza = np.atleast_2d(fuerza)
    n_sim, n_fam = fuerza.shape
    primera = np.where(n_cand >= 1, fuerza, -np.inf)
    segunda = np.where(n_cand >= 2, beta * fuerza, -np.inf)
    entradas = np.concatenate([primera, segunda], axis=1)
    if efecto_candidato is not None:
        entradas = entradas * np.exp(efecto_candidato)  # -inf · x > 0 sigue siendo -inf
    top = np.argsort(-entradas, axis=1, kind="stable")[:, :bancas]
    validas = np.take_along_axis(entradas, top, axis=1) > -np.inf
    res = np.zeros((n_sim, n_fam), dtype=int)
    filas = np.repeat(np.arange(n_sim), bancas)
    fam = (top % n_fam).ravel()
    np.add.at(res, (filas[validas.ravel()], fam[validas.ravel()]), 1)
    return res


def _por_uf(fuerza: pd.DataFrame, cands: pd.DataFrame, familias: list[str]) -> dict:
    """{uf: (vector fuerza, vector n_candidatos)} alineados a `familias`."""
    n = cands.groupby(["uf", "familia"]).size().unstack(fill_value=0)
    return {uf: (fuerza.reindex(columns=familias, fill_value=0.0).loc[uf].to_numpy(),
                 n.reindex(columns=familias, fill_value=0).loc[uf].to_numpy() if uf in n.index
                 else np.zeros(len(familias), dtype=int))
            for uf in fuerza.index}


def calibrar(ano: int, grilla: list[float]) -> tuple[float, pd.DataFrame]:
    """Reproduce `ano` (fuerza = Câmara del mismo año, clasificación de ese año) para cada beta.

    Criterio de elección: menor ERROR EN EL TOTAL NACIONAL por família
    (sum_f |predichas_f - reales_f|), porque eso es lo que reporta el modelo.
    Desempate: más aciertos por UF y família (sum_uf sum_f min(pred, real)).
    Con aciertos por UF como criterio principal, 2018 elegía beta=0.5, que
    acertaba más UFs pero le daba 43 bancas al centrão contra 29 reales.
    """
    fuerza = fuerza_familias(ano, ano)
    cands = candidatos(ano)
    reales = electos(ano).groupby(["uf", "familia"]).size().unstack(fill_value=0)
    familias = sorted(set(fuerza.columns) | set(cands["familia"]))
    datos = _por_uf(fuerza, cands, familias)
    reales = reales.reindex(index=sorted(datos), columns=familias, fill_value=0)
    total_real = reales.sum()

    def evaluar(regla: str, beta: float, predichas: dict) -> dict:
        total_pred = pd.Series(sum(predichas.values()), index=familias)
        return {
            "regla": regla, "beta": beta,
            "error_total_familias": int((total_pred - total_real).abs().sum()),
            "aciertos_uf": int(sum(np.minimum(predichas[uf], reales.loc[uf].to_numpy()).sum() for uf in datos)),
            **{f"pred_{f}": int(total_pred[f]) for f in familias},
        }

    filas = [evaluar(f"beta={b:.2f}", b, {uf: ganadores(s[None, :], n, b)[0] for uf, (s, n) in datos.items()})
             for b in grilla]
    # Ingenua: las 2 famílias más fuertes, sin mirar candidatos
    filas.append(evaluar("ingenua (2 famílias más fuertes)", np.nan,
                         {uf: ganadores(s[None, :], np.ones(len(familias), dtype=int), 0.0)[0]
                          for uf, (s, _) in datos.items()}))
    filas.append({"regla": "real", "beta": np.nan, "error_total_familias": 0,
                  "aciertos_uf": int(total_real.sum()), **{f"pred_{f}": int(total_real[f]) for f in familias}})
    tabla = pd.DataFrame(filas).assign(bancas_reales=int(total_real.sum()))

    betas = tabla.dropna(subset=["beta"])
    mejor = betas[betas["error_total_familias"] == betas["error_total_familias"].min()]
    mejor = mejor[mejor["aciertos_uf"] == mejor["aciertos_uf"].max()]["beta"].to_numpy()
    beta = float(mejor[len(mejor) // 2])  # centro del rango óptimo: menos sensible al borde
    return beta, tabla


def calibrar_efecto_candidato(ano: int, beta: float, grilla_log: list[float],
                              n_sim: int, seed: int) -> tuple[float, pd.DataFrame]:
    """Desvío (escala log) del efecto propio de cada candidatura que hace más probables los
    ganadores reales de `ano`, con la fuerza de Câmara de ese mismo año.

    Verosimilitud = sum_uf log P(bancas por família simuladas == reales), con
    suavizado 1/(2·n_sim) para no dar -inf. Las UF con != 2 electos en los datos
    (MT 2018) quedan fuera. También informa en qué percentil de la distribución
    simulada cae el total real de cada família (control de cobertura)."""
    fuerza = fuerza_familias(ano, ano)
    cands = candidatos(ano)
    reales = electos(ano).groupby(["uf", "familia"]).size().unstack(fill_value=0)
    familias = sorted(set(fuerza.columns) | set(cands["familia"]))
    datos = _por_uf(fuerza, cands, familias)
    reales = reales.reindex(index=sorted(datos), columns=familias, fill_value=0)
    ufs_validas = [uf for uf in datos if reales.loc[uf].sum() == BANCAS_POR_UF]
    total_real = reales.sum().to_numpy()

    filas = []
    for sigma in grilla_log:
        rng = np.random.default_rng(seed)
        loglik, totales = 0.0, np.zeros((n_sim, len(familias)), dtype=int)
        for uf in sorted(datos):
            s_uf, n = datos[uf]
            efecto = rng.normal(0, sigma, (n_sim, 2 * len(familias)))
            g = ganadores(np.repeat(s_uf[None, :], n_sim, axis=0), n, beta, efecto_candidato=efecto)
            totales += g
            if uf in ufs_validas:
                p = (g == reales.loc[uf].to_numpy()).all(axis=1).mean()
                loglik += np.log(p + 1 / (2 * n_sim))
        percentil = (totales < total_real).mean(axis=0) + 0.5 * (totales == total_real).mean(axis=0)
        filas.append({"sigma_log": sigma, "log_verosimilitud": round(float(loglik), 2),
                      **{f"percentil_real_{f}": round(float(q), 2) for f, q in zip(familias, percentil)}})
    tabla = pd.DataFrame(filas).assign(ufs_usadas=len(ufs_validas))
    sigma = float(tabla.loc[tabla["log_verosimilitud"].idxmax(), "sigma_log"])
    if sigma == max(grilla_log):
        raise ValueError(f"La verosimilitud es máxima en el borde de la grilla (sigma={sigma}): ampliarla")
    return sigma, tabla


# ---------------------------------------------------------------- simulación

def simular(fuerza: pd.DataFrame, cands: pd.DataFrame, ruido: pd.DataFrame,
            beta: float, n_sim: int, seed: int,
            sigma_candidato_log: float = 0.0) -> tuple[pd.DataFrame, np.ndarray, list[str], list[str]]:
    familias = sorted(set(fuerza.columns) | set(cands["familia"]))
    sig_uf = ruido["sigma_uf_pp"].reindex(familias).fillna(0).to_numpy() / 100
    sig_nac = ruido["sigma_nacional_pp"].reindex(familias).fillna(0).to_numpy() / 100
    datos = _por_uf(fuerza, cands, familias)
    ufs = sorted(datos)

    rng = np.random.default_rng(seed)
    shock_nac = rng.normal(0, 1, (n_sim, len(familias))) * sig_nac
    shock_uf = rng.normal(0, 1, (len(ufs), n_sim, len(familias))) * sig_uf
    efecto = rng.normal(0, sigma_candidato_log, (len(ufs), n_sim, 2 * len(familias)))

    por_uf = np.zeros((len(ufs), n_sim, len(familias)), dtype=int)
    for i, uf in enumerate(ufs):
        s, n = datos[uf]
        s_sim = np.clip(s + shock_nac + shock_uf[i], 0, None)
        s_sim[:, s == 0] = 0
        por_uf[i] = ganadores(s_sim, n, beta, efecto_candidato=efecto[i])
    return pd.DataFrame(por_uf.sum(axis=0), columns=familias), por_uf, ufs, familias


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-sim", type=int)
    args = parser.parse_args(argv)

    cfg = cargar_config()
    c = cfg["senado"]
    n_sim = args.n_sim or cfg["simulacion"]["n_simulaciones"]
    seed = cfg["simulacion"]["random_seed"]
    if tabla_ano(c["ano_objetivo"])[0] != "vigente":
        raise ValueError(f"La clasificación {c['ano_objetivo']} no está vigente")

    beta, calib = calibrar(c["calibracion"]["ano"], c["calibracion"]["beta_grilla"])
    log.info("Calibración %d (bancas reales: %d):\n%s\n-> beta = %.2f", c["calibracion"]["ano"],
             int(calib["bancas_reales"].iat[0]),
             calib.drop(columns=["beta", "bancas_reales"]).to_string(index=False), beta)

    ec = c["efecto_candidato"]
    sigma_cand, calib_cand = calibrar_efecto_candidato(
        c["calibracion"]["ano"], beta, ec["grilla_log"], ec["n_sim_calibracion"], seed)
    log.info("Efecto candidato — verosimilitud %d por sigma:\n%s\n-> sigma = %.2f (log)",
             c["calibracion"]["ano"], calib_cand.to_string(index=False), sigma_cand)

    fuerza = fuerza_familias(c["ano_base"], c["ano_objetivo"])
    cands = candidatos(c["ano_objetivo"])
    siguen = senadores_que_siguen(c["ano_objetivo"])
    ruido = cargar_ruido(cfg["camara"]["ruido"]["fuente_volatilidad"], cfg["camara"]["ruido"]["componente_nacional"])

    en_juego, por_uf, ufs, familias = simular(fuerza, cands, ruido, beta, n_sim, seed, sigma_cand)
    fijos = siguen["familia"].value_counts().reindex(familias, fill_value=0)
    total = en_juego + fijos.to_numpy()
    if not (total.sum(axis=1) == 81).all():
        raise ValueError("La composición simulada no suma 81 bancas")

    resumen = pd.DataFrame({
        "bancas_que_siguen": fijos,
        "en_juego_media": en_juego.mean().round(1),
        "total_p10": total.quantile(0.10),
        "total_mediana": total.median(),
        "total_p90": total.quantile(0.90),
        "prob_mayoria_propia": (total >= c["bancas_mayoria"]).mean().round(3),
    }).sort_values("total_mediana", ascending=False).rename_axis("familia").reset_index()

    prob_uf = pd.DataFrame([
        {"uf": uf, "familia": f,
         "candidatos": int(cands[(cands["uf"] == uf) & (cands["familia"] == f)].shape[0]),
         "prob_al_menos_una": round(float((por_uf[i][:, j] >= 1).mean()), 3),
         "bancas_esperadas": round(float(por_uf[i][:, j].mean()), 2)}
        for i, uf in enumerate(ufs) for j, f in enumerate(familias)])
    prob_uf = prob_uf[prob_uf["candidatos"] > 0]

    ahora = datetime.now(timezone.utc)
    out = LEGISLATIVO_DIR / "senado" / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    pd.concat([en_juego.assign(tipo="en_juego"), total.assign(tipo="total")]).rename_axis("simulacion") \
        .reset_index().melt(id_vars=["simulacion", "tipo"], var_name="familia", value_name="bancas") \
        .to_parquet(out / "bancas_familia_simulacion.parquet", index=False)
    prob_uf.to_csv(out / "probabilidad_uf_familia.csv", index=False)
    calib.to_csv(out / "calibracion.csv", index=False)
    calib_cand.to_csv(out / "calibracion_efecto_candidato.csv", index=False)
    resumen.to_csv(out / "resumen.csv", index=False)
    siguen.to_csv(out / "senadores_que_siguen.csv", index=False)

    insumos = [ELECTORAL_DIR / "serie_historica_familias.parquet",
               ELECTORAL_DIR / f"camara_familia_uf_{c['calibracion']['ano']}.parquet",
               ELECTORAL_DIR / "volatilidad_familias.parquet",
               ultima_version("candidatos", c["ano_objetivo"]), ultima_referencia("senado_en_ejercicio"),
               CONFIG_MODELO, ROOT / "config" / "familias_partidarias.yaml"]
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "random_seed": seed,
        "n_simulaciones": n_sim,
        "fecha_corte_encuestas": None,
        "base": f"fuerza de família = voto a Câmara {c['ano_base']} por UF, famílias {c['ano_objetivo']} (sin encuestas)",
        "beta_calibrado": beta,
        "calibracion": calib.to_dict(orient="records"),
        "sigma_efecto_candidato_log": sigma_cand,
        "calibracion_efecto_candidato": calib_cand.to_dict(orient="records"),
        "que_estima": "bancas por família; NO nombra candidatos ganadores",
        "limitaciones": [
            "El voto personal del candidato no se modela con datos: entra como ruido por candidatura calibrado con 2018.",
            "consulta_cand 2026 no publica situación de candidatura: incluye candidaturas impugnadas.",
            "Calibración 2018 sobre 53 bancas: en MT la segunda electa (Selma Arruda, PSL) fue casada y sus votos anulados.",
            "Ruido de Câmara (volatilidad 2018->2022) aplicado a la fuerza de família en el Senado.",
            "Senadores que siguen: partido actual según la API del Senado a la fecha de descarga.",
        ],
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in insumos},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    shutil.copyfile(out / "resumen.csv", LEGISLATIVO_DIR / "resumen_bancas_senado.csv")

    log.info("Senado post-2026 — %d simulaciones, semilla %d, beta %.2f, efecto candidato %.2f (log)\n%s",
             n_sim, seed, beta, sigma_cand, resumen.to_string(index=False))
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
