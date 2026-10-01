# Inventario de datos crudos

Generado automáticamente por `python -m src.etl.inventario` el 2026-10-01 14:52. No editar a mano.

`data/raw/` no se versiona en git (pesa GB): este archivo es el registro de qué versión de cada fuente se usó. Para reproducir, re-descargar y comparar sha256.

| Dataset | Año | Versión (UTC) | MB | CSV | sha256 (12) | Fuente |
|---|---|---|---:|---:|---|---|
| candidatos | 2014 | 2026-10-01T145814Z | 4.5 | 29 | `ad31cc36d9a6` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2014.zip |
| candidatos | 2018 | 2026-10-01T050047Z | 4.7 | 29 | `57f6881f1aa0` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip |
| candidatos | 2022 | 2026-10-01T050050Z | 4.4 | 29 | `ea3043ebbec7` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip |
| candidatos | 2022 | 2026-10-01T070111Z | 4.4 | 29 | `ed3b17e4d172` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip |
| candidatos | 2026 | 2026-10-01T050051Z | 3.2 | 29 | `65a93e12ab03` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip |
| candidatos | 2026 | 2026-10-01T135445Z | 3.2 | 29 | `26293feda213` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip |
| coligaciones | 2018 | 2026-10-01T050052Z | 0.4 | 29 | `711074c0596f` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_coligacao/consulta_coligacao_2018.zip |
| coligaciones | 2022 | 2026-10-01T050053Z | 0.4 | 29 | `5abeda793a8c` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_coligacao/consulta_coligacao_2022.zip |
| coligaciones | 2022 | 2026-10-01T070113Z | 0.4 | 29 | `3ab2389bb7e0` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_coligacao/consulta_coligacao_2022.zip |
| coligaciones | 2026 | 2026-10-01T050053Z | 0.4 | 29 | `8b9e2d0cb66e` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_coligacao/consulta_coligacao_2026.zip |
| coligaciones | 2026 | 2026-10-01T135447Z | 0.3 | 29 | `a99a653a0d12` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_coligacao/consulta_coligacao_2026.zip |
| detalle_votacion | 2018 | 2026-10-01T050057Z | 4.3 | 29 | `df68c258a226` | https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2018.zip |
| detalle_votacion | 2022 | 2026-10-01T050059Z | 4.4 | 29 | `1daacae013ec` | https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2022.zip |
| detalle_votacion | 2022 | 2026-10-01T135440Z | 4.4 | 29 | `c826fa7f02e2` | https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2022.zip |
| encuestas_registradas | 2018 | 2026-10-01T050036Z | 1.3 | 29 | `6c26a1510b5a` | https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_2018.zip |
| encuestas_registradas | 2022 | 2026-10-01T050037Z | 3.2 | 29 | `5565b63ced39` | https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_2022.zip |
| encuestas_registradas | 2026 | 2026-10-01T050040Z | 5.9 | 27 | `d965d166bb90` | https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_2026.zip |
| encuestas_wikipedia | 2018 | 2026-10-01T173539Z | 0.6 | 0 | `99cf4d605229` | https://en.wikipedia.org/w/api.php?action=parse&page=Opinion+polling+for+the+2018+Brazilian+presidential+election&prop=text%7Crevid&format=json&formatversion=2 |
| encuestas_wikipedia | 2022 | 2026-10-01T173541Z | 1.4 | 0 | `4dcc0a7f6ec9` | https://en.wikipedia.org/w/api.php?action=parse&page=Opinion+polling+for+the+2022+Brazilian+presidential+election&prop=text%7Crevid&format=json&formatversion=2 |
| encuestas_wikipedia | 2026 | 2026-10-01T173542Z | 1.9 | 0 | `557d0587b310` | https://en.wikipedia.org/w/api.php?action=parse&page=Opinion+polling+for+the+2026+Brazilian+presidential+election&prop=text%7Crevid&format=json&formatversion=2 |
| ibge_municipios | referencia | 2026-10-01T065209Z | 2.4 | 0 | `77bf68d9f5b1` | https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado |
| resultados | 2018 | 2026-10-01T050930Z | 395.4 | 29 | `f880848ef4ba` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2018.zip |
| resultados | 2022 | 2026-10-01T051735Z | 578.0 | 29 | `a53bfa7effb8` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip |
| resultados | 2022 | 2026-10-01T135433Z | 581.8 | 29 | `7f493afba970` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip |
| resultados_partido | 2018 | 2026-10-01T051825Z | 27.9 | 29 | `c3ab9e78efd8` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/votacao_partido_munzona_2018.zip |
| resultados_partido | 2022 | 2026-10-01T051954Z | 25.2 | 29 | `60300ce06258` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/votacao_partido_munzona_2022.zip |
| resultados_partido | 2022 | 2026-10-01T070107Z | 25.1 | 29 | `626d9c1f4a5e` | https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/votacao_partido_munzona_2022.zip |
| senado_en_ejercicio | referencia | 2026-10-01T142728Z | 0.1 | 0 | `394614354d51` | https://legis.senado.leg.br/dadosabertos/senador/lista/atual |
| tse_ibge_betafcc | referencia | 2026-10-01T065210Z | 0.2 | 0 | `723eae7e5ac5` | https://raw.githubusercontent.com/betafcc/Municipios-Brasileiros-TSE/master/municipios_brasileiros_tse.csv |
| vagas | 2022 | 2026-10-01T140823Z | 0.2 | 29 | `9b357e4a0513` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_vagas/consulta_vagas_2022.zip |
| vagas | 2026 | 2026-10-01T140824Z | 0.2 | 29 | `872498ce5508` | https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_vagas/consulta_vagas_2026.zip |

**Total:** 31 archivos, 1.69 GB.
