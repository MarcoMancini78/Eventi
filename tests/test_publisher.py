"""Pubblicazione su Sheets: logica pura testabile senza rete reale (15.1
regola 8) tramite un fake minimale dell'interfaccia gspread.Worksheet
effettivamente usata (clear/update/get_all_records)."""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import publisher, store


class _WorksheetFinto:
    def __init__(self, righe_esistenti=None):
        self._righe_esistenti = righe_esistenti or []
        self.righe_scritte = None
        self.chiamate_format = []
        self.chiamate_update_con_range = []

    def get_all_records(self):
        return self._righe_esistenti

    def clear(self):
        pass

    def update(self, valori, range_name=None, value_input_option=None):
        # Come gspread.Worksheet.update: senza range_name aggiorna l'intero
        # foglio dall'origine (i dati principali che i test verificano via
        # righe_scritte); con range_name e' una scrittura mirata altrove sul
        # foglio (es. la legenda), tracciata a parte per non confondersi
        # con i dati principali.
        if range_name is None:
            self.righe_scritte = valori
        else:
            self.chiamate_update_con_range.append((range_name, valori))

    def format(self, range_name, formato):
        self.chiamate_format.append((range_name, formato))


def _conn_di_prova() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA_SQL)
    return conn


def test_pubblica_fonti_scrive_intestazione_e_righe():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, tier, endpoint, piattaforma, last_run, consecutive_errors) "
        "VALUES ('comune-calosso', 'T1_html', 'https://comune.calosso.at.it/Eventi', 'pa_design_system', '2026-08-27', 0)"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_fonti(ws, conn)

    assert n == 1
    intestazione, riga = ws.righe_scritte
    assert intestazione == publisher.COLONNE_FONTI
    diz = dict(zip(intestazione, riga))
    assert diz["source_id"] == "comune-calosso"
    assert diz["url"] == "https://comune.calosso.at.it/Eventi"
    assert diz["piattaforma"] == "pa_design_system"
    assert diz["giorni_in_errore"] == 0


def test_pubblica_fonti_categoria_vuota_resta_vuota():
    """categoria non è ancora popolata per una fonte appena creata (03):
    non va inventata, resta vuota finché non c'è un dato reale."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id) VALUES ('x')")
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_fonti(ws, conn)

    intestazione, riga = ws.righe_scritte
    diz = dict(zip(intestazione, riga))
    assert diz["categoria"] == ""


def test_pubblica_fonti_deriva_soggetto_e_canale():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, categoria) VALUES ('comune-acqui-terme', 'comune')")
    conn.execute("INSERT INTO sources (source_id, categoria) VALUES ('proloco-calosso-facebook', 'proloco')")
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_fonti(ws, conn)

    righe = {r[0]: dict(zip(ws.righe_scritte[0], r)) for r in ws.righe_scritte[1:]}
    assert righe["comune-acqui-terme"]["soggetto"] == "Comune di Acqui Terme"
    assert righe["comune-acqui-terme"]["canale"] == "sito"
    assert righe["proloco-calosso-facebook"]["soggetto"] == "Pro Loco di Calosso"
    assert righe["proloco-calosso-facebook"]["canale"] == "facebook"


def test_righe_da_sqlite_include_fonti_da_event_sources():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Sagra del Tartufo', '2026-09-12', '2026-09-12', 'Calosso', 'no')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'comune-calosso', 'https://x', '2026-08-27')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'proloco-calosso-sito', 'https://y', '2026-08-27')"
    )
    conn.commit()

    righe = publisher.righe_da_sqlite(conn)
    assert len(righe) == 1
    assert "comune-calosso" in righe[0]["fonti"]
    assert "proloco-calosso-sito" in righe[0]["fonti"]


def test_righe_da_sqlite_esclude_eventi_archiviati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento passato', '2026-01-01', '2026-01-01', 'Calosso', 'si')"
    )
    conn.commit()

    righe = publisher.righe_da_sqlite(conn)
    assert righe == []


def test_righe_da_sqlite_include_fascia_dal_comune():
    """2026-08-31: serve la fascia per separare Eventi (vista) da
    Eventi_estesi — risolta con un JOIN su comuni.comune."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('1', 'Calosso', 'A', 'si')")
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Sagra', '2026-09-12', '2026-09-12', 'Calosso', 'no')"
    )
    conn.commit()

    righe = publisher.righe_da_sqlite(conn)
    assert righe[0]["fascia"] == "A"


def test_righe_eventi_per_mappa_include_coordinate():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo, lat, lon, km) "
        "VALUES ('1', 'Calosso', 'A', 'si', 44.7975, 8.2686, 5.0)"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, tipologia, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Sagra del Tartufo', 'sagra', '2026-09-12', '2026-09-13', 'Calosso', 'no')"
    )
    conn.commit()

    righe = publisher.righe_eventi_per_mappa(conn)
    assert len(righe) == 1
    assert righe[0]["lat"] == 44.7975
    assert righe[0]["lon"] == 8.2686


def test_righe_eventi_per_mappa_include_descrizione_minuti_fonti():
    """2026-08-31, richiesto dall'utente per il dettaglio del popup sulla mappa."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo, lat, lon, km, minuti) "
        "VALUES ('1', 'Calosso', 'A', 'si', 44.7975, 8.2686, 5.0, 8)"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, descrizione, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Sagra del Tartufo', 'Stand gastronomici e musica.', '2026-09-12', '2026-09-13', 'Calosso', 'no')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'comune-calosso', 'https://x', '2026-08-27')"
    )
    conn.commit()

    righe = publisher.righe_eventi_per_mappa(conn)
    assert righe[0]["descrizione"] == "Stand gastronomici e musica."
    assert righe[0]["minuti"] == 8
    assert righe[0]["fonti"] == "comune-calosso"


def test_righe_eventi_per_mappa_segnala_quarantena(tmp_path):
    """2026-08-31, richiesto dall'utente: gli eventi in quarantena
    comparivano su Eventi/mappa senza alcun segnale — restano visibili
    (non nascosti), ma vanno marcati come 'da verificare' invece di
    sembrare confermati."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo, lat, lon) "
        "VALUES ('1', 'Calosso', 'A', 'si', 44.7975, 8.2686)"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Evento culturale', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'quarantena')"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev2', 'Sagra confermata', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'ok')"
    )
    conn.commit()

    righe = publisher.righe_eventi_per_mappa(conn)
    percorso = tmp_path / "eventi_mappa.json"
    publisher.scrivi_eventi_mappa_json(righe, percorso)

    import json
    corpo = json.loads(percorso.read_text(encoding="utf-8"))
    per_id = {e["id"]: e for e in corpo["eventi"]}
    assert per_id["ev1"]["quarantena"] is True
    assert per_id["ev2"]["quarantena"] is False


def test_righe_eventi_per_mappa_esclude_comune_senza_coordinate():
    """04.7: vuoto non è un errore, mai un valore indovinato — un comune
    senza lat/lon non deve piazzare un evento a 0,0."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('1', 'Calosso', 'A', 'si')")
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Sagra', '2026-09-12', '2026-09-12', 'Calosso', 'no')"
    )
    conn.commit()

    righe = publisher.righe_eventi_per_mappa(conn)
    assert righe == []


def test_righe_eventi_per_mappa_esclude_archiviati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo, lat, lon) "
        "VALUES ('1', 'Calosso', 'A', 'si', 44.7975, 8.2686)"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Evento passato', '2026-01-01', '2026-01-01', 'Calosso', 'si')"
    )
    conn.commit()

    righe = publisher.righe_eventi_per_mappa(conn)
    assert righe == []


def test_scrivi_eventi_mappa_json_scrive_file_valido(tmp_path):
    righe = [{
        "id": "ev1", "titolo": "Sagra del Tartufo", "comune": "Calosso",
        "lat": 44.7975, "lon": 8.2686, "km": 5.0,
        "data_inizio": "2026-09-12", "data_fine": "2026-09-13",
        "tipologia": "sagra", "url": "https://x",
    }]
    percorso = tmp_path / "eventi_mappa.json"

    n = publisher.scrivi_eventi_mappa_json(righe, percorso)

    assert n == 1
    import json
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    assert "generato_il" in dati
    assert len(dati["eventi"]) == 1
    assert dati["eventi"][0]["comune"] == "Calosso"
    assert dati["eventi"][0]["lat"] == 44.7975
    assert dati["eventi"][0]["descrizione"] == ""
    assert dati["eventi"][0]["fonti"] == ""


def test_scrivi_eventi_mappa_json_vuoto_non_omesso(tmp_path):
    """04.7: nessun evento con coordinate deve produrre un array vuoto,
    non un file assente — la pagina mostra 'nessun evento', non un errore
    di caricamento."""
    percorso = tmp_path / "eventi_mappa.json"

    n = publisher.scrivi_eventi_mappa_json([], percorso)

    assert n == 0
    import json
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    assert dati["eventi"] == []


class _ConfigFinta:
    vista_principale_giorni = 21
    vista_principale_fasce = ("A", "B")


def test_righe_eventi_vista_principale_filtra_per_fascia_e_orizzonte():
    """03: Eventi = solo prossimi 21 giorni, fasce A/B. Un evento in
    fascia C o oltre l'orizzonte finisce in Eventi_estesi, non qui."""
    oggi = date.today()
    righe = [
        {"id": "a", "fascia": "A", "data_inizio": (oggi + timedelta(days=5)).isoformat()},
        {"id": "b", "fascia": "C", "data_inizio": (oggi + timedelta(days=5)).isoformat()},
        {"id": "c", "fascia": "A", "data_inizio": (oggi + timedelta(days=40)).isoformat()},
        {"id": "d", "fascia": None, "data_inizio": (oggi + timedelta(days=5)).isoformat()},
    ]
    vista = publisher.righe_eventi_vista_principale(righe, _ConfigFinta())
    assert [r["id"] for r in vista] == ["a"]


def test_righe_eventi_estesi_e_complemento_della_vista_principale():
    oggi = date.today()
    righe = [
        {"id": "a", "fascia": "A", "data_inizio": (oggi + timedelta(days=5)).isoformat()},
        {"id": "b", "fascia": "C", "data_inizio": (oggi + timedelta(days=5)).isoformat()},
    ]
    estesi = publisher.righe_eventi_estesi(righe, _ConfigFinta())
    assert [r["id"] for r in estesi] == ["b"]


def test_righe_archivio_da_sqlite_solo_eventi_archiviati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev1', 'Passato', '2026-01-01', '2026-01-01', 'Calosso', 'si')"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato) "
        "VALUES ('ev2', 'Attivo', '2026-09-01', '2026-09-01', 'Calosso', 'no')"
    )
    conn.commit()

    righe = publisher.righe_archivio_da_sqlite(conn)
    assert len(righe) == 1
    assert righe[0]["id"] == "ev1"


def test_pubblica_archivio_scrive_intestazione_e_righe():
    ws = _WorksheetFinto()
    righe = [{"id": "ev1", "titolo": "Passato", "data_inizio": "2026-01-01", "data_fine": "2026-01-01",
              "comune": "Calosso", "fonti": "comune-calosso"}]
    n = publisher.pubblica_archivio(ws, righe)
    assert n == 1
    intestazione, riga = ws.righe_scritte
    assert intestazione == publisher.COLONNE_ARCHIVIO
    diz = dict(zip(intestazione, riga))
    assert diz["titolo"] == "Passato"
    assert diz["fonti"] == "comune-calosso"


def test_righe_quarantena_filtra_solo_stato_quarantena():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, stato, archiviato) "
        "VALUES ('ev1', 'Pubblicato', '2026-09-01', '2026-09-01', 'Calosso', 'nuovo', 'no')"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, stato, archiviato) "
        "VALUES ('ev2', 'In dubbio', '2026-09-02', '2026-09-02', 'Calosso', 'quarantena', 'no')"
    )
    conn.commit()

    righe = publisher.righe_quarantena_da_sqlite(conn)
    assert len(righe) == 1
    assert righe[0]["id"] == "ev2"


def test_pubblica_serie_scrive_intestazione_e_righe():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO series (serie_id, titolo, tipologia, comune, rrule, stato, bloccata) "
        "VALUES ('s1', 'Mercato settimanale', 'mercato', 'Calosso', 'FREQ=WEEKLY;BYDAY=SA', 'attiva', 'no')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_serie(ws, conn)

    assert n == 1
    intestazione, riga = ws.righe_scritte
    assert intestazione == publisher.COLONNE_SERIE
    diz = dict(zip(intestazione, riga))
    assert diz["titolo"] == "Mercato settimanale"
    assert diz["bloccata"] == "no"


def test_pubblica_serie_preserva_bloccata_impostata_a_mano():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO series (serie_id, titolo, comune, rrule, stato, bloccata) "
        "VALUES ('s1', 'Mercato', 'Calosso', 'FREQ=WEEKLY', 'attiva', 'no')"
    )
    conn.commit()

    ws = _WorksheetFinto(righe_esistenti=[{"serie_id": "s1", "bloccata": "si"}])
    publisher.pubblica_serie(ws, conn)

    intestazione, riga = ws.righe_scritte
    diz = dict(zip(intestazione, riga))
    assert diz["bloccata"] == "si"  # non sovrascritta dal valore calcolato 'no'


def test_pubblica_log_scrive_intestazione_e_run():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO runs (run_id, tipo, inizio, fine, durata_min, fonti_tentate, fonti_ok, "
        "fonti_errore, artefatti, chiamate_llm, eventi_nuovi, eventi_aggiornati, in_quarantena, archiviati) "
        "VALUES ('r1', 'principale', '2026-08-27T10:00:00', '2026-08-27T10:30:00', 30.0, "
        "10, 8, 2, 5, 3, 2, 0, 1, 0)"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_log(ws, conn)

    assert n == 1
    intestazione, riga = ws.righe_scritte
    assert intestazione == publisher.COLONNE_LOG
    diz = dict(zip(intestazione, riga))
    assert diz["run_id"] == "r1"
    assert diz["fonti_tentate"] == 10
    assert diz["eventi_nuovi"] == 2


def test_pubblica_log_ordina_dal_piu_recente():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO runs (run_id, tipo, inizio) VALUES ('vecchio', 'principale', '2026-08-25T10:00:00')"
    )
    conn.execute(
        "INSERT INTO runs (run_id, tipo, inizio) VALUES ('recente', 'principale', '2026-08-27T10:00:00')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_log(ws, conn)

    intestazione, prima_riga, seconda_riga = ws.righe_scritte
    diz_prima = dict(zip(intestazione, prima_riga))
    assert diz_prima["run_id"] == "recente"


def test_pubblica_stato_scrive_intestazione_e_indicatori():
    from src.stato_sistema import Indicatore, SEMAFORO_VERDE

    ws = _WorksheetFinto()
    indicatori = [Indicatore(nome="Fonti in errore/rotte", valore="0 in errore, 0 rotte (su 10)", semaforo=SEMAFORO_VERDE)]

    n = publisher.pubblica_stato(ws, indicatori)

    assert n == 1
    intestazione, riga = ws.righe_scritte
    assert intestazione == publisher.COLONNE_STATO
    assert riga == ["Fonti in errore/rotte", "0 in errore, 0 rotte (su 10)", SEMAFORO_VERDE]


def test_pubblica_eventi_preserva_colonne_utente():
    ws = _WorksheetFinto(righe_esistenti=[{"id": "ev1", "stato": "confermato", "note": "verificato a mano", "bloccato": "", "soppressa": ""}])
    righe = [{
        "id": "ev1", "titolo": "Sagra", "descrizione": "", "tipologia": "sagra",
        "data_inizio": "2026-09-12", "ora_inizio": "", "data_fine": "2026-09-12", "ora_fine": "",
        "serie_id": "", "occorrenza": "", "comune": "Calosso", "luogo": "", "km": 0, "minuti": 0,
        "prezzo": "", "organizzatore": "", "url": "", "url_immagine": "", "fonti": "comune-calosso",
        "confidenza": 90, "stato": "nuovo", "note": "", "primo_visto": "", "ultimo_visto": "",
        "bloccato": "no", "soppressa": "no",
    }]

    publisher.pubblica_eventi(ws, righe)

    intestazione, riga = ws.righe_scritte
    diz = dict(zip(intestazione, riga))
    assert diz["stato"] == "confermato"  # non sovrascritto dal calcolo automatico
    assert diz["note"] == "verificato a mano"


def test_pubblica_copertura_comuni_scrive_legenda():
    """Richiesto dall'utente (2026-08-31): i simboli (verde/grigio/rosso/
    trattino/vuoto) non sono autoesplicativi senza una legenda a fianco."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Calosso', 'A', 'si')")
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_copertura_comuni(ws, conn)

    assert len(ws.chiamate_update_con_range) == 1
    range_name, valori = ws.chiamate_update_con_range[0]
    assert range_name.startswith("H1:H")
    testo_legenda = " ".join(riga[0] for riga in valori)
    assert publisher._SIMBOLO_VERDE in testo_legenda
    assert publisher._SIMBOLO_VERIFICATO_ASSENTE in testo_legenda


def test_pubblica_copertura_comuni_simboli_per_stato():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Calosso', 'A', 'si')")
    conn.execute("INSERT INTO sources (source_id, endpoint, consecutive_errors) VALUES ('comune-calosso', 'https://x', 0)")
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('comune-calosso-facebook', 'facebook', 'seguito')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('proloco-calosso-facebook', 'facebook', 'da_seguire')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('proloco-calosso-instagram', 'instagram', 'fallito')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_comuni(ws, conn)

    assert n == 1
    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["fascia"] == "A"
    assert diz["comune"] == "Calosso"
    assert diz["sito_istituzionale"] == publisher._SIMBOLO_VERDE
    assert diz["fb_comune"] == publisher._SIMBOLO_VERDE
    assert diz["fb_proloco"] == publisher._SIMBOLO_GRIGIO
    assert diz["ig_proloco"] == publisher._SIMBOLO_ROSSO


def test_pubblica_copertura_comuni_verificato_assente_su_ricerca_negativa():
    """Caso reale (2026-08-30, Cunico): un comune con esito 'nessuna
    fonte trovata' non deve restare indistinguibile da uno mai cercato —
    mostra '—' invece di vuoto sulle colonne Pro Loco."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Cissone', 'A', 'si')")
    conn.execute("INSERT INTO sources (source_id, endpoint, consecutive_errors) VALUES ('comune-cissone', 'https://x', 0)")
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, stato) "
        "VALUES ('proloco-cissone-nessuna-fonte', 'nessuna', 'Cissone', 'nessuna_fonte_trovata')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_copertura_comuni(ws, conn)

    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["fb_proloco"] == publisher._SIMBOLO_VERIFICATO_ASSENTE
    assert diz["ig_proloco"] == publisher._SIMBOLO_VERIFICATO_ASSENTE


def test_pubblica_copertura_comuni_trovato_prevale_su_ricerca_negativa():
    """Se un canale viene poi trovato (es. dopo una riverifica), il
    simbolo reale prevale sul '—' anche se esiste ancora una riga
    'nessuna_fonte_trovata' per l'altro canale dello stesso comune."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Cissone', 'A', 'si')")
    conn.execute("INSERT INTO sources (source_id, endpoint, consecutive_errors) VALUES ('comune-cissone', 'https://x', 0)")
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, stato) "
        "VALUES ('proloco-cissone-nessuna-fonte', 'nessuna', 'Cissone', 'nessuna_fonte_trovata')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, stato) "
        "VALUES ('proloco-cissone-facebook', 'facebook', 'Cissone', 'seguito')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_copertura_comuni(ws, conn)

    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["fb_proloco"] == publisher._SIMBOLO_VERDE
    assert diz["ig_proloco"] == publisher._SIMBOLO_VERIFICATO_ASSENTE


def test_simbolo_sito_istituzionale_rosso_con_errori():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, endpoint, consecutive_errors) VALUES ('comune-x', 'https://x', 3)")
    conn.commit()
    assert publisher._simbolo_sito_istituzionale(conn, "comune-x") == publisher._SIMBOLO_ROSSO


def test_simbolo_social_quarantena_e_rossa():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO coda_follow (source_id, piattaforma, stato) VALUES ('x', 'facebook', 'quarantena')")
    conn.commit()
    assert publisher._simbolo_social(conn, "x") == publisher._SIMBOLO_ROSSO


def test_pubblica_copertura_altre_entita_scrive_legenda():
    """Richiesto dall'utente (2026-08-31): stessa legenda richiesta per
    CoperturaComuni, applicata anche a CoperturaAltreEntita (colonna G)."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Calosso', 'A', 'si')")
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_copertura_altre_entita(ws, conn)

    assert len(ws.chiamate_update_con_range) == 1
    range_name, valori = ws.chiamate_update_con_range[0]
    assert range_name.startswith("G1:G")
    testo_legenda = " ".join(riga[0] for riga in valori)
    assert publisher._SIMBOLO_VERDE in testo_legenda
    assert publisher._SIMBOLO_VERIFICATO_ASSENTE in testo_legenda


def test_copertura_altre_entita_esclude_proloco_con_comune_in_perimetro():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Calosso', 'A', 'si')")
    conn.execute("INSERT INTO sources (source_id, categoria) VALUES ('proloco-calosso-sito', 'proloco')")
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_altre_entita(ws, conn)
    assert n == 0


def test_copertura_altre_entita_include_proloco_fuori_perimetro():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO comuni (istat, comune, fascia, attivo) VALUES ('001', 'Calosso', 'A', 'si')")
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, categoria, stato) "
        "VALUES ('proloco-fuori-perimetro-facebook', 'facebook', 'proloco', 'seguito')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_altre_entita(ws, conn)
    assert n == 1
    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["nome"] == "proloco-fuori-perimetro"
    assert diz["facebook"] == publisher._SIMBOLO_VERDE
    assert diz["sito"] == ""


def test_copertura_altre_entita_raggruppa_stesso_nome_su_piu_canali():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, categoria) VALUES ('teatro-alessandria', 'teatro')")
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, categoria, stato) "
        "VALUES ('teatro-alessandria-facebook', 'facebook', 'teatro', 'seguito')"
    )
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, categoria, stato) "
        "VALUES ('teatro-alessandria-instagram', 'instagram', 'teatro', 'fallito')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_altre_entita(ws, conn)
    assert n == 1
    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["tipologia"] == "teatro"
    assert diz["facebook"] == publisher._SIMBOLO_VERDE
    assert diz["instagram"] == publisher._SIMBOLO_ROSSO


def test_copertura_altre_entita_sito_diretto_senza_suffisso():
    """Le fonti T0/T1 dirette (teatro-*, aggregatore-*) usano il nome nudo
    come source_id per il sito, non un suffisso '-sito' esplicito."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO sources (source_id, categoria, endpoint, consecutive_errors) "
        "VALUES ('teatro-alessandria', 'teatro', 'https://x', 0)"
    )
    conn.commit()

    ws = _WorksheetFinto()
    publisher.pubblica_copertura_altre_entita(ws, conn)
    intestazione, riga = ws.righe_scritte[0], ws.righe_scritte[1]
    diz = dict(zip(intestazione, riga))
    assert diz["sito"] == publisher._SIMBOLO_VERDE


def test_copertura_altre_entita_esclude_fonti_feed_sintetiche():
    """feed-{piattaforma}-{handle} (feed_social.py) e' un artefatto
    tecnico di tracciamento, non un'entita': il soggetto reale e' gia'
    censito altrove (bug segnalato dall'utente 2026-08-28: 'feed-facebook-
    comunechieri' compariva come riga fantasma invece di essere lo stesso
    Chieri gia' visibile in CoperturaComuni)."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, categoria) VALUES ('feed-facebook-comunechieri', NULL)")
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_altre_entita(ws, conn)
    assert n == 0


def test_copertura_altre_entita_esclude_righe_nessuna_fonte_trovata():
    """Bug trovato nel collaudo (2026-08-30): una riga 'nessuna_fonte_trovata'
    (comune cercato senza esito, non un'entità reale) comparirebbe come
    riga fantasma vuota qui, perché _nome_entita non riconosce il
    suffisso '-nessuna-fonte' come un canale — già visibile come simbolo
    dedicato su CoperturaComuni, non va duplicata qui."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, comune, categoria, stato) "
        "VALUES ('proloco-cissone-nessuna-fonte', 'nessuna', 'Cissone', 'proloco', 'nessuna_fonte_trovata')"
    )
    conn.commit()

    ws = _WorksheetFinto()
    n = publisher.pubblica_copertura_altre_entita(ws, conn)
    assert n == 0


def test_simbolo_sito_istituzionale_vuoto_senza_endpoint():
    """Bug trovato nel collaudo 2026-08-28: una fonte censita senza URL
    (es. un teatro in attesa che si trovi il sito) non deve risultare
    verde solo perche' la riga esiste in sources."""
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, categoria, consecutive_errors) VALUES ('teatro-x', 'teatro', 0)")
    conn.commit()
    assert publisher._simbolo_sito_istituzionale(conn, "teatro-x") == ""


def test_pull_da_verificare_aggiorna_comune_e_stato():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, stato, comune) "
        "VALUES ('sconosciuto-facebook-x', 'facebook', 'x', 'quarantena', '')"
    )
    conn.commit()

    ws = _WorksheetFinto(righe_esistenti=[
        {"source_id": "sconosciuto-facebook-x", "comune": "Ponti", "stato": "da_seguire"}
    ])
    esito = publisher.pull_da_verificare(ws, conn)

    assert esito["aggiornate"] == 1
    riga = conn.execute("SELECT comune, stato FROM coda_follow WHERE source_id='sconosciuto-facebook-x'").fetchone()
    assert riga["comune"] == "Ponti"
    assert riga["stato"] == "da_seguire"


def test_pull_da_verificare_ignora_stato_non_valido():
    """Un valore scritto per errore su Sheets (typo, stato inventato) non
    deve essere accettato: solo gli stati noti di coda_follow."""
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO coda_follow (source_id, piattaforma, handle, stato) "
        "VALUES ('sconosciuto-facebook-x', 'facebook', 'x', 'quarantena')"
    )
    conn.commit()

    ws = _WorksheetFinto(righe_esistenti=[
        {"source_id": "sconosciuto-facebook-x", "comune": "", "stato": "boh"}
    ])
    publisher.pull_da_verificare(ws, conn)

    riga = conn.execute("SELECT stato FROM coda_follow WHERE source_id='sconosciuto-facebook-x'").fetchone()
    assert riga["stato"] == "quarantena"  # non sovrascritto da un valore non riconosciuto


def test_pull_da_verificare_ignora_righe_senza_source_id_in_coda_follow():
    conn = _conn_di_prova()
    ws = _WorksheetFinto(righe_esistenti=[{"source_id": "non-esiste", "comune": "X", "stato": "da_seguire"}])
    esito = publisher.pull_da_verificare(ws, conn)
    assert esito["ignorate"] == 1
    assert esito["aggiornate"] == 0


def test_pubblica_eventi_preserva_comune_corretto_a_mano():
    ws = _WorksheetFinto(righe_esistenti=[{"id": "ev1", "stato": "", "note": "", "bloccato": "", "soppressa": "", "comune": "Comune Corretto"}])
    righe = [{
        "id": "ev1", "titolo": "Sagra", "descrizione": "", "tipologia": "sagra",
        "data_inizio": "2026-09-12", "ora_inizio": "", "data_fine": "2026-09-12", "ora_fine": "",
        "serie_id": "", "occorrenza": "", "comune": "Comune Sbagliato", "luogo": "", "km": 0, "minuti": 0,
        "prezzo": "", "organizzatore": "", "url": "", "url_immagine": "", "fonti": "comune-calosso",
        "confidenza": 90, "stato": "nuovo", "note": "", "primo_visto": "", "ultimo_visto": "",
        "bloccato": "no", "soppressa": "no",
    }]

    publisher.pubblica_eventi(ws, righe)

    intestazione, riga = ws.righe_scritte
    diz = dict(zip(intestazione, riga))
    assert diz["comune"] == "Comune Corretto"


def test_pubblica_eventi_fissa_font_size_su_intera_colonna():
    """Bug trovato dall'utente (2026-08-30): un font impostato a mano su
    singole righe non regge — ogni publish riordina gli eventi e
    riscrive da capo, e Sheets tiene la formattazione per posizione di
    cella, non per contenuto. Fissarla sull'intera colonna la rende
    indipendente da quante righe esistono o in che ordine sono."""
    ws = _WorksheetFinto()
    publisher.pubblica_eventi(ws, [])

    formati = dict(ws.chiamate_format)
    assert formati["A:Z"] == {"textFormat": {"fontSize": 8}}


def _evento_finto(event_id: str, **override) -> dict:
    base = {
        "id": event_id, "titolo": "Sagra", "descrizione": "", "tipologia": "sagra",
        "data_inizio": "2026-09-12", "ora_inizio": "", "data_fine": "2026-09-12", "ora_fine": "",
        "serie_id": "", "occorrenza": "", "comune": "Calosso", "luogo": "", "km": 0, "minuti": 0,
        "prezzo": "", "organizzatore": "", "url": "", "url_immagine": "", "fonti": "comune-calosso",
        "confidenza": 40, "stato": "quarantena", "note": "", "primo_visto": "", "ultimo_visto": "",
        "bloccato": "no", "soppressa": "no",
    }
    base.update(override)
    return base


def test_pubblica_quarantena_include_colonna_azione():
    ws = _WorksheetFinto()
    publisher.pubblica_quarantena(ws, [_evento_finto("ev1")])

    intestazione, riga = ws.righe_scritte
    assert "azione" in intestazione
    diz = dict(zip(intestazione, riga))
    assert diz["azione"] == ""


def test_pubblica_quarantena_preserva_azione_scritta_dall_operatore():
    ws = _WorksheetFinto(righe_esistenti=[{"id": "ev1", "azione": "promuovi"}])
    publisher.pubblica_quarantena(ws, [_evento_finto("ev1")])

    intestazione, riga = ws.righe_scritte
    diz = dict(zip(intestazione, riga))
    assert diz["azione"] == "promuovi"


def test_pull_azioni_quarantena_ignora_valori_non_validi():
    """04.7: un valore non riconosciuto va ignorato, mai interpretato a caso."""
    ws = _WorksheetFinto(righe_esistenti=[
        {"id": "ev1", "azione": "promuovi"},
        {"id": "ev2", "azione": "boh"},
        {"id": "ev3", "azione": ""},
    ])
    azioni = publisher.pull_azioni_quarantena(ws)
    assert azioni == {"ev1": "promuovi"}


def test_applica_azioni_quarantena_promuovi():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Sagra', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'quarantena')"
    )
    conn.commit()

    esiti = publisher.applica_azioni_quarantena(conn, {"ev1": "promuovi"})

    stato = conn.execute("SELECT stato FROM events WHERE event_id='ev1'").fetchone()["stato"]
    assert stato == "ok"
    assert esiti["promossi"] == 1


def test_applica_azioni_quarantena_scarta_esclude_da_righe_da_sqlite():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Sagra', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'quarantena')"
    )
    conn.commit()

    publisher.applica_azioni_quarantena(conn, {"ev1": "scarta"})

    stato = conn.execute("SELECT stato FROM events WHERE event_id='ev1'").fetchone()["stato"]
    assert stato == "scartato"
    assert publisher.righe_da_sqlite(conn) == []  # riga resta in DB, esclusa dalle viste


def test_applica_azioni_quarantena_elimina_rimuove_dal_db():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Sagra', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'quarantena')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'comune-calosso', 'https://x', '2026-08-27')"
    )
    conn.commit()

    esiti = publisher.applica_azioni_quarantena(conn, {"ev1": "elimina"})

    assert conn.execute("SELECT 1 FROM events WHERE event_id='ev1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM event_sources WHERE event_id='ev1'").fetchone() is None
    assert esiti["eliminati"] == 1


def test_applica_azioni_quarantena_ignora_fonte_esclude_la_fonte():
    conn = _conn_di_prova()
    conn.execute("INSERT INTO sources (source_id, tier) VALUES ('feed-facebook-rumoroso', 'social')")
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Rumore', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'quarantena')"
    )
    conn.execute(
        "INSERT INTO event_sources (event_id, source_id, url, seen_at) "
        "VALUES ('ev1', 'feed-facebook-rumoroso', 'https://x', '2026-08-27')"
    )
    conn.commit()

    esiti = publisher.applica_azioni_quarantena(conn, {"ev1": "ignora_fonte"})

    stato_evento = conn.execute("SELECT stato FROM events WHERE event_id='ev1'").fetchone()["stato"]
    stato_fonte = conn.execute("SELECT stato FROM sources WHERE source_id='feed-facebook-rumoroso'").fetchone()["stato"]
    assert stato_evento == "scartato"
    assert stato_fonte == "esclusa"
    assert esiti["fonti_escluse"] == 1


def test_righe_da_sqlite_esclude_eventi_scartati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Scartato', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'scartato')"
    )
    conn.commit()

    assert publisher.righe_da_sqlite(conn) == []


def test_righe_eventi_per_mappa_esclude_eventi_scartati():
    conn = _conn_di_prova()
    conn.execute(
        "INSERT INTO comuni (istat, comune, fascia, attivo, lat, lon) "
        "VALUES ('1', 'Calosso', 'A', 'si', 44.7975, 8.2686)"
    )
    conn.execute(
        "INSERT INTO events (event_id, titolo, data_inizio, data_fine, comune, archiviato, stato) "
        "VALUES ('ev1', 'Scartato', '2026-09-12', '2026-09-12', 'Calosso', 'no', 'scartato')"
    )
    conn.commit()

    assert publisher.righe_eventi_per_mappa(conn) == []
