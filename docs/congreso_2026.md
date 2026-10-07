# El Congreso que sale del 4/10/2026

`src/models/congreso_2026.py` · brief `src/viz/brief_congreso_pdf.py` →
`reports/briefs/ATLAS_Brasil_Congreso_<fecha>.pdf`.

- Electos: TSE, elección estadual 6259, cargos 0006 (Deputado Federal) y 0005
  (Senador), por UF. Família por partido con el resolver del modelo (año 2026).
  Senado total = 54 electos + 27 que siguen (`senadores_que_siguen.csv` del
  modelo del 1/10, API del Senado).
- Resultado 2026-10-07: PL 121 diputados (PT 70) y 28 senadores (19 de 54
  electos). Por família, Câmara: Centrão 214, Gobierno Lula 129, direita
  bolsonarista 121, centro liberal 49. Senado: Centrão 30, direita 28,
  Gobierno Lula 15, centro liberal 7, sin alineamiento 1.
- Contra el Montecarlo del 1/10: Câmara acierta Gobierno Lula (127) y centro
  liberal (49), subestima al PL (mediana 90) y sobreestima al Centrão (240).
  Senado: PL 28 por encima de todas las simulaciones (mediana 17); el
  percentil de la simulación usa `tipo == "total"` del parquet.
- Umbrales: mayoría absoluta 257/41, 3/5 (enmienda) 308/49, 2/3 (juicio
  político) 342/54; bloquean una enmienda 206/33 y un juicio político 172/28.
- Coaliciones (famílias en bloque, supuesto): Flávio + Centrão 335/58 (3/5 en
  las dos cámaras); Lula + Centrão 343/45 (sin 3/5 en el Senado), con centro
  liberal 392/52.
