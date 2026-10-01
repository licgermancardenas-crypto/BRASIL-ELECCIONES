"""
src/etl/transform/encuestas_resultados.py

Lleva las tablas de encuestas presidenciales de Wikipedia (raw de
src/etl/extract/wikipedia_extractor.py) a formato largo: una fila por
encuesta × cruce × candidato, con la casa canónica de config/encuestadoras.yaml
y la família del partido del candidato.

Qué tablas y columnas se leen: config/encuestas_wikipedia.yaml.

Columnas de salida:
  ano, vuelta, id_encuesta, escenario, antes_primera_vuelta, encuestadora_wiki,
  casa, fecha_inicio, fecha_fin, muestra, candidato, partido, familia, pct,
  pct_no_validos
`antes_primera_vuelta`: en 2ª vuelta, cruce medido antes de la 1ª (lo único
que hay en 2026 antes del 4/10; en 2018/2022 mide el error de ese tipo de
cruce contra el resultado del balotaje).
`candidato` = "otros" para la columna Others (1ª vuelta). `escenario` = ids
de los candidatos con dato, ordenados y unidos por "|" (en 2ª vuelta, el cruce).
`pct` es el número publicado (sobre el total, con indecisos); el paso a votos
válidos lo hace el agregador.

Se descartan, con conteo en el log: filas de resultado oficial, filas de
eventos (debates), filas sin fecha o sin ningún candidato con dato.

Input:  data/raw/encuestas_wikipedia/{ano}/<version>/encuestas_presidenciales_{ano}.json
Output: data/processed/electoral/encuestas_resultados.parquet

Uso:
    python -m src.etl.transform.encuestas_resultados --ano 2018 2022 2026
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from src.etl.extract.wikipedia_extractor import ultima_version
from src.models.bloques.resolver_familia import familia, normalizar_sigla

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_TABLAS = ROOT / "config" / "encuestas_wikipedia.yaml"
CONFIG_CASAS = ROOT / "config" / "encuestadoras.yaml"
SALIDA = ROOT / "data" / "processed" / "electoral" / "encuestas_resultados.parquet"

MESES = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def normalizar(texto: str) -> str:
    """Minúscula, sin acentos, sin notas al pie [x] ni 'Archived ...'."""
    texto = re.sub(r"\[[^\]]*\]", "", str(texto))
    texto = re.sub(r"archived .*$", "", texto, flags=re.IGNORECASE)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


def etiqueta(col) -> str:
    """Encabezado de una columna de read_html: el primer nivel que no es 'Unnamed'."""
    niveles = col if isinstance(col, tuple) else (col,)
    texto = next((str(x) for x in niveles if not str(x).startswith("Unnamed")), "?")
    return re.sub(r"\s*\[[^\]]*\]", "", texto).strip()


@lru_cache
def _alias_casas() -> dict[str, str]:
    with open(CONFIG_CASAS, encoding="utf-8") as f:
        casas = yaml.safe_load(f)["casas"]
    return {alias: casa for casa, cfg in casas.items() for alias in cfg.get("alias_wikipedia", [])}


def casa_canonica(nombre_wiki: str) -> str:
    """Casa de config/encuestadoras.yaml. 'Genial/Quaest' -> se prueba cada parte
    (el medio que contrata no es la casa). Sin alias -> slug del nombre."""
    nombre = normalizar(nombre_wiki)
    alias = _alias_casas()
    for parte in [nombre] + [p.strip() for p in nombre.split("/")]:
        if parte in alias:
            return alias[parte]
    return "wiki_" + re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")


def parsear_periodo(texto: str, ano: int) -> tuple[date, date] | None:
    """'27–29 Sep', '30 Sep – 1 Oct', '2–5 October 2018', '24 October 2018' -> (inicio, fin)."""
    t = normalizar(re.sub("[‒-―−]", "-", str(texto)))
    anos = re.findall(r"\b(\d{4})\b", t)
    if anos:  # las tablas largas mezclan años (2017 en la página de 2018)
        ano = int(anos[-1])
    t = re.sub(r"\b\d{4}\b", "", t).strip()
    partes = [p.strip() for p in t.split("-") if p.strip()]
    if not 1 <= len(partes) <= 2:
        return None

    def dia_mes(p: str) -> tuple[int, int | None] | None:
        m = re.fullmatch(r"(\d{1,2})(?:\s+([a-z]+))?", p)
        if not m:
            return None
        mes = MESES.get(m.group(2)[:3]) if m.group(2) else None
        if m.group(2) and mes is None:
            return None
        return int(m.group(1)), mes

    fin = dia_mes(partes[-1])
    ini = dia_mes(partes[0])
    if fin is None or ini is None or fin[1] is None:
        return None
    try:
        f_fin = date(ano, fin[1], fin[0])
        f_ini = date(ano, ini[1] or fin[1], ini[0])
    except ValueError:
        return None
    if f_ini > f_fin:  # '30 Dec – 2 Jan' no ocurre en campaña: dato raro, se descarta
        return None
    return f_ini, f_fin


def numero(valor, nombre: str | None = None) -> float | None:
    """'39', '39.4', '34%', '44,87%' -> float; 'N/a', '–', vacío -> None.
    Con `nombre`, la celda debe decir '41% (Nombre)' (tablas de cruces por
    partido, donde el candidato del partido cambia en el tiempo); si no, None."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    t = re.sub(r"\[[^\]]*\]", "", str(valor))
    entre_parentesis = re.search(r"\(([^)]*)\)", t)
    if nombre is not None and (entre_parentesis is None or normalizar(entre_parentesis.group(1)) != nombre):
        return None
    t = re.sub(r"\([^)]*\)", "", t).replace("%", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


def muestra(valor) -> int | None:
    t = re.sub(r"\[[^\]]*\]", "", str(valor)).replace(",", "").replace(".", "").strip()
    return int(t) if t.isdigit() else None


def leer_tabla(tabla: pd.DataFrame, ano: int, cfg_tabla: dict, cfg_ano: dict, cfg_cols: dict) -> tuple[pd.DataFrame, dict]:
    vuelta, indice = cfg_tabla["vuelta"], cfg_tabla["indice"]
    candidatos = {**cfg_ano["candidatos"], **cfg_tabla.get("candidatos", {})}
    etiquetas = [etiqueta(c) for c in tabla.columns]
    roles: dict[int, tuple[str, dict | None]] = {}
    for i, et in enumerate(etiquetas):
        if et in candidatos:
            roles[i] = ("candidato", candidatos[et])
            continue
        if et in cfg_tabla.get("ignorar", []):
            roles[i] = ("ignorar", None)
            continue
        low = normalizar(et)
        rol = next((r for r in ("encuestadora", "periodo", "muestra", "otros", "no_validos", "ignorar")
                    if re.search(cfg_cols[r], low)), None)
        if rol is None:
            raise ValueError(f"{ano} tabla {indice}: columna sin rol '{et}' — agregarla a "
                             f"config/encuestas_wikipedia.yaml")
        roles[i] = (rol, None)
    for rol in ("encuestadora", "periodo"):
        if sum(r == rol for r, _ in roles.values()) != 1:
            raise ValueError(f"{ano} tabla {indice}: se esperaba una columna '{rol}'")
    if not any(r == "candidato" for r, _ in roles.values()):
        raise ValueError(f"{ano} tabla {indice}: ningún candidato reconocido ({etiquetas})")

    col = {r: i for i, (r, _) in roles.items() if r != "candidato"}
    descartes = {"resultado": 0, "evento": 0, "sin_fecha": 0, "sin_datos": 0, "cruce_incompleto": 0}
    filas = []
    for n, fila in enumerate(tabla.itertuples(index=False)):
        nombre = str(fila[col["encuestadora"]])
        periodo = str(fila[col["periodo"]])
        if "result" in normalizar(nombre) or "result" in normalizar(periodo):
            descartes["resultado"] += 1
            continue
        if "muestra" in col and normalizar(fila[col["muestra"]]) == normalizar(periodo):
            descartes["evento"] += 1   # debates: la fila repite el texto en todas las celdas
            continue
        fechas = parsear_periodo(periodo, ano)
        if fechas is None:
            descartes["sin_fecha"] += 1
            continue
        valores = [(cfg, numero(fila[i], cfg.get("nombre_wiki"))) for i, (r, cfg) in roles.items()
                   if r == "candidato"]
        valores = [(cfg, v) for cfg, v in valores if v is not None]
        if not valores:
            descartes["sin_datos"] += 1
            continue
        if vuelta == 2 and len(valores) != 2:
            descartes["cruce_incompleto"] += 1   # el rival es un candidato sin mapear (ej. Lula 2018)
            continue
        otros = numero(fila[col["otros"]]) if "otros" in col else None
        no_validos = numero(fila[col["no_validos"]]) if "no_validos" in col else None
        n_muestra = muestra(fila[col["muestra"]]) if "muestra" in col else None
        escenario = "|".join(sorted(cfg["id"] for cfg, _ in valores))
        id_encuesta = f"{ano}-{vuelta}-t{indice}-f{n}"
        base = {"ano": ano, "vuelta": vuelta, "id_encuesta": id_encuesta, "escenario": escenario,
                "antes_primera_vuelta": vuelta == 1 or cfg_tabla.get("antes_primera_vuelta", False),
                "encuestadora_wiki": re.sub(r"\s*\[[^\]]*\]", "", nombre).strip(),
                "casa": casa_canonica(nombre), "fecha_inicio": fechas[0], "fecha_fin": fechas[1],
                "muestra": n_muestra, "pct_no_validos": no_validos}
        for cfg, v in valores:
            filas.append({**base, "candidato": cfg["id"], "partido": normalizar_sigla(cfg["partido"]), "pct": v})
        if otros is not None and vuelta == 1:
            filas.append({**base, "candidato": "otros", "partido": None, "pct": otros})
    return pd.DataFrame(filas), descartes


def transformar(anos: list[int]) -> pd.DataFrame:
    with open(CONFIG_TABLAS, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    partes = []
    for ano in anos:
        cfg_ano = cfg["anos"][ano]
        ruta = ultima_version(ano)
        manifest = json.loads((ruta.parent / "manifest.json").read_text(encoding="utf-8"))
        html = json.loads(ruta.read_text(encoding="utf-8"))["parse"]["text"]
        tablas = pd.read_html(io.StringIO(html))
        for t in cfg_ano["tablas"]:
            df, descartes = leer_tabla(tablas[t["indice"]], ano, t, cfg_ano, cfg["columnas"])
            df["revid_wikipedia"] = manifest["revid"]
            log.info("%d vuelta %d (tabla %d): %d encuestas×cruce, descartadas %s",
                     ano, t["vuelta"], t["indice"], df["id_encuesta"].nunique(), descartes)
            partes.append(df)
    df = pd.concat(partes, ignore_index=True)
    df["familia"] = [familia(p, a) if isinstance(p, str) else None for p, a in zip(df["partido"], df["ano"])]
    for c in ("fecha_inicio", "fecha_fin"):
        df[c] = pd.to_datetime(df[c])
    df["muestra"] = df["muestra"].astype("Int64")

    sin_casa = sorted(df.loc[df["casa"].str.startswith("wiki_"), "encuestadora_wiki"].unique())
    if sin_casa:
        log.warning("Encuestadoras sin alias en config/encuestadoras.yaml (quedan sin track record): %s", sin_casa)
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", nargs="+", type=int, default=[2018, 2022, 2026])
    args = parser.parse_args()
    df = transformar(args.ano)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SALIDA, index=False)
    log.info("Guardado %s (%d filas, %d encuestas×cruce)", SALIDA.relative_to(ROOT).as_posix(),
             len(df), df["id_encuesta"].nunique())


if __name__ == "__main__":
    main()
