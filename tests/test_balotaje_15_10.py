import numpy as np
import pandas as pd

from src.models.encuestas_balotaje_2026 import tendencia
from src.models.transferencias_balotaje_2026 import TERCEROS, bloques, lula_pct, posterior


def _T():
    t = pd.DataFrame(0.0, index=["pt", "bolsonaro", "otros", "blanco_nulo", "abstencion"],
                     columns=["pt", "bolsonaro", "blanco_nulo", "abstencion"])
    t.loc["pt"] = [0.9, 0.0, 0.0, 0.1]
    t.loc["bolsonaro"] = [0.0, 1.0, 0.0, 0.0]
    t.loc["otros"] = [0.4, 0.4, 0.2, 0.0]
    t.loc["blanco_nulo"] = [0.1, 0.1, 0.8, 0.0]
    t.loc["abstencion"] = [0.0, 0.0, 0.0, 1.0]
    return {"XX": t}


def _act():
    d = {"uf": ["XX"], "aptos": [200.0], "pt_1": [60.0], "bolsonaro_1": [70.0], "blanco_nulo_1": [10.0],
         "abstencion_1": [20.0]}
    d.update({f"{g}_1": [10.0] for g in TERCEROS})
    return pd.DataFrame(d, index=[1])


def _ext():
    return {"pt_1": 0.0, "bolsonaro_1": 0.0, **{f"{g}_1": 0.0 for g in TERCEROS}}


def test_bloques_suman_los_validos_de_la_matriz():
    b = bloques(_act(), _T(), {g: "otros" for g in TERCEROS}, _ext())
    assert np.isclose(b["pt"]["validos"], 54)          # retiene 90 %
    assert np.isclose(b["bolsonaro"]["validos"], 70)
    assert np.isclose(b["blanco_nulo"]["validos"], 2)
    assert np.isclose(b["cury"]["validos"], 8)          # 80 % de los terceros vota válido


def test_lula_pct_lineal_en_las_proporciones():
    b = bloques(_act(), _T(), {g: "otros" for g in TERCEROS}, _ext())
    a = {g: (v["lula"] / v["validos"] if v["validos"] else 0.0) for g, v in b.items()}
    a.update({g: 0.5 for g in TERCEROS})
    base = lula_pct(b, a)
    # 54 Lula + 1 de blanco + 16 de terceros, sobre 54 + 70 + 2 + 32
    assert np.isclose(base, (54 + 1 + 16) / 158 * 100)
    # vectorizado: una proporción por simulación
    a2 = {**a, "cury": np.array([0.0, 1.0])}
    v = lula_pct(b, a2)
    assert np.isclose(v[1] - v[0], 8 / 158 * 100)


def test_posterior_se_acerca_a_los_datos_con_mas_casos():
    rng = np.random.default_rng(0)
    d = {"lula": 60, "flavio": 40}
    _, chico = posterior(0.3, d, 5, rng, 2000)
    _, grande = posterior(0.3, d, 5000, rng, 2000)
    assert 0.3 < chico["posterior_media"] < 0.45
    assert abs(grande["posterior_media"] - 0.6) < 0.01


def test_tendencia_detecta_pendiente():
    meta = pd.DataFrame({"fecha_fin": pd.to_datetime([f"2026-10-{d:02d}" for d in range(5, 15)]),
                         "muestra": [2000] * 10})
    val = pd.DataFrame({"lula": 0.45 + 0.002 * np.arange(10)})
    t = tendencia(meta, val, "lula", pd.Timestamp("2026-10-04").date())
    assert np.isclose(t["pendiente_pts_por_dia"], 0.2)
