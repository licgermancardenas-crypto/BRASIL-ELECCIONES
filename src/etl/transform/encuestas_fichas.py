"""
src/etl/transform/encuestas_fichas.py

Normaliza las fichas técnicas de encuestas registradas en el TSE (PesqEle)
para 2018, 2022 y 2026 en un único esquema, y resuelve la casa encuestadora
canónica por CNPJ contra config/encuestadoras.yaml.

PesqEle NO trae resultados (porcentajes por candidato): esto es solo la
metadata oficial que después se cruza, por número de registro, con los
resultados publicados.

El esquema del TSE cambia entre años (DS_CARGOS→DS_CARGO,
QT_ENTREVISTADOS→QT_ENTREVISTADO, sin DT_DIVULGACAO en 2018); se mapea acá.

Input:  data/raw/tse/encuestas_registradas/{ano}/<version>/pesquisa_eleitoral_{ano}.zip
Output: data/processed/electoral/encuestas_fichas.parquet

Uso:
    python -m src.etl.transform.encuestas_fichas --ano 2018 2022 2026
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import yaml

from src.etl.extract.tse_extractor import ultima_version
from src.etl.transform.lector_tse import leer_zip_tse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_CASAS = ROOT / "config" / "encuestadoras.yaml"
PROCESSED_DIR = ROOT / "data" / "processed" / "electoral"

# nombre en el TSE (cualquier año) -> nombre en el proyecto
COLUMNAS = {
    "AA_ELEICAO": "ano",
    "NR_PROTOCOLO_REGISTRO": "registro",
    "SG_UF": "uf",
    "NM_UE": "unidad_electoral",
    "DT_REGISTRO": "fecha_registro",
    "ST_PESQUISA_PROPRIA": "propia",
    "NR_CNPJ_EMPRESA": "cnpj",
    "NM_EMPRESA": "razon_social",
    "NM_EMPRESA_FANTASIA": "nombre_fantasia",
    "DS_CARGO": "cargos",
    "DS_CARGOS": "cargos",
    "DT_INICIO_PESQUISA": "fecha_inicio",
    "DT_FIM_PESQUISA": "fecha_fin",
    "DT_DIVULGACAO": "fecha_divulgacion",
    "QT_ENTREVISTADO": "muestra",
    "QT_ENTREVISTADOS": "muestra",
    "VR_PESQUISA": "costo_brl",
    "DS_METODOLOGIA_PESQUISA": "metodologia",
    "DS_PLANO_AMOSTRAL": "plan_muestral",
}

CARGOS = {
    "presidente": "Presidente",
    "governador": "Governador",
    "senador": "Senador",
    "dep_federal": "Deputado Federal",
}


def _parsear_fecha(s: pd.Series) -> pd.Series:
    """El TSE usa dd/mm/aaaa en 2018 y aaaa-mm-dd hh:mm:ss desde 2022."""
    iso = pd.to_datetime(s, errors="coerce", format="%Y-%m-%d %H:%M:%S")
    br = pd.to_datetime(s, errors="coerce", format="%d/%m/%Y")
    return iso.fillna(br).dt.normalize()


def mapa_cnpj_casa(ano: int) -> dict[str, str]:
    """CNPJ -> casa canónica, solo para los vínculos vigentes en `ano`."""
    with open(CONFIG_CASAS, encoding="utf-8") as f:
        casas = yaml.safe_load(f)["casas"]
    mapa = {}
    for casa, cfg in casas.items():
        for cnpj, anos in cfg["cnpj"].items():
            if ano in anos:
                mapa[cnpj] = casa
    return mapa


def normalizar_ano(ano: int) -> pd.DataFrame:
    zip_path = ultima_version("encuestas_registradas", ano)
    df = leer_zip_tse(zip_path).rename(columns=COLUMNAS)
    df = df[[c for c in dict.fromkeys(COLUMNAS.values()) if c in df.columns]].copy()

    # 2018 trae una fila por contratante (mismas columnas de ficha): se colapsan.
    df = df.drop_duplicates()

    for c in ("fecha_registro", "fecha_inicio", "fecha_fin", "fecha_divulgacion"):
        if c in df:
            df[c] = _parsear_fecha(df[c])
    df["ano"] = ano
    df["muestra"] = pd.to_numeric(df["muestra"], errors="coerce").astype("Int64")
    df["costo_brl"] = pd.to_numeric(df["costo_brl"].str.replace(",", ".", regex=False), errors="coerce")
    df["cnpj"] = df["cnpj"].str.zfill(14)
    df["ambito"] = df["uf"].map(lambda u: "nacional" if u == "BR" else "estadual")

    casas = mapa_cnpj_casa(ano)
    df["casa"] = df["cnpj"].map(casas).fillna("cnpj_" + df["cnpj"].fillna("desconocido"))
    df["casa_catalogada"] = df["cnpj"].isin(casas)

    cargos = df["cargos"].fillna("")
    for col, etiqueta in CARGOS.items():
        df[f"mide_{col}"] = cargos.str.contains(etiqueta, regex=False)

    # En 2018 el TSE reutilizó algunos números de protocolo para encuestas
    # distintas (otra empresa, otras fechas). El número solo no es clave:
    # id_ficha = registro + cnpj, y la colisión queda marcada para que el cruce
    # con resultados no se haga por número de registro solo en esos casos.
    df["registro_colision"] = df["registro"].duplicated(keep=False)
    df["id_ficha"] = df["registro"].where(~df["registro_colision"], df["registro"] + "_" + df["cnpj"])

    df["fuente_zip"] = zip_path.relative_to(ROOT).as_posix()
    return df


def validar(df: pd.DataFrame) -> None:
    dup = df["id_ficha"].duplicated().sum()
    if dup:
        raise ValueError(f"{dup} id_ficha duplicados — revisar lectura de archivos del zip")
    colisiones = df.loc[df["registro_colision"], "registro"].nunique()
    if colisiones:
        log.warning("%d números de registro del TSE reutilizados por encuestas distintas "
                    "(marcados en registro_colision)", colisiones)
    sin_fecha = df["fecha_fin"].isna().sum()
    if sin_fecha:
        log.warning("%d fichas sin fecha de fin de campo", sin_fecha)
    invertidas = (df["fecha_fin"] < df["fecha_inicio"]).sum()
    if invertidas:
        log.warning("%d fichas con fecha_fin < fecha_inicio", invertidas)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, nargs="+", default=[2018, 2022, 2026])
    args = parser.parse_args()

    df = pd.concat([normalizar_ano(a) for a in args.ano], ignore_index=True)
    validar(df)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "encuestas_fichas.parquet"
    df.to_parquet(out, index=False)

    resumen = df.groupby(["ano", "ambito"]).agg(
        fichas=("registro", "size"),
        presidente=("mide_presidente", "sum"),
        governador=("mide_governador", "sum"),
        casas=("casa", "nunique"),
    )
    log.info("Guardado %s (%d fichas)\n%s", out, len(df), resumen.to_string())


if __name__ == "__main__":
    main()
