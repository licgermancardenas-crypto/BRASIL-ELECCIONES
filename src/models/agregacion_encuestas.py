"""
src/models/agregacion_encuestas.py

Fase 4 — agregación de encuestas presidenciales (1ª vuelta y cruces de 2ª),
nacional. Input: data/processed/electoral/encuestas_resultados.parquet
(src/etl/transform/encuestas_resultados.py). Parámetros: config/modelo.yaml,
sección `encuestas`.

Todo se trabaja en VOTOS VÁLIDOS (lo que define la elección): cada encuesta
se lleva a % sobre la suma de candidatos + otros, sin blancos/nulos/indecisos.

1. Track record (2018/2022): error de cada casa contra el resultado TSE en
   la última semana (`ventana_final_dias`), sobre los 2 candidatos más
   votados. Una observación por casa × elección × vuelta (las encuestas de
   una misma casa en la misma semana no son independientes). El error
   cuadrático de cada casa se encoge hacia el de la industria con
   `shrink_track_record` pseudo-elecciones; peso de calidad =
   error² industria / error² casa. Casas sin historia o con
   `continuidad_historica: pendiente` en config/encuestadoras.yaml: peso 1.
2. House effect (dentro del ciclo): residuo de cada encuesta contra la
   tendencia de las DEMÁS casas (núcleo exponencial en el tiempo), promedio
   por casa con `shrink_house_effect` pseudo-encuestas en 0, anclado para que
   el promedio ponderado por calidad sea 0. Se corrige ANTES de promediar.
3. Promedio: peso = calidad × min(muestra, tope)/tope × 0,5^(días/vida_media).

Backtest (Fase 6): el mismo procedimiento sobre 2018 y 2022 con corte la
víspera de cada vuelta y track record solo de elecciones anteriores, contra
el resultado real y contra el error medio de las encuestas individuales.
El error del agregador en el backtest es la incertidumbre sistemática que
usa el Montecarlo (src/models/montecarlo/proyeccion_presidencial_encuestas.py).

Salidas en data/processed/electoral/encuestas_agregadas/<fecha_utc>/:
  agregado.csv, house_effects.csv, track_record.csv, backtest.csv,
  ponderacion.csv, meta.json
y la última estimación en data/processed/electoral/intencion_voto_presidencial.parquet.

Uso:
    python -m src.models.agregacion_encuestas [--corte 2026-10-03]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.etl.extract.tse_extractor import ultima_version
from src.etl.extract.versionado import sha256
from src.etl.extract.wikipedia_extractor import ultima_version as ultima_wikipedia
from src.etl.transform.encuestas_resultados import CONFIG_CASAS, CONFIG_TABLAS, SALIDA as ENCUESTAS
from src.etl.transform.lector_tse import leer_zip_tse
from src.models.bloques.resolver_familia import normalizar_sigla
from src.models.montecarlo.proyeccion_bancas import CONFIG_MODELO, ELECTORAL_DIR, ROOT, cargar_config
from src.models.montecarlo.proyeccion_presidencial import FILTRO_PRES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "encuestas_agregadas"
SALIDA_ULTIMA = ELECTORAL_DIR / "intencion_voto_presidencial.parquet"
CACHE_RESULTADOS = ELECTORAL_DIR / "resultado_presidencial_nacional.parquet"
COLS_META = ["ano", "vuelta", "id_encuesta", "escenario", "antes_primera_vuelta", "casa",
             "encuestadora_wiki", "fecha_fin", "muestra"]


def config_tablas() -> dict:
    with open(CONFIG_TABLAS, encoding="utf-8") as f:
        return yaml.safe_load(f)


def fechas_eleccion(ano: int) -> dict[int, date]:
    return {int(v): pd.Timestamp(f).date() for v, f in config_tablas()["anos"][ano]["eleccion"].items()}


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def a_validos(largo: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(meta por encuesta, % válidos por candidato) para filas de un mismo escenario."""
    meta = largo.drop_duplicates("id_encuesta").set_index("id_encuesta")[COLS_META[:2] + COLS_META[3:]]
    pct = largo.pivot_table(index="id_encuesta", columns="candidato", values="pct", aggfunc="first")
    pct = pct.fillna(0.0)
    validos = pct.div(pct.sum(axis=1), axis=0)
    return meta.loc[validos.index], validos


def resultado_nacional(ano: int) -> pd.DataFrame:
    """% de votos válidos por candidato (ids de config/encuestas_wikipedia.yaml) y vuelta, del TSE.
    Se cachea en processed/ con el sha256 del zip de resultados que lo generó."""
    ruta = ultima_version("resultados", ano)
    digest = sha256(ruta)
    if CACHE_RESULTADOS.exists():
        cache = pd.read_parquet(CACHE_RESULTADOS)
        previo = cache[(cache["ano"] == ano) & (cache["insumo_sha256"] == digest)]
        if not previo.empty:
            return previo.drop(columns="insumo_sha256").reset_index(drop=True)
    else:
        cache = pd.DataFrame()

    cand = config_tablas()["anos"][ano]["candidatos"]
    por_partido = {normalizar_sigla(c["partido"]): c["id"] for c in cand.values()}
    d = leer_zip_tse(ruta, columnas=["NR_TURNO", "SG_PARTIDO", "QT_VOTOS_NOMINAIS_VALIDOS"], filtro=FILTRO_PRES)
    d["votos"] = pd.to_numeric(d["QT_VOTOS_NOMINAIS_VALIDOS"])
    d["candidato"] = [por_partido.get(normalizar_sigla(p), "otros") for p in d["SG_PARTIDO"]]
    r = d.groupby([d["NR_TURNO"].astype(int).rename("vuelta"), "candidato"])["votos"].sum().reset_index()
    r["pct"] = r["votos"] / r.groupby("vuelta")["votos"].transform("sum")
    r.insert(0, "ano", ano)
    nuevo = pd.concat([cache[cache["ano"] != ano] if not cache.empty else cache,
                       r.assign(insumo_sha256=digest)], ignore_index=True)
    nuevo.to_parquet(CACHE_RESULTADOS, index=False)
    return r


def casas_sin_continuidad() -> set[str]:
    with open(CONFIG_CASAS, encoding="utf-8") as f:
        casas = yaml.safe_load(f)["casas"]
    return {c for c, cfg in casas.items() if cfg.get("continuidad_historica") != "confirmada"}


def escenario_principal(largo: pd.DataFrame, ano: int, vuelta: int, finalistas: list[str] | None = None) -> pd.DataFrame:
    """Filas del escenario a agregar: en 1ª vuelta el más frecuente; en 2ª el cruce de `finalistas`."""
    d = largo[(largo["ano"] == ano) & (largo["vuelta"] == vuelta)]
    if vuelta == 2:
        return d[d["escenario"] == "|".join(sorted(finalistas))]
    return d[d["escenario"] == d.groupby("escenario")["id_encuesta"].nunique().idxmax()]


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------

def errores_finales(largo: pd.DataFrame, ano: int, ventana: int) -> pd.DataFrame:
    """Error (pp de válidos) de cada casa en la última semana, por vuelta, sobre los 2 más votados.
    Una fila por casa × vuelta × candidato (promedio de sus encuestas en la ventana)."""
    res = resultado_nacional(ano)
    fechas = fechas_eleccion(ano)
    filas = []
    for vuelta in (1, 2):
        r = res[(res["vuelta"] == vuelta) & (res["candidato"] != "otros")].nlargest(2, "pct")
        top2 = r["candidato"].tolist()
        d = escenario_principal(largo, ano, vuelta, top2)
        if vuelta == 2:
            d = d[~d["antes_primera_vuelta"]]
        if d.empty:
            continue
        meta, val = a_validos(d)
        en_ventana = meta["fecha_fin"].dt.date >= fechas[vuelta] - timedelta(days=ventana)
        err = val.loc[en_ventana, top2].sub(r.set_index("candidato")["pct"][top2], axis=1)
        err["casa"] = meta.loc[en_ventana, "casa"]
        por_casa = err.groupby("casa").agg(["mean", "size"])
        for casa, fila in por_casa.iterrows():
            for c in top2:
                filas.append({"ano": ano, "vuelta": vuelta, "casa": casa, "candidato": c,
                              "error": fila[(c, "mean")], "n_encuestas": int(fila[(c, "size")])})
    return pd.DataFrame(filas)


def track_record(errores: pd.DataFrame, k: float) -> tuple[pd.DataFrame, float]:
    """Peso de calidad por casa. Devuelve (tabla, error² medio de la industria)."""
    if errores.empty:
        return pd.DataFrame(columns=["casa", "elecciones", "rmse_pp", "peso_calidad"]), float("nan")
    excluir = casas_sin_continuidad()
    e = errores[~errores["casa"].isin(excluir)]
    # Una observación por casa × elección × vuelta: error² medio de sus 2 candidatos
    obs = e.groupby(["casa", "ano", "vuelta"])["error"].apply(lambda s: float((s ** 2).mean())).reset_index()
    industria = float(obs["error"].mean())
    t = obs.groupby("casa")["error"].agg(["sum", "size"])
    s2 = (k * industria + t["sum"]) / (k + t["size"])
    tabla = pd.DataFrame({"elecciones": t["size"], "rmse_pp": np.sqrt(t["sum"] / t["size"]) * 100,
                          "rmse_encogido_pp": np.sqrt(s2) * 100, "peso_calidad": industria / s2})
    return tabla.reset_index(), industria


# ---------------------------------------------------------------------------
# Agregación
# ---------------------------------------------------------------------------

def agregar(meta: pd.DataFrame, val: pd.DataFrame, corte: date, pesos_calidad: dict[str, float],
            cfg: dict) -> dict:
    """Estimación en `corte` (% válidos por candidato) con house effects y decaimiento."""
    dias = (pd.Timestamp(corte) - meta["fecha_fin"]).dt.days
    dentro = (dias >= 0) & (dias <= cfg["ventana_campana_dias"])
    meta, val, dias = meta[dentro], val[dentro], dias[dentro].to_numpy(float)
    if meta.empty:
        raise ValueError(f"Sin encuestas en los {cfg['ventana_campana_dias']} días previos a {corte}")

    casas = meta["casa"].to_numpy()
    calidad = np.array([pesos_calidad.get(c, 1.0) for c in casas])
    n = meta["muestra"].astype(float).fillna(cfg["muestra_tope"]).to_numpy()
    tamano = np.minimum(n, cfg["muestra_tope"]) / cfg["muestra_tope"]
    base = calidad * tamano
    h = cfg["vida_media_dias"]
    nucleo = 0.5 ** (np.abs(dias[:, None] - dias[None, :]) / h)
    otra_casa = casas[:, None] != casas[None, :]
    k_tend = nucleo * otra_casa * base[None, :]

    S = val.to_numpy()
    unicas = pd.unique(casas)
    he = pd.DataFrame(0.0, index=unicas, columns=val.columns)
    for _ in range(cfg["iteraciones_house_effect"]):
        corregido = S - he.loc[casas].to_numpy()
        suma_k = k_tend.sum(axis=1, keepdims=True)
        # una casa sola en la ventana no tiene contra quién compararse: residuo 0
        tendencia = np.where(suma_k > 0, (k_tend @ corregido) / np.where(suma_k > 0, suma_k, 1), S)
        resid = pd.DataFrame(S - tendencia, columns=val.columns)
        resid["casa"] = casas
        g = resid.groupby("casa")
        nuevo = g.sum() / (g.size().to_numpy()[:, None] + cfg["shrink_house_effect"])
        ancla_w = pd.Series({c: pesos_calidad.get(c, 1.0) * (casas == c).sum() for c in nuevo.index})
        nuevo = nuevo - (nuevo.mul(ancla_w, axis=0).sum() / ancla_w.sum())
        he = nuevo.loc[unicas]

    corregido = S - he.loc[casas].to_numpy()
    w = base * 0.5 ** (dias / h)
    est = (w[:, None] * corregido).sum(axis=0) / w.sum()
    est = np.clip(est, 0, None)
    est = est / est.sum()
    sin_corr = (w[:, None] * S).sum(axis=0) / w.sum()
    simple = S.mean(axis=0)
    pond = meta[["casa", "encuestadora_wiki", "fecha_fin", "muestra"]].assign(
        dias=dias, peso_calidad=calidad, peso=w / w.sum())
    return {
        "estimacion": pd.Series(est, index=val.columns),
        "sin_house_effect": pd.Series(sin_corr / sin_corr.sum(), index=val.columns),
        "promedio_simple": pd.Series(simple / simple.sum(), index=val.columns),
        "house_effects": he.assign(n_encuestas=pd.Series(casas).value_counts()),
        "ponderacion": pond,
        "n_encuestas": int(len(meta)),
        "n_efectivo": float(w.sum() ** 2 / (w ** 2).sum()),
    }


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(largo: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Agregador vs resultado en cada elección histórica (track record solo con años anteriores)."""
    filas = []
    for ano in cfg["anos_historicos"]:
        previos = [a for a in cfg["anos_historicos"] if a < ano]
        errs = pd.concat([errores_finales(largo, a, cfg["ventana_final_dias"]) for a in previos]) if previos else pd.DataFrame()
        tr, _ = track_record(errs, cfg["shrink_track_record"])
        pesos = dict(zip(tr["casa"], tr["peso_calidad"]))
        res = resultado_nacional(ano)
        fechas = fechas_eleccion(ano)
        for vuelta, antes, corte in [(1, True, fechas[1] - timedelta(days=1)),
                                     (2, True, fechas[1] - timedelta(days=1)),
                                     (2, False, fechas[2] - timedelta(days=1))]:
            r = res[(res["vuelta"] == vuelta) & (res["candidato"] != "otros")].set_index("candidato")["pct"]
            top2 = r.nlargest(2).index.tolist()
            d = escenario_principal(largo, ano, vuelta, top2)
            d = d[d["antes_primera_vuelta"] == antes]
            if d.empty:
                continue
            meta, val = a_validos(d)
            a = agregar(meta, val, corte, pesos, cfg)
            # encuestas individuales de la última semana antes del corte
            ult = (pd.Timestamp(corte) - meta["fecha_fin"]).dt.days.between(0, cfg["ventana_final_dias"])
            indiv = (val.loc[ult, top2] - r[top2]).abs().mean(axis=1)
            for c in val.columns:
                real = float(r.get(c, res[(res["vuelta"] == vuelta) & (res["candidato"] == c)]["pct"].sum()))
                filas.append({
                    "ano": ano, "vuelta": vuelta, "cruce_antes_1v": vuelta == 2 and antes,
                    "corte": corte, "candidato": c, "top2": c in top2, "real_pct": real * 100,
                    "agregado_pct": a["estimacion"][c] * 100,
                    "error_agregado_pp": (a["estimacion"][c] - real) * 100,
                    "error_sin_house_effect_pp": (a["sin_house_effect"][c] - real) * 100,
                    "error_promedio_simple_pp": (a["promedio_simple"][c] - real) * 100,
                    "mae_encuestas_individuales_top2_pp": float(indiv.mean() * 100) if len(indiv) else np.nan,
                    "n_encuestas": a["n_encuestas"], "track_record_de": ",".join(map(str, previos)) or "ninguno",
                })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corte", type=date.fromisoformat,
                        help="fecha de corte (default: hoy, sin pasar de la víspera de la 1ª vuelta)")
    args = parser.parse_args(argv)

    cfg = cargar_config()["encuestas"]
    ano = cfg["ano_objetivo"]
    largo = pd.read_parquet(ENCUESTAS)
    fechas = fechas_eleccion(ano)
    corte = args.corte or min(date.today(), fechas[1] - timedelta(days=1))

    errs = pd.concat([errores_finales(largo, a, cfg["ventana_final_dias"]) for a in cfg["anos_historicos"]])
    tr, industria = track_record(errs, cfg["shrink_track_record"])
    pesos = dict(zip(tr["casa"], tr["peso_calidad"]))
    log.info("Track record (%s): error medio industria %.2f pp; %d casas con historia",
             cfg["anos_historicos"], np.sqrt(industria) * 100, len(tr))

    bt = backtest(largo, cfg)
    t2 = bt[bt["top2"]]
    log.info("Backtest (top-2, |error| medio en pp):\n%s", t2.groupby(["ano", "vuelta", "cruce_antes_1v"])[
        ["error_agregado_pp", "error_sin_house_effect_pp", "error_promedio_simple_pp"]].apply(
        lambda x: x.abs().mean()).join(t2.groupby(["ano", "vuelta", "cruce_antes_1v"])[
            "mae_encuestas_individuales_top2_pp"].first()).round(2).to_string())

    salidas, hes, ponds = [], [], []
    for vuelta in (1, 2):
        d_v = largo[(largo["ano"] == ano) & (largo["vuelta"] == vuelta)]
        escenarios = ([escenario_principal(largo, ano, 1)["escenario"].iloc[0]] if vuelta == 1
                      else sorted(d_v["escenario"].unique()))
        for esc in escenarios:
            meta, val = a_validos(d_v[d_v["escenario"] == esc])
            try:
                a = agregar(meta, val, corte, pesos, cfg)
            except ValueError as e:
                log.warning("%s vuelta %d: %s", esc, vuelta, e)
                continue
            for c in val.columns:
                salidas.append({"ano": ano, "vuelta": vuelta, "escenario": esc, "candidato": c, "corte": corte,
                                "pct_validos": a["estimacion"][c] * 100,
                                "pct_sin_house_effect": a["sin_house_effect"][c] * 100,
                                "pct_promedio_simple": a["promedio_simple"][c] * 100,
                                "n_encuestas": a["n_encuestas"], "n_efectivo": round(a["n_efectivo"], 1)})
            hes.append(a["house_effects"].mul(100).round(2).assign(
                n_encuestas=a["house_effects"]["n_encuestas"], vuelta=vuelta, escenario=esc))
            ponds.append(a["ponderacion"].assign(vuelta=vuelta, escenario=esc))
    agregado = pd.DataFrame(salidas)

    ahora = datetime.now(timezone.utc)
    out = SALIDA_DIR / ahora.strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True)
    agregado.round(2).to_csv(out / "agregado.csv", index=False)
    pd.concat(hes).rename_axis("casa").reset_index().to_csv(out / "house_effects.csv", index=False)
    tr.round(3).to_csv(out / "track_record.csv", index=False)
    bt.round(3).to_csv(out / "backtest.csv", index=False)
    pd.concat(ponds).to_csv(out / "ponderacion.csv", index=False)
    agregado.to_parquet(SALIDA_ULTIMA, index=False)

    manifests = {a: json.loads((ultima_wikipedia(a).parent / "manifest.json").read_text(encoding="utf-8"))
                 for a in cfg["anos_historicos"] + [ano]}
    meta = {
        "corrida_utc": ahora.isoformat(timespec="seconds"),
        "fecha_corte_encuestas": corte.isoformat(),
        "parametros": cfg,
        "fuente": "Wikipedia (en), resultados publicados de encuestas; revisión por año",
        "revid_wikipedia": {a: m["revid"] for a, m in manifests.items()},
        "error_medio_industria_pp": round(float(np.sqrt(industria) * 100), 2),
        "casas_sin_continuidad_historica": sorted(casas_sin_continuidad()),
        "insumos_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in
                           [ENCUESTAS, CONFIG_MODELO, CONFIG_TABLAS, CONFIG_CASAS]},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    log.info("Agregado %d al %s (%% votos válidos):\n%s", ano, corte,
             agregado.pivot_table(index="candidato", columns="escenario", values="pct_validos").round(1).to_string())
    log.info("Corrida guardada en %s", out.relative_to(ROOT).as_posix())
    return out


if __name__ == "__main__":
    main()
