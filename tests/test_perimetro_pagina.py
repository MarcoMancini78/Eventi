"""16.8 (webapp perimetro): righe_perimetro_completo / scrivi_perimetro_json."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import publisher, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_righe_perimetro_include_dati_base_comune():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert len(righe) == 1
    assert righe[0]["comune"] == "Calosso"
    assert righe[0]["provincia"] == "AT"


def test_righe_perimetro_collega_sito_comune_e_proloco():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, categoria, endpoint) VALUES ('comune-calosso', 'comune', 'https://comune.calosso.at.it/Eventi')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, categoria, endpoint) VALUES ('proloco-calosso-sito', 'proloco', 'https://prolococalosso.it')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["sito_comune"] == "https://comune.calosso.at.it/Eventi"
    assert righe[0]["sito_proloco"] == "https://prolococalosso.it"


def test_righe_perimetro_collega_social_comune_e_proloco():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, url) "
        "VALUES ('comune-calosso-facebook', 'facebook', 'Calosso', 'comune', 'https://facebook.com/comune.calosso')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, url) "
        "VALUES ('proloco-calosso-instagram', 'instagram', 'Calosso', 'proloco', 'https://instagram.com/prolococalosso')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["facebook_comune"] == "https://facebook.com/comune.calosso"
    assert righe[0]["instagram_proloco"] == "https://instagram.com/prolococalosso"
    assert righe[0]["facebook_proloco"] == ""


def test_righe_perimetro_categoria_teatro_finisce_in_altro():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Cambiano', 'TO', 30.0, 35, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, soggetto, url) "
        "VALUES ('teatro-cambiano-facebook', 'facebook', 'Cambiano', 'teatro', 'Cambiano - Teatro Comunale', 'https://facebook.com/teatrocambiano')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["altro"] == [
        {"soggetto": "Cambiano - Teatro Comunale", "facebook": "https://facebook.com/teatrocambiano", "instagram": ""}
    ]


def test_righe_perimetro_altro_unisce_facebook_e_instagram_stesso_soggetto():
    """Un teatro seguito su entrambe le piattaforme deve comparire una sola
    volta in 'altro', non due righe duplicate per lo stesso soggetto."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Canelli', 'AT', 7.5, 13, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, soggetto, url) "
        "VALUES ('teatro-canelli-facebook', 'facebook', 'Canelli', 'teatro', 'Canelli - Teatro Balbi', 'https://facebook.com/teatrobalbi')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, soggetto, url) "
        "VALUES ('teatro-canelli-instagram', 'instagram', 'Canelli', 'teatro', 'Canelli - Teatro Balbi', 'https://instagram.com/teatrobalbi')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["altro"] == [
        {
            "soggetto": "Canelli - Teatro Balbi",
            "facebook": "https://facebook.com/teatrobalbi",
            "instagram": "https://instagram.com/teatrobalbi",
        }
    ]


def test_righe_perimetro_comune_senza_link_ha_campi_vuoti():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Nessuno', 'XX', 10.0, 15, 'A', 'si')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["sito_comune"] == ""
    assert righe[0]["facebook_comune"] == ""
    assert righe[0]["altro"] == []


def test_scrivi_perimetro_json_scrive_file_valido(tmp_path):
    righe = [{"comune": "Calosso", "km": 0.0}]
    percorso = tmp_path / "perimetro.json"

    n = publisher.scrivi_perimetro_json(righe, percorso)

    assert n == 1
    corpo = json.loads(percorso.read_text(encoding="utf-8"))
    assert corpo["comuni"] == righe
    assert "generato_il" in corpo
