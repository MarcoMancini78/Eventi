"""16.9 (webapp Fonti): righe_fonti_complete / scrivi_fonti_json."""
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


def test_righe_fonti_include_sito_comune_con_comune_risolto():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, provincia, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'AT', 0.0, 0, 'A', 'si')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('comune-calosso', 'comune', 'T0_pa_design_system', 'https://comune.calosso.at.it/Eventi')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert len(righe) == 1
    assert righe[0]["fonte"] == "web"
    assert righe[0]["tipo"] == "Comune"
    assert righe[0]["comune"] == "Calosso"
    assert righe[0]["url"] == "https://comune.calosso.at.it/Eventi"
    assert righe[0]["numero"] == 1


def test_righe_fonti_esclude_source_id_feed_sintetici():
    """I source_id 'feed-{piattaforma}-{handle}' in sources sono solo il
    contatore sintetico dei social (feed_social.py): non fonti a sé, non
    devono comparire come righe indipendenti."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, endpoint) VALUES ('feed-facebook-paginax', NULL, NULL)"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe == []


def test_righe_fonti_include_social_da_coda_follow():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('proloco-calosso-instagram', 'instagram', 'prolococalosso', 'Calosso', 'proloco', "
        "'https://instagram.com/prolococalosso', 'seguito')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert len(righe) == 1
    assert righe[0]["fonte"] == "instagram"
    assert righe[0]["tipo"] == "Pro Loco"
    assert righe[0]["comune"] == "Calosso"
    assert righe[0]["url"] == "https://instagram.com/prolococalosso"


def test_righe_fonti_esclude_coda_follow_non_seguita():
    """16.10, caso Canelli: una fonte scartata (non_valido, fallito,
    quarantena, da_seguire...) non è più una sorgente su cui il sistema
    cerca eventi, non deve comparire nella pagina Fonti."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('teatro-canelli-teatro-balbi-facebook', 'facebook', 'teatrobalbocanelli', 'Canelli', "
        "'teatro', 'https://www.facebook.com/teatrobalbocanelli/', 'non_valido')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe == []


def test_righe_fonti_esclude_coda_follow_senza_url():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('proloco-x-instagram', 'instagram', NULL, 'X', 'proloco', '', 'nessuna_fonte_trovata')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe == []


def test_righe_fonti_teatro_deduce_comune_da_coda_follow_gemella():
    """Un teatro non ha uno slug comune deterministico come comune/proloco:
    il comune si ricava dalla riga social gemella in coda_follow (stesso
    source_id di base, senza suffisso piattaforma)."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('teatro-cambiano-teatro-comunale', 'teatro', 'T1_html', 'https://teatrocambiano.it')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, soggetto, url, stato) "
        "VALUES ('teatro-cambiano-teatro-comunale-facebook', 'facebook', 'teatrocambiano', 'Cambiano', "
        "'teatro', 'Cambiano - Teatro Comunale', 'https://facebook.com/teatrocambiano', 'seguito')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    sito = next(r for r in righe if r["url"] == "https://teatrocambiano.it")
    assert sito["comune"] == "Cambiano"


def test_righe_fonti_conteggio_attivi_e_totale_sito():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('comune-calosso', 'comune', 'T0_pa_design_system', 'https://comune.calosso.at.it/Eventi')"
    )
    oggi = date.today()
    futuro = (oggi + timedelta(days=10)).isoformat()
    passato_archiviato = (oggi - timedelta(days=30)).isoformat()
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
    for eid in ("ev1", "ev2"):
        conn.execute(
            "INSERT INTO event_sources (event_id, source_id, url, seen_at) VALUES (?, 'comune-calosso', 'https://x', '2026-01-01')",
            (eid,),
        )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe[0]["attivi"] == 1
    assert righe[0]["totale"] == 2


def test_righe_fonti_conteggio_social_via_handle_sintetico():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('proloco-calosso-instagram', 'instagram', 'prolococalosso', 'Calosso', 'proloco', "
        "'https://instagram.com/prolococalosso', 'seguito')"
    )
    futuro = (date.today() + timedelta(days=5)).isoformat()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento social', ?, ?, 'Calosso', 'no')",
        (futuro, futuro),
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'feed-instagram-prolococalosso', 'https://x', '2026-01-01')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe[0]["attivi"] == 1
    assert righe[0]["totale"] == 1


def test_righe_fonti_numerate_progressivamente_dopo_ordinamento():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('comune-zeta', 'comune', 'T1_html', 'https://zeta.it')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('comune-alfa', 'comune', 'T1_html', 'https://alfa.it')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    numeri = [r["numero"] for r in righe]
    assert numeri == list(range(1, len(righe) + 1))


def test_righe_fonti_fonte_e_tipo_sono_colonne_separate():
    """16.9, richiesto 2026-09-16: 'fonte' è il canale (web/facebook/
    instagram), 'tipo' è la categoria del soggetto (Comune, Pro Loco,
    Teatro, ecc.) — prima un unico campo 'tipo' mischiava tier tecnico e
    piattaforma social, rendendo la colonna illeggibile per l'utente."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, tier, endpoint) "
        "VALUES ('teatro-cambiano-teatro-comunale', 'teatro', 'T1_html', 'https://teatrocambiano.it')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('aggregatore-sagre-piemonte-facebook', 'facebook', 'sagrepiemonte', '', 'aggregatore', "
        "'https://facebook.com/sagrepiemonte', 'seguito')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    sito = next(r for r in righe if r["url"] == "https://teatrocambiano.it")
    social = next(r for r in righe if r["url"] == "https://facebook.com/sagrepiemonte")

    assert sito["fonte"] == "web"
    assert sito["tipo"] == "Teatro"
    assert social["fonte"] == "facebook"
    assert social["tipo"] == "Aggregatore"


def test_righe_fonti_categoria_assente_diventa_da_classificare():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, categoria, url, stato) "
        "VALUES ('sconosciuto-instagram-x', 'instagram', 'x', '', 'sconosciuto', "
        "'https://instagram.com/x', 'seguito')"
    )
    conn.commit()

    righe = publisher.righe_fonti_complete(conn)
    assert righe[0]["tipo"] == "Da classificare"


def test_scrivi_fonti_json_scrive_file_valido(tmp_path):
    righe = [{"numero": 1, "tipo": "comune", "comune": "Calosso", "attivi": 0, "totale": 0, "url": "https://x"}]
    percorso = tmp_path / "fonti.json"

    n = publisher.scrivi_fonti_json(righe, percorso)

    assert n == 1
    corpo = json.loads(percorso.read_text(encoding="utf-8"))
    assert corpo["fonti"] == righe
    assert "generato_il" in corpo
