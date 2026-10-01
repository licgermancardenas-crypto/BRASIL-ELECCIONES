# Agregación de encuestas y Montecarlo presidencial 2026

Fases 4-6 de `metodologia_analisis.md` para la elección presidencial
(nacional, 1ª vuelta y cruces de 2ª). Decisión del 2026-10-01: resultados de
encuestas tomados de Wikipedia (PesqEle no publica porcentajes); alcance
presidencial 1ª + 2ª vuelta.

```bash
python -m src.etl.extract.wikipedia_extractor --ano 2018 2022 2026
python -m src.etl.transform.encuestas_resultados
python -m src.models.agregacion_encuestas            # Fase 4 + backtest (Fase 6)
python -m src.models.montecarlo.proyeccion_presidencial_encuestas   # Fase 5
```

## Datos

- **Fuente:** páginas *Opinion polling for the {2018,2022,2026} Brazilian
  presidential election* (Wikipedia en inglés). Se guarda el HTML renderizado
  de una revisión concreta (`revid` en el manifest), así cada número es
  trazable aunque la página cambie. Es una compilación comunitaria, no una
  fuente oficial: el cruce con PesqEle (n.º de registro) queda pendiente.
- **Qué tablas:** `config/encuestas_wikipedia.yaml` (índice de tabla, columnas
  de candidatos → partido). Solo el período de campaña.
- **Casas:** `config/encuestadoras.yaml`, clave `alias_wikipedia`. "Genial/Quaest"
  se parte en "/" y se busca cada parte (el medio que contrata no es la casa).
- Todo se pasa a **votos válidos** (candidatos + otros = 100%, sin blancos,
  nulos ni indecisos), que es lo que define la elección.

## Método

1. **Track record.** Error de cada casa contra el resultado del TSE en las
   encuestas que terminan campo en la última semana, sobre los 2 más votados.
   Hay una observación por casa × elección × vuelta (las encuestas de la
   misma casa en la misma semana no son independientes). El error se encoge
   hacia el de la industria con 2 pseudo-elecciones. Peso de calidad =
   error² de la industria / error² de la casa. Las casas con
   `continuidad_historica: pendiente` (Ibope→Ipec, Ideia, Vox Brasil, Gerp)
   y las casas nuevas tienen peso 1.
2. **House effect.** Es el residuo de cada encuesta contra la tendencia de
   las *demás* casas (núcleo exponencial en el tiempo), promediado por casa y
   encogido con 3 pseudo-encuestas en 0. Se ancla para que el promedio
   ponderado por calidad sea 0 y se corrige antes de promediar.
3. **Promedio.** Peso = calidad × min(muestra, 3000)/3000 × 0,5^(días/3).

Parámetros en `config/modelo.yaml`, sección `encuestas`.

## Backtest (Fase 6)

Corte en la víspera de cada vuelta. El track record usa solo elecciones
anteriores (2018 sin historia, 2022 con la de 2018).

| Medición | Real (derecha) | Agregado | Error agregador | MAE encuestas individuales (última semana) |
|---|---|---|---|---|
| 2018 1ª vuelta (Bolsonaro) | 46,0 | 40,0 | −6,1 / Haddad −3,6 | 5,4 |
| 2018 cruce antes de la 1ª | 55,1 | 51,1 | −4,0 | 4,2 |
| 2018 2ª vuelta | 55,1 | 56,8 | +1,7 | 2,4 |
| 2022 1ª vuelta (Bolsonaro) | 43,2 | 37,8 | −5,4 / Lula +1,3 | 3,5 |
| 2022 cruce antes de la 1ª | 49,1 | 42,9 | −6,2 | 6,1 |
| 2022 2ª vuelta | 49,1 | 48,0 | −1,1 | 1,8 |

- |Error| medio del agregador: **3,53 pp**, contra **3,88 pp** de la encuesta
  individual promedio. Es mejor en 5 de 6 mediciones; en la que no, el cruce
  pre-1ª de 2022, la diferencia es de 0,2 pp. El agregador pasa el criterio
  de la Fase 6, por poco.
- La vida media de 3 días **se eligió con este mismo backtest**: con 7 días el
  error medio era 3,95, peor que las encuestas individuales. Es una elección
  in-sample sobre 6 mediciones, no validada fuera de muestra.
- El house effect casi no mueve el resultado (±0,2 pp). En 2026 los efectos
  estimados son chicos, todos por debajo de 1,7 pp.
- **Hallazgo principal:** antes de la 1ª vuelta, las encuestas subestimaron al
  candidato bolsonarista en las 4 mediciones (−4 a −6 pp). No es ruido de
  ninguna casa en particular: es un error de toda la industria. Una vez
  conocida la 1ª vuelta, el cruce sí acertó (±2 pp).

## Montecarlo (Fase 5)

La incertidumbre es el error del agregador en el backtest, no el margen
muestral:

- Lula y Flávio: x = m + σ₁·z, con σ₁ = 4,5 pp (RMS de 4 errores).
- Resto de los candidatos: error relativo, con σ = 42% (los menores se
  sobreestiman: voto útil).
- Cruce de 2ª vuelta: % Lula = m₂ + σ₂·(z_Lula − z_Flávio)/√2, con σ₂ = 5,3 pp.
  Usa **el mismo z** que la 1ª vuelta: si se subestima a la derecha en una, se
  la subestima en la otra.
- `corregir_sesgo_historico: false` (default): el sesgo histórico entra como
  varianza, con media 0. La variante corregida se corre siempre y queda en el
  resumen como sensibilidad.

### Resultado al 2026-10-01

Encuestas hasta el 29/9, Wikipedia revid 1377689808.

| | Sin corrección (principal) | Con corrección de sesgo |
|---|---|---|
| Agregado 1ª vuelta (válidos) | Lula 44,1 · Flávio 41,6 · Santos 4,3 · Cury 4,2 · Caiado 3,6 · Zema 1,4 | — |
| P(hay 2ª vuelta) | 94% | 80% |
| P(gana en 1ª) | Lula 5% · Flávio 1% | Flávio 15% · Lula 5% |
| Par en 2ª vuelta | Lula–Flávio ≈ 100% | Lula–Flávio ≈ 100% |
| Cruce Lula vs Flávio (agregado) | Lula 49,5% (p10–p90: 42,6–56,2) | Lula 44,3% (37,5–51,1) |
| **P(presidente)** | **Flávio 54% · Lula 46%** | **Flávio 86% · Lula 14%** |

Lectura: con las encuestas tal cual, es una moneda al aire con una leve
ventaja para Flávio en el cruce. Si el sesgo de 2018/2022 se repite, Flávio es
claro favorito. Corregirlo o no es la decisión metodológica que más pesa en el
número. Con 2 elecciones de historia, el default es no corregir y publicar
las dos cifras.

## Limitaciones

- Dos elecciones de historia: σ y sesgo salen de 4 errores en 1ª vuelta y 2
  en el cruce.
- Wikipedia como fuente: puede tener errores de transcripción y no tiene
  todas las encuestas registradas.
- Los cruces de 2ª vuelta se miden antes de la 1ª: no incorporan la campaña
  del balotaje. En 2018 y 2022 ese fue el tipo de medición con más error.
- Solo nacional: no hay distribución por UF. El escenario por UF sobre la
  base 2022 sigue en `docs/escenario_presidencial.md`.
- Las casas con continuidad pendiente entran sin track record hasta que se
  decida si heredan el de su antecesora.
