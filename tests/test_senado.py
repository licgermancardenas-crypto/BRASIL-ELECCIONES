import numpy as np

from src.models.montecarlo.proyeccion_senado import ganadores


def test_dos_familias_mas_fuertes_con_beta_bajo():
    r = ganadores(np.array([[0.5, 0.3, 0.2]]), np.array([2, 1, 1]), beta=0.5)
    assert r.tolist() == [[1, 1, 0]]  # 2º candidato de f0 = 0.25 < 0.3


def test_familia_dominante_gana_las_dos_con_beta_alto():
    r = ganadores(np.array([[0.5, 0.3, 0.2]]), np.array([2, 1, 1]), beta=0.7)
    assert r.tolist() == [[2, 0, 0]]  # 0.35 > 0.3


def test_sin_candidatos_no_gana():
    r = ganadores(np.array([[0.6, 0.3, 0.1]]), np.array([0, 1, 1]), beta=0.0)
    assert r.tolist() == [[0, 1, 1]]


def test_con_un_solo_candidato_maximo_una_banca():
    r = ganadores(np.array([[0.9, 0.1]]), np.array([1, 0]), beta=1.0)
    assert r.tolist() == [[1, 0]]  # solo una entrada válida: queda una banca sin asignar


def test_vectorizado_suma_dos_por_simulacion():
    rng = np.random.default_rng(0)
    r = ganadores(rng.random((300, 6)), np.array([3, 2, 1, 1, 0, 2]), beta=0.6)
    assert (r.sum(axis=1) == 2).all()
