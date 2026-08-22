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
    p_perimetro.set_defaults(func=cmd_import_perimetro)

    # Sottocomandi previsti dalla guida (15.1), da implementare nelle tappe successive.
    for nome, aiuto in [
        ("discover", "Discovery e fingerprinting delle fonti (M8)"),
        ("follow", "Lotto di follow social (M9)"),
        ("run", "Esegue una pipeline di raccolta (M2+)"),
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
