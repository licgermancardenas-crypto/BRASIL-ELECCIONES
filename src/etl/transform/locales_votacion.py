"""
src/etl/transform/locales_votacion.py

Padrón y ubicación de cada seção eleitoral (TSE, eleitorado_local_votacao):
cuántos electores tiene, en qué local de votación vota y dónde queda ese
local (latitud/longitud publicadas por el TSE).

Secciones agregadas: el TSE junta algunas secciones chicas con otra
("principal") el día de la elección, y publica sus votos bajo el número de la
principal. Por eso el padrón se suma a la sección principal: así el padrón y
los votos de votacion_seccion hablan de la misma urna.

Columnas de salida (una fila por sección principal, 1ª vuelta):
  uf, cd_municipio, nm_municipio, nr_zona, nr_secao, nr_local, nm_local,
  bairro, lat, lon, aptos, secciones_agregadas

Input:  data/raw/tse/locales_votacion/{ano}/<version>/eleitorado_local_votacao_{ano}.zip
Output: data/processed/electoral/seccion/padron_seccion_{ano}.parquet

Uso:
    python -m src.etl.transform.locales_votacion --ano 2018 2022
"""
from __future__ import annotations

import argparse
import logging
import zipfile

import numpy as np
import pandas as pd

from src.etl.extract.tse_extractor import ultima_version
from src.etl.transform.votacion_seccion import SALIDA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

COLUMNAS = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_TIPO_SECAO_AGREGADA",
            "NR_SECAO_PRINCIPAL", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_BAIRRO", "NR_LATITUDE", "NR_LONGITUDE",
            "QT_ELEITOR_SECAO"]


def salida(ano: int):
    return SALIDA_DIR / f"padron_seccion_{ano}.parquet"


def transformar(ano: int) -> pd.DataFrame:
    with zipfile.ZipFile(ultima_version("locales_votacion", ano)) as z:
        csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(csv) as f:
            d = pd.read_csv(f, sep=";", encoding="latin1", usecols=COLUMNAS, dtype=str)
    d = d[d["NR_TURNO"] == "1"]
    for c in ["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_SECAO_PRINCIPAL", "NR_LOCAL_VOTACAO", "QT_ELEITOR_SECAO",
              "CD_TIPO_SECAO_AGREGADA"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
    for c in ["NR_LATITUDE", "NR_LONGITUDE"]:
        d[c] = pd.to_numeric(d[c].str.replace(",", "."), errors="coerce")
    # Coordenadas faltantes vienen como -1 o 0
    d.loc[(d["NR_LATITUDE"].abs() < 0.01) | (d["NR_LATITUDE"] == -1), ["NR_LATITUDE", "NR_LONGITUDE"]] = np.nan

    agregada = d["CD_TIPO_SECAO_AGREGADA"] != 1
    d["secao_urna"] = d["NR_SECAO"].where(~agregada | (d["NR_SECAO_PRINCIPAL"] < 0), d["NR_SECAO_PRINCIPAL"])
    clave = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "secao_urna"]
    aptos = d.groupby(clave)["QT_ELEITOR_SECAO"].sum().rename("aptos")
    n_agr = d[agregada].groupby(clave).size().rename("secciones_agregadas")
    principal = d[~agregada].drop_duplicates(clave).set_index(clave)
    out = principal[["NM_MUNICIPIO", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_BAIRRO", "NR_LATITUDE",
                     "NR_LONGITUDE"]].join(aptos).join(n_agr).reset_index()
    out["secciones_agregadas"] = out["secciones_agregadas"].fillna(0).astype(int)
    out = out.rename(columns={"SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio", "NM_MUNICIPIO": "nm_municipio",
                              "NR_ZONA": "nr_zona", "secao_urna": "nr_secao", "NR_LOCAL_VOTACAO": "nr_local",
                              "NM_LOCAL_VOTACAO": "nm_local", "NM_BAIRRO": "bairro", "NR_LATITUDE": "lat",
                              "NR_LONGITUDE": "lon"})
    for c in ["cd_municipio", "nr_zona", "nr_secao", "nr_local", "aptos"]:
        out[c] = out[c].astype("int64")
    out.to_parquet(salida(ano), index=False)
    log.info("%d: %s secciones (urna), %s agregadas a otra, %s electores, %.1f%% con coordenadas", ano,
             f"{len(out):,}", f"{int(agregada.sum()):,}", f"{int(out['aptos'].sum()):,}", out["lat"].notna().mean() * 100)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", nargs="+", type=int, default=[2018, 2022])
    args = parser.parse_args()
    for ano in args.ano:
        transformar(ano)


if __name__ == "__main__":
    main()
