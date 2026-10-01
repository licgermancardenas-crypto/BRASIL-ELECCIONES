import pytest

from src.models.bloques import resolver_familia as rf


def test_propuesta_rechazada_por_defecto():
    estado, _ = rf.tabla_ano(2026)
    if estado == "vigente":
        pytest.skip("2026 ya validada")
    with pytest.raises(rf.ClasificacionNoValidada):
        rf.familia("PT", 2026)


def test_alias_normaliza_sigla():
    assert rf.familia("PCDOB", 2026, permitir_propuesta=True) == rf.familia("PC do B", 2026, permitir_propuesta=True)
    assert rf.familia("PATRI", 2018, permitir_propuesta=True) == rf.familia("PATRIOTA", 2018, permitir_propuesta=True)


def test_familia_depende_del_ano():
    # SOLIDARIEDADE: centrão en 2018, coligação de Lula en 2022
    assert rf.familia("SOLIDARIEDADE", 2018, permitir_propuesta=True) == "centrao"
    assert rf.familia("SOLIDARIEDADE", 2022, permitir_propuesta=True) == "gobierno_lula"


def test_sin_familia_por_defecto():
    with pytest.raises(rf.PartidoSinClasificar):
        rf.familia("PARTIDO_INEXISTENTE", 2022, permitir_propuesta=True)


def test_ningun_partido_en_dos_familias():
    for ano in (2018, 2022, 2026):
        rf.tabla_ano(ano)  # levanta ValueError si hay duplicado


def test_asignar_familia_lista_todos_los_faltantes():
    import pandas as pd
    df = pd.DataFrame({"partido": ["PT", "XX1", "XX2"]})
    with pytest.raises(rf.PartidoSinClasificar, match="XX1.*XX2"):
        rf.asignar_familia(df, 2022, permitir_propuesta=True)
