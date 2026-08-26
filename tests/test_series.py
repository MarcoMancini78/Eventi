"""M6 collegato: dal campo Ricorrenza dell'estrattore alla Serie e alle occorrenze (07.9)."""
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import series, store
from src.config import Config
from src.extractor.schema import Ricorrenza


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'Calosso', 'AT', 44.74, 8.23, 0.0, 0, 'A', 'si')"
    )
    return conn


def test_upsert_serie_prima_volta_crea_riga():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(
        e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1,
        mesi_inclusi=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12],
    )
    sid = series.upsert_serie(
        conn, ricorrenza, titolo="Mercatino dell'antiquariato", tipologia="fiera",
        comune="Calosso", luogo="Piazza Roma", fonte="proloco-calosso",
        oggi=date(2026, 8, 22),
    )
    assert sid is not None

    riga = conn.execute("SELECT * FROM series WHERE serie_id = ?", (sid,)).fetchone()
    assert riga["regola_leggibile"] == "prima domenica del mese, escluso agosto"
    assert "BYDAY=1SU" in riga["rrule"]
    assert riga["stato"] == "attiva"


def test_upsert_serie_stessa_ricorrenza_non_duplica():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1, mesi_inclusi=list(range(1, 13)))

    sid1 = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Roma", "fonte-a", oggi=date(2026, 8, 1))
    sid2 = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Roma", "fonte-b", oggi=date(2026, 8, 15))

    assert sid1 == sid2
    totale = conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]
    assert totale == 1


def test_upsert_serie_bloccata_non_viene_modificata():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1, mesi_inclusi=list(range(1, 13)))
    sid = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Roma", "fonte-a", oggi=date(2026, 8, 1))

    conn.execute("UPDATE series SET bloccata='si', luogo='Corretto a mano' WHERE serie_id=?", (sid,))
    conn.commit()

    series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Diversa", "fonte-a", oggi=date(2026, 9, 1))

    riga = conn.execute("SELECT luogo FROM series WHERE serie_id=?", (sid,)).fetchone()
    assert riga["luogo"] == "Corretto a mano"


def test_upsert_serie_frequenza_annuale_non_supportata_ritorna_none():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="annuale", giorni_settimana=[], mesi_inclusi=[])
    sid = series.upsert_serie(conn, ricorrenza, "Sagra annuale", "sagra", "Calosso", None, "fonte-a")
    assert sid is None


def test_upsert_serie_normalizza_giorno_settimana_per_esteso():
    """Bug reale (2026-08-26): l'LLM ha restituito 'mercoledì' invece del
    codice RFC5545 'WE' nonostante il prompt lo richieda esplicitamente,
    facendo sollevare KeyError in regola_leggibile e fermare l'intero run
    multi-fonte. Deve essere normalizzato in silenzio, non far fallire."""
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(
        e_ricorrente=True, frequenza="settimanale", giorni_settimana=["mercoledì"],
        mesi_inclusi=list(range(1, 13)),
    )
    sid = series.upsert_serie(
        conn, ricorrenza, titolo="Mercato settimanale", tipologia="fiera",
        comune="Calosso", luogo=None, fonte="comune-calosso", oggi=date(2026, 8, 22),
    )
    assert sid is not None
    riga = conn.execute("SELECT rrule, regola_leggibile FROM series WHERE serie_id=?", (sid,)).fetchone()
    assert "BYDAY=WE" in riga["rrule"]
    assert "mercoledì" in riga["regola_leggibile"]


def test_upsert_serie_giorno_non_riconosciuto_scarta_senza_fallire():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(
        e_ricorrente=True, frequenza="settimanale", giorni_settimana=["giorno-inventato"],
        mesi_inclusi=list(range(1, 13)),
    )
    sid = series.upsert_serie(
        conn, ricorrenza, "Evento boh", "altro", "Calosso", None, "fonte-a", oggi=date(2026, 8, 22),
    )
    assert sid is None


def test_espandi_serie_in_eventi_genera_occorrenze_future():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1, mesi_inclusi=list(range(1, 13)))
    sid = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Roma", "fonte-a", oggi=date(2026, 8, 1))

    occorrenze = series.espandi_serie_in_eventi(conn, sid, Config(), oggi=date(2026, 8, 1))

    assert len(occorrenze) > 0
    for occ in occorrenze:
        assert occ["serie_id"] == sid
        assert occ["comune"] == "Calosso"
        assert "di" in occ["occorrenza"]


def test_espandi_serie_rispetta_le_eccezioni():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1, mesi_inclusi=list(range(1, 13)))
    sid = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Calosso", "Piazza Roma", "fonte-a", oggi=date(2026, 8, 1))

    prime_occorrenze = series.espandi_serie_in_eventi(conn, sid, Config(), oggi=date(2026, 8, 1))
    data_da_escludere = prime_occorrenze[0]["data_inizio"]

    conn.execute("UPDATE series SET eccezioni = ? WHERE serie_id = ?", (data_da_escludere, sid))
    conn.commit()

    dopo = series.espandi_serie_in_eventi(conn, sid, Config(), oggi=date(2026, 8, 1))
    date_generate = {o["data_inizio"] for o in dopo}
    assert data_da_escludere not in date_generate


def test_espandi_serie_comune_fuori_perimetro_non_genera():
    conn = _conn_di_prova()
    ricorrenza = Ricorrenza(e_ricorrente=True, frequenza="mensile", giorni_settimana=["SU"], ordinale=1, mesi_inclusi=list(range(1, 13)))
    sid = series.upsert_serie(conn, ricorrenza, "Mercatino", "fiera", "Comune Fantasma", None, "fonte-a", oggi=date(2026, 8, 1))

    occorrenze = series.espandi_serie_in_eventi(conn, sid, Config(), oggi=date(2026, 8, 1))
    assert occorrenze == []
