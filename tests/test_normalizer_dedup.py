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


def test_titoli_simili_titolo_frammento_contenuto_nell_altro():
    """Caso reale (2026-08-28): 'Fiorinchiostro' vs 'Fiorinchiostro -
    Mostra Mercato Florovivaismo di qualità' — dedup_key esatta li manca
    (slug troncato a 20 char cambia con la parola in più), il fuzzy deve
    riconoscerli come lo stesso evento."""
    a = normalizer.titolo_normalizzato("Fiorinchiostro")
    b = normalizer.titolo_normalizzato("Fiorinchiostro - Mostra Mercato Florovivaismo di qualità")
    assert normalizer.titoli_simili(a, b) is True


def test_titoli_simili_falso_su_parola_generica_isolata():
    """Bug trovato nel collaudo (2026-08-30): 'Evento culturale' è un
    placeholder frequente dell'LLM per estrazioni a bassa confidenza. Il
    titolo normalizzato di 'Evento' da solo (una sola parola dopo la
    normalizzazione) non deve matchare qualunque altro titolo che
    contenga quella parola generica — a differenza di un titolo-frammento
    distintivo come 'Fiorinchiostro'."""
    a = normalizer.titolo_normalizzato("Evento")
    b = normalizer.titolo_normalizzato("Grande evento in piazza con musica e stand gastronomici")
    assert normalizer.titoli_simili(a, b) is False


def test_titoli_simili_riformulazione_con_parole_aggiunte():
    """Caso reale: 'Capodanno Alessandrino...' vs 'Il 31 agosto torna il
    Capodanno Alessandrino...' — stesso evento, titolo riformulato dal
    sito tra un giro e l'altro."""
    a = normalizer.titolo_normalizzato("Capodanno Alessandrino: è l'Anno dell'amore")
    b = normalizer.titolo_normalizzato("Il 31 agosto torna il Capodanno Alessandrino: è l'Anno dell'amore")
    assert normalizer.titoli_simili(a, b) is True


def test_titoli_simili_falso_su_eventi_diversi_con_parola_comune():
    a = normalizer.titolo_normalizzato("Sagra del Tartufo")
    b = normalizer.titolo_normalizzato("Sagra della Nocciola")
    assert normalizer.titoli_simili(a, b) is False


def test_titoli_simili_falso_su_titoli_brevi_con_specificita_diversa():
    """'Concerto in piazza' e 'Concerto rock in piazza del comune'
    condividono overlap 1.0 ma sono probabilmente due eventi diversi (uno
    generico, uno specifico) — la soglia minima di 3 token condivisi
    evita il falso positivo su titoli di sole 2 parole generiche."""
    a = normalizer.titolo_normalizzato("Concerto in piazza")
    b = normalizer.titolo_normalizzato("Concerto rock in piazza del comune")
    assert normalizer.titoli_simili(a, b) is False


def test_upsert_evento_livello_fuzzy_unisce_titoli_riformulati():
    """Stesso scenario del bug reale trovato dall'utente: due estrazioni
    con titolo leggermente diverso, stesso comune e stessa data, devono
    finire sullo stesso event_id anche se dedup_key esatta li manca."""
    conn = _conn_di_prova()
    base = {
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
    evento1 = {**base, "titolo": "Fiorinchiostro", "titolo_normalizzato": normalizer.titolo_normalizzato("Fiorinchiostro")}
    evento2 = {
        **base,
        "titolo": "Fiorinchiostro - Mostra Mercato Florovivaismo di qualità",
        "titolo_normalizzato": normalizer.titolo_normalizzato("Fiorinchiostro - Mostra Mercato Florovivaismo di qualità"),
        "url": "https://fonte-b.it/evento",
    }

    id1 = dedup.upsert_evento(conn, evento1, source_id="fonte-a")
    id2 = dedup.upsert_evento(conn, evento2, source_id="fonte-b")

    assert id1 == id2
    totale = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert totale == 1


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


def test_eventi_duplicati_stessa_fonte_e_overlap_titolo_perfetto():
    """Caso reale più frequente trovato nell'analisi (2026-08-30, Envie,
    17 coppie): il titolo aggiunge solo un dettaglio organizzativo breve,
    troppo poco per titoli_simili da solo (2 token nel titolo corto,
    sotto la soglia di 3) — ma la stessa fonte conferma che è lo stesso
    evento."""
    a = normalizer.titolo_normalizzato("Gruppi di Cammino")
    b = normalizer.titolo_normalizzato("Gruppi di Cammino promossi dall'A.S.L. CN1")
    assert normalizer.eventi_duplicati(a, b, "", "", {"comune-envie"}, {"comune-envie"}) is True


def test_eventi_duplicati_falso_su_titoli_brevi_fonti_diverse():
    a = normalizer.titolo_normalizzato("Concerto in piazza")
    b = normalizer.titolo_normalizzato("Concerto rock in piazza del comune")
    assert normalizer.eventi_duplicati(a, b, "", "", {"fonte-x"}, {"fonte-y"}) is False


def test_eventi_duplicati_descrizione_simile_conferma_overlap_titolo():
    a = normalizer.titolo_normalizzato("Serata alla Vineria")
    b = normalizer.titolo_normalizzato("Domani sera alla Vineria")
    descr = "CON GRANDE ONORE, DOMANI SERA ALLA VINERIA!"
    assert normalizer.eventi_duplicati(a, b, descr, descr, {"fonte-x"}, {"fonte-y"}) is True


def test_eventi_duplicati_falso_senza_overlap_titolo_perfetto():
    """Fonte comune da sola non basta se il titolo non è nemmeno
    contenuto interamente — evita falsi positivi su eventi diversi
    della stessa fonte generica (es. due post diversi dello stesso feed)."""
    a = normalizer.titolo_normalizzato("Presentazione libro Pia Pera")
    b = normalizer.titolo_normalizzato("Concerto Big Band Jazz Cuneo")
    assert normalizer.eventi_duplicati(a, b, "x", "y", {"comune-garessio"}, {"comune-garessio"}) is False


def test_eventi_duplicati_falso_stessa_fonte_titolo_ok_ma_descrizioni_diverse():
    """Falso positivo reale trovato nel collaudo (2026-08-30, Fubine
    Monferrato): 'Evento culturale' (un pranzo) vs 'Evento culturale al
    Parco Storico Bricherasio' (un evento serale), stessa fonte comunale,
    overlap titolo perfetto — ma sono due eventi diversi, e le
    descrizioni lo dimostrano. Deciso dall'utente: stessa fonte non basta
    più da sola, serve anche titolo E descrizione simili insieme."""
    a = normalizer.titolo_normalizzato("Evento culturale")
    b = normalizer.titolo_normalizzato("Evento culturale al Parco Storico Bricherasio")
    descr_a = "Programma da volantino. Domenica 30 Pranzo i Campi Cerrina ore 13:00"
    descr_b = "Sabato 29 agosto 2026 - ore 18:00 presso Parco Storico Bricherasio"
    assert normalizer.eventi_duplicati(a, b, descr_a, descr_b, {"comune-fubine"}, {"comune-fubine"}) is False


def test_upsert_evento_fuzzy_unisce_con_stessa_fonte_titolo_breve():
    """Stesso scenario end-to-end del bug reale trovato dall'utente
    (2026-08-30): due estrazioni dalla stessa fonte con titolo breve
    che aggiunge solo un dettaglio organizzativo devono finire sullo
    stesso event_id."""
    conn = _conn_di_prova()
    base = {
        "descrizione": "",
        "tipologia": "altro",
        "data_inizio": "2026-09-03",
        "ora_inizio": None,
        "data_fine": "2026-09-03",
        "ora_fine": None,
        "comune": "Calosso",
        "comune_normalizzato": "calosso",
        "luogo": None,
        "km": 0.0,
        "minuti": 0,
        "prezzo": None,
        "organizzatore": None,
        "url": "https://comune-calosso.it/evento",
        "url_immagine": None,
        "confidenza": 90,
    }
    evento1 = {**base, "titolo": "Gruppi di Cammino", "titolo_normalizzato": normalizer.titolo_normalizzato("Gruppi di Cammino")}
    evento2 = {
        **base,
        "titolo": "Gruppi di Cammino promossi dall'A.S.L. CN1",
        "titolo_normalizzato": normalizer.titolo_normalizzato("Gruppi di Cammino promossi dall'A.S.L. CN1"),
    }

    id1 = dedup.upsert_evento(conn, evento1, source_id="comune-calosso")
    id2 = dedup.upsert_evento(conn, evento2, source_id="comune-calosso")

    assert id1 == id2
    totale = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert totale == 1
