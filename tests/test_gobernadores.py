import numpy as np

from src.models.montecarlo.proyeccion_gobernadores import Carrera, eleccion


def _carrera(fuerza, fam_idx, primero, incumbente):
    return Carrera(uf="X", familias=[f"f{i}" for i in range(len(fuerza))], fuerza=np.array(fuerza),
                   fam_idx=np.array(fam_idx), primero=np.array(primero),
                   incumbente=np.array(incumbente), nombres=[f"c{i}" for i in range(len(fam_idx))])


def _correr(k, n=1, beta=0.5, delta=0.0, sigma=0.0, sigma_bal=0.0, z_bal=None):
    f = np.repeat(np.array(k.fuerza)[None, :], n, axis=0)
    zc = np.zeros((n, len(k.fam_idx)))
    zb = np.zeros((n, 2)) if z_bal is None else z_bal
    return eleccion(f, k, beta, delta, zc, zb, sigma, sigma_bal)


def test_gana_en_primera_vuelta_con_mas_de_50():
    k = _carrera([0.6, 0.3, 0.1], [0, 1, 2], [True] * 3, [False] * 3)
    gan, bal = _correr(k)
    assert gan.tolist() == [0] and bal.tolist() == [False]


def test_balotaje_si_nadie_supera_50():
    k = _carrera([0.45, 0.35, 0.20], [0, 1, 2], [True] * 3, [False] * 3)
    gan, bal = _correr(k)
    assert bal.tolist() == [True] and gan.tolist() == [0]


def test_balotaje_puede_dar_vuelta_el_resultado():
    k = _carrera([0.45, 0.35, 0.20], [0, 1, 2], [True] * 3, [False] * 3)
    gan, _ = _correr(k, sigma_bal=1.0, z_bal=np.array([[-1.0, 1.0]]))  # 0.45·e^-1 < 0.35·e^1
    assert gan.tolist() == [1]


def test_ventaja_de_incumbente():
    k = _carrera([0.4, 0.3, 0.3], [0, 1, 2], [True] * 3, [False, True, False])
    gan, _ = _correr(k, delta=1.5)  # 0.3·e^1.5 = 1.34 > 0.4
    assert gan.tolist() == [1]


def test_segundo_candidato_de_la_familia_con_beta():
    # f0 tiene dos candidatos: el 2º compite con beta·S y le resta votos al 1º
    k = _carrera([0.5, 0.5], [0, 0, 1], [True, False, True], [False] * 3)
    gan, bal = _correr(k, beta=0.5)
    assert bal.tolist() == [True]  # 0.5/1.25 = 40% para cada 1º: nadie pasa el 50%
