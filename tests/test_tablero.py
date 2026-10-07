import numpy as np
import pandas as pd

from src.models.tablero_2v_2026 import proyectar


def _pron(p):
    mun = pd.DataFrame({"uf": ["SP", "SP", "BA", "BA"], "validos_pred": [100.0, 100.0, 100.0, 100.0], "p": p},
                       index=[1, 2, 3, 4])
    return {"mun": mun, "sd": 1.5, "ext_p": 0.5, "ext_val": 0.0, "lula": float(np.mean(p) * 100)}


def test_sin_conteo_devuelve_el_pronostico():
    e = proyectar(_pron([0.4, 0.4, 0.7, 0.7]), pd.DataFrame(columns=["lula", "flavio", "pct"]), (0, 0, 0), 1e5)
    assert np.isclose(e["lula_proyectado"], 55.0)
    assert np.isclose(e["sd_pp"], 1.5)


def test_desvio_parejo_se_corrige_con_lo_contado():
    # el pronóstico subestima a Lula 5 pts en todos lados; solo SP contó (completo)
    real = [0.45, 0.45, 0.75, 0.75]
    cont = pd.DataFrame({"lula": [45.0, 45.0], "flavio": [55.0, 55.0], "pct": [1.0, 1.0]}, index=[1, 2])
    e = proyectar(_pron([0.4, 0.4, 0.7, 0.7]), cont, (0, 0, 0), 1.0)
    assert np.isclose(e["lula_contado"], 45.0)
    assert np.isclose(e["desvio_nacional_pp"], 5.0)
    assert abs(e["lula_proyectado"] - np.mean(real) * 100) < 0.1


def test_todo_contado_es_el_resultado():
    cont = pd.DataFrame({"lula": [30.0, 50.0, 80.0, 60.0], "flavio": [70.0, 50.0, 20.0, 40.0], "pct": [1.0] * 4},
                        index=[1, 2, 3, 4])
    e = proyectar(_pron([0.4, 0.4, 0.7, 0.7]), cont, (0, 0, 0), 1e5)
    assert np.isclose(e["lula_proyectado"], 55.0)
    assert np.isclose(e["votos_contados_pct"], 100.0)
