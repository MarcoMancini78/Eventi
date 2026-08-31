"""M9: sincronizzazione lista 'seguiti' reale con coda_follow, senza browser (funzione pura)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import store, sync_seguiti


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def _inserisci(conn: sqlite3.Connection, source_id: str, handle: str, stato: str = "da_seguire") -> None:
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato) "
        "VALUES (?, 'instagram', ?, ?, ?, 'Calosso', 'A', 'proloco', ?)",
        (source_id, handle, f"https://instagram.com/{handle}", source_id, stato),
    )
    conn.commit()


def test_handle_esistente_viene_marcato_seguito():
    conn = _conn_di_prova()
    _inserisci(conn, "proloco-calosso-instagram", "prolococalosso")

    esito = sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["prolococalosso"])

    assert esito.aggiornati == 1
    assert esito.nuovi == 0
    riga = conn.execute("SELECT stato FROM coda_follow WHERE handle='prolococalosso'").fetchone()
    assert riga["stato"] == "seguito"


def test_handle_gia_seguito_non_viene_ricontato():
    conn = _conn_di_prova()
    _inserisci(conn, "proloco-calosso-instagram", "prolococalosso", stato="seguito")

    esito = sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["prolococalosso"])

    assert esito.aggiornati == 0  # già seguito, nessun cambio di stato da contare


def test_handle_sconosciuto_va_in_quarantena_non_scartato():
    conn = _conn_di_prova()

    esito = sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["profilo_mai_visto"])

    assert esito.nuovi == 1
    assert esito.aggiornati == 0
    riga = conn.execute("SELECT stato, comune, categoria FROM coda_follow WHERE handle='profilo_mai_visto'").fetchone()
    assert riga["stato"] == "quarantena"
    assert riga["comune"] == ""  # da verificare a mano, mai inventato


def test_normalizzazione_handle_case_e_chiocciola():
    conn = _conn_di_prova()
    _inserisci(conn, "proloco-calosso-instagram", "prolococalosso")

    esito = sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["@PROLOCOCALOSSO"])

    assert esito.aggiornati == 1


def test_lista_vuota_non_tocca_nulla():
    conn = _conn_di_prova()
    _inserisci(conn, "proloco-calosso-instagram", "prolococalosso")

    esito = sync_seguiti.confronta_e_aggiorna(conn, "instagram", [])

    assert esito.aggiornati == 0
    assert esito.nuovi == 0
    assert esito.handle_letti == 0
    riga = conn.execute("SELECT stato FROM coda_follow WHERE handle='prolococalosso'").fetchone()
    assert riga["stato"] == "da_seguire"  # non toccato


def test_rilancio_ripetuto_e_idempotente():
    """Lanciare due volte la stessa sincronizzazione non deve raddoppiare le righe nuove."""
    conn = _conn_di_prova()

    sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["profilo_nuovo"])
    esito2 = sync_seguiti.confronta_e_aggiorna(conn, "instagram", ["profilo_nuovo"])

    assert esito2.nuovi == 0  # la seconda volta esiste già, non viene ricreato
    totale = conn.execute("SELECT COUNT(*) FROM coda_follow WHERE handle='profilo_nuovo'").fetchone()[0]
    assert totale == 1


# --- URL corretti confermati dall'utente ispezionando l'interfaccia reale:
# Instagram: instagram.com/?variant=following
# Facebook: facebook.com/profile.php?id=...&sk=following
# (i due tentativi precedenti, /following e /pages_followed_by, erano ipotesi sbagliate) ---

def test_aggiungi_parametro_query_su_url_con_query_string_esistente():
    """Caso reale: facebook_page_url è già 'profile.php?id=...', il
    parametro sk=following va aggiunto con '&', non '?'."""
    url = sync_seguiti._aggiungi_parametro_query(
        "https://www.facebook.com/profile.php?id=61593736766094", "sk", "following"
    )
    assert url == "https://www.facebook.com/profile.php?id=61593736766094&sk=following"


def test_aggiungi_parametro_query_su_url_senza_query_string():
    url = sync_seguiti._aggiungi_parametro_query("https://www.facebook.com/nomepagina", "sk", "following")
    assert url == "https://www.facebook.com/nomepagina?sk=following"


def test_verifica_profilo_pertinente_passa_a_da_seguire():
    """Richiesto dall'utente (2026-08-29): un profilo con nome/comune
    riconoscibili come Pro Loco/Comune non deve più fermarsi in
    quarantena — la verifica automatica sostituisce l'apertura manuale
    del link."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Ponti', '', 'AL', 44.7, 8.5, 50.0, 60, 'B', 'si')"
    )
    conn.commit()

    def verifica_finta(url):
        return sync_seguiti.ProfiloVerificato(soggetto="Pro loco Ponti", comune="Ponti")

    esito = sync_seguiti.confronta_e_aggiorna(
        conn, "facebook", ["sconosciuto123"], verifica_profilo=verifica_finta
    )

    assert esito.nuovi == 1
    riga = conn.execute("SELECT stato, comune, soggetto FROM coda_follow WHERE handle='sconosciuto123'").fetchone()
    assert riga["stato"] == "da_seguire"
    assert riga["comune"] == "Ponti"
    assert riga["soggetto"] == "Pro loco Ponti"


def test_verifica_profilo_non_pertinente_resta_in_quarantena():
    """Caso reale trovato nel collaudo: 'La Nuova Drogheria' a Cassinasco
    e' un bar, non una Pro Loco — il comune si risolve ma il nome non
    contiene una parola chiave pertinente, quindi resta da rivedere a
    mano invece di passare automaticamente a da_seguire."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, alias, provincia, lat, lon, km, minuti, fascia, attivo) "
        "VALUES ('1', 'Cassinasco', '', 'AT', 44.7, 8.3, 20.0, 30, 'A', 'si')"
    )
    conn.commit()

    def verifica_finta(url):
        return sync_seguiti.ProfiloVerificato(soggetto="La Nuova Drogheria", comune="Cassinasco")

    esito = sync_seguiti.confronta_e_aggiorna(
        conn, "facebook", ["lanuovadrogheria"], verifica_profilo=verifica_finta
    )

    riga = conn.execute("SELECT stato, comune, soggetto FROM coda_follow WHERE handle='lanuovadrogheria'").fetchone()
    assert riga["stato"] == "quarantena"
    assert riga["comune"] == "Cassinasco"  # popolato comunque: chi rivede non deve piu' cercarlo
    assert riga["soggetto"] == "La Nuova Drogheria"


def test_verifica_profilo_comune_non_risolvibile_resta_in_quarantena():
    conn = _conn_di_prova()

    def verifica_finta(url):
        return sync_seguiti.ProfiloVerificato(soggetto="Pro loco Qualcosa", comune="Comune Inesistente Xyz")

    esito = sync_seguiti.confronta_e_aggiorna(
        conn, "facebook", ["handle_test"], verifica_profilo=verifica_finta
    )

    riga = conn.execute("SELECT stato, comune FROM coda_follow WHERE handle='handle_test'").fetchone()
    assert riga["stato"] == "quarantena"
    assert riga["comune"] == ""  # mai inventato: il comune letto non e' nel perimetro


def test_verifica_profilo_fallita_ricade_su_comportamento_esistente():
    """verifica_profilo che ritorna None (pagina non aperta/nessun dato
    letto) non deve rompere nulla: stesso comportamento di prima."""
    conn = _conn_di_prova()

    esito = sync_seguiti.confronta_e_aggiorna(
        conn, "facebook", ["handle_irraggiungibile"], verifica_profilo=lambda url: None
    )

    riga = conn.execute("SELECT stato, comune FROM coda_follow WHERE handle='handle_irraggiungibile'").fetchone()
    assert riga["stato"] == "quarantena"
    assert riga["comune"] == ""
