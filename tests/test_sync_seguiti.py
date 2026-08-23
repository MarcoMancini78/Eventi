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
