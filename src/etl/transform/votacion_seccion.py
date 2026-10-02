"""
src/etl/transform/votacion_seccion.py

Base "mesa por mesa" de la elección presidencial: votos por seção eleitoral
(TSE, archivo nacional de presidente) en formato ancho, una fila por
sección y vuelta, una columna por opción de voto.

Columnas de salida:
  ano, turno, uf, cd_municipio (código TSE), nr_zona, nr_secao, nr_local,
  v_<NR_VOTAVEL> (votos de cada candidato por su número; 95 = blanco,
  96 = nulo), comparecencia (suma de todo lo anterior), nm_local
Los nombres de cada número quedan en el log y en <salida>.candidatos.csv.

El CSV del TSE pesa ~2 GB por año: se lee en bloques con solo las columnas
necesarias y se agrega en el camino.

Input:  data/raw/tse/votacion_seccion/{ano}/<version>/votacao_secao_{ano}_BR.zip
Output: data/processed/electoral/seccion/presidente_seccion_{ano}.parquet

También gobernador (archivos por UF): gobernador_seccion_{ano}.parquet.

Uso:
    python -m src.etl.transform.votacion_seccion --ano 2018 2022
    python -m src.etl.transform.votacion_seccion --cargo gobernador --ano 2022
"""
from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path

import pandas as pd

from src.etl.extract.tse_extractor import ultima_version

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
SALIDA_DIR = ROOT / "data" / "processed" / "electoral" / "seccion"
CLAVE = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"]
COLUMNAS = CLAVE + ["NM_TIPO_ELEICAO", "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS", "NM_LOCAL_VOTACAO"]
BLOQUE = 2_000_000


def salida(ano: int) -> Path:
    return SALIDA_DIR / f"presidente_seccion_{ano}.parquet"


def transformar(ano: int) -> pd.DataFrame:
    ruta = ultima_version("votacion_seccion_presidente", ano)
    with zipfile.ZipFile(ruta) as z:
        csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        partes, nombres, locales = [], {}, {}
        filas = 0
        with z.open(csv) as f:
            for bloque in pd.read_csv(f, sep=";", encoding="latin1", usecols=COLUMNAS, chunksize=BLOQUE,
                                      dtype={"NM_VOTAVEL": str, "NM_LOCAL_VOTACAO": str, "SG_UF": str,
                                             "NM_TIPO_ELEICAO": str}):
                filas += len(bloque)
                # Solo elección ordinaria y cargo presidente (el archivo _BR es solo presidente,
                # pero se filtra igual para no depender de eso)
                # (el TSE escribe "Eleição Ordinária" en 2018 y "ELEIÇÃO ORDINÁRIA" en 2022)
                bloque = bloque[(bloque["CD_CARGO"] == 1)
                                & bloque["NM_TIPO_ELEICAO"].str.contains("ordin", case=False)]
                for nr, nm in bloque[["NR_VOTAVEL", "NM_VOTAVEL"]].drop_duplicates().itertuples(index=False):
                    nombres.setdefault(int(nr), nm)
                loc = bloque.drop_duplicates(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"])
                for r in loc[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO"]].itertuples(index=False):
                    locales.setdefault(tuple(r[:4]), r[4])
                partes.append(bloque.groupby(CLAVE + ["NR_VOTAVEL"], as_index=False)["QT_VOTOS"].sum())
                log.info("%d: %s filas leídas", ano, f"{filas:,}")

    largo = pd.concat(partes).groupby(CLAVE + ["NR_VOTAVEL"], as_index=False)["QT_VOTOS"].sum()
    ancho = largo.pivot_table(index=CLAVE, columns="NR_VOTAVEL", values="QT_VOTOS", aggfunc="sum", fill_value=0)
    ancho.columns = [f"v_{int(c)}" for c in ancho.columns]
    ancho["comparecencia"] = ancho.sum(axis=1)
    ancho = ancho.reset_index().rename(columns={
        "ANO_ELEICAO": "ano", "NR_TURNO": "turno", "SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio",
        "NR_ZONA": "nr_zona", "NR_SECAO": "nr_secao", "NR_LOCAL_VOTACAO": "nr_local"})
    ancho["nm_local"] = [locales.get(k) for k in zip(ancho["uf"], ancho["cd_municipio"], ancho["nr_zona"], ancho["nr_local"])]
    cols_v = sorted(c for c in ancho.columns if c.startswith("v_"))
    ancho[cols_v + ["comparecencia"]] = ancho[cols_v + ["comparecencia"]].astype("int32")

    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    ancho.to_parquet(salida(ano), index=False)
    pd.Series(nombres, name="nm_votavel").rename_axis("nr_votavel").sort_index().to_csv(
        salida(ano).with_suffix(".candidatos.csv"))
    for turno, g in ancho.groupby("turno"):
        tot = g[cols_v].sum()
        top = (tot / tot.drop(["v_95", "v_96"], errors="ignore").sum() * 100).drop(["v_95", "v_96"], errors="ignore")
        log.info("%d vuelta %d: %s secciones, %s locales, comparecencia %s. Válidos: %s", ano, turno,
                 f"{len(g):,}", f"{g.groupby(['uf', 'cd_municipio', 'nr_zona', 'nr_local']).ngroups:,}",
                 f"{int(g['comparecencia'].sum()):,}",
                 ", ".join(f"{nombres.get(int(c[2:]), c)} {v:.2f}%" for c, v in top.nlargest(4).items()))
    return ancho


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", nargs="+", type=int, default=[2018, 2022])
    parser.add_argument("--cargo", choices=["presidente", "gobernador"], default="presidente")
    parser.add_argument("--uf", nargs="+", help="solo gobernador: UF a procesar (default: las 27)")
    args = parser.parse_args()
    for ano in args.ano:
        if args.cargo == "gobernador":
            transformar_gobernador(ano, args.uf)
        else:
            transformar(ano)



# ---------------------------------------------------------------------------
# Gobernador (archivos por UF, todos los cargos)
# ---------------------------------------------------------------------------

def salida_gobernador(ano: int) -> Path:
    return SALIDA_DIR / f"gobernador_seccion_{ano}.parquet"


def transformar_gobernador(ano: int, ufs: list[str] | None = None) -> pd.DataFrame:
    """Votos a gobernador por sección (una fila por sección y vuelta; v_<número> por candidato).
    Lee cada UF por separado y en bloques, quedándose solo con CD_CARGO 3."""
    from src.etl.extract.tse_extractor import UFS
    partes, candidatos = [], []
    for uf in ufs or UFS:
        try:
            ruta = ultima_version("votacion_seccion_uf", ano, uf)
        except FileNotFoundError:
            log.warning("%d %s: sin archivo por UF, se omite", ano, uf)
            continue
        with zipfile.ZipFile(ruta) as z:
            csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            sub = []
            with z.open(csv) as f:
                for b in pd.read_csv(f, sep=";", encoding="latin1", usecols=COLUMNAS, chunksize=BLOQUE,
                                     dtype={"NM_VOTAVEL": str, "NM_LOCAL_VOTACAO": str, "SG_UF": str, "NM_TIPO_ELEICAO": str}):
                    b = b[(b["CD_CARGO"] == 3) & b["NM_TIPO_ELEICAO"].str.contains("ordin", case=False)]
                    sub.append(b.groupby(CLAVE + ["NR_VOTAVEL", "NM_VOTAVEL"], as_index=False)["QT_VOTOS"].sum())
        d = pd.concat(sub)
        candidatos.append(d.groupby(["NR_TURNO", "NR_VOTAVEL", "NM_VOTAVEL"], as_index=False)["QT_VOTOS"].sum()
                          .assign(uf=uf))
        w = d.pivot_table(index=CLAVE, columns="NR_VOTAVEL", values="QT_VOTOS", aggfunc="sum", fill_value=0)
        w.columns = [f"v_{int(c)}" for c in w.columns]
        partes.append(w.reset_index())
        top = candidatos[-1][candidatos[-1]["NR_TURNO"] == 1].query("NR_VOTAVEL < 95").nlargest(2, "QT_VOTOS")
        val = candidatos[-1].query("NR_TURNO == 1 and NR_VOTAVEL < 95")["QT_VOTOS"].sum()
        log.info("%d %s: %s secciones; vueltas %s; 1ª: %s", ano, uf, f"{len(w):,}", sorted(d["NR_TURNO"].unique()),
                 ", ".join(f"{r.NM_VOTAVEL} {r.QT_VOTOS / val * 100:.1f}%" for r in top.itertuples()))
    ancho = pd.concat(partes, ignore_index=True)
    cols_v = [c for c in ancho.columns if c.startswith("v_")]
    ancho[cols_v] = ancho[cols_v].fillna(0).astype("int32")
    ancho["comparecencia"] = ancho[cols_v].sum(axis=1).astype("int32")
    ancho = ancho.rename(columns={"ANO_ELEICAO": "ano", "NR_TURNO": "turno", "SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio",
                                  "NR_ZONA": "nr_zona", "NR_SECAO": "nr_secao", "NR_LOCAL_VOTACAO": "nr_local"})
    ancho.to_parquet(salida_gobernador(ano), index=False)
    pd.concat(candidatos).rename(columns=str.lower).to_csv(salida_gobernador(ano).with_suffix(".candidatos.csv"), index=False)
    return ancho


if __name__ == "__main__":
    main()
