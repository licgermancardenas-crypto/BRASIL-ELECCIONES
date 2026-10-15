"""
src/models/encuestas_balotaje_2026.py

Validación externa del pronóstico del balotaje (balotaje_2026, desde el TSE)
con las encuestas de 2ª vuelta publicadas DESPUÉS del 4/10. Las encuestas no
entran al modelo (decisión del 2026-10-07): son un control independiente.

  1. Track record por horizonte (2018 y 2022): el agregador de
     agregacion_encuestas, solo con encuestas posteriores a la 1ª vuelta,
     cortado D días antes del balotaje (D = 1..20), contra el resultado real.
     Mide el sesgo y el error según cuánto falta, y cuánto se movió el
     electorado en los últimos días.
  2. Agregado 2026 al corte (house effects, peso de calidad de 2018/2022,
     decaimiento) y tendencia desde el 4/10 (regresión ponderada sobre la
     fecha de campo, y cambio dentro de la misma casa).
  3. Corrección de sesgo con el error del agregador en 2018/2022 al MISMO
     horizonte, SOLO si los dos años erraron en la misma dirección (la regla
     de `corregir_sesgo_historico` para la 1ª vuelta: sesgo repetido). En los
     balotajes no pasa: 2018 subestimó al PT (giro tardío a Haddad) y 2022
     lo sobreestimó; entonces el error entra solo como varianza (t de
     Student) y las dos correcciones quedan como variantes.
  4. Contraste con el modelo: diferencia, z, y la síntesis por precisión
     (media ponderada por 1/varianza) como lectura conjunta.
  5. Lo que las encuestas implican para el modelo: qué proporción de los
     terceros a Lula (uniforme) reproduciría el número de las encuestas.

Salida: data/processed/electoral/encuestas_balotaje_2026/<fecha_utc>/
    resumen.json, horizonte.csv, encuestas.csv, house_effects.csv

Uso:
    python -m src.models.encuestas_balotaje_2026 [--corte 2026-10-15]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.etl.transform.encuestas_resultados import SALIDA as ENCUESTAS
from src.models.agregacion_encuestas import (a_validos, agregar, errores_finales, fechas_eleccion,
                                             resultado_nacional, track_record)
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.montecarlo.proyeccion_bancas import ELECTORAL_DIR, cargar_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SALIDA_DIR = ELECTORAL_DIR / "encuestas_balotaje_2026"
# Candidato del PT (lado Lula) y rival bolsonarista en cada balotaje.
CRUCE = {2018: ("haddad", "bolsonaro"), 2022: ("lula", "bolsonaro"), 2026: ("lula", "flavio_bolsonaro")}
HORIZONTES = list(range(1, 21))


def ultima_corrida_balotaje():
    return sorted(p.parent for p in BALOTAJE_DIR.glob("*/meta.json"))[-1]


def post_1v(largo: pd.DataFrame, ano: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    pt, rival = CRUCE[ano]
    d = largo[(largo["ano"] == ano) & (largo["vuelta"] == 2) & (~largo["antes_primera_vuelta"])
              & (largo["escenario"] == "|".join(sorted([pt, rival])))]
    return a_validos(d)


def pesos_calidad(largo: pd.DataFrame, anos: list[int], cfg: dict) -> dict:
    if not anos:
        return {}
    errs = pd.concat([errores_finales(largo, a, cfg["ventana_final_dias"]) for a in anos])
    tr, _ = track_record(errs, cfg["shrink_track_record"])
    return dict(zip(tr["casa"], tr["peso_calidad"]))


def horizonte(largo: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Error del agregador (solo post-1ª vuelta) cortado D días antes del balotaje, 2018 y 2022."""
    filas = []
    for ano in (2018, 2022):
        pt, _ = CRUCE[ano]
        pesos = pesos_calidad(largo, [a for a in (2018, 2022) if a < ano], cfg)
        real = float(resultado_nacional(ano).query("vuelta == 2 and candidato == @pt")["pct"].iloc[0]) * 100
        meta, val = post_1v(largo, ano)
        f2 = fechas_eleccion(ano)[2]
        for D in HORIZONTES:
            corte = f2 - timedelta(days=D)
            antes = meta["fecha_fin"].dt.date <= corte
            if antes.sum() < 2:
                continue
            a = agregar(meta[antes], val[antes], corte, pesos, cfg)
            filas.append({"ano": ano, "dias_antes": D, "corte": corte, "n_encuestas": a["n_encuestas"],
                          "agregado_pt": a["estimacion"][pt] * 100, "promedio_simple_pt": a["promedio_simple"][pt] * 100,
                          "real_pt": real, "error_pp": a["estimacion"][pt] * 100 - real})
    return pd.DataFrame(filas)


def tendencia(meta: pd.DataFrame, val: pd.DataFrame, pt: str, inicio: date) -> dict:
    """Pendiente (pts/día) del % Lula en válidos sobre la fecha de campo, MCO ponderado por muestra."""
    x = (meta["fecha_fin"] - pd.Timestamp(inicio)).dt.days.to_numpy(float)
    y = val[pt].to_numpy() * 100
    w = np.minimum(meta["muestra"].astype(float).fillna(2000).to_numpy(), 3000)
    X = np.column_stack([np.ones_like(x), x])
    W = np.diag(w / w.mean())
    beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ y)
    resid = y - X @ beta
    # error estándar HC1 (heterocedasticidad entre casas)
    n, k = X.shape
    bread = np.linalg.inv(X.T @ W @ X)
    meat = X.T @ W @ np.diag(resid ** 2) @ W @ X
    cov = bread @ meat @ bread * n / (n - k)
    se = float(np.sqrt(cov[1, 1]))
    # Spearman entre fecha y % Lula (no paramétrico)
    rho = float(pd.Series(x).rank().corr(pd.Series(y).rank()))
    return {"pendiente_pts_por_dia": float(beta[1]), "se": se, "t": float(beta[1] / se) if se else None,
            "spearman": rho, "n": int(n), "dispersion_entre_encuestas_pp": float(np.std(y, ddof=1))}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corte", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    cfg_all = cargar_config()
    cfg = cfg_all["encuestas"]
    rng = np.random.default_rng(cfg_all["balotaje"]["random_seed"])
    largo = pd.read_parquet(ENCUESTAS)

    # 1 · Track record por horizonte
    hz = horizonte(largo, cfg)
    f2 = fechas_eleccion(2026)[2]
    D_hoy = max((f2 - args.corte).days, 1)
    D_ref = min(HORIZONTES, key=lambda D: abs(D - D_hoy))
    en_D = hz[hz["dias_antes"] == D_ref]
    sesgo = float(en_D["error_pp"].mean())
    # desvío: RMS de los dos errores al horizonte de hoy, con piso = error medio de
    # la industria (las dos elecciones son pocas para un desvío confiable)
    rms_D = float(np.sqrt((en_D["error_pp"] ** 2).mean()))
    movimiento_final = (hz[hz["dias_antes"] == 1].set_index("ano")["agregado_pt"]
                        - en_D.set_index("ano")["agregado_pt"]).to_dict()
    log.info("horizonte D=%d: sesgo PT %+.2f pp, RMS %.2f; movimiento D->1: %s", D_ref, sesgo, rms_D,
             {k: round(v, 2) for k, v in movimiento_final.items()})

    # 2 · Agregado 2026
    pesos = pesos_calidad(largo, [2018, 2022], cfg)
    meta, val = post_1v(largo, 2026)
    meta = meta[meta["fecha_fin"].dt.date <= args.corte]
    val = val.loc[meta.index]
    a = agregar(meta, val, args.corte, pesos, cfg)
    lula_agr = float(a["estimacion"]["lula"]) * 100
    tend = tendencia(meta, val, "lula", fechas_eleccion(2026)[1])
    misma_casa = {}
    for casa, g in meta.groupby("casa"):
        if len(g) > 1:
            g = g.sort_values("fecha_fin")
            v = val.loc[g.index, "lula"] * 100
            misma_casa[casa] = {"de": str(g["fecha_fin"].iloc[0].date()), "a": str(g["fecha_fin"].iloc[-1].date()),
                                "lula_de": float(v.iloc[0]), "lula_a": float(v.iloc[-1]),
                                "cambio_pp": float(v.iloc[-1] - v.iloc[0])}
    encuestas = meta[["casa", "encuestadora_wiki", "fecha_fin", "muestra"]].assign(
        lula_validos=val["lula"] * 100, flavio_validos=val["flavio_bolsonaro"] * 100,
        peso=a["ponderacion"]["peso"].to_numpy(), peso_calidad=a["ponderacion"]["peso_calidad"].to_numpy()
    ).sort_values("fecha_fin")
    log.info("agregado 2026 al %s: Lula %.2f (simple %.2f, sin HE %.2f), n_ef %.1f, tendencia %+.3f pts/día (t %.2f)",
             args.corte, lula_agr, a["promedio_simple"]["lula"] * 100, a["sin_house_effect"]["lula"] * 100,
             a["n_efectivo"], tend["pendiente_pts_por_dia"], tend["t"])

    # 3 · Corrección de sesgo y distribución de las encuestas
    piso = 1.5
    sd_enc = float(np.sqrt(rms_D ** 2 - sesgo ** 2 + piso ** 2))  # dispersión alrededor del sesgo + piso
    gl = cfg_all["balotaje"]["grados_libertad_t"]
    n = cfg_all["balotaje"]["n_simulaciones"]
    t = rng.standard_t(gl, n) / np.sqrt(gl / (gl - 2))
    errores = en_D["error_pp"].to_numpy()
    corregir = bool(np.all(errores > 0) or np.all(errores < 0))
    variantes = {f"como_{int(r.ano)}": lula_agr - r.error_pp for r in en_D.itertuples()}
    variantes["sin_corregir"] = lula_agr
    variantes["sesgo_medio"] = lula_agr - sesgo
    dist = {k: v + sd_enc * t for k, v in variantes.items()}

    # 4 · Contraste con el modelo
    corrida = ultima_corrida_balotaje()
    res_mod = json.loads((corrida / "resumen.json").read_text(encoding="utf-8"))
    sim_mod = np.load(corrida / "lula_nacional_sim.npy")
    mu_m, sd_m = float(sim_mod.mean()), float(sim_mod.std())
    mu_e = lula_agr - sesgo if corregir else lula_agr
    enc = mu_e + sd_enc * t
    dif = mu_e - mu_m
    z = dif / np.sqrt(sd_m ** 2 + sd_enc ** 2)
    w_m, w_e = 1 / sd_m ** 2, 1 / sd_enc ** 2
    mu_s = (w_m * mu_m + w_e * mu_e) / (w_m + w_e)
    sd_s = float(np.sqrt(1 / (w_m + w_e)))
    sint = mu_s + sd_s * rng.standard_t(gl, n) / np.sqrt(gl / (gl - 2))

    # 5 · Proporción uniforme de terceros a Lula que reproduce el número de las encuestas
    sens = pd.DataFrame(res_mod["sensibilidad"])
    pend = np.polyfit(sens["a_lula_terceros"], sens["lula_pct"], 1)
    implicita = {k: float((v - pend[1]) / pend[0]) for k, v in
                 {**variantes, "principal": mu_e}.items()}

    resumen = {
        "corte": str(args.corte), "dias_al_balotaje": (f2 - args.corte).days,
        "encuestas_post_1v": int(len(meta)), "casas": int(meta["casa"].nunique()),
        "agregado_lula_validos": lula_agr,
        "promedio_simple_lula": float(a["promedio_simple"]["lula"]) * 100,
        "sin_house_effect_lula": float(a["sin_house_effect"]["lula"]) * 100,
        "n_efectivo": a["n_efectivo"],
        "rango_encuestas_lula": [float(val["lula"].min() * 100), float(val["lula"].max() * 100)],
        "encuestas_con_flavio_adelante": int((val["flavio_bolsonaro"] > val["lula"]).sum()),
        "tendencia": tend, "misma_casa": misma_casa,
        "horizonte_referencia_dias": D_ref,
        "track_record_horizonte": en_D[["ano", "agregado_pt", "real_pt", "error_pp"]].to_dict(orient="records"),
        "sesgo_historico_pt_pp": sesgo, "rms_historico_pp": rms_D,
        "movimiento_ultimos_dias_pp": movimiento_final,
        "corrige_sesgo": corregir,
        "encuestas": {"media": mu_e, "sd": sd_enc, "prob_lula": float((enc > 50).mean()),
                      "p5_50_95": [float(x) for x in np.percentile(enc, [5, 50, 95])]},
        "variantes_encuestas": {k: {"media": float(variantes[k]), "prob_lula": float((d > 50).mean())}
                                for k, d in dist.items()},
        "modelo": {"media": mu_m, "sd": sd_m, "prob_lula": float((sim_mod > 50).mean()),
                   "corrida": corrida.name},
        "contraste": {"diferencia_encuestas_menos_modelo_pp": dif, "z": float(z),
                      "p_valor_bilateral": float(2 * norm.sf(abs(z)))},
        "sintesis": {"media": mu_s, "sd": sd_s, "peso_modelo": w_m / (w_m + w_e),
                     "prob_lula": float((sint > 50).mean()),
                     "p5_50_95": [float(x) for x in np.percentile(sint, [5, 50, 95])]},
        "a_lula_terceros_implicita": implicita,
        "a_lula_terceros_modelo": res_mod["a_lula_terceros"]["R"],
        "nota": "Las encuestas son control externo; el pronóstico oficial sigue siendo el modelo (decisión 2026-10-07).",
    }
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = SALIDA_DIR / sello
    out.mkdir(parents=True, exist_ok=True)
    (out / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    hz.to_csv(out / "horizonte.csv", index=False)
    encuestas.to_csv(out / "encuestas.csv", index=False)
    a["house_effects"].mul({"lula": 100, "flavio_bolsonaro": 100, "n_encuestas": 1}).to_csv(out / "house_effects.csv")
    log.info("encuestas %.2f (P %.0f%%, corrige=%s) vs modelo %.2f (P %.0f%%): z %.2f · síntesis %.2f (P %.0f%%) · %s",
             mu_e, 100 * resumen["encuestas"]["prob_lula"], corregir, mu_m, 100 * resumen["modelo"]["prob_lula"],
             z, mu_s, 100 * resumen["sintesis"]["prob_lula"], out)


if __name__ == "__main__":
    main()
