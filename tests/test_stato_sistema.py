"""Foglio Stato (M11): 5 indicatori (4 scelti dall'utente il 2026-08-27, +1
coda follow richiesto il 2026-08-28), ciascuno con semaforo
verde/giallo/rosso calcolato da soglie esplicite, non a caso."""
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import stato_sistema, store


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_fonti_in_errore_verde_quando_nessun_errore():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier, consecutive_errors) VALUES ('x', 'T1_html', 0)")
    conn.commit()

    ind = stato_sistema._indicatore_fonti_in_errore(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_VERDE


def test_fonti_in_errore_giallo_con_qualche_errore_isolato():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier, consecutive_errors) VALUES ('a', 'T1_html', 1)")
    for i in range(9):
        conn.execute(f"INSERT INTO sources (source_id, tier, consecutive_errors) VALUES ('b{i}', 'T1_html', 0)")
    conn.commit()

    ind = stato_sistema._indicatore_fonti_in_errore(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_GIALLO


def test_fonti_in_errore_rosso_se_una_fonte_e_rotta():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier, stato) VALUES ('x', 'T1_html', 'rotta')")
    conn.commit()

    ind = stato_sistema._indicatore_fonti_in_errore(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_ROSSO


def test_fonti_in_errore_rosso_se_quota_alta():
    conn = _conn_di_prova()
    for i in range(3):
        conn.execute(f"INSERT INTO sources (source_id, tier, consecutive_errors) VALUES ('e{i}', 'T1_html', 1)")
    conn.execute("INSERT INTO sources (source_id, tier, consecutive_errors) VALUES ('ok', 'T1_html', 0)")
    conn.commit()

    ind = stato_sistema._indicatore_fonti_in_errore(conn)  # 3/4 = 75% > 20%
    assert ind.semaforo == stato_sistema.SEMAFORO_ROSSO


def test_quota_llm_verde_sotto_soglia():
    conn = _conn_di_prova()
    ind = stato_sistema._indicatore_quota_llm(conn, budget_giornaliero=1200)
    assert ind.semaforo == stato_sistema.SEMAFORO_VERDE
    assert "0/1200" in ind.valore


def test_quota_llm_giallo_a_70_percento():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('src1', 'T1_html')")
    conn.execute("INSERT INTO artifacts (artifact_id, source_id) VALUES ('a1', 'src1')")
    for i in range(7):
        conn.execute(
            "INSERT INTO extractions (extraction_id, artifact_id, created_at) VALUES (?, 'a1', ?)",
            (f"e{i}", datetime.now().isoformat()),
        )
    conn.commit()

    ind = stato_sistema._indicatore_quota_llm(conn, budget_giornaliero=10)
    assert ind.semaforo == stato_sistema.SEMAFORO_GIALLO


def test_quota_llm_rosso_a_85_percento():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('src1', 'T1_html')")
    conn.execute("INSERT INTO artifacts (artifact_id, source_id) VALUES ('a1', 'src1')")
    for i in range(9):
        conn.execute(
            "INSERT INTO extractions (extraction_id, artifact_id, created_at) VALUES (?, 'a1', ?)",
            (f"e{i}", datetime.now().isoformat()),
        )
    conn.commit()

    ind = stato_sistema._indicatore_quota_llm(conn, budget_giornaliero=10)
    assert ind.semaforo == stato_sistema.SEMAFORO_ROSSO


def test_quota_llm_conta_solo_oggi():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('src1', 'T1_html')")
    conn.execute("INSERT INTO artifacts (artifact_id, source_id) VALUES ('a1', 'src1')")
    ieri = (datetime.now() - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO extractions (extraction_id, artifact_id, created_at) VALUES ('e1', 'a1', ?)", (ieri,)
    )
    conn.commit()

    ind = stato_sistema._indicatore_quota_llm(conn, budget_giornaliero=10)
    assert "0/10" in ind.valore


def test_ultimo_run_rosso_se_mai_eseguito():
    conn = _conn_di_prova()
    ind = stato_sistema._indicatore_ultimo_run(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_ROSSO
    assert ind.valore == "mai eseguito"


def test_ultimo_run_verde_se_recente():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, tier, last_run) VALUES ('x', 'T1_html', ?)",
        (datetime.now().isoformat(),),
    )
    conn.commit()

    ind = stato_sistema._indicatore_ultimo_run(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_VERDE


def test_ultimo_run_rosso_se_molto_vecchio():
    conn = _conn_di_prova()
    vecchio = (datetime.now() - timedelta(days=5)).isoformat()
    conn.execute("INSERT INTO sources (source_id, tier, last_run) VALUES ('x', 'T1_html', ?)", (vecchio,))
    conn.commit()

    ind = stato_sistema._indicatore_ultimo_run(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_ROSSO


def test_quarantena_verde_sotto_dieci():
    conn = _conn_di_prova()
    ind = stato_sistema._indicatore_quarantena(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_VERDE
    assert ind.valore == "0"


def test_quarantena_giallo_tra_dieci_e_trenta():
    conn = _conn_di_prova()
    for i in range(12):
        conn.execute(
            f"INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, stato, archiviato) "
            f"VALUES ('e{i}', 't', '2026-09-01', '2026-09-01', 'Calosso', 'quarantena', 'no')"
        )
    conn.commit()

    ind = stato_sistema._indicatore_quarantena(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_GIALLO


def test_quarantena_esclude_eventi_archiviati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, stato, archiviato) "
        "VALUES ('e1', 't', '2026-01-01', '2026-01-01', 'Calosso', 'quarantena', 'si')"
    )
    conn.commit()

    ind = stato_sistema._indicatore_quarantena(conn)
    assert ind.valore == "0"


def test_coda_follow_verde_sotto_soglia():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('x', 'facebook', 'da_seguire')")
    conn.commit()

    ind = stato_sistema._indicatore_coda_follow(conn)
    assert ind.semaforo == stato_sistema.SEMAFORO_VERDE
    assert "1 da lavorare" in ind.valore


def test_coda_follow_ignora_stati_gia_chiusi():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('x', 'facebook', 'seguito')")
    conn.execute("INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('y', 'facebook', 'fallito')")
    conn.execute("INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('z', 'facebook', 'non_valido')")
    conn.commit()

    ind = stato_sistema._indicatore_coda_follow(conn)
    assert "0 da lavorare" in ind.valore


def test_coda_follow_giallo_e_rosso_su_soglie():
    conn = _conn_di_prova()
    for i in range(60):
        conn.execute(
            "INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES (?, 'facebook', 'da_seguire')", (f"s{i}",)
        )
    conn.commit()
    assert stato_sistema._indicatore_coda_follow(conn).semaforo == stato_sistema.SEMAFORO_GIALLO

    for i in range(60, 210):
        conn.execute(
            "INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES (?, 'facebook', 'da_seguire')", (f"s{i}",)
        )
    conn.commit()
    assert stato_sistema._indicatore_coda_follow(conn).semaforo == stato_sistema.SEMAFORO_ROSSO


def test_calcola_indicatori_ritorna_i_cinque_scelti():
    conn = _conn_di_prova()
    indicatori = stato_sistema.calcola_indicatori(conn, budget_llm_giornaliero=1200)
    nomi = {i.nome for i in indicatori}
    assert len(indicatori) == 5
    assert nomi == {
        "Fonti in errore/rotte",
        "Quota LLM residua",
        "Ultimo run completato",
        "Eventi in quarantena da rivedere",
        "Coda follow in attesa",
    }
