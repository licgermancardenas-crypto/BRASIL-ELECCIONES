import os

import pandas as pd
import pytest

from src.models.montecarlo.proyeccion_presidencial import nacional

lento = pytest.mark.skipif(os.environ.get("ATLAS_TESTS_LENTOS") != "1",
                           reason="lee data/raw (~75 s): correr con ATLAS_TESTS_LENTOS=1")


def test_total_nacional_pondera_por_votos_validos():
    validos = pd.Series([900, 100], index=["SP", "AC"])
    assert nacional(pd.Series([0.40, 0.90], index=["SP", "AC"]), validos) == 0.45


@lento
def test_reproduce_la_segunda_vuelta_2022():
    from src.models.montecarlo.proyeccion_presidencial import segunda_vuelta
    try:
        base, _ = segunda_vuelta(2022, ["gobierno_lula", "direita_bolsonarista"])
    except FileNotFoundError:
        pytest.skip("sin data/raw de resultados 2022")
    assert round(nacional(base["pct"], base["validos"]) * 100, 2) == 50.90
