"""
src/geo/empaquetar.py

Arma la entrega geoespacial: un zip por UF en reports/geo/ con las capas de
src.geo.divisiones (GeoJSON + GeoPackage), la tabla de mesas con coordenadas y
un LEEME con el diccionario de campos.

Uso:
    python -m src.geo.empaquetar
"""
from __future__ import annotations

import json
import logging
import zipfile

from src.etl.extract.tse_extractor import UFS
from src.geo.divisiones import GEO_DIR
from src.models.montecarlo.proyeccion_bancas import ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ENTREGA = ROOT / "reports" / "geo"

LEEME = """ATLAS Analytics · Brasil 2026 · capas geoespaciales de {uf}
=================================================================

Todas las capas en GeoJSON (EPSG:4326, WGS84) y juntas en {uf}.gpkg (EPSG:4674,
SIRGAS 2000) para abrir en QGIS/ArcGIS. Gobernador 2022: 1 = {g1}, 2 = {g2}.

Capas (polígonos)
  regioes_intermediarias, regioes_imediatas, municipios, distritos  (IBGE, oficiales)
  bairros            barrios del IBGE (solo donde el IBGE los define)
  zonas_eleitorais   zonas del TSE, APROXIMADAS (el TSE no publica polígonos: cada
                     setor censitário va a la zona de la escuela más cercana)
  areas_escuelas     área de influencia de cada local de votación (setores más
                     cercanos a la escuela dentro de su município), APROXIMADA
Capas (puntos)
  locales            cada escuela con coordenadas; coord_origen: tse (TSE 2022),
                     tse_2024 / tse_2018 (misma escuela en otro año),
                     bairro (centroide del barrio: aproximada)
  secciones.csv      cada mesa (sección) con votos y la coordenada de su escuela

Campos de resultados (votos válidos, %)
  electores          padrón (aptos) 2022
  locales / secciones / setores   cantidad de escuelas, mesas y setores del Censo
  lula_1v, bolsonaro_1v           % en la 1ª vuelta presidencial 2022
  lula_2v                         % de Lula en la 2ª vuelta presidencial 2022
  votos_lula_2v, votos_bolsonaro_2v
  abstencion_2v                   % del padrón que no votó en la 2ª vuelta
  gob_1_pct, gob_2_pct            % de los dos primeros a gobernador (1ª vuelta 2022)
  haddad_2v_2018, cambio_2018_2022  (solo municípios)
  poblacion, area_km2             Censo 2022 (IBGE)
  censo_*                         (solo locales) área de influencia de la escuela:
                                  alfabetizacion, preta_parda, banos_2mas (proxy de
                                  ingreso), cloaca_red, mayores_60, urbano (0-1)

Cómo se asignan los votos: município y regiones por código IBGE (exacto, incluye
escuelas sin coordenadas); distrito y barrio por la ubicación de la escuela; zona
por el número de zona del TSE (exacto). En las capas por ubicación faltan las
escuelas sin coordenadas: {sin_xy} del padrón de la UF.

Fuentes: TSE (resultados por sección, locales de votación), IBGE (Censo 2022 por
setor censitário y su malla). Documentación: docs/analisis_seccion.md del proyecto.
"""


def main() -> None:
    import pandas as pd
    from src.etl.transform.base_locales import salida as salida_locales
    loc = pd.read_parquet(salida_locales(2022))
    ENTREGA.mkdir(parents=True, exist_ok=True)
    for uf in UFS:
        d = GEO_DIR / uf
        if not (d / "resumen.json").exists():
            log.warning("%s: sin capas", uf)
            continue
        r = json.loads((d / "resumen.json").read_text(encoding="utf-8"))
        l = loc[loc["uf"] == uf]
        sin_xy = f"{(l.loc[l['lat'].isna(), 'aptos'].sum() / l['aptos'].sum() * 100):.1f} %"
        zf = ENTREGA / f"ATLAS_Brasil_geo_{uf}.zip"
        with zipfile.ZipFile(zf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(d.glob("*.geojson")) + [d / f"{uf}.gpkg", d / "secciones.csv"]:
                z.write(f, f"{uf}/{f.name}")
            z.writestr(f"{uf}/LEEME.txt", LEEME.format(uf=uf, g1=r["gobernador_2022"]["gob_1"], g2=r["gobernador_2022"]["gob_2"],
                                                      sin_xy=sin_xy))
        log.info("%s: %s (%.1f MB)", uf, zf.name, zf.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
