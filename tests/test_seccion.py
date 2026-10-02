import numpy as np
import pandas as pd

from src.etl.transform.base_locales import grupos_por_seccion
from src.models.analisis_seccion import descomposicion, matriz_transferencia


def test_regresion_ecologica_recupera_una_matriz_conocida():
    rng = np.random.default_rng(1)
    B = np.array([[0.9, 0.05, 0.05], [0.1, 0.8, 0.1], [0.4, 0.4, 0.2]])
    X = rng.dirichlet([3, 3, 1], size=800)
    Y = X @ B + rng.normal(0, 0.005, (800, 3))
    est = matriz_transferencia(X, Y, rng.uniform(200, 2000, 800))  # pesos en electores, sin normalizar
    np.testing.assert_allclose(est, B, atol=0.03)
    np.testing.assert_allclose(est.sum(axis=1), 1, atol=1e-6)
    assert (est >= -1e-9).all()


def test_descomposicion_de_varianza_suma_uno():
    loc = pd.DataFrame({"uf": list("AAAABBBB"), "cd_municipio": [1, 1, 2, 2, 3, 3, 4, 4],
                        "y": [.2, .3, .5, .6, .7, .8, .6, .9], "w": [1, 2, 1, 2, 1, 2, 1, 2]})
    d = descomposicion(loc, "y", "w")
    assert abs(d["entre_uf"] + d["entre_municipios"] + d["dentro_municipio"] - 1) < 1e-9


def test_grupos_por_seccion_reparte_todos_los_votos():
    votos = pd.DataFrame({"uf": ["SP"], "cd_municipio": [1], "nr_zona": [1], "nr_secao": [1], "nr_local": [10],
                          "v_13": [100], "v_22": [80], "v_12": [10], "v_30": [5], "v_95": [3], "v_96": [2],
                          "comparecencia": [200]})
    g = grupos_por_seccion(votos, {"pt": [13], "bolsonaro": [22], "ciro": [12]}, [95, 96])
    r = g.iloc[0]
    assert (r["pt"], r["bolsonaro"], r["ciro"], r["otros"], r["blanco_nulo"]) == (100, 80, 10, 5, 5)
    assert r[["pt", "bolsonaro", "ciro", "otros", "blanco_nulo"]].sum() == r["comparecencia"]


def test_titulo_del_panorama_segun_el_voto():
    from src.viz.informe_estados_pdf import titulo_panorama
    assert titulo_panorama({"nombre": "Bahia", "lula_2v": 72.1}) == "Bahia, bastión de Lula"
    assert titulo_panorama({"nombre": "Minas Gerais", "lula_2v": 50.2}) == "Minas Gerais, un estado partido al medio"
    assert titulo_panorama({"nombre": "Acre", "lula_2v": 29.7}) == "Acre, territorio bolsonarista"
