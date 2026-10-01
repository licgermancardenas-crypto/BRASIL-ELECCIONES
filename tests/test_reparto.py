import numpy as np
import pandas as pd

from src.models.montecarlo.reparto import repartir


def test_dhondt_basico():
    # cocientes: A 100,50,33.3 | B 50 | C 30 -> A3 B1 C1
    assert repartir([[100, 50, 30]], 5).tolist() == [[3, 1, 1]]


def test_umbral_80_por_ciento_del_cociente():
    # QE = 165/5 = 33; 80% = 26.4 -> C (20) no compite
    assert repartir([[100, 45, 20]], 5).tolist() == [[4, 1, 0]]


def test_si_ninguna_llega_al_umbral_compiten_todas():
    votos = np.full((1, 10), 10.0)  # QE = 50, nadie llega a 40
    r = repartir(votos, 2)
    assert r.sum() == 2 and r.max() == 1


def test_muchas_simulaciones_a_la_vez_y_suma_exacta():
    rng = np.random.default_rng(0)
    votos = rng.random((500, 12))
    r = repartir(votos, 70)
    assert r.shape == (500, 12) and (r.sum(axis=1) == 70).all()


def test_simulacion_reproducible_con_semilla():
    from src.models.montecarlo.proyeccion_bancas import simular
    base = pd.DataFrame({"uf": ["X"] * 3, "lista": ["a", "b", "c"],
                         "familia": ["f1", "f1", "f2"], "pct": [0.5, 0.2, 0.3]})
    ruido = pd.DataFrame({"sigma_uf_pp": [5.0, 5.0], "sigma_nacional_pp": [2.0, 2.0]}, index=["f1", "f2"])
    s1 = simular(base, {"X": 10}, ruido, 200, 42, 0.8)
    s2 = simular(base, {"X": 10}, ruido, 200, 42, 0.8)
    pd.testing.assert_frame_equal(s1, s2)
    assert (s1.groupby("simulacion")["bancas"].sum() == 10).all()
