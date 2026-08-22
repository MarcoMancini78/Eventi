"""M9: logica di stato/circuito del follow (14.4, 14.5), nessun browser reale nei test."""
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import follow, store
from src.config import Config


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def _inserisci_candidato(conn: sqlite3.Connection, source_id: str, piattaforma: str = "facebook") -> None:
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato) "
        "VALUES (?, ?, ?, ?, ?, 'Calosso', 'A', 'proloco', 'da_seguire')",
        (source_id, piattaforma, source_id, f"https://facebook.com/{source_id}", source_id),
    )
    conn.commit()


def test_verifica_precondizioni_passa_su_coda_pulita():
    conn = _conn_di_prova()
    follow.verifica_precondizioni(conn, "facebook", Config())  # non deve sollevare


def test_verifica_precondizioni_fallisce_se_circuito_aperto():
    conn = _conn_di_prova()
    follow.apri_circuito(conn, "facebook", ore=72)

    try:
        follow.verifica_precondizioni(conn, "facebook", Config())
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_fallisce_se_intervallo_lotti_troppo_corto():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO app_state (chiave, valore) VALUES ('ultimo_lotto_follow_facebook', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()

    try:
        follow.verifica_precondizioni(conn, "facebook", Config(follow_intervallo_lotti_min=45))
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_fallisce_se_limite_giornaliero_raggiunto():
    conn = _conn_di_prova()
    oggi = datetime.now().isoformat()
    for i in range(5):
        conn.execute(
            "INSERT INTO coda_follow_log (source_id, piattaforma, esito, data_follow) VALUES (?, 'facebook', 'seguito', ?)",
            (f"fonte-{i}", oggi),
        )
    conn.commit()

    try:
        follow.verifica_precondizioni(conn, "facebook", Config(follow_max_giornalieri=5))
        assert False, "doveva sollevare CircuitoApertoError"
    except follow.CircuitoApertoError:
        pass


def test_verifica_precondizioni_conta_solo_oggi_non_ieri():
    conn = _conn_di_prova()
    ieri = (datetime.now() - timedelta(days=1)).isoformat()
    for i in range(10):
        conn.execute(
            "INSERT INTO coda_follow_log (source_id, piattaforma, esito, data_follow) VALUES (?, 'facebook', 'seguito', ?)",
            (f"fonte-{i}", ieri),
        )
    conn.commit()

    follow.verifica_precondizioni(conn, "facebook", Config(follow_max_giornalieri=5))  # non deve sollevare


def test_prossimi_n_da_seguire_rispetta_lo_stato_e_i_tentativi():
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1")
    _inserisci_candidato(conn, "fonte-2")
    conn.execute("UPDATE coda_follow SET stato='seguito' WHERE source_id='fonte-2'")
    conn.execute("UPDATE coda_follow SET tentativi=3 WHERE source_id='fonte-1'")
    _inserisci_candidato(conn, "fonte-3")
    conn.commit()

    candidati = follow.prossimi_n_da_seguire(conn, "facebook", 10)
    source_ids = [c["source_id"] for c in candidati]

    assert source_ids == ["fonte-3"]  # fonte-1 ha troppi tentativi, fonte-2 è già seguita


def test_pausa_casuale_nel_range_atteso():
    config = Config(follow_pausa_min_sec=25, follow_pausa_max_sec=70, follow_pausa_lunga_ogni=4)
    for _ in range(50):
        p = follow.pausa_casuale(config, indice_nel_lotto=1)
        assert 25 <= p <= 70


def test_pausa_lunga_ogni_n_follow():
    config = Config(follow_pausa_lunga_ogni=4, follow_pausa_lunga_min_sec=120, follow_pausa_lunga_max_sec=240)
    for _ in range(50):
        p = follow.pausa_casuale(config, indice_nel_lotto=4)
        assert 120 <= p <= 240


def test_dry_run_non_modifica_lo_stato_della_coda():
    conn = _conn_di_prova()
    _inserisci_candidato(conn, "fonte-1")

    esiti = follow.follow_batch(conn, Config(), "facebook", n=5, dry_run=True)

    assert len(esiti) == 1
    assert esiti[0].esito == "dry_run"
    riga = conn.execute("SELECT stato FROM coda_follow WHERE source_id='fonte-1'").fetchone()
    assert riga["stato"] == "da_seguire"  # nessuna modifica


def test_follow_batch_con_coda_vuota_ritorna_lista_vuota():
    conn = _conn_di_prova()
    esiti = follow.follow_batch(conn, Config(), "facebook", n=5, dry_run=True)
    assert esiti == []


def test_follow_batch_rispetta_precondizioni_anche_in_dry_run():
    conn = _conn_di_prova()
    follow.apri_circuito(conn, "facebook", ore=72)
    _inserisci_candidato(conn, "fonte-1")

    try:
        follow.follow_batch(conn, Config(), "facebook", dry_run=True)
        assert False, "doveva sollevare CircuitoApertoError anche in dry-run"
    except follow.CircuitoApertoError:
        pass
