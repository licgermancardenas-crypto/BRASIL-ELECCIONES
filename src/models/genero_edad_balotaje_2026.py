"""
src/models/genero_edad_balotaje_2026.py

Sexo y edad en el balotaje del 25/10/2026. El voto es secreto: no hay votos
oficiales por sexo o edad. Se combinan tres fuentes, cada una con su alcance:

  1. Padrón del TSE (perfil_eleitorado 2022 y 2026): cuántos electores hay de
     cada sexo y edad, y cómo cambió el padrón.
  2. Comparecencia oficial por perfil (perfil_comparecimento_abstencao): quién
     fue a votar en la 1ª y la 2ª vuelta de 2022 y en la 1ª de 2026, por sexo y
     edad. Es un dato oficial, no una estimación.
  3. Encuestas con cortes por sexo y edad (config/encuestas_segmentos_2026.yaml),
     como CONTROL, igual que las encuestas generales (decisión del 2026-10-07).

Y una estimación ecológica por município (Goodman con efectos fijos de UF): el
voto de Lula según la composición por sexo y edad de los que fueron a votar,
probada primero contra el balotaje de 2022 y la encuesta Datafolha de ese año.
Describe territorios, no personas: con la poca variación del % de mujeres entre
municípios, la brecha de género ecológica tiene un error grande y se reporta así.

Escenarios: cuánto movería el resultado que la participación por sexo y edad
cambie entre vueltas como en 2022, con las preferencias de las encuestas.

Salida: data/processed/electoral/genero_edad_balotaje_2026/<fecha_utc>/
    resumen.json, padron.csv, comparecencia.csv, encuestas.csv, municipios.parquet

Uso:
    python -m src.models.genero_edad_balotaje_2026
"""
from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml

from src.etl.extract.versionado import ultima_version_en
from src.etl.transform.base_locales import salida as salida_locales
from src.etl.transform.correspondencia_municipios import cargar as cargar_correspondencia
from src.models.conteo_2026 import SALIDA_FINAL as RESULTADO_2026
from src.models.montecarlo.proyeccion_bancas import ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RAW = ROOT / "data" / "raw" / "tse"
SALIDA_DIR = ROOT / "data" / "processed" / "electoral" / "genero_edad_balotaje_2026"
CFG_ENCUESTAS = ROOT / "config" / "encuestas_segmentos_2026.yaml"
# Boa Esperança do Norte (MT) se creó en 2023: no está en la correspondencia 2018/2022.
# Su código TSE (73709) sale del padrón 2026 (NM_MUNICIPIO "BOA ESPERANÇA DO NORTE", MT).
TSE_FALTANTES = {"73709": 5101837}
EDADES = ["16-24", "25-34", "35-44", "45-59", "60+"]
GRUPOS = ["mujeres", "hombres"] + [f"e_{e.replace('-', '_').replace('+', '')}" for e in EDADES]
NOMBRE_GRUPO = {"mujeres": "Mujeres", "hombres": "Hombres", "e_16_24": "16 a 24", "e_25_34": "25 a 34",
                "e_35_44": "35 a 44", "e_45_59": "45 a 59", "e_60": "60 o más"}


def banda(cd_faixa: pd.Series) -> pd.Series:
    """Código de faixa etária del TSE (1600, 2124, 6064, ...) -> banda de edad."""
    desde = pd.to_numeric(cd_faixa, errors="coerce") // 100
    return pd.cut(desde, [15, 24, 34, 44, 59, 200], labels=EDADES).astype(object)


def zip_ultimo(carpeta: str, ano: int) -> Path:
    try:
        return ultima_version_en(RAW / carpeta / str(ano))
    except FileNotFoundError as e:
        raise FileNotFoundError(f"{e}: python -m src.etl.extract.tse_extractor --dataset {carpeta} --ano {ano}") from e


def leer_por_uf(path: Path, cols: list[str], valor: list[str]) -> pd.DataFrame:
    """Lee los CSV por UF de un zip del TSE (sin el _BRASIL ni el exterior) y agrega por `cols`.
    El agregado se guarda junto al zip (versión inmutable), así la 2ª corrida no relee 600 MB."""
    cache = path.with_name(path.stem + "_agregado_genero_edad.parquet")
    if cache.exists():
        return pd.read_parquet(cache)
    out = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if not n.endswith(".csv") or n.endswith(("_BRASIL.csv", "_BR.csv", "_ZZ.csv")):
                continue
            # por bloques: el CSV de SP de comparecencia pasa los 5 M de filas
            for d in pd.read_csv(z.open(n), sep=";", encoding="latin1", usecols=cols + valor, dtype=str,
                                 chunksize=500_000):
                for v in valor:
                    d[v] = pd.to_numeric(d[v], errors="coerce").fillna(0)
                out.append(d.groupby(cols, as_index=False)[valor].sum())
    d = pd.concat(out, ignore_index=True).groupby(cols, as_index=False)[valor].sum()
    d.to_parquet(cache)
    return d


def con_ibge(d: pd.DataFrame) -> pd.DataFrame:
    tabla = cargar_correspondencia().set_index("codigo_tse")["codigo_ibge"].astype(float)
    cod = d["CD_MUNICIPIO"].astype(str).str.zfill(5)
    ibge = cod.map(tabla).fillna(cod.map(TSE_FALTANTES))
    if ibge.isna().any():
        raise KeyError(f"códigos TSE sin IBGE: {sorted(cod[ibge.isna()].unique())[:10]}")
    return d.assign(codigo=ibge.astype(int))


def normalizar(d: pd.DataFrame) -> pd.DataFrame:
    d = d.assign(genero=d["DS_GENERO"].str.upper().map({"FEMININO": "mujeres", "MASCULINO": "hombres"}),
                 edad=banda(d["CD_FAIXA_ETARIA"]),
                 superior=d["DS_GRAU_ESCOLARIDADE"].str.upper().str.startswith("SUPERIOR"))
    return d


# ---------------------------------------------------------------------------
# 1 · Padrón
# ---------------------------------------------------------------------------

def padron(ano: int) -> pd.DataFrame:
    cols = ["SG_UF", "CD_MUNICIPIO", "DS_GENERO", "CD_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE"]
    return normalizar(con_ibge(leer_por_uf(zip_ultimo("padron", ano), cols, ["QT_ELEITORES"])))


def composicion(d: pd.DataFrame, q: str) -> dict:
    t = d[q].sum()
    out = {g: float(d.loc[d["genero"] == g, q].sum() / t) for g in ("mujeres", "hombres")}
    out.update({e: float(d.loc[d["edad"] == e, q].sum() / t) for e in EDADES})
    out["superior"] = float(d.loc[d["superior"], q].sum() / t)
    out["total"] = float(t)
    return out


# ---------------------------------------------------------------------------
# 2 · Comparecencia oficial por perfil
# ---------------------------------------------------------------------------

def comparecencia(ano: int) -> pd.DataFrame:
    path = zip_ultimo("comparecencia_perfil", ano)
    with zipfile.ZipFile(path) as z:
        n = next(x for x in z.namelist() if x.endswith(".csv") and "_ZZ" not in x)
        cab = pd.read_csv(z.open(n), sep=";", encoding="latin1", nrows=0).columns
    apt = next(c for c in ("QT_APTOS", "QT_ELEITORES_PERFIL", "QT_ELEITORES") if c in cab)
    com = next(c for c in ("QT_COMPARECIMENTO", "QT_COMPARECIMENTOS") if c in cab)
    cols = ["SG_UF", "CD_MUNICIPIO", "NR_TURNO", "DS_GENERO", "CD_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE"]
    d = leer_por_uf(path, cols, [apt, com]).rename(columns={apt: "aptos", com: "comparecencia"})
    d["turno"] = d.pop("NR_TURNO").astype(int)
    return normalizar(con_ibge(d))


def tasas(d: pd.DataFrame) -> pd.DataFrame:
    """Participación nacional por grupo y turno."""
    filas = []
    for turno, g in d.groupby("turno"):
        for col, cats in (("genero", ("mujeres", "hombres")), ("edad", EDADES)):
            for c in cats:
                s = g[g[col] == c]
                filas.append({"turno": turno, "grupo": c, "aptos": s["aptos"].sum(),
                              "comparecencia": s["comparecencia"].sum()})
        filas.append({"turno": turno, "grupo": "total", "aptos": g["aptos"].sum(), "comparecencia": g["comparecencia"].sum()})
    t = pd.DataFrame(filas)
    t["tasa"] = t["comparecencia"] / t["aptos"]
    return t


def mezcla_votantes(d: pd.DataFrame, turno: int) -> pd.DataFrame:
    """Composición de los que votaron, por município: % mujeres, por edad y superior."""
    g = d[d["turno"] == turno]
    tot = g.groupby("codigo")["comparecencia"].sum()
    m = pd.DataFrame({"votantes": tot, "uf": g.groupby("codigo")["SG_UF"].first()})
    m["mujeres"] = g[g["genero"] == "mujeres"].groupby("codigo")["comparecencia"].sum() / tot
    for e in EDADES:
        m[e] = g[g["edad"] == e].groupby("codigo")["comparecencia"].sum() / tot
    m["superior"] = g[g["superior"]].groupby("codigo")["comparecencia"].sum() / tot
    return m.fillna(0)


# ---------------------------------------------------------------------------
# 3 · Encuestas por segmento
# ---------------------------------------------------------------------------

def encuestas() -> tuple[pd.DataFrame, dict]:
    cfg = yaml.safe_load(CFG_ENCUESTAS.read_text(encoding="utf-8"))
    filas = []
    for e in cfg["encuestas_2026"]:
        for g in set(e["lula"]) | set(e["flavio"]):
            l, f = e["lula"].get(g), e["flavio"].get(g)
            filas.append({"casa": e["casa"], "fecha_fin": str(e["fecha_fin"]), "muestra": e["muestra"], "grupo": g,
                          "lula": l, "flavio": f,
                          "lula_validos": l / (l + f) * 100 if l is not None and f is not None else np.nan})
    df = pd.DataFrame(filas)
    ref = cfg["referencia_2022"]
    return df, ref


def brechas(df: pd.DataFrame, ref: dict) -> dict:
    p = df.pivot_table(index="casa", columns="grupo", values="lula_validos")
    out = {"por_casa": {}}
    for casa, r in p.iterrows():
        x = {}
        if pd.notna(r.get("mujeres")) and pd.notna(r.get("hombres")):
            x["brecha_genero_pp"] = float(r["mujeres"] - r["hombres"])
        if pd.notna(r.get("e_16_24")) and pd.notna(r.get("e_60")):
            x["brecha_jovenes_mayores_pp"] = float(r["e_16_24"] - r["e_60"])
        x.update({g: float(r[g]) for g in r.index if pd.notna(r[g])})
        out["por_casa"][casa] = x
    gen = [v["brecha_genero_pp"] for v in out["por_casa"].values() if "brecha_genero_pp" in v]
    out["brecha_genero_media_pp"] = float(np.mean(gen))
    out["brecha_genero_rango_pp"] = [float(min(gen)), float(max(gen))]
    out["brecha_genero_2022_pp"] = ref["lula"]["mujeres"] - ref["lula"]["hombres"]
    out["mujeres_media"] = float(p["mujeres"].mean())
    out["hombres_media"] = float(p["hombres"].mean())
    return out


# ---------------------------------------------------------------------------
# 4 · Estimación ecológica por município
# ---------------------------------------------------------------------------

def resultados_municipio() -> pd.DataFrame:
    r = pd.read_parquet(RESULTADO_2026).query("uf != 'ZZ'").set_index("codigo")
    loc = pd.read_parquet(salida_locales(2022)).query("uf != 'ZZ'")
    m22 = loc.groupby(loc["cd_ibge"].astype(int))[["pt_1", "bolsonaro_1", "pt_2", "bolsonaro_2"]].sum()
    return pd.DataFrame({
        "uf": r["uf"],
        "lula_2026": r["lula"] / (r["lula"] + r["flavio_bolsonaro"]),
        "dos_2026": r["lula"] + r["flavio_bolsonaro"],
        "lula_2022": (m22["pt_2"] / (m22["pt_2"] + m22["bolsonaro_2"])).reindex(r.index),
        "dos_2022": (m22["pt_2"] + m22["bolsonaro_2"]).reindex(r.index),
    })


def goodman(y: pd.Series, X: pd.DataFrame, w: pd.Series, uf: pd.Series) -> dict:
    """MCO ponderado con efectos fijos de UF y errores robustos. Los coeficientes de las
    proporciones se leen como diferencia de apoyo entre grupos (Goodman)."""
    fe = pd.get_dummies(uf, prefix="uf", drop_first=True, dtype=float)
    Z = sm.add_constant(pd.concat([X, fe], axis=1))
    m = sm.WLS(y, Z, weights=w).fit(cov_type="HC1")
    return {"coef": m.params[X.columns].to_dict(), "se": m.bse[X.columns].to_dict(), "r2": float(m.rsquared),
            "n": int(m.nobs)}


def ecologico(res: pd.DataFrame, mez22: pd.DataFrame, mez26: pd.DataFrame) -> dict:
    out = {}
    # mujeres: diferencia mujeres - hombres; edades: contra 25-44 (omitidas 25-34 y 35-44)
    cols = ["mujeres", "16-24", "45-59", "60+", "superior"]
    for nombre, y, mez, w in (("2022_2v", res["lula_2022"], mez22, res["dos_2022"]),
                              ("2026_1v", res["lula_2026"], mez26, res["dos_2026"])):
        d = pd.concat([y.rename("y"), w.rename("w"), mez[cols], res["uf"]], axis=1).dropna()
        d = d[d["w"] > 0]
        g = goodman(d["y"] * 100, d[cols], d["w"], d["uf"])
        out[nombre] = {"brecha_genero_pp": g["coef"]["mujeres"], "brecha_genero_se": g["se"]["mujeres"],
                       "jovenes_vs_25_44_pp": g["coef"]["16-24"], "jovenes_se": g["se"]["16-24"],
                       "mayores_vs_25_44_pp": g["coef"]["60+"], "mayores_se": g["se"]["60+"],
                       "superior_pp": g["coef"]["superior"], "superior_se": g["se"]["superior"],
                       "r2": g["r2"], "n": g["n"],
                       "sd_mujeres_entre_municipios_pp": float(d["mujeres"].std() * 100),
                       "sd_60_entre_municipios_pp": float(d["60+"].std() * 100)}
    # cambio 2022 -> 2026: dónde cayó más Lula según la composición
    d = pd.concat([((res["lula_2026"] - res["lula_2022"]) * 100).rename("y"), res["dos_2026"].rename("w"),
                   mez26[cols], res["uf"]], axis=1).dropna()
    g = goodman(d["y"], d[cols], d["w"], d["uf"])
    out["cambio"] = {k: {"coef": g["coef"][k], "se": g["se"][k]} for k in cols} | {"r2": g["r2"]}
    return out


# ---------------------------------------------------------------------------
# 5 · Escenarios de participación
# ---------------------------------------------------------------------------

def escenarios(t22: pd.DataFrame, t26: pd.DataFrame, apoyo: dict, aptos26: dict) -> dict:
    """Si la participación de cada grupo cambia de la 1ª a la 2ª vuelta como en 2022,
    ¿cuánto se mueve Lula con las preferencias de las encuestas? Solo el efecto de
    composición: compara Lula con la mezcla de votantes del 4/10 y con la nueva."""
    out = {}
    for dim, grupos in (("genero", ["mujeres", "hombres"]), ("edad", EDADES)):
        c22 = t22.set_index(["turno", "grupo"])["tasa"]
        base = {g: t26.set_index(["turno", "grupo"]).loc[(1, g), "comparecencia"] for g in grupos}
        nuevo = {g: base[g] * c22.loc[(2, g)] / c22.loc[(1, g)] for g in grupos}
        a = {g: apoyo.get(g) for g in grupos}
        if any(v is None or pd.isna(v) for v in a.values()):
            continue
        lula = lambda n: sum(n[g] * a[g] for g in grupos) / sum(n.values())
        out[dim] = {"lula_mezcla_4_10": lula(base), "lula_mezcla_como_2022": lula(nuevo),
                    "efecto_pp": lula(nuevo) - lula(base),
                    "cambio_tasa_2022_pp": {g: float((c22.loc[(2, g)] - c22.loc[(1, g)]) * 100) for g in grupos}}
    # cuánto vale un punto más de participación femenina (sobre las aptas del 4/10)
    m, h = apoyo.get("mujeres"), apoyo.get("hombres")
    if m is not None and h is not None:
        b = {g: t26.set_index(["turno", "grupo"]).loc[(1, g), "comparecencia"] for g in ("mujeres", "hombres")}
        extra = aptos26["mujeres"] * 0.01
        l0 = (b["mujeres"] * m + b["hombres"] * h) / (b["mujeres"] + b["hombres"])
        l1 = ((b["mujeres"] + extra) * m + b["hombres"] * h) / (b["mujeres"] + extra + b["hombres"])
        out["mujeres_+1pt_participacion_pp"] = l1 - l0
        out["mujeres_extra_votantes"] = extra
    return out


def main() -> None:
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    salida = SALIDA_DIR / sello
    salida.mkdir(parents=True, exist_ok=True)

    log.info("Padrón 2022 y 2026")
    p22, p26 = padron(2022), padron(2026)
    comp = {"2022": composicion(p22, "QT_ELEITORES"), "2026": composicion(p26, "QT_ELEITORES")}
    pd.DataFrame(comp).to_csv(salida / "padron.csv")

    log.info("Comparecencia por perfil 2022 y 2026")
    c22, c26 = comparecencia(2022), comparecencia(2026)
    t22, t26 = tasas(c22), tasas(c26)
    pd.concat([t22.assign(ano=2022), t26.assign(ano=2026)]).to_csv(salida / "comparecencia.csv", index=False)
    votantes_26 = composicion(c26[c26["turno"] == 1], "comparecencia")

    log.info("Encuestas por segmento")
    enc, ref = encuestas()
    enc.to_csv(salida / "encuestas.csv", index=False)
    B = brechas(enc, ref)
    apoyo = {"mujeres": B["mujeres_media"] / 100, "hombres": B["hombres_media"] / 100}
    ind = enc[enc["casa"] == "Indexa/Broadcast"].set_index("grupo")["lula_validos"] / 100
    apoyo.update({e: ind.get(f"e_{e.replace('-', '_').replace('+', '')}") for e in EDADES})
    # lo que implican las encuestas con la mezcla real de votantes del 4/10
    impl = votantes_26["mujeres"] / (votantes_26["mujeres"] + votantes_26["hombres"])
    B["lula_implicito_por_genero"] = float((impl * apoyo["mujeres"] + (1 - impl) * apoyo["hombres"]) * 100)

    log.info("Estimación ecológica")
    res = resultados_municipio()
    mez22, mez26 = mezcla_votantes(c22, 2), mezcla_votantes(c26, 1)
    eco = ecologico(res, mez22, mez26)
    pd.concat([res, mez26.add_prefix("v26_")], axis=1).to_parquet(salida / "municipios.parquet")

    esc = escenarios(t22, t26, apoyo, {"mujeres": comp["2026"]["mujeres"] * comp["2026"]["total"]})

    pick = lambda t, turno: {r.grupo: float(r.tasa) for r in t[t["turno"] == turno].itertuples()}
    resumen = {
        "corte": datetime.now(timezone.utc).date().isoformat(),
        "padron": comp,
        "votantes_1v_2026": votantes_26,
        "participacion": {"2022_1v": pick(t22, 1), "2022_2v": pick(t22, 2), "2026_1v": pick(t26, 1)},
        "encuestas": B,
        "apoyo_usado": {k: (None if v is None or pd.isna(v) else float(v)) for k, v in apoyo.items()},
        "referencia_2022": ref,
        "ecologico": eco,
        "escenarios": esc,
        "nota": "Voto secreto: sexo y edad salen de encuestas (control) y de inferencia ecológica (territorios, no personas).",
    }
    (salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else float(o)), encoding="utf-8")
    log.info("Escrito %s", salida.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
