from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.etl.transform.encuestas_resultados import casa_canonica, numero, parsear_periodo
from src.models.agregacion_encuestas import agregar, track_record
from src.models.montecarlo.proyeccion_presidencial_encuestas import simular

CFG = {"ventana_campana_dias": 45, "vida_media_dias": 3, "muestra_tope": 3000,
       "shrink_house_effect": 0, "iteraciones_house_effect": 10}


@pytest.mark.parametrize("texto, ano, esperado", [
    ("27–29 Sep", 2026, (date(2026, 9, 27), date(2026, 9, 29))),
    ("30 Sep – 1 Oct", 2022, (date(2022, 9, 30), date(2022, 10, 1))),
    ("2–5 October 2018", 2018, (date(2018, 10, 2), date(2018, 10, 5))),
    ("24 October 2018", 2018, (date(2018, 10, 24), date(2018, 10, 24))),
    ("16–20 Sep 2017", 2018, (date(2017, 9, 16), date(2017, 9, 20))),  # año explícito manda
    ("Third presidential debate.", 2022, None),
])
def test_parsear_periodo(texto, ano, esperado):
    assert parsear_periodo(texto, ano) == esperado


def test_numero_y_nombre_entre_parentesis():
    assert numero("44,87%") == 44.87
    assert numero("–N/a") is None
    assert numero("41% (Haddad)", "haddad") == 41.0
    assert numero("39% (Lula)", "haddad") is None   # el PT con otro candidato: no es el cruce


@pytest.mark.parametrize("nombre, casa", [
    ("Genial/Quaest[19]", "quaest"),
    ("Paraná Pesquisas/Crusoé", "paranapesquisas"),
    ("Arko/Atlas[29]", "atlasintel"),
    ("DataPoder360", "poderdata"),
    ("Encuestadora Nueva", "wiki_encuestadora_nueva"),
])
def test_casa_canonica(nombre, casa):
    assert casa_canonica(nombre) == casa


def _encuestas(filas):
    meta = pd.DataFrame([{"casa": c, "encuestadora_wiki": c, "fecha_fin": pd.Timestamp(f), "muestra": 2000}
                         for c, f, _ in filas])
    val = pd.DataFrame([{"a": p, "b": 1 - p} for _, _, p in filas])
    return meta, val


def test_house_effect_se_corrige_antes_de_promediar():
    # verdad 50%; dos casas sin sesgo y una que publica +4 pp, todas el mismo día
    filas = [(c, "2026-09-30", 0.50) for c in ("x", "y")] * 3 + [("sesgada", "2026-09-30", 0.54)] * 6
    meta, val = _encuestas(filas)
    a = agregar(meta, val, date(2026, 10, 1), {}, CFG)
    assert abs(a["sin_house_effect"]["a"] - 0.52) < 1e-9          # sin corregir: arrastrada por el volumen
    assert abs(a["estimacion"]["a"] - 0.50) < abs(a["sin_house_effect"]["a"] - 0.50)


def test_decaimiento_prioriza_lo_reciente():
    meta, val = _encuestas([("x", "2026-09-01", 0.40), ("x", "2026-09-30", 0.50)])
    a = agregar(meta, val, date(2026, 10, 1), {}, CFG)
    assert a["estimacion"]["a"] > 0.49


def test_track_record_premia_a_la_casa_precisa():
    errores = pd.DataFrame([
        {"ano": a, "vuelta": 1, "casa": casa, "candidato": c, "error": e}
        for a in (2018, 2022) for c in ("p", "q")
        for casa, e in (("precisa", 0.01), ("errada", 0.06), ("media", 0.03))
    ])
    tr, _ = track_record(errores, k=2)
    peso = tr.set_index("casa")["peso_calidad"]
    assert peso["precisa"] > 1 > peso["errada"]


def test_montecarlo_sin_incertidumbre_es_deterministico():
    inc = {"sigma_1v": 0.0, "sesgo_1v": {"gobierno_lula": 0.0, "direita_bolsonarista": 0.0},
           "sigma_rel_menores": 0.0, "sesgo_rel_menores": 0.0, "sigma_2v": 0.0, "sesgo_2v_lula": 0.0}
    principales = {"gobierno_lula": "l", "direita_bolsonarista": "f"}
    m1 = pd.Series({"l": 0.45, "f": 0.40, "otro": 0.15})
    r, dist = simular(m1, {"f": 0.48}, principales, inc, False, 200, 1)
    assert r["prob_hay_segunda_vuelta"] == 1.0
    assert r["prob_presidente"] == {"f": 1.0}
    np.testing.assert_allclose(dist.sum(axis=1), 100)
