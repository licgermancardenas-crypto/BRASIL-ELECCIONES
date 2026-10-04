# -*- coding: utf-8 -*-
"""Conteo en vivo de la 1ª vuelta presidencial 2026 (TSE) y proyección del final.

Baja el JSON de divulgación del TSE por UF (más el exterior, "zz"), guarda la
foto cruda con fecha y proyecta el resultado final.

Proyección: dentro de cada UF, las secciones que faltan votan como las ya
contadas y tienen el mismo tamaño medio. El total nacional es la suma de las UF
escaladas por 100 / %secciones contadas. Esto corrige el sesgo de orden del
conteo entre regiones (el Nordeste suele contar más tarde), pero no el de
dentro de cada UF (interior vs. capital).

    python -m src.models.conteo_2026 [--municipios]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parents[2]
RAW = RAIZ / "data" / "raw" / "tse" / "resultados" / "2026_1v_divulgacion"
SALIDA = RAIZ / "data" / "processed" / "electoral" / "conteo_presidencial_2026_1v.json"
SALIDA_MUN = RAIZ / "data" / "processed" / "electoral" / "conteo_presidencial_2026_1v_municipios.parquet"

ELEICAO = "6257"  # Eleição Ordinária Federal 2026, 1º turno (comum/config/ele-c.json)
BASE = "https://resultados.tse.jus.br/oficial/ele2026/{e}"
URL = BASE + "/dados/{uf}/{uf}-c0001-e{e:0>6}-u.json"
URL_MUN = BASE + "/dados/{uf}/{uf}{mu}-c0001-e{e:0>6}-u.json"
URL_CONFIG_MUN = BASE + "/config/mun-e{e:0>6}-cm.json"
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa",
       "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]
CLAVES = {"FLAVIO BOLSONARO": "flavio_bolsonaro", "LULA": "lula", "RENAN SANTOS": "renan_santos",
          "ESCRITOR AUGUSTO CURY": "cury", "RONALDO CAIADO": "caiado", "ZEMA": "zema"}


def _num(s):
    return float(s.replace(",", "."))


def _get(url, intentos=4):
    for i in range(intentos):
        try:
            with urlopen(Request(url, headers={"User-Agent": "atlas-analytics"}), timeout=60) as r:
                return r.read()
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(2 * (i + 1))


def bajar(uf):
    return uf, _get(URL.format(e=ELEICAO, uf=uf))


def municipios(carpeta):
    """Una fila por municipio (código IBGE) con lo contado hasta ahora."""
    import pandas as pd
    cfg = json.loads(_get(URL_CONFIG_MUN.format(e=ELEICAO)))
    lista = [(a["cd"], m["cd"], m["cdi"]) for a in cfg["abr"] if a["cd"] != "zz" for m in a["mu"]]
    # incremental: los municipios ya completos no se vuelven a pedir (el TSE
    # corta pedidos en la noche de la elección)
    previo = pd.read_parquet(SALIDA_MUN) if SALIDA_MUN.exists() else pd.DataFrame(
        columns=["uf", "codigo", "pct_secciones", "validos", "flavio", "lula"])
    completos = set(previo.loc[previo.pct_secciones >= 100, "codigo"].astype(int))
    pedir = [t for t in lista if int(t[2]) not in completos]

    def uno(t):
        uf, mu, ibge = t
        try:
            return uf, ibge, leer(_get(URL_MUN.format(e=ELEICAO, uf=uf, mu=mu)))
        except Exception:
            return uf, ibge, None

    with ThreadPoolExecutor(6) as ex:
        filas = list(ex.map(uno, pedir))
    out = []
    for uf, ibge, r in filas:
        if r is None:
            continue
        v = r["votos"]
        vv = r["validos_contados"]
        out.append({"uf": uf.upper(), "codigo": int(ibge), "pct_secciones": r["pct_secciones"],
                    "validos": vv, "flavio": v.get("flavio_bolsonaro", 0), "lula": v.get("lula", 0)})
    nuevo = pd.DataFrame(out)
    viejo = previo[~previo.codigo.astype(int).isin(set(nuevo.codigo))] if len(nuevo) else previo
    df = pd.concat([viejo, nuevo], ignore_index=True)
    df.to_parquet(SALIDA_MUN, index=False)
    (carpeta / "municipios.json").write_text(df.to_json(orient="records"), encoding="utf-8")
    print(f"municipios: {len(nuevo)} de {len(pedir)} pedidos; total {len(df)} de {len(lista)}, {int((df.validos > 0).sum())} con votos")


def leer(crudo):
    d = json.loads(crudo)
    votos = {}
    for agr in d["carg"][0]["agr"]:
        for par in agr["par"]:
            for c in par["cand"]:
                votos[CLAVES.get(c["nmu"], "otros")] = votos.get(CLAVES.get(c["nmu"], "otros"), 0) + int(c["vap"])
    return {
        "hora_tse": f'{d["dg"]} {d["hg"]}',
        "pct_secciones": _num(d["s"]["pst"]),
        "secciones": int(d["s"]["ts"]),
        "secciones_contadas": int(d["s"]["st"]),
        "validos_contados": int(d["v"]["vv"]),
        "votos": votos,
    }


def proyectar(ufs):
    tot, cont = {}, {}
    for r in ufs.values():
        k = 100 / r["pct_secciones"] if r["pct_secciones"] else 0
        for c, v in r["votos"].items():
            tot[c] = tot.get(c, 0) + v * k
            cont[c] = cont.get(c, 0) + v
    vt, vc = sum(tot.values()), sum(cont.values())
    secc = sum(r["secciones"] for r in ufs.values())
    secc_c = sum(r["secciones_contadas"] for r in ufs.values())
    return {
        "pct_secciones_contadas": round(100 * secc_c / secc, 2),
        "contado_pct": {c: round(100 * v / vc, 2) for c, v in sorted(cont.items())},
        "proyeccion_pct": {c: round(100 * v / vt, 2) for c, v in sorted(tot.items())},
    }


def main():
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    carpeta = RAW / sello
    carpeta.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        crudos = dict(ex.map(bajar, UFS))
    ufs = {}
    for uf, crudo in crudos.items():
        (carpeta / f"{uf}.json").write_bytes(crudo)
        ufs[uf] = leer(crudo)
    res = {"eleicao_tse": ELEICAO, "descarga_utc": sello, "fuente": str(carpeta.relative_to(RAIZ)),
           **proyectar(ufs), "por_uf": ufs}
    SALIDA.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{res['pct_secciones_contadas']}% secciones · contado {res['contado_pct']}")
    print(f"proyección {res['proyeccion_pct']}")
    if "--municipios" in sys.argv:
        municipios(carpeta)


if __name__ == "__main__":
    main()
