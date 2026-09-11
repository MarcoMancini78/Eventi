"""collega_teatri.py: deduzione del comune per teatri/attività da coda_follow."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import collega_teatri, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    conn.execute(
        """
        INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo)
        VALUES ('1', 'Cambiano', 'Cambiano', 'TO', 44.9, 7.8, 30, 35, 'A', 'si')
        """
    )
    return conn


def test_deduci_comune_da_soggetto_formato_standard():
    assert collega_teatri.deduci_comune_da_soggetto("Cambiano - Teatro Comunale") == "Cambiano"


def test_deduci_comune_da_soggetto_senza_separatore():
    assert collega_teatri.deduci_comune_da_soggetto("Sagre Piemonte") is None


def test_deduci_comune_da_soggetto_vuoto():
    assert collega_teatri.deduci_comune_da_soggetto("") is None
    assert collega_teatri.deduci_comune_da_soggetto(None) is None


def test_collega_teatri_risolve_e_salva_comune_valido():
    conn = _conn_di_prova()
    conn.execute(
        """
        INSERT INTO coda_follow (source_id, piattaforma, soggetto, categoria)
        VALUES ('teatro-cambiano-facebook', 'facebook', 'Cambiano - Teatro Comunale', 'teatro')
        """
    )
    conn.commit()

    esiti = collega_teatri.collega_teatri(conn)

    assert esiti == [
        {
            "source_id": "teatro-cambiano-facebook",
            "piattaforma": "facebook",
            "soggetto": "Cambiano - Teatro Comunale",
            "comune": "Cambiano",
        }
    ]
    riga = conn.execute("SELECT comune, note FROM coda_follow WHERE source_id = 'teatro-cambiano-facebook'").fetchone()
    assert riga["comune"] == "Cambiano"
    assert "dedotto" in riga["note"]


def test_collega_teatri_non_sovrascrive_comune_esistente():
    conn = _conn_di_prova()
    conn.execute(
        """
        INSERT INTO coda_follow (source_id, piattaforma, soggetto, categoria, comune)
        VALUES ('teatro-x-facebook', 'facebook', 'Cambiano - Altro Teatro', 'teatro', 'ComuneManualeGiaCorretto')
        """
    )
    conn.commit()

    esiti = collega_teatri.collega_teatri(conn)

    assert esiti == []
    riga = conn.execute("SELECT comune FROM coda_follow WHERE source_id = 'teatro-x-facebook'").fetchone()
    assert riga["comune"] == "ComuneManualeGiaCorretto"


def test_collega_teatri_comune_non_risolvibile_resta_null():
    conn = _conn_di_prova()
    conn.execute(
        """
        INSERT INTO coda_follow (source_id, piattaforma, soggetto, categoria)
        VALUES ('teatro-fantasma-facebook', 'facebook', 'ComuneInesistente - Teatro X', 'teatro')
        """
    )
    conn.commit()

    esiti = collega_teatri.collega_teatri(conn)

    assert esiti == [
        {
            "source_id": "teatro-fantasma-facebook",
            "piattaforma": "facebook",
            "soggetto": "ComuneInesistente - Teatro X",
            "comune": None,
        }
    ]
    riga = conn.execute("SELECT comune FROM coda_follow WHERE source_id = 'teatro-fantasma-facebook'").fetchone()
    assert riga["comune"] is None
