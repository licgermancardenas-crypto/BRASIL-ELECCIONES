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


def test_sigla_sucesora_sigue_cadenas():
    assert rf.sigla_sucesora("PRP", 2018, 2026) == "PRD"       # PRP -> PATRIOTA (2019) -> PRD (2023)
    assert rf.sigla_sucesora("PSL", 2018, 2026) == "UNIÃO"
    assert rf.sigla_sucesora("PRB", 2018, 2026) == "REPUBLICANOS"
    assert rf.sigla_sucesora("PATRI", 2018, 2026) == "PRD"     # alias + cadena
    assert rf.sigla_sucesora("PT", 2018, 2026) == "PT"


def test_sigla_sucesora_respeta_el_ano_destino():
    assert rf.sigla_sucesora("PRP", 2018, 2022) == "PATRIOTA"  # PRD recién desde 2023
    assert rf.sigla_sucesora("PROS", 2022, 2022) == "PROS"


def test_todos_los_partidos_historicos_llegan_a_2026():
    for ano in (2018, 2022):
        _, mapa = rf.tabla_ano(ano)
        for partido in mapa:
            rf.familia_composicion_fija(partido, ano, 2026)  # no debe levantar


def test_composicion_fija_ignora_reclasificacion():
    # SOLIDARIEDADE estaba en gobierno_lula en 2022; fija en 2026 es centrao en ambos años
    assert rf.familia_composicion_fija("SOLIDARIEDADE", 2022, 2026) == "centrao"
    assert rf.familia_composicion_fija("SOLIDARIEDADE", 2018, 2026) == "centrao"
