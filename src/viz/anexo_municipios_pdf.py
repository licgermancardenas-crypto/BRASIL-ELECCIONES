"""
src/viz/anexo_municipios_pdf.py

Anexo del brief del balotaje: los 5.571 municípios con quién ganó cada uno.
Por município: resultado de la 1ª vuelta del 4/10/2026 (TSE, 100 % de las
secciones), ganador de la 2ª vuelta de 2022 y proyección del modelo para el
25/10 (última corrida de src/models/balotaje_2026.py).

Output: reports/briefs/ATLAS_Brasil_Municipios_<fecha>.pdf
        reports/briefs/ATLAS_Brasil_Municipios_<fecha>.xlsx (la misma tabla, filtrable)

Uso:
    python -m src.viz.anexo_municipios_pdf [--fecha 2026-10-15]
"""
from __future__ import annotations

import argparse
import logging
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

from src.etl.transform.base_locales import salida as salida_locales
from src.etl.transform.correspondencia_municipios import cargar as cargar_correspondencia
from src.models.balotaje_2026 import SALIDA_DIR as BALOTAJE_DIR
from src.models.conteo_2026 import SALIDA_FINAL as RESULTADO_2026
from src.models.montecarlo.proyeccion_bancas import ROOT
from src.viz.brief_pdf import BRIEFS, C_FLAVIO, C_LULA, CHROME, CSS_MARCA, Documento, f0, f1, insight, tabla, ultima

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BUILD = BRIEFS / "_build_municipios"
FILAS_POR_COLUMNA = 40
# Creado en 2023 (desmembrado de Nova Ubiratã); no está en la correspondencia TSE-IBGE de 2018/2022.
NOMBRES_FALTANTES = {5101837: "Boa Esperança do Norte"}
UF_NOMBRE = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
             "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
             "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
             "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
             "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
             "TO": "Tocantins"}
CANDIDATOS = ["flavio_bolsonaro", "lula", "renan_santos", "cury", "caiado", "zema", "otros"]
CORTO = {"lula": "Lula", "flavio_bolsonaro": "Flávio", "bolsonaro": "Bolsonaro"}
COLOR = {"Lula": C_LULA, "Flávio": C_FLAVIO, "Bolsonaro": C_FLAVIO}


def tabla_municipios() -> pd.DataFrame:
    r = pd.read_parquet(RESULTADO_2026).query("uf != 'ZZ'").set_index("codigo")
    nombres = cargar_correspondencia().dropna(subset=["codigo_ibge"])
    nombres = nombres.set_index(nombres["codigo_ibge"].astype(int))["nombre_ibge"]
    t = pd.DataFrame({"uf": r["uf"], "municipio": nombres.reindex(r.index)})
    t["municipio"] = t["municipio"].fillna(pd.Series(NOMBRES_FALTANTES))
    if t["municipio"].isna().any():
        raise ValueError(f"Municípios sin nombre: {t.index[t['municipio'].isna()].tolist()}")
    t["electores"] = r["aptos"]
    t["participacion_pct"] = r["comparecencia"] / r["aptos"] * 100
    for c in CANDIDATOS:
        t[f"{c}_pct"] = r[c] / r["validos"] * 100
    orden = r[CANDIDATOS].apply(lambda f: f.sort_values(ascending=False).index[:2].tolist(), axis=1)
    t["ganador_1v"] = orden.str[0].map(lambda c: CORTO.get(c, c))
    t["margen_1v_pts"] = [(r.at[i, a] - r.at[i, b]) / r.at[i, "validos"] * 100 for i, (a, b) in orden.items()]

    loc = pd.read_parquet(salida_locales(2022)).query("uf != 'ZZ'")
    m22 = loc.groupby(loc["cd_ibge"].astype(int))[["pt_2", "bolsonaro_2"]].sum()
    lula22 = m22["pt_2"] / (m22["pt_2"] + m22["bolsonaro_2"]) * 100
    t["lula_2v_2022_pct"] = lula22.reindex(t.index)
    t["ganador_2v_2022"] = t["lula_2v_2022_pct"].map(lambda x: None if pd.isna(x) else "Lula" if x > 50 else "Bolsonaro")

    mod = pd.read_parquet(ultima(BALOTAJE_DIR) / "municipios.parquet")
    t["lula_proy_25_10_pct"] = mod["lula_pct"].reindex(t.index)
    t["ganador_proy_25_10"] = t["lula_proy_25_10_pct"].map(lambda x: None if pd.isna(x) else "Lula" if x > 50 else "Flávio")
    t["cambio_vs_2022"] = (t["ganador_1v"].replace({"Flávio": "Bolsonaro"}) != t["ganador_2v_2022"]) & t["ganador_2v_2022"].notna()
    t.index.name = "codigo_ibge"
    return t.sort_values(["uf", "municipio"], key=lambda s: s.str.normalize("NFKD") if s.dtype == object else s)


def resumen_uf(t: pd.DataFrame) -> pd.DataFrame:
    g = t.groupby("uf")
    return pd.DataFrame({
        "municipios": g.size(),
        "lula_1v": g["ganador_1v"].apply(lambda s: (s == "Lula").sum()),
        "flavio_1v": g["ganador_1v"].apply(lambda s: (s == "Flávio").sum()),
        "lula_2022": g["ganador_2v_2022"].apply(lambda s: (s == "Lula").sum()),
        "cambios_vs_2022": g["cambio_vs_2022"].sum(),
        "lula_proy": g["ganador_proy_25_10"].apply(lambda s: (s == "Lula").sum()),
    })


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def chip(g) -> str:
    if g is None or pd.isna(g):
        return '<span class="chip vacio">—</span>'
    return f'<span class="chip" style="background:{COLOR[g]}">{g}</span>'


def fila(i: int, r) -> str:
    return (f'<tr><td class="mun">{r.municipio}</td><td class="num">{f0(r.electores)}</td>'
            f'<td class="num">{f1(r.lula_pct)}</td><td class="num">{f1(r.flavio_bolsonaro_pct)}</td>'
            f'<td>{chip(r.ganador_1v)}</td><td class="num">{f1(r.margen_1v_pts)}</td>'
            f'<td>{chip(r.ganador_2v_2022)}</td>'
            f'<td class="num">{"—" if pd.isna(r.lula_proy_25_10_pct) else f1(r.lula_proy_25_10_pct)}</td></tr>')


CAB = ('<thead><tr><th>Município</th><th class="num">Electores</th><th class="num">Lula %</th>'
       '<th class="num">Flávio %</th><th>Ganó 4/10</th><th class="num">Margen</th><th>2ª v. 2022</th>'
       '<th class="num">Lula 25/10*</th></tr></thead>')


def columnas(t: pd.DataFrame) -> list[str]:
    """Filas de las tablas (con una fila de título por estado) partidas en columnas de largo fijo."""
    filas: list[tuple[str, str]] = []          # (uf, html); los títulos de estado van con uf vacía
    for uf, g in t.groupby("uf", sort=True):
        n_l = (g["ganador_1v"] == "Lula").sum()
        filas.append(("", f'<tr class="uf"><td colspan="8">{UF_NOMBRE[uf]} ({uf}) · {len(g)} municípios · '
                          f'Lula ganó {n_l}, Flávio {len(g) - n_l}</td></tr>'))
        filas += [(uf, fila(i, r)) for i, r in enumerate(g.itertuples())]
    trozos, k = [], 0
    while k < len(filas):
        uf = filas[k][0]
        cont = [f'<tr class="uf"><td colspan="8">{UF_NOMBRE[uf]} ({uf}) · continuación</td></tr>'] if uf else []
        n = FILAS_POR_COLUMNA - len(cont)
        trozos.append(cont + [h for _, h in filas[k:k + n]])
        k += n
    return [f'<table class="lista">{CAB}<tbody>{"".join(x)}</tbody></table>' for x in trozos]


CSS_EXTRA = """
.cab h2 { font-size:15pt; } .cab { margin-bottom:.25cm; }
table.lista { font-size:6.6pt; margin:0; table-layout:fixed; }
table.lista th { font-size:6pt; padding:.07cm .1cm; }
table.lista td { padding:.035cm .1cm; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
table.lista th:nth-child(1) { width:30%; } table.lista th:nth-child(2) { width:11%; }
table.lista th:nth-child(3), table.lista th:nth-child(4), table.lista th:nth-child(6) { width:8.5%; }
table.lista th:nth-child(5), table.lista th:nth-child(7) { width:11.5%; } table.lista th:nth-child(8) { width:10.5%; }
table.lista tr.uf td { background:#1D1631 !important; color:#fff; font-weight:bold; font-size:6.8pt; padding:.06cm .12cm; }
.chip { display:inline-block; color:#fff; border-radius:.06cm; padding:0 .1cm; font-size:6.1pt; font-weight:bold; line-height:1.35; }
.chip.vacio { color:#8A8983; }
.par { display:grid; grid-template-columns:1fr 1fr; gap:.5cm; }
.resumen table { font-size:8.4pt; } .resumen td { padding:.07cm .16cm; } .resumen th { font-size:7.4pt; }
.insight { font-size:9.4pt; line-height:1.4; padding:.26cm .34cm; margin:.2cm 0; }
.nota { font-size:8.4pt; line-height:1.4; color:#55525E; }
"""


def construir(fecha: date) -> tuple[Path, Path]:
    BUILD.mkdir(parents=True, exist_ok=True)
    t = tabla_municipios()
    u = resumen_uf(t)
    marca = "Atlas Analytics · Brasil 2026"
    D = Documento(marca)
    pie = "TSE, divulgación oficial del 4/10/2026 al 100 % y resultados por sección de 2022. * Proyección del modelo ATLAS."

    # ------------------------------------------------ resumen
    n = len(t)
    n_l, n_f = (t["ganador_1v"] == "Lula").sum(), (t["ganador_1v"] == "Flávio").sum()
    el_l = t.loc[t["ganador_1v"] == "Lula", "electores"].sum() / t["electores"].sum() * 100
    a_fl = (t["ganador_1v"] == "Flávio") & (t["ganador_2v_2022"] == "Lula")
    a_lu = (t["ganador_1v"] == "Lula") & (t["ganador_2v_2022"] == "Bolsonaro")
    p_l = (t["ganador_proy_25_10"] == "Lula").sum()
    ajustados = t[t["margen_1v_pts"] < 2]
    top_fl = t[a_fl].nlargest(8, "electores")
    filas_u = [[f"{UF_NOMBRE[k]} ({k})", f0(r.municipios), f0(r.lula_1v), f0(r.flavio_1v), f0(r.lula_2022),
                f0(r.cambios_vs_2022), f0(r.lula_proy)] for k, r in u.iterrows()]
    filas_u.append(["<b>Brasil</b>", f"<b>{f0(n)}</b>", f"<b>{f0(n_l)}</b>", f"<b>{f0(n_f)}</b>",
                    f"<b>{f0(u['lula_2022'].sum())}</b>", f"<b>{f0(u['cambios_vs_2022'].sum())}</b>", f"<b>{f0(p_l)}</b>"])
    cuerpo = ('<div class="par"><div class="resumen">'
              + tabla(["Estado", "Municípios", "Lula 4/10", "Flávio 4/10", "Lula 2ª v. 2022", "Cambiaron", "Lula 25/10*"],
                      filas_u, num=(1, 2, 3, 4, 5, 6))
              + "</div><div>"
              + insight(f"<b>Flávio ganó {f0(n_f)} municípios y Lula {f0(n_l)}</b> en la 1ª vuelta del 4/10, entre los dos "
                        f"finalistas. Los municípios de Lula reúnen el {f1(el_l)} % del padrón: gana en más pueblos chicos, "
                        "pero Flávio se queda con las ciudades medianas.")
              + insight(f"<b>{f0(a_fl.sum())} municípios pasaron de Lula a Flávio</b> respecto de la 2ª vuelta de 2022, y "
                        f"{f0(a_lu.sum())} de Bolsonaro a Lula. Los más grandes que cambiaron hacia Flávio: "
                        + ", ".join(f"{r.municipio} ({r.uf})" for r in top_fl.itertuples()) + ".")
              + insight(f"<b>{f0(len(ajustados))} municípios se definieron por menos de 2 puntos</b> "
                        f"({f1(ajustados['electores'].sum() / 1e6)} M de electores). Para el 25/10 el modelo proyecta a "
                        f"Lula ganando en {f0(p_l)}.")
              + '<p class="nota"><b>Cómo leer la lista.</b> Un estado por bloque, municípios en orden alfabético. '
                "Lula % y Flávio % son sobre votos válidos de la 1ª vuelta. Margen: puntos de diferencia entre el primero "
                "y el segundo. 2ª v. 2022: quién ganó ese município en el balotaje Lula–Bolsonaro. Lula 25/10: proyección "
                "del modelo (votos válidos), sin encuestas. La misma tabla, con todos los candidatos y filtrable, está en "
                f"ATLAS_Brasil_Municipios_{fecha:%Y-%m-%d}.xlsx.</p>"
              + "</div></div>")
    D.pagina(cuerpo, kicker="ANEXO · MUNICÍPIOS", titulo=f"Quién ganó cada uno de los {f0(n)} municípios el 4 de octubre",
             bajada="Resultado de la 1ª vuelta, ganador en 2022 y proyección para el balotaje, por estado.", pie=pie)

    # ------------------------------------------------ lista
    cols = columnas(t)
    for k in range(0, len(cols), 2):
        par = cols[k:k + 2]
        D.pagina('<div class="par">' + "".join(f"<div>{c}</div>" for c in par) + "</div>",
                 kicker="ANEXO · MUNICÍPIOS", titulo="Resultado por município", pie=pie)

    html = (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Atlas Analytics · Municípios</title>'
            f'<style>{CSS_MARCA.read_text(encoding="utf-8")}{CSS_EXTRA}</style></head><body>{"".join(D.paginas)}</body></html>')
    (BUILD / "anexo.html").write_text(html, encoding="utf-8")
    chrome = next((c for c in CHROME if Path(c).exists()), None)
    if chrome is None:
        raise FileNotFoundError("No se encontró Chrome/Edge para imprimir el PDF")
    pdf = BRIEFS / f"ATLAS_Brasil_Municipios_{fecha:%Y-%m-%d}.pdf"
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        (BUILD / "anexo.html").as_uri()], capture_output=True, text=True)
    if r.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"Chrome no generó el PDF: {r.stderr[-500:]}")

    # ------------------------------------------------ Excel
    xlsx = BRIEFS / f"ATLAS_Brasil_Municipios_{fecha:%Y-%m-%d}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        x = t.reset_index().rename(columns={
            "codigo_ibge": "Código IBGE", "uf": "UF", "municipio": "Município", "electores": "Electores",
            "participacion_pct": "Participación %", "flavio_bolsonaro_pct": "Flávio %", "lula_pct": "Lula %",
            "renan_santos_pct": "Renan Santos %", "cury_pct": "Cury %", "caiado_pct": "Caiado %", "zema_pct": "Zema %",
            "otros_pct": "Otros %", "ganador_1v": "Ganó 4/10", "margen_1v_pts": "Margen 4/10 (pts)",
            "lula_2v_2022_pct": "Lula 2ª v. 2022 %", "ganador_2v_2022": "Ganó 2ª v. 2022",
            "lula_proy_25_10_pct": "Lula proyección 25/10 %", "ganador_proy_25_10": "Ganador proyectado 25/10",
            "cambio_vs_2022": "Cambió vs 2022"})
        x.round(2).to_excel(w, sheet_name="Municipios", index=False)
        ws = w.sheets["Municipios"]
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "C2"
        ws.column_dimensions["C"].width = 32
        u.reset_index().to_excel(w, sheet_name="Resumen por UF", index=False)
    log.info("PDF %s (%d páginas) · Excel %s", pdf.relative_to(ROOT).as_posix(), len(D.paginas),
             xlsx.relative_to(ROOT).as_posix())
    return pdf, xlsx


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    construir(args.fecha)


if __name__ == "__main__":
    main()
