"""Criterio di accettazione M1 (15-guida-implementazione.md)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import perimetro, store
from src.config import Config


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_import_filtra_a_100km_e_deriva_fascia(tmp_path):
    csv_content = (
        "IdComune;Comune;Provincia;Regione;CodiceISTAT;Latitudine;Longitudine;"
        "DistanzaKm;DurataStimataMinuti;DataCalcolo;Incluso\n"
        "1;Calosso;AT;Piemonte;1;44.74;8.23;0.0;0;2026-08-05;SI\n"
        "2;VicinoA;AT;Piemonte;2;44.7;8.2;30.0;40;2026-08-05;SI\n"
        "3;VicinoB;AT;Piemonte;3;44.7;8.2;60.0;70;2026-08-05;SI\n"
        "4;VicinoC;AT;Piemonte;4;44.7;8.2;90.0;100;2026-08-05;SI\n"
        "5;Lontano;AT;Piemonte;5;44.7;8.2;150.0;120;2026-08-05;SI\n"
    )
    csv_path = tmp_path / "perimetro.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    conn = _conn_di_prova()
    conteggi = perimetro.importa_perimetro(csv_path, conn, Config())

    assert conteggi == {"A": 2, "B": 1, "C": 1, "esclusi": 1}


def test_risolvi_comune_case_insensitive_e_alias(tmp_path):
    csv_path = tmp_path / "perimetro.csv"
    csv_path.write_text(
        "IdComune;Comune;Provincia;Regione;CodiceISTAT;Latitudine;Longitudine;"
        "DistanzaKm;DurataStimataMinuti;DataCalcolo;Incluso\n"
        "1;Calosso;AT;Piemonte;1;44.74;8.23;0.0;0;2026-08-05;SI\n",
        encoding="utf-8",
    )
    conn = _conn_di_prova()
    perimetro.importa_perimetro(csv_path, conn, Config())

    assert perimetro.risolvi_comune("Calosso", conn)["comune"] == "Calosso"
    assert perimetro.risolvi_comune("CALOSSO", conn)["comune"] == "Calosso"
    assert perimetro.risolvi_comune("comune-inesistente", conn) is None

    conn.execute("UPDATE comuni SET alias = 'Calosso;Frazione Test' WHERE istat = '1'")
    assert perimetro.risolvi_comune("Frazione Test", conn)["comune"] == "Calosso"
