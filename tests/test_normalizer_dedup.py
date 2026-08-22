"""M2: normalizzazione e dedup L1 (07.1, 07.6, 03.3)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import dedup, normalizer, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'Calosso', 'AT', 44.74, 8.23, 0.0, 0, 'A', 'si')"
    )
    return conn


def test_titolo_visualizzato_gestisce_maiuscolo_urlato_e_punteggiatura():
    assert normalizer.titolo_visualizzato("SAGRA DEL TARTUFO!!!") == "Sagra del Tartufo!"


def test_titolo_normalizzato_ordina_i_token_per_matching_tra_fonti():
    a = normalizer.titolo_normalizzato("Sagra della Rana Vimercate")
    b = normalizer.titolo_normalizzato("Vimercate: la Sagra della Rana")
    assert a == b


def test_normalizza_orario_formati_comuni():
    assert normalizer.normalizza_orario("21") == "21:00"
    assert normalizer.normalizza_orario("21.30") == "21:30"
    assert normalizer.normalizza_orario("9:5") == "09:05"


def test_stessa_chiave_titolo_data_comune_produce_stesso_event_id():
    chiave1 = normalizer.dedup_key(normalizer.titolo_normalizzato("Sagra del Tartufo"), "2026-09-12", "calosso")
    chiave2 = normalizer.dedup_key(normalizer.titolo_normalizzato("SAGRA DEL TARTUFO"), "2026-09-12", "calosso")
    assert normalizer.event_id(chiave1) == normalizer.event_id(chiave2)


def test_upsert_evento_stesso_evento_da_due_fonti_non_duplica():
    conn = _conn_di_prova()
    evento = {
        "titolo": "Sagra del Tartufo",
        "titolo_normalizzato": normalizer.titolo_normalizzato("Sagra del Tartufo"),
        "descrizione": "Degustazioni in piazza",
        "tipologia": "sagra",
        "data_inizio": "2026-09-12",
        "ora_inizio": "21:00",
        "data_fine": "2026-09-12",
        "ora_fine": None,
        "comune": "Calosso",
        "comune_normalizzato": "calosso",
        "luogo": "Piazza Roma",
        "km": 0.0,
        "minuti": 0,
        "prezzo": None,
        "organizzatore": None,
        "url": "https://fonte-a.it/evento",
        "url_immagine": None,
        "confidenza": 95,
    }

    id1 = dedup.upsert_evento(conn, evento, source_id="fonte-a")
    evento["url"] = "https://fonte-b.it/evento-duplicato"
    id2 = dedup.upsert_evento(conn, evento, source_id="fonte-b")

    assert id1 == id2
    totale = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert totale == 1

    fonti = conn.execute("SELECT COUNT(*) FROM event_sources WHERE event_id = ?", (id1,)).fetchone()[0]
    assert fonti == 2  # entrambe le fonti sono tracciate, ma un solo evento


def test_evento_bloccato_non_viene_sovrascritto(monkeypatch=None):
    conn = _conn_di_prova()
    evento_base = {
        "titolo": "Sagra del Tartufo",
        "titolo_normalizzato": normalizer.titolo_normalizzato("Sagra del Tartufo"),
        "descrizione": "Degustazioni in piazza",
        "tipologia": "sagra",
        "data_inizio": "2026-09-12",
        "ora_inizio": "21:00",
        "data_fine": "2026-09-12",
        "ora_fine": None,
        "comune": "Calosso",
        "comune_normalizzato": "calosso",
        "luogo": "Piazza Roma",
        "km": 0.0,
        "minuti": 0,
        "prezzo": None,
        "organizzatore": None,
        "url": "https://fonte-a.it/evento",
        "url_immagine": None,
        "confidenza": 95,
    }
    eid = dedup.upsert_evento(conn, evento_base, source_id="fonte-a")
    conn.execute("UPDATE events SET bloccato = 'si', luogo = 'Corretto a mano' WHERE event_id = ?", (eid,))
    conn.commit()

    evento_base["luogo"] = "Piazza Diversa"
    dedup.upsert_evento(conn, evento_base, source_id="fonte-a")

    riga = conn.execute("SELECT luogo FROM events WHERE event_id = ?", (eid,)).fetchone()
    assert riga["luogo"] == "Corretto a mano"


def test_archivia_eventi_conclusi_sposta_solo_i_passati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, dedup_key, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('vecchio', 'x', 'Passato', '2020-01-01', '2020-01-01', 'Calosso', 'no')"
    )
    conn.execute(
        "INSERT INTO events (event_id, dedup_key, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('futuro', 'y', 'Futuro', '2030-01-01', '2030-01-01', 'Calosso', 'no')"
    )
    conn.commit()

    n = dedup.archivia_eventi_conclusi(conn, giorni_archiviazione=2)

    assert n == 1
    assert conn.execute("SELECT archiviato FROM events WHERE event_id='vecchio'").fetchone()[0] == "si"
    assert conn.execute("SELECT archiviato FROM events WHERE event_id='futuro'").fetchone()[0] == "no"
