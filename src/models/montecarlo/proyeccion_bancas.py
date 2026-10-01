"""
src/models/montecarlo/proyeccion_bancas.py

Simulación Montecarlo de composición de Câmara dos Deputados y Senado
post-elección 2026, a partir de intención de voto por partido/família
y el sistema electoral correspondiente (proporcional D'Hondt con cláusula
de desempenho para Diputados; mayoritario para Senado).

Metodología hermana de la usada en atlas-congreso-2027 (Argentina), adaptada
al sistema electoral brasileño:
  - Câmara: proporcional D'Hondt por UF, con piso de desempenho federal.
  - Senado: mayoritario, 1 o 2 bancas por UF según el ciclo (2026 = 2 por UF).

Input esperado: data/processed/electoral/intencion_voto_familia.parquet
Output: data/processed/legislativo/simulacion_bancas_{camara|senado}.parquet
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

N_SIMULACIONES = 10_000
RANDOM_SEED = 42

PROCESSED_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"


def dhondt(votos: dict[str, float], bancas: int) -> dict[str, int]:
    """Reparto D'Hondt estándar. votos: {partido: cantidad_de_votos}."""
    cocientes = []
    for partido, v in votos.items():
        for i in range(1, bancas + 1):
            cocientes.append((v / i, partido))
    cocientes.sort(reverse=True)
    ganadores = [p for _, p in cocientes[:bancas]]
    resultado = {p: 0 for p in votos}
    for p in ganadores:
        resultado[p] += 1
    return resultado


def simular_camara(intencion_voto_por_uf: pd.DataFrame,
                    bancas_por_uf: dict[str, int],
                    n_sim: int = N_SIMULACIONES) -> pd.DataFrame:
    """
    Corre n_sim escenarios, perturbando la intención de voto con ruido
    proporcional al margen de error reportado de las encuestas (~2pp),
    y aplica D'Hondt por UF en cada escenario.
    """
    rng = np.random.default_rng(RANDOM_SEED)
    resultados = []

    for sim in range(n_sim):
        for uf, bancas in bancas_por_uf.items():
            fila_uf = intencion_voto_por_uf[intencion_voto_por_uf["uf"] == uf]
            votos_perturbados = {
                row["familia"]: max(0.0, row["intencion"] + rng.normal(0, 0.02))
                for _, row in fila_uf.iterrows()
            }
            reparto = dhondt(votos_perturbados, bancas)
            for familia, n_bancas in reparto.items():
                resultados.append({
                    "simulacion": sim, "uf": uf,
                    "familia": familia, "bancas": n_bancas,
                })

    return pd.DataFrame(resultados)


def resumen_probabilistico(df_simulaciones: pd.DataFrame) -> pd.DataFrame:
    """Agrega bancas totales por familia y simulación, y resume percentiles."""
    totales = df_simulaciones.groupby(["simulacion", "familia"])["bancas"].sum().reset_index()
    resumen = totales.groupby("familia")["bancas"].agg(
        media="mean", p10=lambda s: s.quantile(0.10),
        mediana="median", p90=lambda s: s.quantile(0.90),
    ).reset_index()
    return resumen.sort_values("media", ascending=False)


def main() -> None:
    input_path = PROCESSED_DIR / "electoral" / "intencion_voto_familia.parquet"
    if not input_path.exists():
        log.error("No existe %s — correr primero el pipeline de transform.", input_path)
        return

    intencion = pd.read_parquet(input_path)
    bancas_por_uf = {}  # TODO: cargar desde data/raw/tse/distribuicao_cadeiras_uf.csv

    sims = simular_camara(intencion, bancas_por_uf)
    resumen = resumen_probabilistico(sims)

    out_dir = PROCESSED_DIR / "legislativo"
    out_dir.mkdir(parents=True, exist_ok=True)
    sims.to_parquet(out_dir / "simulacion_bancas_camara.parquet")
    resumen.to_csv(out_dir / "resumen_bancas_camara.csv", index=False)

    log.info("Simulación completa. Resumen:\n%s", resumen)


if __name__ == "__main__":
    main()
