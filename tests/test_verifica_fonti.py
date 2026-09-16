"""16.10 — Verifica di disponibilità delle fonti social (caso Canelli, 2026-09-17)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import follow, store, verifica_fonti


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_classifica_testo_pagina_contenuto_disponibile():
    disponibile, dettaglio = verifica_fonti.classifica_testo_pagina(
        "Teatro Balbi Canelli\n1234 mi piace\nInformazioni\nEventi"
    )
    assert disponibile is True
    assert dettaglio == ""


def test_classifica_testo_pagina_rileva_contenuto_non_disponibile_italiano():
    disponibile, dettaglio = verifica_fonti.classifica_testo_pagina(
        "Questo contenuto non è al momento disponibile\nMotivo: violazione degli standard"
    )
    assert disponibile is False
    assert "non disponibile" in dettaglio


def test_classifica_testo_pagina_rileva_contenuto_non_disponibile_inglese():
    disponibile, dettaglio = verifica_fonti.classifica_testo_pagina(
        "Sorry, this content isn't available right now"
    )
    assert disponibile is False


def test_classifica_testo_pagina_case_insensitive():
    disponibile, _ = verifica_fonti.classifica_testo_pagina(
        "QUESTO CONTENUTO NON È DISPONIBILE"
    )
    assert disponibile is False


def test_fonti_social_da_verificare_esclude_non_seguite():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('x-facebook', 'facebook', 'x', 'https://facebook.com/x', 'teatro', 'da_seguire')"
    )
    conn.commit()

    candidati = verifica_fonti.fonti_social_da_verificare(conn)
    assert candidati == []


def test_fonti_social_da_verificare_esclude_instagram():
    """Il caso segnalato è Facebook; il campo di analisi di questo giro
    resta limitato lì (richiesto esplicitamente dall'utente)."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('x-instagram', 'instagram', 'x', 'https://instagram.com/x', 'teatro', 'seguito')"
    )
    conn.commit()

    candidati = verifica_fonti.fonti_social_da_verificare(conn)
    assert candidati == []


def test_fonti_social_da_verificare_esclude_fonti_con_eventi():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('x-facebook', 'facebook', 'paginaattiva', 'https://facebook.com/paginaattiva', 'teatro', 'seguito')"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento', '2026-01-01', '2026-01-01', 'X', 'si')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'feed-facebook-paginaattiva', 'https://x', '2026-01-01')"
    )
    conn.commit()

    candidati = verifica_fonti.fonti_social_da_verificare(conn)
    assert candidati == []


def test_fonti_social_da_verificare_include_fonte_seguita_senza_eventi():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('teatro-canelli-teatro-balbi-facebook', 'facebook', 'teatrobalbocanelli', "
        "'https://www.facebook.com/teatrobalbocanelli/', 'teatro', 'seguito')"
    )
    conn.commit()

    candidati = verifica_fonti.fonti_social_da_verificare(conn)
    assert len(candidati) == 1
    assert candidati[0]["handle"] == "teatrobalbocanelli"


def test_registra_esito_verifica_marca_non_valido_se_indisponibile():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('x-facebook', 'facebook', 'x', 'https://facebook.com/x', 'teatro', 'seguito')"
    )
    conn.commit()
    candidato = conn.execute("SELECT rowid, * FROM coda_follow").fetchone()

    esito = verifica_fonti.EsitoVerifica("x-facebook", "https://facebook.com/x", disponibile=False, dettaglio="contenuto non disponibile: 'x'")
    verifica_fonti.registra_esito_verifica(conn, candidato, esito)

    riga = conn.execute("SELECT stato, note FROM coda_follow WHERE source_id='x-facebook'").fetchone()
    assert riga["stato"] == "non_valido"
    assert "non disponibile" in riga["note"]


def test_registra_esito_verifica_non_tocca_stato_se_disponibile():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, categoria, stato) "
        "VALUES ('x-facebook', 'facebook', 'x', 'https://facebook.com/x', 'teatro', 'seguito')"
    )
    conn.commit()
    candidato = conn.execute("SELECT rowid, * FROM coda_follow").fetchone()

    esito = verifica_fonti.EsitoVerifica("x-facebook", "https://facebook.com/x", disponibile=True)
    verifica_fonti.registra_esito_verifica(conn, candidato, esito)

    riga = conn.execute("SELECT stato FROM coda_follow WHERE source_id='x-facebook'").fetchone()
    assert riga["stato"] == "seguito"


# --- Controllo all'ingresso: follow._apri_e_segui deve rifiutare una fonte
# il cui contenuto risulta già indisponibile, invece di seguirla a vuoto
# (caso Canelli, teatrobalbocanelli). ---

class _LocatorVuoto:
    def count(self):
        return 0


class _PaginaContenutoIndisponibileFinta:
    def __init__(self, testo_visibile: str):
        self._testo_visibile = testo_visibile
        self.url = "https://www.facebook.com/teatrobalbocanelli/"

    def goto(self, url, timeout=None):
        pass

    def content(self):
        return "<html></html>"

    def inner_text(self, selettore):
        return self._testo_visibile

    def get_by_role(self, ruolo, name=None):
        return _LocatorVuoto()

    def close(self):
        pass


class _ContestoPaginaIndisponibileFinto:
    def __init__(self, testo_visibile: str):
        self._testo_visibile = testo_visibile

    class _Browser:
        def __init__(self, outer):
            self._outer = outer

        def new_page(self):
            return _PaginaContenutoIndisponibileFinta(self._outer._testo_visibile)

    def __getitem__(self, chiave):
        if chiave == "browser":
            return self._Browser(self)
        raise KeyError(chiave)


def test_apri_e_segui_rifiuta_fonte_con_contenuto_non_disponibile():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato) "
        "VALUES ('teatro-canelli-teatro-balbi-facebook', 'facebook', 'teatrobalbocanelli', "
        "'https://www.facebook.com/teatrobalbocanelli/', 'Canelli - Teatro Balbi', 'Canelli', 'A', 'teatro', 'da_seguire')"
    )
    conn.commit()
    candidato = conn.execute("SELECT rowid, * FROM coda_follow").fetchone()

    contesto = _ContestoPaginaIndisponibileFinto("Questo contenuto non è al momento disponibile")
    esito = follow._apri_e_segui(contesto, candidato)

    assert esito.esito == "non_valido"
    assert "non disponibile" in esito.dettaglio
