"""
src/models/montecarlo/proyeccion_bancas.py

Simulación Montecarlo de la composición de la Câmara dos Deputados 2026.

Base (decisión del 2026-10-01, "sin encuestas"): resultado 2022 por UF y
partido, llevado a partidos 2026 (linaje de config/partidos.yaml), a sus
listas 2026 (federaciones) y a sus famílias 2026. NO es una proyección de
intención de voto: es "qué pasa si 2026 se parece a 2022 con el ruido que
mostraron las famílias entre 2018 y 2022".

Ruido por simulación (pp sobre el % de votos de la família en la UF):
  shock_nacional[família] ~ N(0, |cambio medio 2018->2022|)   común a todas las UF
  shock_uf[uf, família]   ~ N(0, volatilidad medida)          independiente por UF
El ruido mueve el total de cada família y se reparte entre sus listas en
proporción a su peso en la base. Después se renormaliza la UF a 100%.

Reparto: por lista (partido o federación), no por família — ver reparto.py.
Validación: con los votos reales de 2022 el reparto reproduce las bancas
reales con 6 de 513 de error a nivel família (se recalcula en cada corrida).

Limitaciones (quedan en el meta.json de cada corrida):
  - Partidos nuevos (ej. MISSÃO) no tienen votos en la base.
  - Listas que en 2026 no compiten en una UF conservan su voto 2022 ahí.
  - Volatilidad estimada con una sola diferencia entre elecciones.

Salidas versionadas en data/processed/legislativo/camara/<fecha_utc>/:
  bancas_familia_simulacion.parquet   simulación × família (total nacional)
  bancas_uf_familia_simulacion.parquet simulación × UF × família
  resumen.csv                          media, p10, mediana, p90 por família
  meta.json                            parámetros, semilla, insumos (sha256), validación
Y copia de resumen.csv en data/processed/legislativo/resumen_bancas_camara.csv.

Uso:
    python -m src.models.montecarlo.proyeccion_bancas [--sin-nacional] [--n-sim 2000]
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
import yaml

from src.etl.extract.tse_extractor import ultima_version
from src.etl.extract.versionado import sha256
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import (
    familia, normalizar_sigla, sigla_sucesora, tabla_ano,
)
from src.models.montecarlo.reparto import repartir

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_MODELO = ROOT / "config" / "modelo.yaml"
CONFIG_PARTIDOS = ROOT / "config" / "partidos.yaml"
ELECTORAL_DIR = ROOT / "data" / "processed" / "electoral"
LEGISLATIVO_DIR = ROOT / "data" / "processed" / "legislativo"

BLOQUE_SIMULACIONES = 2000  # limita memoria del reparto vectorizado


def cargar_config() -> dict:
    with open(CONFIG_MODELO, encoding="utf-8") as f:
        return yaml.safe_load(f)


def lista_de_partido(ano: int) -> dict[str, str]:
    """Partido -> lista (nombre de federación, o el propio partido) para un año."""
    with open(CONFIG_PARTIDOS, encoding="utf-8") as f:
        feds = yaml.safe_load(f)["federaciones"].get(ano, {})
    return {normalizar_sigla(p): nombre for nombre, partidos in feds.items() for p in partidos}


def bancas_por_uf(ano: int) -> dict[str, int]:
    vagas = leer_zip_tse(ultima_version("vagas", ano), columnas=["SG_UF", "QT_VAGA"],
                         filtro={"NM_TIPO_ELEICAO": {"Eleição Ordinária"}, "DS_CARGO": {"DEPUTADO FEDERAL"}})
    b = pd.to_numeric(vagas["QT_VAGA"]).groupby(vagas["SG_UF"]).sum().astype(int)
    if b.sum() != 513 or len(b) != 27:
        raise ValueError(f"vagas {ano}: {b.sum()} bancas en {len(b)} UF")
    return b.to_dict()


# ---------------------------------------------------------------- base

def construir_base(ano_base: int, ano_objetivo: int) -> pd.DataFrame:
    """Votos ano_base por UF agregados en listas y famílias de ano_objetivo."""
    estado, _ = tabla_ano(ano_objetivo)
    if estado != "vigente":
        raise ValueError(f"La clasificación {ano_objetivo} no está vigente")
    path = ELECTORAL_DIR / f"camara_partido_uf_{ano_base}.parquet"
    d = pd.read_parquet(path)
    listas = lista_de_partido(ano_objetivo)
    d["partido_objetivo"] = [sigla_sucesora(p, ano_base, ano_objetivo) for p in d["partido"]]
    d["familia"] = [familia(p, ano_objetivo) for p in d["partido_objetivo"]]
    d["lista"] = d["partido_objetivo"].map(lambda p: listas.get(p, p))

    mezcla = d.groupby("lista")["familia"].nunique()
    if (mezcla > 1).any():
        raise ValueError(f"Listas {ano_objetivo} con partidos de famílias distintas: {list(mezcla[mezcla > 1].index)}")

    base = d.groupby(["uf", "lista", "familia"], as_index=False)["votos"].sum()
    base["pct"] = base["votos"] / base.groupby("uf")["votos"].transform("sum")
    return base


def cargar_ruido(fuente: str, componente_nacional: bool) -> pd.DataFrame:
    vol = pd.read_parquet(ELECTORAL_DIR / "volatilidad_familias.parquet")
    vol = vol[vol["composicion"] == fuente].set_index("familia")
    if vol.empty:
        raise ValueError(f"No hay volatilidad con composicion={fuente}")
    return pd.DataFrame({
        "sigma_uf_pp": vol["volatilidad_pp"],
        "sigma_nacional_pp": vol["cambio_medio_pp"].abs() if componente_nacional else 0.0,
    })


# ---------------------------------------------------------------- simulación

def simular(base: pd.DataFrame, bancas: dict[str, int], ruido: pd.DataFrame,
            n_sim: int, seed: int, umbral: float) -> pd.DataFrame:
    familias = sorted(base["familia"].unique())
    faltan = set(familias) - set(ruido.index)
    if faltan:
        raise ValueError(f"Sin volatilidad para: {faltan}")
    sig_uf = ruido.loc[familias, "sigma_uf_pp"].to_numpy() / 100
    sig_nac = ruido.loc[familias, "sigma_nacional_pp"].to_numpy() / 100

    rng = np.random.default_rng(seed)
    ufs = sorted(bancas)
    # Todos los shocks se sortean de una vez y en orden fijo: reproducible con la semilla
    shock_nac = rng.normal(0, 1, (n_sim, len(familias))) * sig_nac
    shock_uf = rng.normal(0, 1, (len(ufs), n_sim, len(familias))) * sig_uf

    salida = []
    for i_uf, uf in enumerate(ufs):
        g = base[base["uf"] == uf]
        p = g["pct"].to_numpy()
        fam_idx = np.array([familias.index(f) for f in g["familia"]])
        fam_base = np.bincount(fam_idx, weights=p, minlength=len(familias))

        fam_sim = np.clip(fam_base + shock_nac + shock_uf[i_uf], 0, None)
        fam_sim[:, fam_base == 0] = 0  # una família sin votos en la UF no aparece por ruido
        factor = np.divide(fam_sim, fam_base, out=np.zeros_like(fam_sim), where=fam_base > 0)
        listas_sim = p[None, :] * factor[:, fam_idx]
        listas_sim /= listas_sim.sum(axis=1, keepdims=True)

        res = np.vstack([repartir(listas_sim[i:i + BLOQUE_SIMULACIONES], bancas[uf], umbral)
                         for i in range(0, n_sim, BLOQUE_SIMULACIONES)])
        por_fam = np.zeros((n_sim, len(familias)), dtype=int)
        for j in range(len(familias)):
            por_fam[:, j] = res[:, fam_idx == j].sum(axis=1)
        salida.append(pd.DataFrame({
            "simulacion": np.repeat(np.arange(n_sim), len(familias)),
            "uf": uf,
            "familia": np.tile(familias, n_sim),
            "bancas": por_fam.ravel(),
        }))
    return pd.concat(salida, ignore_index=True)


def bancas_base(base: pd.DataFrame, bancas: dict[str, int], umbral: float) -> pd.Series:
    """Bancas por família con la base sin ruido (referencia determinística)."""
    filas = []
    for uf, g in base.groupby("uf"):
        res = repartir(g["pct"].to_numpy()[None, :], bancas[uf], umbral)[0]
        filas.append(pd.Series(res, index=g["familia"].to_numpy()).groupby(level=0).sum())
    return pd.concat(filas).groupby(level=0).sum()


def validar_reparto(ano: int, umbral: float) -> dict:
    """Reparte los votos reales de `ano` con sus listas reales y compara con las bancas reales."""
    d = pd.read_parquet(ELECTORAL_DIR / f"camara_partido_uf_{ano}.parquet")
    listas = lista_de_partido(ano)
    d["lista"] = d["partido"].map(lambda p: listas.get(p, p))
    filas = []
    for uf, g in d.groupby("uf"):
        lv = g.groupby("lista").agg(votos=("votos", "sum"), real=("bancas", "sum"),
                                    familia=("familia", "first"))
        lv["modelo"] = repartir(lv["votos"].to_numpy()[None, :], int(lv["real"].sum()), umbral)[0]
        filas.append(lv)
    r = pd.concat(filas)
    fam = r.groupby("familia")[["modelo", "real"]].sum()
    return {
        "ano": ano,
        "bancas_distinta_lista": int((r["modelo"] - r["real"]).abs().sum() // 2),
        "error_absoluto_familias": int((fam["modelo"] - fam["real"]).abs().sum()),
        "por_familia": {f: {"modelo": int(x.modelo), "real": int(x.real)} for f, x in fam.iterrows()},
    }


def resumir(sims: pd.DataFrame, base_det: pd.Series) -> pd.DataFrame:
    tot = sims.groupby(["simulacion", "familia"])["bancas"].sum().unstack(fill_value=0)
    r = pd.DataFrame({
        "bancas_base_sin_ruido": base_det.reindex(tot.columns).fillna(0).astype(int),
        "media": tot.mean().round(1),
        "p10": tot.quantile(0.10),
        "mediana": tot.median(),
        "p90": tot.quantile(0.90),
    })
    return r.sort_values("media", ascending=False).rename_axis("familia").reset_index()


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-nacional", action="store_true", help="sin shock nacional (comparación)")
    parser.add_argument("--n-sim", type=int, help="sobrescribe n_simulaciones de config/modelo.yaml")
    args = parser.parse_args(argv)

    cfg = cargar_config()
    c = cfg["camara"]
    n_sim = args.n_sim or cfg["simulacion"]["n_simulaciones"]
    seed = cfg["simulacion"]["random_seed"]
    nacional = c["ruido"]["componente_nacional"] and not args.sin_nacional

    base = construir_base(c["ano_base"], c["ano_objetivo"])
    bancas = bancas_por_uf(c["ano_objetivo"])
    ruido = cargar_ruido(c["ruido"]["fuente_volatilidad"], nacional)
    validacion = validar_reparto(c["ano_base"], c["umbral_cociente"])
    log.info("Validación del reparto con %d: %d bancas en otra lista, error por família %d",
             validacion["ano"], validacion["bancas_distinta_lista"], validacion["error_absoluto_familias"])

    sims = simular(base, bancas, ruido, n_sim, seed, c["umbral_cociente"])
    base_det = bancas_base(base, bancas, c["umbral_cociente"])
    resumen = resumir(sims, base_det)

    ahora = datetime.now(timezone.utc)
    out = LEGISLATIVO_DIR / "camara" / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    tot = sims.groupby(["simulacion", "familia"], as_index=False)["bancas"].sum()
    tot.to_parquet(out / "bancas_familia_simulacion.parquet", index=False)
    sims.to_parquet(out / "bancas_uf_familia_simulacion.parquet", index=False)
    resumen.to_csv(out / "resumen.csv", index=False)

    insumos = [ELECTORAL_DIR / f"camara_partido_uf_{c['ano_base']}.parquet",
               ELECTORAL_DIR / "volatilidad_familias.parquet",
               ultima_version("vagas", c["ano_objetivo"]), CONFIG_MODELO, CONFIG_PARTIDOS,
               ROOT / "config" / "familias_partidarias.yaml"]
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "random_seed": seed,
        "n_simulaciones": n_sim,
        "fecha_corte_encuestas": None,
        "base": f"resultado Câmara {c['ano_base']} en partidos/listas/famílias {c['ano_objetivo']} (sin encuestas)",
        "ruido": {"fuente_volatilidad": c["ruido"]["fuente_volatilidad"], "componente_nacional": nacional,
                  "sigma_pp": ruido.round(3).to_dict(orient="index")},
        "umbral_cociente": c["umbral_cociente"],
        "validacion_reparto": validacion,
        "limitaciones": [
            "Partidos nuevos (ej. MISSÃO) no tienen votos en la base.",
            "Listas que no compiten en 2026 en una UF conservan su voto 2022 ahí.",
            "Volatilidad estimada con una sola diferencia entre elecciones (2018->2022).",
            "El shock nacional usa el cambio medio 2018->2022 de cada família: una observación.",
            "No se modela el piso individual de 20% del cociente por candidato.",
        ],
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in insumos},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(out / "resumen.csv", LEGISLATIVO_DIR / "resumen_bancas_camara.csv")

    log.info("Câmara 2026 — %d simulaciones, semilla %d, shock nacional: %s\n%s",
             n_sim, seed, "sí" if nacional else "no", resumen.to_string(index=False))
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
