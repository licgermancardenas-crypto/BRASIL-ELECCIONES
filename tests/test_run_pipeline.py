"""Lógica del orquestador con pasos simulados (no toca datos ni red)."""
from src.etl.transform.run_pipeline import Paso, PasoOmitido, ejecutar, resumen


def _ok():
    return []


def _falla():
    raise ValueError("dato corrupto")


def _omitido():
    raise PasoOmitido("sin datos 2026")


def test_paso_requerido_que_falla_corta_el_pipeline():
    corrio = []
    pasos = [
        Paso("extraccion", "a", _ok),
        Paso("transformacion", "b", _falla),
        Paso("carga", "c", lambda: corrio.append("c") or []),
    ]
    corte = ejecutar(pasos)
    assert corte is pasos[1]
    assert pasos[1].estado == "FALLÓ" and "dato corrupto" in pasos[1].detalle
    assert pasos[2].estado == "pendiente" and corrio == []
    assert "CORTADO en fase 'transformacion'" in resumen(pasos, corte)


def test_paso_opcional_que_falla_no_corta():
    pasos = [Paso("extraccion", "a", _falla, requerido=False), Paso("carga", "b", _ok)]
    assert ejecutar(pasos) is None
    assert pasos[0].estado == "omitido" and pasos[1].estado == "ok"


def test_paso_omitido_no_corta():
    pasos = [Paso("familia", "2026", _omitido), Paso("carga", "b", _ok)]
    assert ejecutar(pasos) is None
    assert pasos[0].estado == "omitido"


def test_desde_saltea_fases_anteriores():
    pasos = [Paso("extraccion", "a", _falla), Paso("familia", "b", _ok)]
    assert ejecutar(pasos, desde="familia") is None
    assert pasos[0].estado == "salteado" and pasos[1].estado == "ok"
