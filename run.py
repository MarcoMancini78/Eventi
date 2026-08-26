#!/usr/bin/env python3
"""Unico punto d'ingresso del sistema (15.1). Sottocomandi come da guida M0-M11."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import DB_PATH, load_config
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

    fonti = conn.execute("SELECT source_id, endpoint, tier FROM sources").fetchall()
    if not fonti:
        print("Nessuna fonte in SQLite. Popola il foglio Fonti e sincronizzalo, oppure usa --fonte per un test puntuale.")

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

    for riga in fonti:
        fonte = {"source_id": riga["source_id"], "endpoint": riga["endpoint"], "metodo": riga["tier"], "comune_riferimento": None}
        riepilogo = pipeline.esegui_fonte(fonte, conn, config, extractor)
        print(riepilogo)


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

    config = load_config()
    conn = store.connect(DB_PATH)
    store.migrate(conn)

    print(f"Lettura della lista 'seguiti' reale su {args.platform} (sola lettura, nessuna azione)...")
    handle = sync_seguiti.leggi_seguiti_reali(args.platform, config)
    print(f"Trovati {len(handle)} profili seguiti.")

    esito = sync_seguiti.confronta_e_aggiorna(conn, args.platform, handle)
    print(f"Aggiornati a 'seguito': {esito.aggiornati}")
    print(f"Nuovi (non censiti, messi in quarantena da verificare): {esito.nuovi}")
    if esito.nuovi:
        print("Controlla il foglio/coda_follow per assegnare il comune corretto ai nuovi profili prima che diventino fonti attive.")


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
        choices=["T0_ical", "T0_jsonld", "T0_rss", "T0_email", "T0_telegram", "T1_html"],
        help="Adattatore da usare, con --fonte",
    )
    p_run.add_argument("--comune", help="Comune di riferimento della fonte, con --fonte")
    p_run.add_argument("--no-llm", action="store_true", help="Disabilita l'estrazione LLM: i T1 si fermano al pre-filtro")
    p_run.add_argument("--limite", type=int, default=0, help="Limita il numero di fonti processate dal giro multi-fonte (0 = tutte)")
    p_run.set_defaults(func=cmd_run)

    p_coda = sub.add_parser("populate-coda-follow", help="Bonifica ed importa le fonti social nella CodaFollow (M9)")
    p_coda.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv, ProLoco.csv, Social.csv")
    p_coda.add_argument("--publish", action="store_true", help="Scrive anche il foglio CodaFollow su Google Sheets")
    p_coda.set_defaults(func=cmd_populate_coda_follow)

    p_imp = sub.add_parser("import-fonti", help="Import base di Comuni/ProLoco in sources per un giro di ricerca eventi (12.8)")
    p_imp.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv, ProLoco.csv")
    p_imp.set_defaults(func=cmd_import_fonti)

    p_fp = sub.add_parser("fingerprint-comuni", help="Fingerprinting batch dei siti comunali per famiglia CMS (M8, 12.5)")
    p_fp.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv (colonna SitoIstituzionale)")
    p_fp.add_argument("--limite", type=int, default=0, help="Limita il numero di comuni (0 = tutti, utile per un primo test)")
    p_fp.add_argument("--pausa", type=float, default=0.2, help="Pausa in secondi tra una richiesta e l'altra")
    p_fp.set_defaults(func=cmd_fingerprint_comuni)

    p_login = sub.add_parser("login", help="Apre il browser per il login manuale una tantum (M9, 14.3)")
    p_login.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_login.set_defaults(func=cmd_login)

    p_sync = sub.add_parser("sync-seguiti", help="Legge la lista 'seguiti' reale e aggiorna coda_follow (M9, sola lettura)")
    p_sync.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_sync.set_defaults(func=cmd_sync_seguiti)

    p_follow = sub.add_parser("follow", help="Lotto di follow social (M9)")
    p_follow.add_argument("--platform", required=True, choices=["facebook", "instagram"])
    p_follow.add_argument("--n", type=int, default=None, help="Quanti follow in questo lotto (default: follow_per_lotto)")
    p_follow.add_argument("--dry-run", action="store_true", help="Elenca cosa farebbe, senza eseguire alcuna azione")
    p_follow.set_defaults(func=cmd_follow)

    # Sottocomandi previsti dalla guida (15.1), da implementare nelle tappe successive.
    for nome, aiuto in [
        ("discover", "Discovery e fingerprinting delle fonti (M8)"),
        ("publish", "Solo pubblicazione su Sheets"),
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
