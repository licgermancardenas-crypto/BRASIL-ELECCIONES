import numpy as np
import pandas as pd

from src.models.balotaje_2026 import DESTINO_2V, ORIGEN, celdas_origen, predecir


def _T():
    """Matriz 1ª -> 2ª vuelta de juguete: retención total, el análogo 'otros' vota 50/50 y 20% no vota."""
    t = pd.DataFrame(0.0, index=["pt", "bolsonaro", "otros", "blanco_nulo", "abstencion"], columns=DESTINO_2V)
    t.loc["pt", "pt"] = t.loc["bolsonaro", "bolsonaro"] = 1
    t.loc["blanco_nulo", "blanco_nulo"] = t.loc["abstencion", "abstencion"] = 1
    t.loc["otros"] = [0.4, 0.4, 0.2, 0.0]
    return {"XX": t}


def _act():
    return pd.DataFrame({"uf": ["XX", "XX"], "aptos": [100.0, 100.0], "pt_1": [40.0, 30.0],
                         "bolsonaro_1": [30.0, 40.0], "t_1": [20.0, 20.0],
                         "blanco_nulo_1": [5.0, 5.0], "abstencion_1": [5.0, 5.0]}, index=[1, 2])


def test_analogia_reparte_como_el_analogo():
    p = predecir(_act(), _T(), {"t": "otros"}, "A", None, ["t"])
    # 40 votos de terceros: 80% válidos, mitad y mitad
    assert np.isclose(p.loc["XX", "pt"], 70 + 16)
    assert np.isclose(p.loc["XX", "bolsonaro"], 70 + 16)
    assert np.isclose(p.loc["XX", "blanco_nulo"], 10 + 8)


def test_origen_devuelve_cada_tercero_a_su_lado():
    act = _act()
    prev = pd.DataFrame({"pt_2": [100.0, 0.0], "bolsonaro_2": [0.0, 100.0], "blanco_nulo_2": [0.0, 0.0],
                         "abstencion_2": [0.0, 0.0], "aptos": [100.0, 100.0]}, index=[1, 2])
    B = {"XX": pd.DataFrame(1 / 6, index=ORIGEN, columns=["pt", "bolsonaro", "t", "blanco_nulo", "abstencion"])}
    celdas = celdas_origen(act, prev, B, ["pt", "bolsonaro", "t"], ["t"])
    # município 1 venía todo de Lula, el 2 todo de Bolsonaro
    assert np.isclose(celdas.loc[1, "pt"], 20) and np.isclose(celdas.loc[2, "bolsonaro"], 20)
    p = predecir(act, _T(), {"t": "otros"}, "R", celdas, ["t"])
    assert np.isclose(p.loc["XX", "pt"], 70 + 16)


def test_ajuste_pisa_al_metodo():
    p = predecir(_act(), _T(), {"t": "otros"}, "A", None, ["t"], ajuste={"t": 1.0})
    assert np.isclose(p.loc["XX", "pt"], 70 + 32)
    assert np.isclose(p.loc["XX", "bolsonaro"], 70)
