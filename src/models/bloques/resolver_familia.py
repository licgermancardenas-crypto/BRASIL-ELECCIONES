"""
src/models/bloques/resolver_familia.py

Resuelve partido -> familia política para un año de elección dado, contra
config/familias_partidarias.yaml (clasificación) y config/partidos.yaml
(alias de siglas).

Reglas:
  - Nunca hay familia por defecto: un partido sin clasificar en ese año
    levanta PartidoSinClasificar.
  - Un partido en dos familias del mismo año es un error de configuración.
  - Los años en estado `propuesta` se rechazan salvo permitir_propuesta=True
    (para exploración/notebooks, nunca para outputs a cliente).

Uso (reporte de cobertura + evidencia, escribe docs/familias_evidencia.md):
    python -m src.models.bloques.resolver_familia --reporte
"""
from __future__ import annotations

import argparse
import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_FAMILIAS = ROOT / "config" / "familias_partidarias.yaml"
CONFIG_PARTIDOS = ROOT / "config" / "partidos.yaml"
SALIDA_EVIDENCIA = ROOT / "docs" / "familias_evidencia.md"


class PartidoSinClasificar(KeyError):
    pass


class ClasificacionNoValidada(RuntimeError):
    pass


@lru_cache
def _alias() -> dict[str, str]:
    with open(CONFIG_PARTIDOS, encoding="utf-8") as f:
        return yaml.safe_load(f)["alias"]


def normalizar_sigla(sigla: str) -> str:
    s = sigla.strip()
    return _alias().get(s, _alias().get(s.upper(), s))


@lru_cache
def tabla_ano(ano: int) -> tuple[str, dict[str, str]]:
    """(estado, {sigla: familia}) para un año. Valida que no haya duplicados."""
    with open(CONFIG_FAMILIAS, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if ano not in cfg["anos"]:
        raise ClasificacionNoValidada(f"No hay clasificación para {ano} en {CONFIG_FAMILIAS.name}")
    bloque = cfg["anos"][ano]
    familias_validas = set(cfg["familias"])
    mapa: dict[str, str] = {}
    for familia, partidos in bloque["clasificacion"].items():
        if familia not in familias_validas:
            raise ValueError(f"{ano}: familia '{familia}' no declarada en `familias`")
        for p in partidos:
            p = normalizar_sigla(p)
            if p in mapa:
                raise ValueError(f"{ano}: {p} está en dos familias ({mapa[p]} y {familia})")
            mapa[p] = familia
    return bloque["estado"], mapa


def familia(sigla: str, ano: int, permitir_propuesta: bool = False) -> str:
    estado, mapa = tabla_ano(ano)
    if estado != "vigente" and not permitir_propuesta:
        raise ClasificacionNoValidada(
            f"La clasificación {ano} está en estado '{estado}' — validarla en "
            f"{CONFIG_FAMILIAS.name} o usar permitir_propuesta=True solo para exploración"
        )
    s = normalizar_sigla(sigla)
    if s not in mapa:
        raise PartidoSinClasificar(f"{sigla} (normalizado: {s}) sin familia en {ano}")
    return mapa[s]


def asignar_familia(df: pd.DataFrame, ano: int, col_partido: str = "partido",
                    permitir_propuesta: bool = False) -> pd.DataFrame:
    """Agrega columna `familia`. Falla listando TODOS los partidos sin clasificar."""
    siglas = df[col_partido].dropna().unique()
    faltan = []
    mapa = {}
    for s in siglas:
        try:
            mapa[s] = familia(s, ano, permitir_propuesta)
        except PartidoSinClasificar:
            faltan.append(s)
    if faltan:
        raise PartidoSinClasificar(f"{ano}: sin familia -> {sorted(faltan)}")
    return df.assign(familia=df[col_partido].map(mapa))


# ---------------------------------------------------------------- reporte

def _evidencia(ano: int) -> pd.DataFrame:
    """Peso de cada partido en Câmara (voto y bancas si hay resultado; candidatos si no)
    y su coligação presidencial de 1ª vuelta, desde los datos crudos del TSE."""
    from src.etl.extract.tse_extractor import ultima_version
    from src.etl.transform.lector_tse import leer_zip_tse

    ordinaria = {"NM_TIPO_ELEICAO": {"Eleição Ordinária"}}
    dep = {**ordinaria, "DS_CARGO": {"DEPUTADO FEDERAL"}}

    cand = leer_zip_tse(ultima_version("candidatos", ano),
                        columnas=["SG_PARTIDO", "DS_SIT_TOT_TURNO"], filtro=dep)
    cand["SG_PARTIDO"] = cand["SG_PARTIDO"].map(normalizar_sigla)
    t = pd.DataFrame({"candidatos_camara": cand.groupby("SG_PARTIDO").size()})
    electos = cand[cand["DS_SIT_TOT_TURNO"].str.startswith("ELEITO", na=False)]
    if len(electos):
        t["bancas"] = electos.groupby("SG_PARTIDO").size()

    try:
        part = leer_zip_tse(ultima_version("resultados_partido", ano),
                            columnas=["SG_PARTIDO", "QT_TOTAL_VOTOS_LEG_VALIDOS"], filtro=dep)
        part["SG_PARTIDO"] = part["SG_PARTIDO"].map(normalizar_sigla)
        v = pd.to_numeric(part["QT_TOTAL_VOTOS_LEG_VALIDOS"]).groupby(part["SG_PARTIDO"]).sum()
        t["voto_camara_pct"] = v / v.sum() * 100
    except FileNotFoundError:
        pass

    col = leer_zip_tse(ultima_version("coligaciones", ano),
                       columnas=["SG_PARTIDO", "DS_COMPOSICAO_COLIGACAO", "NR_TURNO"],
                       filtro={**ordinaria, "DS_CARGO": {"PRESIDENTE"}})
    col = col[col["NR_TURNO"] == "1"]
    col["SG_PARTIDO"] = col["SG_PARTIDO"].map(normalizar_sigla)
    t["coligacao_presidencial"] = col.groupby("SG_PARTIDO")["DS_COMPOSICAO_COLIGACAO"].first()
    return t


def reporte() -> None:
    with open(CONFIG_FAMILIAS, encoding="utf-8") as f:
        anos = sorted(yaml.safe_load(f)["anos"], reverse=True)

    lineas = ["# Evidencia de clasificación partido → familia", "",
              "Generado por `python -m src.models.bloques.resolver_familia --reporte`. "
              "No editar a mano. Fuente: TSE (consulta_cand, consulta_coligacao, "
              "votacao_partido_munzona), solo elección ordinaria.", ""]
    hay_faltantes = False
    for ano in anos:
        estado, mapa = tabla_ano(ano)
        ev = _evidencia(ano)
        ev["familia"] = [mapa.get(p, "**SIN CLASIFICAR**") for p in ev.index]
        faltan = ev[ev["familia"] == "**SIN CLASIFICAR**"]
        sobran = sorted(set(mapa) - set(ev.index))
        hay_faltantes |= len(faltan) > 0

        orden = "voto_camara_pct" if "voto_camara_pct" in ev else "candidatos_camara"
        ev = ev.sort_values(orden, ascending=False)
        lineas += [f"## {ano} — estado: `{estado}`", ""]
        if "voto_camara_pct" in ev:
            cub = ev.loc[ev["familia"] != "**SIN CLASIFICAR**", "voto_camara_pct"].sum()
            lineas.append(f"Cobertura del voto válido a Câmara: **{cub:.2f}%**.")
            por_fam = ev.groupby("familia")[["voto_camara_pct"] + (["bancas"] if "bancas" in ev else [])].sum()
            lineas += ["", por_fam.sort_values("voto_camara_pct", ascending=False).to_markdown(floatfmt=".2f"), ""]
        if len(faltan):
            lineas.append(f"Partidos con candidatos y sin familia: {', '.join(faltan.index)}.")
        if sobran:
            lineas.append(f"Clasificados pero sin candidatos a Câmara ese año: {', '.join(sobran)}.")
        ev["coligacao_presidencial"] = ev["coligacao_presidencial"].fillna("").str.slice(0, 70)
        lineas += ["", ev.to_markdown(floatfmt=".2f"), ""]
        log.info("%d (%s): %d partidos, %d sin clasificar, %d clasificados sin candidatos",
                 ano, estado, len(ev), len(faltan), len(sobran))

    SALIDA_EVIDENCIA.write_text("\n".join(lineas), encoding="utf-8")
    log.info("Escrito %s", SALIDA_EVIDENCIA)
    if hay_faltantes:
        raise SystemExit("Hay partidos sin clasificar — ver reporte.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reporte", action="store_true")
    args = parser.parse_args()
    if args.reporte:
        reporte()


if __name__ == "__main__":
    main()
