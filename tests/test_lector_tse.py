import zipfile

from src.etl.transform.lector_tse import archivos_a_leer, leer_zip_tse


def _zip(tmp_path, archivos: dict[str, str]):
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido.encode("latin-1"))
    return p


def test_prefiere_brasil_si_existe():
    nombres = ["d_2022_BR.csv", "d_2022_SP.csv", "d_2022_BRASIL.csv", "leiame.pdf"]
    assert archivos_a_leer(nombres) == ["d_2022_BRASIL.csv"]


def test_sin_brasil_lee_todos_los_csv():
    nombres = ["d_2018_BR.csv", "d_2018_SP.csv", "leiame.pdf"]
    assert archivos_a_leer(nombres) == ["d_2018_BR.csv", "d_2018_SP.csv"]


def test_no_duplica_registros(tmp_path):
    cab = "SG_UF;QT\n"
    p = _zip(tmp_path, {
        "d_2022_SP.csv": cab + "SP;10\n",
        "d_2022_RJ.csv": cab + "RJ;5\n",
        "d_2022_BRASIL.csv": cab + "SP;10\nRJ;5\n",
    })
    df = leer_zip_tse(p)
    assert len(df) == 2


def test_centinelas_a_na(tmp_path):
    p = _zip(tmp_path, {"d_2022_BRASIL.csv": "A;B;C\n#NULO#;-1;ok\n"})
    df = leer_zip_tse(p)
    assert df["A"].isna().all() and df["B"].isna().all() and df.loc[0, "C"] == "ok"
