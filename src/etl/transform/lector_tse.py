"""
src/etl/transform/lector_tse.py

Lectura uniforme de los zips del CDN del TSE.

Cada zip trae, según el año:
  - <dataset>_<ano>_BRASIL.csv : consolidado de todo el país (todas las UF)
  - <dataset>_<ano>_BR.csv     : solo registros de alcance nacional (presidente)
  - <dataset>_<ano>_<UF>.csv   : un archivo por UF
  - <dataset>_<ano>_ZZ.csv     : exterior

Si existe _BRASIL.csv se lee SOLO ese (ya contiene todo lo demás); leer
todos los CSV duplica los registros. Si no existe (ej. PesqEle 2018), se
concatenan los demás, que en ese caso son disjuntos.

Valores centinela del TSE (#NULO#, #NE#, -1, -3) se convierten a NA.

Los consolidados de resultados pesan >4 GB descomprimidos: para esos se
pasan `columnas` y `filtro` ({columna: valores aceptados, sin distinguir
mayúsculas}), y la lectura se hace por bloques descartando filas temprano.

OJO: el zip de resultados de un año puede incluir elecciones extraordinarias
posteriores (el de 2022 trae la suplementaria de gobernador de RR del
21/06/2026). Para resultados de la elección general, filtrar siempre
{"NM_TIPO_ELEICAO": {"Eleição Ordinária"}}.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

CENTINELAS = ["#NULO#", "#NULO", "#NE#", "#NE", "-1", "-3"]


def archivos_a_leer(nombres: list[str]) -> list[str]:
    csvs = [n for n in nombres if n.lower().endswith(".csv")]
    brasil = [n for n in csvs if n.upper().endswith("_BRASIL.CSV")]
    return brasil if brasil else csvs


TAMANO_BLOQUE = 500_000


def leer_zip_tse(
    zip_path: Path,
    columnas: list[str] | None = None,
    filtro: dict[str, set[str]] | None = None,
) -> pd.DataFrame:
    """Devuelve el contenido del zip como DataFrame de strings, sin duplicados por archivo."""
    filtro_norm = {c: {v.upper() for v in vals} for c, vals in (filtro or {}).items()}
    if columnas and filtro_norm:
        columnas = list(dict.fromkeys([*columnas, *filtro_norm]))

    with zipfile.ZipFile(zip_path) as z:
        frames = []
        for nombre in archivos_a_leer(z.namelist()):
            bloques = pd.read_csv(
                z.open(nombre), sep=";", encoding="latin-1", dtype=str,
                na_values=CENTINELAS, keep_default_na=True,
                usecols=(lambda c: c in columnas) if columnas else None,
                chunksize=TAMANO_BLOQUE,
            )
            for bloque in bloques:
                for col, vals in filtro_norm.items():
                    bloque = bloque[bloque[col].str.upper().isin(vals)]
                if len(bloque):
                    bloque = bloque.assign(archivo_origen=nombre)
                    frames.append(bloque)
    if not frames:
        raise ValueError(f"{zip_path}: sin filas (sin CSV o el filtro no dejó nada)")
    return pd.concat(frames, ignore_index=True)
