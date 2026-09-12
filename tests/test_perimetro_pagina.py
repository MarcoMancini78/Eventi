"""16.8 (webapp perimetro): righe_perimetro_completo / scrivi_perimetro_json."""
import json
import sqlite3
import sys
from datetime import date, timedelta
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
    assert righe[0]["sito_comune"]["url"] == "https://comune.calosso.at.it/Eventi"
    assert righe[0]["sito_proloco"]["url"] == "https://prolococalosso.it"


def test_righe_perimetro_collega_social_comune_e_proloco():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url) "
        "VALUES ('comune-calosso-facebook', 'facebook', 'comune.calosso', 'Calosso', 'comune', 'https://facebook.com/comune.calosso')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url) "
        "VALUES ('proloco-calosso-instagram', 'instagram', 'prolococalosso', 'Calosso', 'proloco', 'https://instagram.com/prolococalosso')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["facebook_comune"]["url"] == "https://facebook.com/comune.calosso"
    assert righe[0]["instagram_proloco"]["url"] == "https://instagram.com/prolococalosso"
    assert righe[0]["facebook_proloco"]["url"] == ""


def test_righe_perimetro_categoria_teatro_finisce_in_altro():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Cambiano', 'TO', 30.0, 35, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, soggetto, url) "
        "VALUES ('teatro-cambiano-facebook', 'facebook', 'teatrocambiano', 'Cambiano', 'teatro', 'Cambiano - Teatro Comunale', 'https://facebook.com/teatrocambiano')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["altro"] == [
        {
            "soggetto": "Cambiano - Teatro Comunale",
            "facebook": "https://facebook.com/teatrocambiano",
            "instagram": "",
            "attivi": 0,
            "totale": 0,
        }
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
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, soggetto, url) "
        "VALUES ('teatro-canelli-facebook', 'facebook', 'teatrobalbi', 'Canelli', 'teatro', 'Canelli - Teatro Balbi', 'https://facebook.com/teatrobalbi')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, soggetto, url) "
        "VALUES ('teatro-canelli-instagram', 'instagram', 'teatrobalbi', 'Canelli', 'teatro', 'Canelli - Teatro Balbi', 'https://instagram.com/teatrobalbi')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["altro"] == [
        {
            "soggetto": "Canelli - Teatro Balbi",
            "facebook": "https://facebook.com/teatrobalbi",
            "instagram": "https://instagram.com/teatrobalbi",
            "attivi": 0,
            "totale": 0,
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
    assert righe[0]["sito_comune"] == {"url": "", "attivi": 0, "totale": 0}
    assert righe[0]["facebook_comune"] == {"url": "", "attivi": 0, "totale": 0}
    assert righe[0]["altro"] == []


def test_righe_perimetro_conteggio_sito_attivi_e_totale():
    """Primo numero: eventi attivi/futuri (non archiviati, data_fine >= oggi).
    Secondo numero: tutti gli eventi mai trovati da quella fonte, archiviati
    inclusi — non solo il passato isolato, il totale storico."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, categoria, endpoint) VALUES ('comune-calosso', 'comune', 'https://comune.calosso.at.it/Eventi')"
    )
    oggi = date.today()
    futuro = (oggi + timedelta(days=10)).isoformat()
    passato_archiviato = (oggi - timedelta(days=30)).isoformat()
    passato_non_archiviato = (oggi - timedelta(days=1)).isoformat()

    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento futuro', ?, ?, 'Calosso', 'no')",
        (futuro, futuro),
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev2', 'Evento passato archiviato', ?, ?, 'Calosso', 'si')",
        (passato_archiviato, passato_archiviato),
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev3', 'Evento appena concluso non ancora archiviato', ?, ?, 'Calosso', 'no')",
        (passato_non_archiviato, passato_non_archiviato),
    )
    for eid in ("ev1", "ev2", "ev3"):
        conn.execute(
            "INSERT INTO event_sources (event_id, source_id, url, seen_at) VALUES (?, 'comune-calosso', 'https://x', '2026-01-01')",
            (eid,),
        )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["sito_comune"]["attivi"] == 1
    assert righe[0]["sito_comune"]["totale"] == 3


def test_righe_perimetro_conteggio_social_via_handle():
    """Il conteggio eventi social si collega tramite l'handle (coda_follow),
    non il source_id di coda_follow: gli eventi letti dal feed sono
    registrati sotto 'feed-{piattaforma}-{handle}' (feed_social.py)."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url) "
        "VALUES ('comune-calosso-facebook', 'facebook', 'comune.calosso', 'Calosso', 'comune', 'https://facebook.com/comune.calosso')"
    )
    futuro = (date.today() + timedelta(days=5)).isoformat()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento social', ?, ?, 'Calosso', 'no')",
        (futuro, futuro),
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'feed-facebook-comune.calosso', 'https://x', '2026-01-01')"
    )
    conn.commit()

    righe = publisher.righe_perimetro_completo(conn)
    assert righe[0]["facebook_comune"]["attivi"] == 1
    assert righe[0]["facebook_comune"]["totale"] == 1


def test_scrivi_perimetro_json_scrive_file_valido(tmp_path):
    righe = [{"comune": "Calosso", "km": 0.0}]
    percorso = tmp_path / "perimetro.json"

    n = publisher.scrivi_perimetro_json(righe, percorso)

    assert n == 1
    corpo = json.loads(percorso.read_text(encoding="utf-8"))
    assert corpo["comuni"] == righe
    assert "generato_il" in corpo
