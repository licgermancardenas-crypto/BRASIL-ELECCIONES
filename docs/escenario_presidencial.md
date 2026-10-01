# Escenario presidencial 2026 (segunda vuelta)

Código: `src/models/montecarlo/proyeccion_presidencial.py`. Parámetros:
`config/modelo.yaml` (sección `presidencial`). Cada corrida queda en
`data/processed/electoral/presidencial_sim/<fecha_utc>/`.

## Es un escenario, no un pronóstico

Sin encuestas (decisión del 2026-10-01) responde una sola pregunta:

> Si la 2ª vuelta es **Lula (PT) vs. Flávio Bolsonaro (PL)** y cada uno parte
> del voto de su família en la 2ª vuelta 2022, ¿qué tan probable es cada
> resultado con el nivel de cambio que hubo entre 2018 y 2022?

### Premisas

1. **No se modela quién pasa la 1ª vuelta.** Con 14 candidatos y sin
   encuestas no hay base para estimar si un tercero (Caiado, Zema, Marçal,
   Cury, Renan Santos…) entra al balotaje.
2. **Herencia de voto:** Lula 2026 parte del voto de Lula 2022; Flávio
   Bolsonaro parte del voto de Jair Bolsonaro 2022.
3. **Balotaje nacional:** una sola elección; gana quien suma más votos
   válidos en el país. Independiente de los balotajes de gobernador por UF.
4. Los candidatos se fijan por partido en la config (PT y PL), porque cada
   família tiene más de un candidato presidencial: AVANTE (Augusto Cury)
   figura en `gobierno_lula` y PRTB en `direita_bolsonarista` (los dos
   estaban anotados para revisar en la clasificación 2026).

## Ruido medido (2ª vuelta 2018 → 2022, PT vs. bolsonarismo)

| Medida | Valor |
|---|---:|
| Cambio nacional del campo PT (Haddad 44,87% → Lula 50,90%) | +6,03 pp |
| Desvío entre UF del cambio, respecto del nacional (sin el exterior) | 4,57 pp |
| Correlación por UF entre 2018 y 2022 | 0,95 |

- Shock nacional ~ N(0; 6,03 pp), común a todas las UF.
- Shock por UF ~ N(0; 4,57 pp).
- El exterior (ZZ) se movió +22 pp entre 2018 y 2022: queda fuera del
  cálculo del desvío, pero sus votos cuentan para el total nacional.

## Resultado (corrida 2026-10-01, 10.000 simulaciones, semilla 42)

| | Valor |
|---|---:|
| Base (2ª vuelta 2022) | Lula 50,9% |
| **Probabilidad de que gane Lula** | **55,7%** |
| % de Lula, p10 – mediana – p90 | 42,9% – 50,9% – 58,9% |

**Lectura:** con los datos disponibles sin encuestas, la 2ª vuelta es
prácticamente una moneda al aire con leve ventaja para Lula. La amplitud
(43%–59%) viene de que entre 2018 y 2022 el campo PT se movió 6 puntos.

Por UF (`por_uf.csv`): la geografía es muy estable (correlación 0,95). Los
estados del Nordeste quedan casi seguros para Lula (PI, BA, MA > 99%) y los
del Norte agropecuario para el bolsonarismo (RR, RO, AC < 1%); MG (50,2% en
2022) y AP son los más parejos.

## Limitaciones

- Una sola transición (2018 → 2022) para medir el ruido.
- Sin efecto de incumbencia presidencial: no hay casos comparables en los
  datos del proyecto (2018 sin incumbente; 2022 el incumbente perdió).
- Ignora todo lo que cambió desde 2022 (gestión, candidatos nuevos, economía).
- Si un tercero pasa a la 2ª vuelta, el escenario no aplica.
