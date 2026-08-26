"""M10: logica pura del feed social (attribuzione, separazione follow/lettura,
parsing selettori) — nessun browser reale, 15.1 regola 8."""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import feed_social, store
from src.config import Config
from src.extractor.client import ExtractorClient
from src.extractor.providers import ProviderLLM


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_verifica_separazione_passa_senza_follow_precedente():
    conn = _conn_di_prova()
    feed_social.verifica_separazione_da_follow(conn, "facebook")  # non deve sollevare


def test_verifica_separazione_fallisce_se_follow_recente():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()

    try:
        feed_social.verifica_separazione_da_follow(conn, "facebook", minuti_minimi=60)
        assert False, "doveva sollevare SessioneTroppoVicinaAlFollowError"
    except feed_social.SessioneTroppoVicinaAlFollowError:
        pass


def test_verifica_separazione_passa_se_follow_abbastanza_vecchio():
    conn = _conn_di_prova()
    vecchio = (datetime.now() - timedelta(hours=2)).isoformat()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)", (vecchio,)
    )
    conn.commit()
    feed_social.verifica_separazione_da_follow(conn, "facebook", minuti_minimi=60)  # non deve sollevare


def test_attribuisci_post_handle_noto_ritorna_riga():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('proloco-calosso-facebook', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()

    riga = feed_social.attribuisci_post(conn, "facebook", "ProLocoCalosso")
    assert riga is not None
    assert riga["comune"] == "Calosso"


def test_attribuisci_post_handle_sconosciuto_crea_candidato_e_ritorna_none():
    conn = _conn_di_prova()
    riga = feed_social.attribuisci_post(conn, "instagram", "prolocosconosciuta")
    assert riga is None

    candidato = conn.execute(
        "SELECT * FROM coda_follow WHERE piattaforma='instagram' AND handle='prolocosconosciuta'"
    ).fetchone()
    assert candidato is not None
    assert candidato["stato"] == "candidato_da_feed"
    assert candidato["comune"] == ""  # mai scartato, ma mai un comune inventato


def test_attribuisci_post_handle_noto_ma_senza_comune_non_pubblica():
    """Un handle già in coda_follow ma senza comune assegnato (es. in
    quarantena) non deve produrre un'attribuzione valida — nessun evento
    va pubblicato senza un comune attendibile."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'handlesenzacomune', '', 'quarantena')"
    )
    conn.commit()

    riga = feed_social.attribuisci_post(conn, "facebook", "handlesenzacomune")
    assert riga is None


def test_handle_da_href_profilo_facebook():
    assert feed_social._handle_da_href_profilo("/prolococalosso/", "facebook") == "prolococalosso"
    assert feed_social._handle_da_href_profilo("/prolococalosso?ref=x", "facebook") == "prolococalosso"


def test_handle_da_href_profilo_instagram():
    assert feed_social._handle_da_href_profilo("/eventi.langa/", "instagram") == "eventi.langa"


def test_post_id_da_permalink_facebook():
    assert feed_social._post_id_da_permalink("/prolococalosso/posts/1234567890") == "1234567890"
    assert feed_social._post_id_da_permalink("/watch/videos/999888777") == "999888777"


def test_post_id_da_permalink_instagram():
    assert feed_social._post_id_da_permalink("/p/ABC123xyz/") == "ABC123xyz"
    assert feed_social._post_id_da_permalink("/reel/XYZ987/") == "XYZ987"


class _ProviderFinto(ProviderLLM):
    def __init__(self, risposte):
        self._risposte = list(risposte)

    def estrai(self, prompt_sistema, prompt_utente, immagini=None):
        return self._risposte.pop(0)


def _risposta_json(comune="Calosso", confidenza=92):
    return (
        '{"eventi": [{"titolo": "Sagra del Tartufo", "descrizione": "Degustazioni", "tipologia": "sagra", '
        '"data_inizio": "2026-09-12", "data_fine": "2026-09-12", "ora_inizio": "21:00", "ora_fine": null, '
        '"ricorrenza": {"e_ricorrente": false}, "luogo_testuale": "Piazza Roma", "comune_testuale": "%s", '
        '"indirizzo": null, "prezzo": null, "organizzatore": null, "anno_esplicito": true, '
        '"confidenza": %d, "campi_incerti": [], "note_estrazione": null}], '
        '"non_e_un_evento": false, "motivo": null}'
    ) % (comune, confidenza)


def _risposta_non_evento():
    return '{"eventi": [], "non_e_un_evento": true, "motivo": "nessun evento nel testo"}'


def _conn_con_comune() -> sqlite3.Connection:
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Calosso', 'Calosso', 'AT', 44.74, 8.23, 0.0, 0, 'A', 'si')"
    )
    return conn


def test_elabora_post_handle_sconosciuto_ritorna_candidato():
    conn = _conn_con_comune()
    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolocosconosciuta", post_id="1",
        url="https://www.facebook.com/prolocosconosciuta/posts/1", testo="Sagra del tartufo sabato 12 settembre",
    )
    esito = feed_social.elabora_post(post, conn, Config())
    assert esito == "candidato"


def test_elabora_post_senza_testo_ritorna_senza_testo():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1", testo=None,
    )
    assert feed_social.elabora_post(post, conn, Config()) == "senza_testo"


def test_elabora_post_pubblica_evento_con_estrattore():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_json(confidenza=92)])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Sagra del Tartufo sabato 12 settembre in Piazza Roma a Calosso, degustazioni e musica.",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "pubblicato"

    riga = conn.execute("SELECT titolo, comune FROM events").fetchone()
    assert riga["titolo"] == "Sagra del Tartufo"
    assert riga["comune"] == "Calosso"


def test_elabora_post_gruppo_senza_comune_esplicito_non_pubblica():
    """14.6: per i gruppi il comune non va mai inferito dall'autore del
    post — un evento senza comune_testuale esplicito non deve pubblicare."""
    conn = _conn_con_comune()
    provider = _ProviderFinto([_risposta_json(comune="")])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="sagrepiemonte", post_id="1",
        url="https://www.facebook.com/groups/12345/posts/1",
        testo="Sagra del Tartufo sabato 12 settembre, degustazioni e musica.",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "gruppo_comune_non_inferito"

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_elabora_post_non_evento_scartato():
    conn = _conn_con_comune()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, comune, stato) "
        "VALUES ('x', 'facebook', 'prolococalosso', 'Calosso', 'seguito')"
    )
    conn.commit()
    provider = _ProviderFinto([_risposta_non_evento()])
    extractor = ExtractorClient(Config(), conn, provider=provider)

    post = feed_social.PostFeed(
        piattaforma="facebook", handle_autore="prolococalosso", post_id="1",
        url="https://www.facebook.com/prolococalosso/posts/1",
        testo="Buongiorno a tutti, oggi splende il sole su Calosso!",
    )
    esito = feed_social.elabora_post(post, conn, Config(), extractor)
    assert esito == "scartato"
