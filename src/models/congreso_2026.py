"""
src/models/congreso_2026.py

El Congreso que sale del 4/10/2026: Câmara (513) y Senado (54 en juego + 27
que siguen), contra el Montecarlo de bancas del 1/10 y frente a los umbrales
que necesita el próximo presidente.

  1. Resultado oficial (TSE, elección estadual 6259): electos de Deputado
     Federal (cargo 0006) y Senador (0005) por UF, con partido y família
     (config/familias_partidarias.yaml, año 2026, mismo resolver del modelo).
  2. Pronóstico vs. resultado: bancas por família contra la distribución de
     las simulaciones del 1/10 (percentil del resultado, p10–p90).
  3. Gobernabilidad: bancas de cada coalición posible para Flávio y para Lula
     contra mayoría absoluta, 3/5 (enmienda constitucional) y el tercio que
     bloquea (juicio político / PEC).

Salida: data/processed/electoral/congreso_2026/<fecha_utc>/
    resumen.json, electos.csv, bancas_partido.csv, meta.json

Uso:
    python -m src.models.congreso_2026
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from src.models.bloques.resolver_familia import familia, normalizar_sigla
from src.models.conteo_2026 import UFS, _get
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, LEGISLATIVO_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "congreso_2026"
URL = "https://resultados.tse.jus.br/oficial/ele2026/6259/dados/{uf}/{uf}-c{cargo}-e006259-u.json"
CARGOS = {"camara": "0006", "senado": "0005"}
# mayoria: mayoría absoluta (leyes complementarias); pec_3_5: enmienda constitucional (dos turnos en cada casa);
# dos_tercios: admitir (Câmara) o condenar (Senado) en un juicio político; bloqueo_pec / bloqueo_juicio: bancas
# que alcanzan para impedir una enmienda o un juicio político votando en contra.
UMBRALES = {"camara": {"total": 513, "mayoria": 257, "pec_3_5": 308, "dos_tercios": 342, "bloqueo_pec": 206,
                       "bloqueo_juicio": 172},
            "senado": {"total": 81, "mayoria": 41, "pec_3_5": 49, "dos_tercios": 54, "bloqueo_pec": 33,
                       "bloqueo_juicio": 28}}
# Coaliciones posibles del próximo gobierno, de la más estrecha a la más amplia.
COALICIONES = {
    "flavio": [("Núcleo bolsonarista", ["direita_bolsonarista"]),
               ("+ Centrão", ["direita_bolsonarista", "centrao"]),
               ("+ centro liberal", ["direita_bolsonarista", "centrao", "centro_liberal"])],
    "lula": [("Base de gobierno", ["gobierno_lula"]),
             ("+ Centrão", ["gobierno_lula", "centrao"]),
             ("+ centro liberal", ["gobierno_lula", "centrao", "centro_liberal"])],
}


def fam(sigla: str) -> str:
    try:
        return familia(normalizar_sigla(sigla), 2026)
    except KeyError:
        log.warning("%s sin família en 2026: va a sin_alineamiento", sigla)
        return "sin_alineamiento"


def bajar(cargo: str) -> pd.DataFrame:
    def uno(uf):
        d = json.loads(_get(URL.format(uf=uf, cargo=CARGOS[cargo])))
        c = d["carg"][0]
        filas = []
        for a in c["agr"]:
            for p in a["par"]:
                for x in p["cand"]:
                    filas.append({"uf": uf.upper(), "nombre": x["nmu"], "partido": p["sg"], "votos": int(x["vap"]),
                                  "situacion": x["st"], "electo": x["e"] == "s"})
        return pd.DataFrame(filas).assign(pct_secciones=float(d["s"]["pst"].replace(",", ".")))

    with ThreadPoolExecutor(8) as ex:
        df = pd.concat(ex.map(uno, [u for u in UFS if u != "zz"]), ignore_index=True)
    df["familia"] = df["partido"].map(fam)
    return df


def ultima(base):
    return sorted(p for p in base.iterdir() if (p / "resumen.csv").exists())[-1]


def percentil(sim: pd.DataFrame, fam_: str, valor: int) -> float:
    s = sim[sim["familia"] == fam_]["bancas"]
    return float(((s < valor).mean() + 0.5 * (s == valor).mean()) * 100) if len(s) else float("nan")


def main() -> None:
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)

    cam, sen = bajar("camara"), bajar("senado")
    el_c, el_s = cam[cam["electo"]], sen[sen["electo"]]
    log.info("Câmara: %d electos (secciones %.1f%%); Senado: %d electos", len(el_c), cam["pct_secciones"].min(), len(el_s))
    assert len(el_c) == 513, f"la Câmara tiene {len(el_c)} electos"
    pd.concat([el_c.assign(casa="camara"), el_s.assign(casa="senado")]).to_csv(out / "electos.csv", index=False)

    # Senado: 27 que siguen (del modelo del 1/10, partido según la API del Senado)
    sen_dir = ultima(LEGISLATIVO_DIR / "senado")
    siguen = pd.read_csv(sen_dir / "senadores_que_siguen.csv")
    bancas = {
        "camara": el_c.groupby("familia").size(),
        "senado_en_juego": el_s.groupby("familia").size(),
        "senado_siguen": siguen.groupby("familia").size(),
    }
    bancas["senado"] = bancas["senado_en_juego"].add(bancas["senado_siguen"], fill_value=0).astype(int)
    partido = pd.DataFrame({"camara": el_c.groupby("partido").size(),
                            "senado_electos": el_s.groupby("partido").size()}).fillna(0).astype(int)
    partido["familia"] = partido.index.map(fam)
    partido.sort_values("camara", ascending=False).to_csv(out / "bancas_partido.csv")
    votos_fam = (cam.groupby("familia")["votos"].sum() / cam["votos"].sum() * 100)

    # Pronóstico del 1/10 contra resultado
    cam_dir = ultima(LEGISLATIVO_DIR / "camara")
    sim_c = pd.read_parquet(cam_dir / "bancas_familia_simulacion.parquet")
    res_c = pd.read_csv(cam_dir / "resumen.csv").set_index("familia")
    sim_s = pd.read_parquet(sen_dir / "bancas_familia_simulacion.parquet")
    sim_s = sim_s[sim_s["tipo"] == "total"]   # el parquet trae "en_juego" y "total" (en juego + los 27 que siguen)
    res_s = pd.read_csv(sen_dir / "resumen.csv").set_index("familia")
    comp = {}
    for f in res_c.index:
        comp[f] = {
            "camara": {"real": int(bancas["camara"].get(f, 0)), "mediana": float(res_c.loc[f, "mediana"]),
                       "p10": float(res_c.loc[f, "p10"]), "p90": float(res_c.loc[f, "p90"]),
                       "percentil": percentil(sim_c, f, int(bancas["camara"].get(f, 0)))},
            "senado": {"real": int(bancas["senado"].get(f, 0)), "mediana": float(res_s.loc[f, "total_mediana"]),
                       "p10": float(res_s.loc[f, "total_p10"]), "p90": float(res_s.loc[f, "total_p90"]),
                       "percentil": percentil(sim_s, f, int(bancas["senado"].get(f, 0)))},
            "votos_camara_pct": float(votos_fam.get(f, 0)),
        }

    gob = {}
    for pres, coal in COALICIONES.items():
        gob[pres] = []
        for nombre, fams in coal:
            fila = {"coalicion": nombre, "familias": fams}
            for casa in ("camara", "senado"):
                n = int(sum(bancas[casa].get(f, 0) for f in fams))
                u = UMBRALES[casa]
                fila[casa] = {"bancas": n, **{k: n >= v for k, v in u.items() if k != "total"},
                              "falta_mayoria": max(u["mayoria"] - n, 0), "falta_pec": max(u["pec_3_5"] - n, 0)}
            gob[pres].append(fila)

    resumen = {"bancas": {k: {f: int(v) for f, v in s.items()} for k, s in bancas.items()},
               "partidos_top": partido.sort_values("camara", ascending=False).head(12).reset_index()
               .rename(columns={"index": "partido"}).to_dict(orient="records"),
               "pronostico_vs_resultado": comp, "gobernabilidad": gob, "umbrales": UMBRALES,
               "corridas_modelo": {"camara": cam_dir.name, "senado": sen_dir.name},
               "senado_electos": el_s[["uf", "nombre", "partido", "familia", "votos"]].to_dict(orient="records")}
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"fecha_utc": sello}), encoding="utf-8")
    log.info("bancas:\n%s", pd.DataFrame(bancas).fillna(0).astype(int).to_string())
    log.info("pronóstico vs resultado:\n%s", pd.DataFrame({f: {"cam_real": v["camara"]["real"], "cam_med": v["camara"]["mediana"],
                                                               "cam_pct": round(v["camara"]["percentil"]),
                                                               "sen_real": v["senado"]["real"], "sen_med": v["senado"]["mediana"],
                                                               "sen_pct": round(v["senado"]["percentil"])}
                                                           for f, v in comp.items()}).T.to_string())
    for pres, filas in gob.items():
        for f in filas:
            log.info("%s %-20s Câmara %3d  Senado %2d", pres, f["coalicion"], f["camara"]["bancas"], f["senado"]["bancas"])
    log.info("salida %s", out)


if __name__ == "__main__":
    main()
