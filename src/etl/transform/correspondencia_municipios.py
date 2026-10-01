"""
src/etl/transform/correspondencia_municipios.py

Tabla de correspondencia código de município TSE (5 dígitos) <-> código
IBGE (7 dígitos), versionada en git en
src/etl/transform/correspondencia/municipios_tse_ibge.csv.

No existe una tabla oficial publicada por ninguno de los dos organismos, así
que se construye y se valida acá:

  Universo TSE : municípios presentes en detalhe_votacao_munzona (elección
                 ordinaria) de los años disponibles. Se excluye el exterior (ZZ).
  Universo IBGE: Localidades API (lista oficial vigente).

  Métodos de cruce, en orden de prioridad (columna `metodo`):
    nombre_exacto      UF + nombre normalizado (sin tildes/puntuación) idéntico.
    nombre_aproximado  el nombre no coincide exacto (grafías distintas:
                       Camacã/Camacan, Espigão do Oeste/D'Oeste); se acepta el
                       código que propone la tabla comunitaria SOLO si el
                       nombre IBGE de ese código es de la misma UF y similar
                       (>= UMBRAL_SIMILITUD).
    manual             config/correspondencia_municipios_manual.yaml, con motivo.

  La tabla comunitaria (betafcc) nunca es fuente única: se guarda su código
  en `codigo_ibge_comunitaria` y si discrepa del cruce por nombre exacto se
  marca en `coincide_comunitaria` (en la versión de 2026-10-01 tiene 7 errores
  verificados: códigos rotados en BA y permutados en SC).

Validaciones (si falla alguna, no se escribe la tabla):
  - 1:1 en ambos sentidos.
  - todo código TSE tiene código IBGE.
  - los 2 primeros dígitos del código IBGE corresponden a la UF.
  - todo município IBGE está cruzado o declarado en `ibge_sin_tse`.

Uso:
    python -m src.etl.transform.correspondencia_municipios
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.etl.extract.referencia_extractor import ultima_version as ultima_referencia
from src.etl.extract.tse_extractor import ultima_version as ultima_tse
from src.etl.extract.versionado import sha256
from src.etl.transform.lector_tse import leer_zip_tse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_MANUAL = ROOT / "config" / "correspondencia_municipios_manual.yaml"
SALIDA_DIR = Path(__file__).resolve().parent / "correspondencia"
SALIDA_CSV = SALIDA_DIR / "municipios_tse_ibge.csv"
SALIDA_META = SALIDA_DIR / "municipios_tse_ibge.meta.json"

ANOS_TSE = [2018, 2022, 2026]
UMBRAL_SIMILITUD = 0.75

# Código IBGE de UF (2 primeros dígitos del código de município)
UF_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17",
    "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27",
    "SE": "28", "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35", "PR": "41",
    "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}


def normalizar_nombre(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similitud(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalizar_nombre(a), normalizar_nombre(b)).ratio()


# ---------------------------------------------------------------- insumos

def universo_tse() -> tuple[pd.DataFrame, list[str]]:
    frames, fuentes = [], []
    for ano in ANOS_TSE:
        try:
            zip_path = ultima_tse("detalle_votacion", ano)
        except FileNotFoundError:
            log.info("detalle_votacion %d no disponible — se omite", ano)
            continue
        d = leer_zip_tse(zip_path, columnas=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"],
                         filtro={"NM_TIPO_ELEICAO": {"Eleição Ordinária"}})
        frames.append(d.drop(columns="archivo_origen").drop_duplicates().assign(ano=ano))
        fuentes.append(zip_path)
    t = pd.concat(frames)
    t = t[t["SG_UF"] != "ZZ"]
    t["CD_MUNICIPIO"] = t["CD_MUNICIPIO"].str.zfill(5)

    def resumir(g: pd.DataFrame) -> pd.Series:
        ultimo = g.sort_values("ano").iloc[-1]
        return pd.Series({
            "nombre_tse": ultimo["NM_MUNICIPIO"],
            "nombres_tse_alternativos": "|".join(sorted(set(g["NM_MUNICIPIO"]) - {ultimo["NM_MUNICIPIO"]})),
            "anos_tse": "|".join(str(a) for a in sorted(set(g["ano"]))),
        })

    u = (t.groupby(["SG_UF", "CD_MUNICIPIO"])[["NM_MUNICIPIO", "ano"]]
         .apply(resumir).reset_index()
         .rename(columns={"SG_UF": "uf", "CD_MUNICIPIO": "codigo_tse"}))
    return u, [str(p.relative_to(ROOT).as_posix()) for p in fuentes]


def universo_ibge() -> tuple[pd.DataFrame, Path]:
    path = ultima_referencia("ibge_municipios")
    ib = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    ib = ib.rename(columns={"municipio-id": "codigo_ibge", "municipio-nome": "nombre_ibge",
                            "UF-sigla": "uf"})[["codigo_ibge", "nombre_ibge", "uf"]]
    ib["codigo_ibge"] = ib["codigo_ibge"].astype(str)
    return ib, path


def tabla_comunitaria() -> tuple[pd.DataFrame, Path]:
    path = ultima_referencia("tse_ibge_betafcc")
    bt = pd.read_csv(path, dtype=str)
    bt["codigo_tse"] = bt["codigo_tse"].str.zfill(5)
    return bt[["codigo_tse", "codigo_ibge"]].rename(columns={"codigo_ibge": "codigo_ibge_comunitaria"}), path


# ---------------------------------------------------------------- cruce

def construir() -> tuple[pd.DataFrame, dict]:
    tse, fuentes_tse = universo_tse()
    ibge, path_ibge = universo_ibge()
    comunitaria, path_com = tabla_comunitaria()
    with open(CONFIG_MANUAL, encoding="utf-8") as f:
        manual_cfg = yaml.safe_load(f)

    tse["clave"] = tse["uf"] + "|" + tse["nombre_tse"].map(normalizar_nombre)
    ibge["clave"] = ibge["uf"] + "|" + ibge["nombre_ibge"].map(normalizar_nombre)
    if ibge["clave"].duplicated().any():
        raise ValueError("Nombres IBGE duplicados dentro de una UF — el cruce por nombre no es inequívoco")

    # Las grafías alternativas del TSE (años anteriores) también cuentan para el cruce exacto
    claves_alt = (tse.assign(alt=tse["nombres_tse_alternativos"].str.split("|"))
                  .explode("alt").dropna(subset=["alt"]).query("alt != ''"))
    claves_alt["clave"] = claves_alt["uf"] + "|" + claves_alt["alt"].map(normalizar_nombre)
    candidatos = pd.concat([tse[["codigo_tse", "clave"]], claves_alt[["codigo_tse", "clave"]]])
    exactos = (candidatos.merge(ibge[["clave", "codigo_ibge"]], on="clave")
               .drop_duplicates(["codigo_tse", "codigo_ibge"]))
    if exactos["codigo_tse"].duplicated().any():
        raise ValueError("Un código TSE matchea por nombre con más de un município IBGE")

    t = tse.drop(columns="clave").merge(exactos[["codigo_tse", "codigo_ibge"]], on="codigo_tse", how="left")
    t["metodo"] = t["codigo_ibge"].notna().map({True: "nombre_exacto", False: None})
    t = t.merge(comunitaria, on="codigo_tse", how="left")

    nombre_ibge = ibge.set_index("codigo_ibge")["nombre_ibge"]
    uf_ibge = ibge.set_index("codigo_ibge")["uf"]

    # nombre aproximado: código comunitario, misma UF, nombre similar
    for i in t.index[t["codigo_ibge"].isna()]:
        cand = t.at[i, "codigo_ibge_comunitaria"]
        if pd.isna(cand) or cand not in nombre_ibge.index:
            continue
        if uf_ibge[cand] == t.at[i, "uf"] and similitud(t.at[i, "nombre_tse"], nombre_ibge[cand]) >= UMBRAL_SIMILITUD:
            t.at[i, "codigo_ibge"] = cand
            t.at[i, "metodo"] = "nombre_aproximado"

    # manual
    motivos = {}
    for m in manual_cfg.get("manual", []):
        sel = (t["codigo_tse"] == m["codigo_tse"].zfill(5)) & (t["uf"] == m["uf"])
        if not sel.any():
            raise ValueError(f"Entrada manual {m['codigo_tse']} no existe en el universo TSE")
        if t.loc[sel, "codigo_ibge"].notna().any():
            log.warning("Entrada manual %s ya resuelta automáticamente — revisar si sigue haciendo falta",
                        m["codigo_tse"])
            continue
        t.loc[sel, ["codigo_ibge", "metodo"]] = [m["codigo_ibge"], "manual"]
        motivos[m["codigo_tse"].zfill(5)] = m["motivo"].strip()
    t["motivo_manual"] = t["codigo_tse"].map(motivos)

    t["nombre_ibge"] = t["codigo_ibge"].map(nombre_ibge)
    t["coincide_comunitaria"] = t["codigo_ibge"] == t["codigo_ibge_comunitaria"]

    validar(t, ibge, manual_cfg)

    columnas = ["uf", "codigo_tse", "nombre_tse", "nombres_tse_alternativos", "codigo_ibge",
                "nombre_ibge", "metodo", "motivo_manual", "codigo_ibge_comunitaria",
                "coincide_comunitaria", "anos_tse"]
    t = t[columnas].sort_values(["uf", "codigo_tse"]).reset_index(drop=True)

    meta = {
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filas": len(t),
        "por_metodo": t["metodo"].value_counts().to_dict(),
        "discrepancias_comunitaria": t.loc[~t["coincide_comunitaria"], "codigo_tse"].tolist(),
        "ibge_sin_tse": [m["codigo_ibge"] for m in manual_cfg.get("ibge_sin_tse", [])],
        "exterior": "excluido (UF ZZ, sin código IBGE)",
        "fuentes": {
            "tse_detalle_votacion": fuentes_tse,
            "ibge_localidades": {"archivo": path_ibge.relative_to(ROOT).as_posix(), "sha256": sha256(path_ibge)},
            "comunitaria_betafcc": {"archivo": path_com.relative_to(ROOT).as_posix(), "sha256": sha256(path_com)},
        },
    }
    return t, meta


def validar(t: pd.DataFrame, ibge: pd.DataFrame, manual_cfg: dict) -> None:
    errores = []
    sin = t[t["codigo_ibge"].isna()]
    if len(sin):
        errores.append(f"{len(sin)} códigos TSE sin IBGE: {sin[['uf', 'codigo_tse', 'nombre_tse']].values.tolist()}")
    dup = t["codigo_ibge"].dropna()
    if dup.duplicated().any():
        errores.append(f"códigos IBGE asignados a más de un TSE: {sorted(set(dup[dup.duplicated()]))}")
    if t["codigo_tse"].duplicated().any():
        errores.append("códigos TSE duplicados")
    malos_uf = t[t["codigo_ibge"].notna() & (t["codigo_ibge"].str[:2] != t["uf"].map(UF_IBGE))]
    if len(malos_uf):
        errores.append(f"código IBGE de otra UF: {malos_uf[['uf', 'codigo_tse', 'codigo_ibge']].values.tolist()}")
    declarados = {m["codigo_ibge"] for m in manual_cfg.get("ibge_sin_tse", [])}
    huerfanos = set(ibge["codigo_ibge"]) - set(t["codigo_ibge"].dropna()) - declarados
    if huerfanos:
        errores.append(f"municípios IBGE sin código TSE y no declarados: {sorted(huerfanos)}")
    sobran = declarados & set(t["codigo_ibge"].dropna())
    if sobran:
        log.warning("Declarados como ibge_sin_tse pero ya tienen código TSE (sacarlos del yaml): %s", sobran)
    if errores:
        raise ValueError("Correspondencia TSE-IBGE inválida:\n  - " + "\n  - ".join(errores))


# ---------------------------------------------------------------- uso

def cargar() -> pd.DataFrame:
    """Tabla versionada, con códigos como string."""
    return pd.read_csv(SALIDA_CSV, dtype=str, keep_default_na=False, na_values=[""])


def agregar_codigo_ibge(df: pd.DataFrame, col_tse: str = "CD_MUNICIPIO") -> pd.DataFrame:
    """Agrega `codigo_ibge` a un DataFrame con código TSE. Falla si algún código no cruza
    (el exterior, UF ZZ, se debe filtrar antes)."""
    tabla = cargar().set_index("codigo_tse")["codigo_ibge"]
    codigos = df[col_tse].astype(str).str.zfill(5)
    faltan = sorted(set(codigos) - set(tabla.index))
    if faltan:
        raise KeyError(f"códigos TSE sin correspondencia IBGE: {faltan[:10]}{'...' if len(faltan) > 10 else ''}")
    return df.assign(codigo_ibge=codigos.map(tabla))


def main() -> None:
    t, meta = construir()
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    t.to_csv(SALIDA_CSV, index=False, encoding="utf-8")
    SALIDA_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Escrito %s (%d filas) — por método: %s", SALIDA_CSV.name, len(t), meta["por_metodo"])
    if meta["discrepancias_comunitaria"]:
        d = t[~t["coincide_comunitaria"]][["uf", "codigo_tse", "nombre_tse", "codigo_ibge",
                                           "codigo_ibge_comunitaria"]]
        log.warning("La tabla comunitaria discrepa en %d casos (prevalece el cruce por nombre IBGE):\n%s",
                    len(d), d.to_string(index=False))


if __name__ == "__main__":
    main()
