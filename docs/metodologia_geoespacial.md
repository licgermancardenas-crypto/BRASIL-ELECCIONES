# Metodología geoespacial — ATLAS Brasil 2026

## El problema de fondo

Brasil tiene **dos jerarquías territoriales que no coinciden**:

1. **Jerarquía electoral** (TSE): UF → município → zona eleitoral → **seção
   eleitoral**. La sección es la unidad mínima de resultado electoral, pero
   **no tiene geometría propia** — es un agrupamiento administrativo de
   electores, no un polígono en el mapa.
2. **Jerarquía estadística** (IBGE): UF → município → distrito → **setor
   censitário**. El setor sí tiene geometría (polígono shapefile), es la
   unidad mínima del censo, pero no tiene resultado electoral.

No existe una tabla de equivalencia oficial 1:1 entre seção eleitoral y
setor censitário. Cualquier análisis que cruce "cómo votó tal zona" con
"qué características socioeconómicas tiene" está haciendo una
**aproximación geográfica**, no un join exacto.

## Estrategia de agregación (de más confiable a menos)

| Nivel | Confiabilidad del cruce | Uso recomendado |
|---|---|---|
| **UF (estado)** | Exacta | Comparaciones regionales, mapas de "quién lidera por estado" |
| **Município** | Exacta (ambas jerarquías coinciden en código IBGE de município) | Nivel por defecto para todo cruce electoral × socioeconómico |
| **Setor censitário ≈ local de votação** | Aproximada — se geocodifica el local de votação (dirección publicada por el TSE) contra el polígono del setor que lo contiene | Análisis intra-urbano fino (ej. CABA-style, por barrio) |
| **Seção eleitoral** | No tiene geometría propia — solo sirve agregada a local de votação | Solo para detectar anomalías de totalización, no para mapas |

**Regla del proyecto: todo mapa o modelo que opere por debajo del nivel
município debe declarar explícitamente en su output qué método de
aproximación usó** (geocodificación de local de votação, centroid del
setor, etc.), para que el número sea trazable y defendible.

## Pipeline de unión geoespacial

```
seção eleitoral (resultado)
        │
        ▼
local de votação (dirección — padrón TSE)
        │  geocoding (src/geo/geocode_locais.py)
        ▼
setor censitário que contiene el punto (join espacial, GeoPandas)
        │
        ▼
dataset: resultado_electoral × atributos_censales por setor
```

## Sistema de referencia

Todas las capas IBGE vienen en **EPSG:4674 (SIRGAS 2000)**. Reproyectar a
EPSG:4326 (WGS84) solo al momento de visualizar en web (Leaflet/Mapbox);
mantener SIRGAS 2000 para cualquier cálculo de área o distancia.

## Pendiente de definición (abierto hasta el inicio de la fase de modelado)

- Si se va a trabajar con geocodificación propia del padrón de locais de
  votação, o si alcanza con el nivel município para el objetivo del
  proyecto (comparar con `atlas-caba-jg2027`, que sí necesitó nivel barrio
  por ser un distrito único — acá hay que decidir si el recorte vale la
  pena para un país de 27 estados y >5.500 municípios).
