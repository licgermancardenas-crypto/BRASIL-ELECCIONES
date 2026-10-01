"""
src/models/montecarlo/reparto.py

Reparto de bancas de la Câmara dos Deputados dentro de una UF, vectorizado
para muchas simulaciones a la vez.

Regla (Código Eleitoral art. 106-109, con Lei 14.211/2021):
  1. Cociente electoral QE = votos válidos de la UF / bancas.
  2. Solo compiten las listas (partido o federación) con votos >= 80% del QE.
     Si ninguna llega, compiten todas.
  3. Entre las que compiten, bancas por mayores promedios (votos / (bancas+1)),
     que equivale a cociente partidario + sobras por "maiores médias" = D'Hondt.

Simplificación documentada: no se modela el piso individual de 20% del QE por
candidato (requiere votos por candidato) ni la tercera ronda de sobras que
habilitó el STF en 2024 (ADI 7228) para cuando quedan bancas sin asignar por
ese piso. El error de esta simplificación se mide reproduciendo 2022.
"""
from __future__ import annotations

import numpy as np


def repartir(votos: np.ndarray, bancas: int, umbral_cociente: float = 0.80) -> np.ndarray:
    """
    votos: matriz (simulaciones × listas) con votos (o proporciones) por lista.
    Devuelve matriz entera (simulaciones × listas) con bancas por lista.
    """
    votos = np.atleast_2d(np.asarray(votos, dtype=float))
    n_sim, n_listas = votos.shape
    if bancas <= 0:
        return np.zeros_like(votos, dtype=int)

    cociente = votos.sum(axis=1, keepdims=True) / bancas
    elegibles = votos >= umbral_cociente * cociente
    ninguna = ~elegibles.any(axis=1)
    elegibles[ninguna] = votos[ninguna] > 0
    v = np.where(elegibles, votos, 0.0)

    divisores = np.arange(1, bancas + 1, dtype=float)
    promedios = (v[:, :, None] / divisores[None, None, :]).reshape(n_sim, -1)
    # Las `bancas` mayores medias de cada simulación (desempate: orden de lista, estable)
    top = np.argsort(-promedios, axis=1, kind="stable")[:, :bancas]
    lista_de = top // bancas
    resultado = np.zeros((n_sim, n_listas), dtype=int)
    np.add.at(resultado, (np.repeat(np.arange(n_sim), bancas), lista_de.ravel()), 1)
    return resultado
