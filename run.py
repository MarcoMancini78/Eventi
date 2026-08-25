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
    p_run.set_defaults(func=cmd_run)

    p_coda = sub.add_parser("populate-coda-follow", help="Bonifica ed importa le fonti social nella CodaFollow (M9)")
    p_coda.add_argument("--raw-dir", default="data/raw_import", help="Cartella con Comuni.csv, ProLoco.csv, Social.csv")
    p_coda.add_argument("--publish", action="store_true", help="Scrive anche il foglio CodaFollow su Google Sheets")
    p_coda.set_defaults(func=cmd_populate_coda_follow)

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
