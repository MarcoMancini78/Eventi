#!/usr/bin/env python3
"""Unico punto d'ingresso del sistema (15.1). Sottocomandi come da guida M0-M11."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR, DB_PATH, load_config
from src import store


def cmd_init(args: argparse.Namespace) -> None:
    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)
    print(f"SQLite pronto in {DB_PATH}")

    if args.skip_sheets:
        print("Creazione fogli Google saltata (--skip-sheets)")
        return

    if not Path(config.google_oauth_client_json).exists():
        print(
            f"File credenziali OAuth non trovato: {config.google_oauth_client_json}. "
            "Copia config/.env.example in config/.env e verifica il percorso, poi rilancia."
        )
        return

    from src import sheets_client

    ids = sheets_client.init_workbooks(config)
    print("Workbook creati:")
    for nome, spreadsheet_id in ids.items():
        print(f"  {nome}: {spreadsheet_id}")
    print("Copia questi ID nelle relative variabili GOOGLE_SPREADSHEET_ID_* di config/.env")


def cmd_import_perimetro(args: argparse.Namespace) -> None:
    from src import perimetro

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    csv_path = Path(args.file)
    if not csv_path.exists():
        print(f"File non trovato: {csv_path}")
        sys.exit(1)

    conteggi = perimetro.importa_perimetro(csv_path, conn, config)
    print("Import completato. Conteggio per fascia:")
    for fascia, n in conteggi.items():
        print(f"  {fascia}: {n}")

    if args.publish:
        from src import publisher, sheets_client

        client = sheets_client.get_client(config)
        ws = client.open_by_key(config.spreadsheet_id_anagrafiche).worksheet("Perimetro")
        n = publisher.pubblica_perimetro(ws, conn)
        print(f"Foglio Perimetro aggiornato: {n} righe scritte.")


def _crea_extractor_se_configurato(config, conn):
    if not config.llm_api_key:
        print("LLM_API_KEY non impostata: le fonti T1 si fermeranno al pre-filtro, senza estrazione.")
        return None
    from src.extractor.client import ExtractorClient

    return ExtractorClient(config, conn)


def cmd_run(args: argparse.Namespace) -> None:
    from src import pipeline

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)
    extractor = None if args.no_llm else _crea_extractor_se_configurato(config, conn)

    # tier IS NULL esclude le fonti sintetiche "feed-{piattaforma}-{handle}"
    # create da _assicura_source (feed_social.py, M10): sono satelliti degli
    # artefatti letti dal feed, mai fonti da interrogare con questo giro
    # generico (si leggono solo con 'run.py feed-social').
    query = (
        "SELECT source_id, endpoint, tier, eventi_totali, eventi_utili, last_run, consecutive_errors "
        "FROM sources WHERE tier IS NOT NULL"
    )
    if args.solo_errori:
        query += " AND consecutive_errors > 0"
    fonti = conn.execute(query).fetchall()
    if not fonti:
        if args.solo_errori:
            print("Nessuna fonte con errori pendenti: niente da riciclare.")
        else:
            print("Nessuna fonte in SQLite. Popola il foglio Fonti e sincronizzalo, oppure usa --fonte per un test puntuale.")

    if not args.no_priorita:
        from src.scheduling import ordina_fonti_per_priorita

        fonti = ordina_fonti_per_priorita(conn, fonti)

    if args.limite:
        fonti = fonti[: args.limite]

    if args.fonte and args.endpoint and args.metodo:
        fonte = {
            "source_id": args.fonte,
            "endpoint": args.endpoint,
            "metodo": args.metodo,
            "comune_riferimento": args.comune,
        }
        riepilogo = pipeline.esegui_fonte(fonte, conn, config, extractor)
        print(riepilogo)
        return

    from src.lockfile import RunGiaInCorsoError, lock_run

    tipo_run = "riciclo" if args.solo_errori else "principale"
    paralleli = 1 if args.no_llm else (args.paralleli or config.run_paralleli)  # --no-llm è un test rapido, non serve parallelizzarlo
    try:
        with lock_run(DATA_DIR / "run.lock"):
            _esegui_giro_multi_fonte(fonti, config, args.no_llm, config.budget_run_minuti, tipo_run, paralleli)
    except RunGiaInCorsoError as exc:
        print(exc)
        sys.exit(1)


def _elabora_una_fonte_worker(riga, no_llm: bool, config) -> dict:
    """Eseguito in un thread del pool (M11, run.py run --paralleli): ogni
    worker apre la propria connessione SQLite (store.connect ha WAL
    abilitato, sicuro per scritture concorrenti da connessioni diverse —
    condividerne una sola tra thread non lo è) e il proprio ExtractorClient,
    così la sola quota LLM resta condivisa tramite il lock di modulo in
    extractor/client.py, non l'intera connessione."""
    from src import pipeline

    conn_worker = store.connect(DB_PATH)
    extractor_worker = None if no_llm else _crea_extractor_se_configurato(config, conn_worker)

    fonte = {"source_id": riga["source_id"], "endpoint": riga["endpoint"], "metodo": riga["tier"], "comune_riferimento": None}
    try:
        riepilogo = pipeline.esegui_fonte(fonte, conn_worker, config, extractor_worker)
    except Exception as exc:
        # Ultima rete di sicurezza (15.1 regola 4): esegui_fonte non
        # dovrebbe mai sollevare, ma un bug imprevisto in una fonte non deve
        # comunque poter fermare il giro sulle altre 700+.
        riepilogo = {"source_id": fonte["source_id"], "errore": f"eccezione non gestita: {exc}"}
    finally:
        conn_worker.close()
    return riepilogo


def _esegui_giro_multi_fonte(fonti, config, no_llm: bool, budget_minuti: int, tipo_run: str, paralleli: int) -> None:
    """Processa le fonti in ordine di priorità finché il budget di tempo non
    si esaurisce (08.3: 'poi processa in ordine finché il budget di tempo
    non si esaurisce. Le fonti non raggiunte partono in testa alla coda del
    run successivo'): non serve altro qui, giorni_da_ultimo_run nella
    formula di priorità le fa già risalire da sole al giro dopo.

    Con paralleli > 1 (M11, richiesto dall'utente 2026-08-27) le fonti sono
    elaborate da un pool di thread: ogni worker ha la propria connessione
    SQLite (vedi _elabora_una_fonte_worker), ma tutte le scritture di stato
    aggregato (sources.consecutive_errors, la riga in runs) restano nel
    thread principale via la connessione 'conn' qui sotto, per evitare
    scritture concorrenti sparse su più connessioni allo stesso tempo.

    Registra il riepilogo aggregato in `runs` (M11, foglio Log): 'un run' è
    definito qui come l'intera esecuzione di run.py run, dal lock acquisito
    alla fine del loop (o all'esaurimento del budget) — non include
    run.py feed-social o follow, che hanno un proprio ciclo separato e non
    condividono questa coda a priorità."""
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    conn = store.connect(DB_PATH)

    run_id = str(uuid.uuid4())
    inizio = datetime.now()
    fonti_tentate = fonti_ok = fonti_errore = 0
    artefatti_totali = chiamate_llm_totali = eventi_nuovi = in_quarantena = 0

    def _budget_esaurito() -> bool:
        return (datetime.now() - inizio).total_seconds() > budget_minuti * 60

    fonti_da_processare = fonti
    fonti_saltate = 0
    if _budget_esaurito():
        fonti_saltate = len(fonti_da_processare)
        fonti_da_processare = []

    n_worker = max(1, paralleli)

    def _registra_esito(riepilogo: dict) -> None:
        nonlocal fonti_tentate, fonti_ok, fonti_errore, artefatti_totali, chiamate_llm_totali, eventi_nuovi, in_quarantena
        ora = datetime.now().isoformat()
        fonti_tentate += 1
        # Persistenza dell'esito per fonte (M11, 08.3/08.4): consente il
        # riciclo mirato con --solo-errori invece di rilanciare sempre
        # l'intero elenco. consecutive_errors si azzera appena una fonte
        # torna a funzionare, non serve un reset esplicito altrove.
        # eventi_totali/eventi_utili alimentano la resa_storica della coda a
        # priorità (08.3): 'utili' conta anche la quarantena (un evento
        # trovato ma da confermare non è un fallimento della fonte).
        eventi_utili = riepilogo.get("eventi_pubblicati", 0) + riepilogo.get("eventi_in_quarantena", 0) + riepilogo.get("occorrenze_generate", 0)
        if riepilogo.get("errore"):
            fonti_errore += 1
            conn.execute(
                "UPDATE sources SET last_run=?, consecutive_errors=consecutive_errors+1 WHERE source_id=?",
                (ora, riepilogo["source_id"]),
            )
        else:
            fonti_ok += 1
            artefatti_totali += riepilogo.get("artefatti", 0)
            chiamate_llm_totali += riepilogo.get("chiamate_llm", 0)
            eventi_nuovi += riepilogo.get("eventi_pubblicati", 0) + riepilogo.get("occorrenze_generate", 0)
            in_quarantena += riepilogo.get("eventi_in_quarantena", 0)
            conn.execute(
                """
                UPDATE sources SET last_run=?, consecutive_errors=0,
                    eventi_totali=eventi_totali+?, eventi_utili=eventi_utili+?
                WHERE source_id=?
                """,
                (ora, riepilogo.get("artefatti", 0), eventi_utili, riepilogo["source_id"]),
            )
        conn.commit()
        print(riepilogo)

    # Il pool resta sempre pieno (fino a n_worker richieste in volo): appena
    # un future finisce se ne sottomette subito un altro, invece di
    # sottomettere tutto in blocco (che userebbe memoria inutile e non
    # rispetterebbe il budget di tempo a metà giro).
    with ThreadPoolExecutor(max_workers=n_worker) as pool:
        in_volo = {}
        indice_prossima = 0

        def _rifornisci():
            nonlocal indice_prossima
            while indice_prossima < len(fonti_da_processare) and len(in_volo) < n_worker and not _budget_esaurito():
                fut = pool.submit(_elabora_una_fonte_worker, fonti_da_processare[indice_prossima], no_llm, config)
                in_volo[fut] = True
                indice_prossima += 1

        _rifornisci()
        while in_volo:
            fatto = next(as_completed(in_volo))
            del in_volo[fatto]
            _registra_esito(fatto.result())
            _rifornisci()

    if fonti_saltate or indice_prossima < len(fonti_da_processare):
        rimandate = fonti_saltate + (len(fonti_da_processare) - indice_prossima)
        print(f"Budget di {budget_minuti} minuti esaurito: {rimandate} fonti rimandate al prossimo run.")

    # eventi_aggiornati e archiviati restano a 0: esegui_fonte non distingue
    # oggi un evento nuovo da uno aggiornato dal dedup (upsert_evento non lo
    # segnala nel riepilogo), e l'archiviazione avviene solo in fase di
    # publish, non durante run — un valore qui sarebbe indovinato.
    fine = datetime.now()
    conn.execute(
        """
        INSERT INTO runs (run_id, tipo, inizio, fine, durata_min, fonti_tentate, fonti_ok,
            fonti_errore, artefatti, chiamate_llm, eventi_nuovi, eventi_aggiornati,
            in_quarantena, archiviati)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0)
        """,
        (
            run_id, tipo_run, inizio.isoformat(), fine.isoformat(),
            (fine - inizio).total_seconds() / 60, fonti_tentate, fonti_ok,
            fonti_errore, artefatti_totali, chiamate_llm_totali, eventi_nuovi, in_quarantena,
        ),
    )
    conn.commit()
    conn.close()


def cmd_populate_coda_follow(args: argparse.Namespace) -> None:
    from src.bonifica_social import importa_e_bonifica

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    cartella = Path(args.raw_dir)
    comuni_csv = cartella / "Comuni.csv"
    proloco_csv = cartella / "ProLoco.csv"
    social_csv = cartella / "Social.csv"
    for f in (comuni_csv, proloco_csv):
        if not f.exists():
            print(f"File non trovato: {f}")
            sys.exit(1)

    righe = importa_e_bonifica(comuni_csv, proloco_csv, social_csv, conn)
    print(f"Righe bonificate pronte: {len(righe)}")

    for r in righe:
        conn.execute(
            """
            INSERT INTO coda_follow (source_id, piattaforma, handle, url, soggetto, comune, fascia, categoria, stato)
            VALUES (:source_id, :piattaforma, :handle, :url, :soggetto, :comune, :fascia, :categoria, :stato)
            ON CONFLICT(source_id, piattaforma) DO UPDATE SET
                handle=excluded.handle, url=excluded.url, soggetto=excluded.soggetto,
                comune=excluded.comune, fascia=excluded.fascia, categoria=excluded.categoria
            """,
            r,
        )
    conn.commit()
    print(f"Coda follow aggiornata in SQLite: {len(righe)} righe (nuove o aggiornate).")

    if args.publish:
        from src import sheets_client

        client = sheets_client.get_client(config)
        ws = client.open_by_key(config.spreadsheet_id_principale).worksheet("CodaFollow")
        intestazione = ["source_id", "piattaforma", "handle", "url", "soggetto", "comune", "fascia", "priorita", "stato", "tentativi", "data_follow", "note"]
        tutte = conn.execute("SELECT * FROM coda_follow ORDER BY fascia ASC, categoria ASC").fetchall()
        corpo = [
            [r["source_id"], r["piattaforma"], r["handle"], r["url"], r["soggetto"], r["comune"], r["fascia"], "", r["stato"], r["tentativi"], r["data_follow"] or "", r["note"] or ""]
            for r in tutte
        ]
        ws.clear()
        ws.update([intestazione] + corpo, value_input_option="USER_ENTERED")
        print(f"Foglio CodaFollow aggiornato: {len(corpo)} righe scritte.")


def cmd_prober(args: argparse.Namespace) -> None:
    """M8/12.8, discovery (04.2): trova la vera pagina eventi per ogni
    fonte già importata in sources, invece di restare fermi alla
    homepage. Isolamento totale per fonte (15.1 regola 4): un sito
    irraggiungibile non deve fermare il probing sulle altre."""
    from src.prober import prova_fonte

    conn = store.connect(DB_PATH)
    store.migrate(conn)

    righe = conn.execute("SELECT source_id, endpoint FROM sources WHERE endpoint IS NOT NULL").fetchall()
    if args.limite:
        righe = righe[: args.limite]

    trovate = 0
    con_feed = 0
    errori = 0
    for riga in righe:
        try:
            risultato = prova_fonte(riga["endpoint"])
        except Exception as exc:
            print(f"  {riga['source_id']:40} errore: {exc}")
            errori += 1
            continue

        nuovo_endpoint = risultato.endpoint_strutturato or risultato.pagina_eventi
        if risultato.fonte_scoperta != "nessuna":
            trovate += 1
        if risultato.tipo_endpoint:
            con_feed += 1
            print(f"  {riga['source_id']:40} {risultato.fonte_scoperta:10} feed={risultato.tipo_endpoint}: {nuovo_endpoint}")
        else:
            print(f"  {riga['source_id']:40} {risultato.fonte_scoperta:10} -> {nuovo_endpoint}")

        conn.execute("UPDATE sources SET endpoint=? WHERE source_id=?", (nuovo_endpoint, riga["source_id"]))
        conn.commit()

    print(f"\nProbing completato: {len(righe)} fonti, {trovate} con pagina eventi migliorata, {con_feed} con feed strutturato, {errori} errori.")


def cmd_import_fonti(args: argparse.Namespace) -> None:
    """M11/12.8 (parziale): import base delle fonti in sources, primo passo
    per un giro di ricerca eventi multi-fonte reale.

    L'elenco delle fonti è già disponibile (decisione D10, 12.8): non
    scoperta da zero, ma importato dagli stessi CSV già usati per la
    bonifica social (Comuni.csv: SitoIstituzionale, copertura 683/683 sul
    perimetro; ProLoco.csv: Sito, solo dove presente — la maggioranza delle
    Pro Loco vive solo su Facebook, che richiede feed_social.py di M10, non
    ancora costruito). Tutte importate con metodo T1_html (l'adattatore
    generico già collaudato): l'arricchimento verso T0 (feed strutturati,
    fingerprinting per famiglia) resta un passo successivo."""
    import csv

    conn = store.connect(DB_PATH)
    store.migrate(conn)

    cartella = Path(args.raw_dir)
    comuni_csv = cartella / "Comuni.csv"
    proloco_csv = cartella / "ProLoco.csv"
    for f in (comuni_csv, proloco_csv):
        if not f.exists():
            print(f"File non trovato: {f}")
            sys.exit(1)

    comuni_perimetro = {
        r["comune"].strip().lower() for r in conn.execute("SELECT comune FROM comuni WHERE attivo='si'").fetchall()
    }

    fonti = []
    with open(comuni_csv, encoding="utf-8-sig", newline="") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            nome = riga.get("Comune", "").strip()
            url = riga.get("SitoIstituzionale", "").strip()
            if nome.lower() in comuni_perimetro and url:
                fonti.append((f"comune-{nome.lower().replace(' ', '-')}", url))

    with open(proloco_csv, encoding="utf-8-sig", newline="") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            nome_comune = riga.get("Comune", "").strip()
            url = riga.get("Sito", "").strip()
            if nome_comune.lower() in comuni_perimetro and url:
                fonti.append((f"proloco-{nome_comune.lower().replace(' ', '-')}-sito", url))

    for source_id, endpoint in fonti:
        conn.execute(
            """
            INSERT INTO sources (source_id, endpoint, tier)
            VALUES (?, ?, 'T1_html')
            ON CONFLICT(source_id) DO UPDATE SET endpoint=excluded.endpoint, tier=excluded.tier
            """,
            (source_id, endpoint),
        )
    conn.commit()

    print(f"Fonti importate/aggiornate in sources: {len(fonti)} (tutte T1_html).")
    print("Lancia 'python run.py run' per il primo giro multi-fonte, oppure 'python run.py run --no-llm' per un test senza consumare quota LLM.")


def cmd_publish(args: argparse.Namespace) -> None:
    """Elabora lo stato eventi e pubblica i risultati su Google Sheets.

    'Elaborare lo stato' oggi significa archiviare gli eventi già conclusi
    (03.1.2, archivia_eventi_conclusi già scritta e testata ma mai chiamata
    da run.py) prima di scrivere il foglio Eventi, così l'export non
    contiene manifestazioni passate da giorni. Pubblica anche Quarantena,
    Serie, Fonti, Stato e Log (storico dei run.py run) nello stesso
    passaggio. Restano fuori (non un semplice collegamento meccanico, vedi
    STATO-PROGETTO.md): Newsletter (nessuno schema), Config/Tipologie
    (gestiti a mano su Sheets)."""
    from src import publisher, sheets_client
    from src.dedup import archivia_eventi_conclusi
    from src.stato_sistema import calcola_indicatori

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    archiviati = archivia_eventi_conclusi(conn, config.giorni_archiviazione)
    conn.commit()
    print(f"Eventi archiviati (conclusi da oltre {config.giorni_archiviazione} giorni): {archiviati}")

    client = sheets_client.get_client(config)

    spreadsheet_principale = client.open_by_key(config.spreadsheet_id_principale)

    righe_tutte = publisher.righe_da_sqlite(conn)

    ws_eventi = spreadsheet_principale.worksheet("Eventi")
    righe_eventi = publisher.righe_eventi_vista_principale(righe_tutte, config)
    publisher.pubblica_eventi(ws_eventi, righe_eventi)
    print(f"Foglio Eventi aggiornato: {len(righe_eventi)} righe scritte.")

    ws_eventi_estesi = spreadsheet_principale.worksheet("Eventi_estesi")
    righe_estesi = publisher.righe_eventi_estesi(righe_tutte, config)
    publisher.pubblica_eventi(ws_eventi_estesi, righe_estesi)
    print(f"Foglio Eventi_estesi aggiornato: {len(righe_estesi)} righe scritte.")

    ws_quarantena = spreadsheet_principale.worksheet("Quarantena")
    righe_quarantena = publisher.righe_quarantena_da_sqlite(conn)
    publisher.pubblica_quarantena(ws_quarantena, righe_quarantena)
    print(f"Foglio Quarantena aggiornato: {len(righe_quarantena)} righe scritte.")

    ws_archivio = spreadsheet_principale.worksheet("Archivio")
    righe_archivio = publisher.righe_archivio_da_sqlite(conn)
    publisher.pubblica_archivio(ws_archivio, righe_archivio)
    print(f"Foglio Archivio aggiornato: {len(righe_archivio)} righe scritte.")

    righe_mappa = publisher.righe_eventi_per_mappa(conn)
    n_mappa = publisher.scrivi_eventi_mappa_json(righe_mappa, DATA_DIR / "eventi_mappa.json")
    print(f"File eventi_mappa.json scritto: {n_mappa} eventi con coordinate.")
    # Copia in docs/ (16, T10): GitHub Pages serve index.html ed
    # eventi_mappa.json dallo stesso dominio, evitando il blocco CORS che
    # rendeva impossibile un fetch() diretto dal link di condivisione Drive.
    # Richiede comunque un 'git push' manuale per pubblicare l'aggiornamento.
    docs_dir = Path(__file__).resolve().parent / "docs"
    if docs_dir.exists():
        publisher.scrivi_eventi_mappa_json(righe_mappa, docs_dir / "eventi_mappa.json")
        print(f"File docs/eventi_mappa.json aggiornato (ricorda 'git push' per pubblicarlo su GitHub Pages).")

    ws_serie = spreadsheet_principale.worksheet("Serie")
    n_serie = publisher.pubblica_serie(ws_serie, conn)
    print(f"Foglio Serie aggiornato: {n_serie} righe scritte.")

    ws_fonti = client.open_by_key(config.spreadsheet_id_anagrafiche).worksheet("Fonti")
    n_fonti = publisher.pubblica_fonti(ws_fonti, conn)
    print(f"Foglio Fonti aggiornato: {n_fonti} righe scritte.")

    ws_da_verificare = spreadsheet_principale.worksheet("DaVerificare")
    n_da_verificare = publisher.pubblica_da_verificare(ws_da_verificare, conn)
    print(f"Foglio DaVerificare aggiornato: {n_da_verificare} righe scritte.")

    ws_copertura = spreadsheet_principale.worksheet("CoperturaComuni")
    n_copertura = publisher.pubblica_copertura_comuni(ws_copertura, conn)
    print(f"Foglio CoperturaComuni aggiornato: {n_copertura} righe scritte.")

    ws_altre_entita = spreadsheet_principale.worksheet("CoperturaAltreEntita")
    n_altre_entita = publisher.pubblica_copertura_altre_entita(ws_altre_entita, conn)
    print(f"Foglio CoperturaAltreEntita aggiornato: {n_altre_entita} righe scritte.")

    ws_stato = spreadsheet_principale.worksheet("Stato")
    indicatori = calcola_indicatori(conn, config.budget_llm_giornaliero)
    publisher.pubblica_stato(ws_stato, indicatori)
    print(f"Foglio Stato aggiornato: {len(indicatori)} indicatori scritti.")
    for i in indicatori:
        print(f"  [{i.semaforo:6}] {i.nome}: {i.valore}")

    ws_log = spreadsheet_principale.worksheet("Log")
    n_log = publisher.pubblica_log(ws_log, conn)
    print(f"Foglio Log aggiornato: {n_log} run registrati.")


def cmd_pull_fonti(args: argparse.Namespace) -> None:
    """Rilegge dai fogli Sheets verso SQLite le poche colonne che
    l'operatore compila a mano invece di editare SQLite direttamente:
    `categoria`/`polling_diretto` dal foglio Fonti (richiesto dall'utente
    2026-08-28) e `comune`/`stato` dal foglio DaVerificare (2026-08-29,
    stesso principio: l'operatore apre un profilo sconosciuto, capisce
    di chi è, scrive qui invece che in SQLite). Unico verso Sheets ->
    SQLite di tutto il sistema: run.py publish resta l'unico verso
    opposto per tutto il resto."""
    from src import publisher, sheets_client

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    client = sheets_client.get_client(config)
    ws_fonti = client.open_by_key(config.spreadsheet_id_anagrafiche).worksheet("Fonti")
    esito = publisher.pull_fonti(ws_fonti, conn)
    print(f"Fonti aggiornate da Sheets: {esito['aggiornate']}")
    if esito["ignorate"]:
        print(f"Righe ignorate (source_id non trovato in SQLite): {esito['ignorate']}")

    spreadsheet_principale = client.open_by_key(config.spreadsheet_id_principale)
    ws_da_verificare = spreadsheet_principale.worksheet("DaVerificare")
    esito_dv = publisher.pull_da_verificare(ws_da_verificare, conn)
    print(f"DaVerificare aggiornate da Sheets: {esito_dv['aggiornate']}")
    if esito_dv["ignorate"]:
        print(f"Righe ignorate (source_id non trovato in coda_follow): {esito_dv['ignorate']}")

    # 2026-09-01, richiesto dall'utente: colonna 'azione' del foglio
    # Quarantena (03.1.2), applicata qui — stesso verso Sheets -> SQLite
    # delle altre righe di questo comando, prima del prossimo 'publish'.
    ws_quarantena = spreadsheet_principale.worksheet("Quarantena")
    azioni = publisher.pull_azioni_quarantena(ws_quarantena)
    if azioni:
        esito_azioni = publisher.applica_azioni_quarantena(conn, azioni)
        print(
            f"Azioni Quarantena applicate: {esito_azioni['promossi']} promossi, "
            f"{esito_azioni['scartati']} scartati, {esito_azioni['eliminati']} eliminati, "
            f"{esito_azioni['fonti_escluse']} fonti escluse."
        )


def cmd_run_and_publish(args: argparse.Namespace) -> None:
    """Comando composito richiesto dall'utente (2026-08-27, esteso
    2026-08-28 per il social, esteso 2026-08-29 per il follow) per il
    menu interattivo: un solo lancio per un giro completo — follow
    Facebook, follow Instagram, siti, feed Facebook e Instagram, poi
    pubblica.

    Il follow gira sempre per primo (richiesto dall'utente): fa avanzare
    la coda_follow ad ogni lancio, invece di restare un passo separato
    che l'operatore deve ricordarsi di lanciare a parte. Conseguenza
    accettata esplicitamente (14.5b: mai follow e lettura feed nella
    stessa sessione, serve un'ora di separazione): il feed social di
    QUESTO giro risulterà quasi sempre "saltato per troppa vicinanza al
    follow" — non un errore, viene letto al giro successivo. Ogni stadio
    è isolato (15.1 regola 4): un follow bloccato dal circuito di
    sicurezza o fallito non deve impedire siti/feed/pubblicazione."""
    from src import feed_social, follow

    conn = store.connect(DB_PATH)
    store.migrate(conn)
    config = load_config()
    for platform in ("facebook", "instagram"):
        try:
            esiti = follow.follow_batch(conn, config, platform, n=None, dry_run=False)
            seguiti = sum(1 for e in esiti if e.esito == "seguito")
            print(f"Follow {platform}: {seguiti}/{len(esiti)} seguiti con successo." if esiti else f"Follow {platform}: nessun candidato in coda_follow con stato 'da_seguire'.")
        except follow.CircuitoApertoError as exc:
            print(f"Follow {platform} interrotto dal circuito di sicurezza: {exc}")
        except Exception as exc:
            print(f"Follow {platform} fallito, proseguo con il resto del giro: {exc}")

    cmd_run(args)

    for platform in ("facebook", "instagram"):
        try:
            _esegui_feed_social(platform, args.no_llm, config, conn)
        except feed_social.SessioneTroppoVicinaAlFollowError as exc:
            print(f"Feed {platform} saltato: {exc}")
        except Exception as exc:
            print(f"Feed {platform} fallito, proseguo con il resto del giro: {exc}")

    cmd_publish(args)


def cmd_fingerprint_comuni(args: argparse.Namespace) -> None:
    """M8, 12.5: fingerprinting batch dei siti comunali nel perimetro.

    Legge SitoIstituzionale da Comuni.csv (già raccolto e verificato per
    tutti i 992 comuni, non un pattern URL indovinato), filtra sui comuni
    attivi nel perimetro (comuni.attivo='si'), fa una richiesta HTTP per
    ciascuno e classifica per famiglia CMS. Salva tutto in
    fingerprint_comuni, poi stampa la distribuzione per famiglia."""
    import csv
    from datetime import datetime

    from src.fingerprint import fingerprint_batch

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    comuni_csv = Path(args.raw_dir) / "Comuni.csv"
    if not comuni_csv.exists():
        print(f"File non trovato: {comuni_csv}")
        sys.exit(1)

    comuni_perimetro = {
        r["comune"].strip().lower(): r["istat"]
        for r in conn.execute("SELECT istat, comune FROM comuni WHERE attivo='si'").fetchall()
    }

    da_fingerprintare = []
    with open(comuni_csv, encoding="utf-8-sig", newline="") as f:
        for riga in csv.DictReader(f, delimiter=";"):
            nome = riga.get("Comune", "").strip()
            istat = comuni_perimetro.get(nome.lower())
            url = riga.get("SitoIstituzionale", "").strip()
            if istat and url:
                da_fingerprintare.append({"istat": istat, "comune": nome, "url": url})

    print(f"Comuni con URL nel perimetro: {len(da_fingerprintare)}/{len(comuni_perimetro)}")

    if args.limite:
        da_fingerprintare = da_fingerprintare[: args.limite]
        print(f"Limitato a {len(da_fingerprintare)} per --limite")

    risultati = fingerprint_batch(da_fingerprintare, pausa_secondi=args.pausa)

    ora = datetime.now().isoformat()
    for r in risultati:
        conn.execute(
            """
            INSERT INTO fingerprint_comuni (istat, comune, url, piattaforma, indizi, http_status, errore, fingerprinted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(istat) DO UPDATE SET
                url=excluded.url, piattaforma=excluded.piattaforma, indizi=excluded.indizi,
                http_status=excluded.http_status, errore=excluded.errore, fingerprinted_at=excluded.fingerprinted_at
            """,
            (r.istat, r.comune, r.url, r.piattaforma, "; ".join(r.indizi), r.http_status, r.errore, ora),
        )
    conn.commit()

    conteggio: dict[str, int] = {}
    errori = 0
    for r in risultati:
        if r.errore:
            errori += 1
        else:
            conteggio[r.piattaforma or "sconosciuta"] = conteggio.get(r.piattaforma or "sconosciuta", 0) + 1

    print(f"\nFingerprint completato: {len(risultati)} comuni, {errori} errori/irraggiungibili.")
    for piattaforma, n in sorted(conteggio.items(), key=lambda kv: -kv[1]):
        percentuale = 100 * n / len(risultati) if risultati else 0
        print(f"  {piattaforma:20} {n:4}  ({percentuale:.1f}%)")


def cmd_promuovi_jsonld(args: argparse.Namespace) -> None:
    """L3 (17-lavoro-residuo.md, 2026-09-01): promuove a T0_jsonld le
    fonti T1_html che espongono davvero JSON-LD schema.org/Event —
    verificato con una richiesta reale (fingerprint.verifica_jsonld_batch),
    non un pattern URL indovinato. Riusabile: nuove fonti comunali con lo
    stesso template (trovato: ComWeb/ePublic, URL
    /it-it/vivere-il-comune/eventi) possono essere ripromosse allo stesso
    modo in futuro, senza duplicare questo giro a mano."""
    from src.fingerprint import verifica_jsonld_batch

    conn = store.connect(DB_PATH)
    store.migrate(conn)

    query = "SELECT source_id, endpoint FROM sources WHERE tier = 'T1_html' AND endpoint IS NOT NULL"
    if args.filtro_url:
        query += " AND endpoint LIKE ?"
        fonti = conn.execute(query, (f"%{args.filtro_url}%",)).fetchall()
    else:
        fonti = conn.execute(query).fetchall()

    fonti = [dict(r) for r in fonti]
    if args.limite:
        fonti = fonti[: args.limite]
    print(f"Verifica JSON-LD su {len(fonti)} fonti T1_html...")

    risultati = verifica_jsonld_batch(fonti, pausa_secondi=args.pausa)

    promosse = 0
    errori = 0
    for r in risultati:
        if r.errore:
            errori += 1
            continue
        if r.ha_jsonld:
            conn.execute("UPDATE sources SET tier = 'T0_jsonld' WHERE source_id = ?", (r.source_id,))
            promosse += 1
    conn.commit()

    print(f"Promosse a T0_jsonld: {promosse}/{len(fonti)} (errori/irraggiungibili: {errori}).")


def cmd_promuovi_pa_design_system(args: argparse.Namespace) -> None:
    """L3 (17-lavoro-residuo.md, 2026-09-01): promuove a T0_pa_design_system
    le fonti T1_html con endpoint '.../Eventi' che espongono davvero il
    markup `.card-wrapper` del template legacy AGID — verificato con una
    richiesta reale, non un pattern URL preso per buono. Distinto da
    promuovi-jsonld: qui non c'è JSON-LD, il selettore è CSS/XPath dedicato
    (adapters/pa_design_system.py)."""
    from src.fingerprint import verifica_pa_design_system_batch

    conn = store.connect(DB_PATH)
    store.migrate(conn)

    fonti = conn.execute(
        "SELECT source_id, endpoint FROM sources WHERE tier = 'T1_html' AND endpoint LIKE '%/Eventi'"
    ).fetchall()
    fonti = [dict(r) for r in fonti]
    if args.limite:
        fonti = fonti[: args.limite]
    print(f"Verifica markup pa_design_system su {len(fonti)} fonti T1_html...")

    # Una fonte alla volta con commit incrementale (2026-09-01, batch di
    # 330 fonti reali osservato bloccarsi per un tempo anomalo — probabile
    # sito con connessione che ignora il timeout httpx dichiarato):
    # progresso visibile riga per riga e nessun lavoro perso se va
    # interrotto a metà (15.1 regola 4, isolamento anche del progresso).
    promosse = 0
    errori = 0
    for i, fonte in enumerate(fonti, start=1):
        risultato = verifica_pa_design_system_batch([fonte], pausa_secondi=0)[0]
        if risultato.errore:
            errori += 1
            esito = f"errore: {risultato.errore[:60]}"
        elif risultato.ha_markup:
            conn.execute(
                "UPDATE sources SET tier = 'T0_pa_design_system' WHERE source_id = ?", (fonte["source_id"],)
            )
            conn.commit()
            promosse += 1
            esito = "promossa"
        else:
            esito = "markup assente"
        print(f"[{i}/{len(fonti)}] {fonte['source_id']:35} {esito}")
        if args.pausa:
            import time

            time.sleep(args.pausa)

    print(f"Promosse a T0_pa_design_system: {promosse}/{len(fonti)} (errori/irraggiungibili: {errori}).")


def cmd_backup_sheets(args: argparse.Namespace) -> None:
    """17.2.2 (17-lavoro-residuo.md, 2026-09-01): mitiga il rischio "foglio
    corrotto da un bug di publish" (11.1), esplicitamente accettato in
    documentazione ma mai mitigato in codice. Copia lo spreadsheet
    principale in una cartella Drive dedicata, nome con la data — nessuna
    cancellazione automatica delle copie vecchie (deciso con l'utente:
    l'operatore ripulisce a mano quando vuole)."""
    from src import sheets_client
    from src.drive_backup import backup_spreadsheet

    config = load_config()
    client = sheets_client.get_client(config)

    backup_id = backup_spreadsheet(client, config.spreadsheet_id_principale)
    print(f"Backup creato: https://docs.google.com/spreadsheets/d/{backup_id}")


def cmd_follow(args: argparse.Namespace) -> None:
    from src import follow

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    try:
        esiti = follow.follow_batch(conn, config, args.platform, n=args.n, dry_run=args.dry_run)
    except follow.CircuitoApertoError as exc:
        print(f"Impossibile procedere: {exc}")
        sys.exit(1)

    if not esiti:
        print("Nessun candidato in coda_follow con stato 'da_seguire'.")
        return

    for e in esiti:
        print(f"  {e.source_id:40} {e.esito:12} {e.dettaglio}")

    if args.dry_run:
        print(f"\n--dry-run: {len(esiti)} candidati elencati, nessuna azione eseguita.")
    else:
        bloccati = [e for e in esiti if e.esito == "bloccato_da_circuito"]
        if bloccati:
            print(f"\nATTENZIONE: interrotto da un segnale di blocco: {bloccati[0].dettaglio}")
            print("Il circuito di sicurezza è ora aperto per questa piattaforma: nessun follow ripartirà finché non si richiude da solo.")
        seguiti = sum(1 for e in esiti if e.esito == "seguito")
        print(f"\nLotto completato: {seguiti}/{len(esiti)} seguiti con successo.")


def cmd_login(args: argparse.Namespace) -> None:
    from src import follow

    print(f"Apertura del browser per il login {args.platform}...")
    follow.login_manuale(args.platform)
    print("Sessione salvata. I prossimi 'run.py follow' non richiederanno più il login.")


def cmd_sync_seguiti(args: argparse.Namespace) -> None:
    from src import sync_seguiti
    from src.follow import _apri_sessione_browser, _assicura_identita_pagina, _chiudi_sessione_browser

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    print(f"Lettura della lista 'seguiti' reale su {args.platform} (sola lettura, nessuna azione)...")
    handle = sync_seguiti.leggi_seguiti_reali(args.platform, config)
    print(f"Trovati {len(handle)} profili seguiti.")

    # Richiesto dall'utente 2026-08-29: apre i profili non censiti e legge
    # nome pagina + comune dall'indirizzo, invece di lasciare all'operatore
    # aprire ogni link a mano. Solo Facebook (unica piattaforma dove il
    # pattern è stato verificato dal vivo, 15.1) e solo se ci sono handle
    # davvero nuovi da verificare — una seconda sessione browser breve,
    # separata da quella di lettura sopra (già chiusa a quel punto).
    verifica_profilo = None
    contesto_verifica = None
    if args.platform == "facebook":
        esistenti = {
            r["handle"].lower()
            for r in conn.execute(
                "SELECT handle FROM coda_follow WHERE piattaforma='facebook'"
            ).fetchall()
            if r["handle"]
        }
        nuovi_da_verificare = {h.strip().lower().lstrip("@") for h in handle if h.strip()} - esistenti
        if nuovi_da_verificare:
            print(f"Verifica automatica di {len(nuovi_da_verificare)} profili non censiti...")
            contesto_verifica = _apri_sessione_browser("facebook", None)
            _assicura_identita_pagina(contesto_verifica, config)
            verifica_profilo = lambda url: sync_seguiti.verifica_profilo_facebook(contesto_verifica, url)

    try:
        esito = sync_seguiti.confronta_e_aggiorna(conn, args.platform, handle, verifica_profilo=verifica_profilo)
    finally:
        if contesto_verifica is not None:
            _chiudi_sessione_browser(contesto_verifica)

    print(f"Aggiornati a 'seguito': {esito.aggiornati}")
    print(f"Nuovi (non censiti, messi in quarantena da verificare): {esito.nuovi}")
    if esito.nuovi:
        print("Controlla il foglio/coda_follow per assegnare il comune corretto ai nuovi profili prima che diventino fonti attive.")


def _esegui_feed_social(platform: str, no_llm: bool, config, conn) -> dict[str, int]:
    """Logica core di M10, riusabile sia dal comando isolato 'feed-social'
    sia dal giro composito 'run-publish' (2026-08-28, richiesto dall'utente:
    il giro completo deve includere anche il social, non solo i siti). Non
    fa mai sys.exit: solleva SessioneTroppoVicinaAlFollowError se 14.5b
    blocca la lettura, così il chiamante decide se è fatale (comando
    isolato) o solo da saltare (dentro un giro più ampio)."""
    from src import feed_social
    from src.extractor.client import EstrazioneSospesaPerQuota

    extractor = None if no_llm else _crea_extractor_se_configurato(config, conn)
    post = feed_social.leggi_feed_reale(platform, config, conn)

    print(f"Post nuovi letti dal feed {platform}: {len(post)}")
    conteggio: dict[str, int] = {}
    for p in post:
        try:
            esito = feed_social.elabora_post(p, conn, config, extractor)
        except EstrazioneSospesaPerQuota as exc:
            # 08.5: non un errore, solo un rinvio deciso dalla degradazione
            # progressiva della quota — l'artefatto resta comunque salvato
            # (elabora_post lo registra prima di chiamare l'estrattore),
            # ripreso al prossimo giro.
            esito = "quota_sospesa"
            print(f"  {p.handle_autore:30} {'quota_sospesa':28} {exc}")
            conteggio[esito] = conteggio.get(esito, 0) + 1
            continue
        except Exception as exc:
            # Isolamento totale (15.1 regola 4), come in run.py run: un
            # errore del provider LLM (es. 503 momentaneo) o un bug
            # imprevisto su un singolo post non deve far perdere la lettura
            # degli altri post già scaricati dal feed (bug reale, 2026-08-27
            # — un 503 di Gemini ha fermato l'intero comando a metà lista).
            esito = "errore"
            print(f"  {p.handle_autore:30} {'errore':28} {exc}")
            conteggio[esito] = conteggio.get(esito, 0) + 1
            continue
        conteggio[esito] = conteggio.get(esito, 0) + 1
        print(f"  {p.handle_autore:30} {esito:28} {p.url}")
    return conteggio


def cmd_feed_social(args: argparse.Namespace) -> None:
    """M10: lettura passiva del feed cronologico (14.5b), attribuzione
    handle->comune (12.3) ed estrazione LLM, riusando la pipeline
    esistente. Rispetta la separazione minima di un'ora dal follow
    (14.5b) e la stessa verifica di identità già scritta per il follow."""
    from src import feed_social

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    try:
        conteggio = _esegui_feed_social(args.platform, args.no_llm, config, conn)
    except feed_social.SessioneTroppoVicinaAlFollowError as exc:
        print(f"Impossibile procedere: {exc}")
        sys.exit(1)

    if conteggio:
        print("\nRiepilogo:")
        for esito, n in sorted(conteggio.items(), key=lambda kv: -kv[1]):
            print(f"  {esito:28} {n}")


def cmd_doctor(args: argparse.Namespace) -> None:
    config = load_config()
    problemi = []
    if not DB_PATH.exists():
        problemi.append(f"Database non trovato in {DB_PATH}. Esegui 'run.py init'.")
    if not Path(config.google_oauth_client_json).exists():
        problemi.append(f"File credenziali OAuth non trovato: {config.google_oauth_client_json}")
    if not config.spreadsheet_id_principale:
        problemi.append("GOOGLE_SPREADSHEET_ID_PRINCIPALE non impostato in config/.env.")

    if problemi:
        print("Problemi rilevati:")
        for p in problemi:
            print(f"  - {p}")
        sys.exit(1)
    print("OK: configurazione e database presenti.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregatore Eventi Locali")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_init = sub.add_parser("init", help="Crea fogli Google e database SQLite")
    p_init.add_argument("--skip-sheets", action="store_true", help="Crea solo il database locale")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="Diagnostica configurazione e stato")
    p_doctor.set_defaults(func=cmd_doctor)

    p_perimetro = sub.add_parser("import-perimetro", help="Importa il file Perimetro (M1)")
    p_perimetro.add_argument("--file", default="../Perimetro.txt", help="Percorso del CSV Perimetro (';' separato)")
    p_perimetro.add_argument("--publish", action="store_true", help="Scrive anche il foglio Perimetro su Google Sheets")
    p_perimetro.set_defaults(func=cmd_import_perimetro)

    p_run = sub.add_parser("run", help="Esegue la raccolta sulle fonti T0/T1 note (M2, parziale)")
    p_run.add_argument("--fonte", help="source_id per un test puntuale, invece di leggere da SQLite")
    p_run.add_argument("--endpoint", help="URL della fonte, con --fonte")
    p_run.add_argument(
        "--metodo",
        choices=["T0_ical", "T0_jsonld", "T0_rss", "T0_email", "T0_telegram", "T1_html", "T0_aggregatore_playwright"],
        help="Adattatore da usare, con --fonte",
    )
    p_run.add_argument("--comune", help="Comune di riferimento della fonte, con --fonte")
    p_run.add_argument("--no-llm", action="store_true", help="Disabilita l'estrazione LLM: i T1 si fermano al pre-filtro")
    p_run.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti processate dal giro multi-fonte (0 = tutte)")
    p_run.add_argument(
        "--solo-errori",
        action="store_true",
        help="Riciclo mirato: rilancia solo le fonti con un errore pendente dall'ultimo giro (consecutive_errors > 0)",
    )
    p_run.add_argument(
        "--no-priorita",
        action="store_true",
        help="Disabilita l'ordinamento per priorità dinamica (08.3): processa le fonti nell'ordine restituito da SQLite",
    )
    p_run.add_argument(
        "--paralleli",
        type=int,
        default=None,
        help="Numero di fonti elaborate in parallelo (default: Config.run_paralleli). Ignorato con --no-llm (sempre 1)",
    )
    p_run.set_defaults(func=cmd_run)

    p_run_publish = sub.add_parser(
        "run-publish", help="Esegue il giro multi-fonte e poi pubblica su Google Sheets in un solo comando"
    )
    p_run_publish.add_argument("--fonte", help="source_id per un test puntuale, invece di leggere da SQLite")
    p_run_publish.add_argument("--endpoint", help="URL della fonte, con --fonte")
    p_run_publish.add_argument(
        "--metodo",
        choices=["T0_ical", "T0_jsonld", "T0_rss", "T0_email", "T0_telegram", "T1_html", "T0_aggregatore_playwright"],
        help="Adattatore da usare, con --fonte",
    )
    p_run_publish.add_argument("--comune", help="Comune di riferimento della fonte, con --fonte")
    p_run_publish.add_argument("--no-llm", action="store_true", help="Disabilita l'estrazione LLM: i T1 si fermano al pre-filtro")
    p_run_publish.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti processate (0 = tutte)")
    p_run_publish.add_argument("--solo-errori", action="store_true", help="Riciclo mirato sulle fonti con errore pendente")
    p_run_publish.add_argument("--no-priorita", action="store_true", help="Disabilita l'ordinamento per priorità dinamica")
    p_run_publish.add_argument("--paralleli", type=int, default=None, help="Numero di fonti elaborate in parallelo")
    p_run_publish.set_defaults(func=cmd_run_and_publish)

    p_coda = sub.add_parser("populate-coda-follow", help="Bonifica ed importa le fonti social nella CodaFollow (M9)")
    p_coda.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv, ProLoco.csv, Social.csv")
    p_coda.add_argument("--publish", action="store_true", help="Scrive anche il foglio CodaFollow su Google Sheets")
    p_coda.set_defaults(func=cmd_populate_coda_follow)

    p_prober = sub.add_parser("prober", help="Discovery della vera pagina eventi/feed per le fonti già importate (04.2, 12.8)")
    p_prober.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti (0 = tutte)")
    p_prober.set_defaults(func=cmd_prober)

    p_imp = sub.add_parser("import-fonti", help="Import base di Comuni/ProLoco in sources per un giro di ricerca eventi (12.8)")
    p_imp.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv, ProLoco.csv")
    p_imp.set_defaults(func=cmd_import_fonti)

    p_fp = sub.add_parser("fingerprint-comuni", help="Fingerprinting batch dei siti comunali per famiglia CMS (M8, 12.5)")
    p_fp.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv (colonna SitoIstituzionale)")
    p_fp.add_argument("--limite", type=int, default=0, help="Limita il numero di comuni (0 = tutti, utile per un primo test)")
    p_fp.add_argument("--pausa", type=float, default=0.2, help="Pausa in secondi tra una richiesta e l'altra")
    p_fp.set_defaults(func=cmd_fingerprint_comuni)

    p_pj = sub.add_parser(
        "promuovi-jsonld",
        help="L3: verifica e promuove a T0_jsonld le fonti T1_html che espongono già schema.org/Event",
    )
    p_pj.add_argument(
        "--filtro-url", default="", help="Solo fonti con questo testo nell'endpoint (es. 'vivere-il-comune/eventi')"
    )
    p_pj.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti verificate (0 = tutte)")
    p_pj.add_argument("--pausa", type=float, default=0.2, help="Pausa in secondi tra una richiesta e l'altra")
    p_pj.set_defaults(func=cmd_promuovi_jsonld)

    p_ppds = sub.add_parser(
        "promuovi-pa-design-system",
        help="L3: verifica e promuove a T0_pa_design_system le fonti /Eventi con markup .card-wrapper",
    )
    p_ppds.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti verificate (0 = tutte)")
    p_ppds.add_argument("--pausa", type=float, default=0.2, help="Pausa in secondi tra una richiesta e l'altra")
    p_ppds.set_defaults(func=cmd_promuovi_pa_design_system)

    p_backup = sub.add_parser(
        "backup-sheets", help="Copia lo spreadsheet principale in una cartella Drive dedicata (17.2.2, mitiga 11.1)"
    )
    p_backup.set_defaults(func=cmd_backup_sheets)

    p_login = sub.add_parser("login", help="Apre il browser per il login manuale una tantum (M9, 14.3)")
    p_login.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_login.set_defaults(func=cmd_login)

    p_sync = sub.add_parser("sync-seguiti", help="Legge la lista 'seguiti' reale e aggiorna coda_follow (M9, sola lettura)")
    p_sync.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_sync.set_defaults(func=cmd_sync_seguiti)

    p_feed = sub.add_parser("feed-social", help="Lettura cronologica del feed, attribuzione ed estrazione eventi (M10, sola lettura)")
    p_feed.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_feed.add_argument("--no-llm", action="store_true", help="Disabilita l'estrazione LLM: elenca solo i post letti")
    p_feed.set_defaults(func=cmd_feed_social)

    p_follow = sub.add_parser("follow", help="Lotto di follow social (M9)")
    p_follow.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_follow.add_argument("--n", type=int, default=None, help="Quanti follow in questo lotto (default: follow_per_lotto)")
    p_follow.add_argument("--dry-run", action="store_true", help="Elenca cosa farebbe, senza eseguire alcuna azione")
    p_follow.set_defaults(func=cmd_follow)

    p_publish = sub.add_parser(
        "publish", help="Elabora lo stato eventi (archiviazione) e pubblica Eventi/Fonti su Google Sheets"
    )
    p_publish.set_defaults(func=cmd_publish)

    p_pull_fonti = sub.add_parser(
        "pull-fonti",
        help="Rilegge da Sheets verso SQLite: categoria/polling_diretto (Fonti), comune/stato (DaVerificare), azione (Quarantena)",
    )
    p_pull_fonti.set_defaults(func=cmd_pull_fonti)

    # Sottocomandi previsti dalla guida (15.1), da implementare nelle tappe successive.
    for nome, aiuto in [
        ("discover", "Discovery e fingerprinting delle fonti (M8)"),
        ("reprocess", "Riestrae dal grezzo, senza rete (M5)"),
    ]:
        p = sub.add_parser(nome, help=aiuto)
        p.set_defaults(func=lambda args, nome=nome: print(f"'{nome}' non ancora implementato (vedi STATO-PROGETTO.md)"))

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
