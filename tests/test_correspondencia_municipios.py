"""Invariantes de la tabla versionada TSE<->IBGE (no requiere data/raw)."""
import pandas as pd
import pytest

from src.etl.transform.correspondencia_municipios import UF_IBGE, agregar_codigo_ibge, cargar


@pytest.fixture(scope="module")
def tabla():
    return cargar()


def test_uno_a_uno(tabla):
    assert not tabla["codigo_tse"].duplicated().any()
    assert not tabla["codigo_ibge"].duplicated().any()
    assert tabla["codigo_ibge"].notna().all()


def test_formato_codigos(tabla):
    assert tabla["codigo_tse"].str.fullmatch(r"\d{5}").all()
    assert tabla["codigo_ibge"].str.fullmatch(r"\d{7}").all()


def test_codigo_ibge_corresponde_a_la_uf(tabla):
    assert (tabla["codigo_ibge"].str[:2] == tabla["uf"].map(UF_IBGE)).all()


def test_27_ufs_sin_exterior(tabla):
    assert set(tabla["uf"]) == set(UF_IBGE)


def test_manuales_tienen_motivo(tabla):
    manuales = tabla[tabla["metodo"] == "manual"]
    assert manuales["motivo_manual"].notna().all()


def test_casos_conocidos(tabla):
    t = tabla.set_index("codigo_tse")["codigo_ibge"]
    assert t["97012"] == "5300108"  # Brasília
    assert t["71072"] == "3550308"  # São Paulo
    assert t["36765"] == "2918753"  # Lagoa Real (la tabla comunitaria lo tiene mal)


def test_agregar_codigo_ibge_acepta_codigos_sin_ceros():
    df = pd.DataFrame({"CD_MUNICIPIO": ["97012", "256"]})
    out = agregar_codigo_ibge(df)
    assert out["codigo_ibge"].tolist() == ["5300108", "1100098"]


def test_agregar_codigo_ibge_falla_con_codigo_desconocido():
    with pytest.raises(KeyError):
        agregar_codigo_ibge(pd.DataFrame({"CD_MUNICIPIO": ["99999"]}))
