"""Pulizia dei file locali accumulati in data/ che nessun modulo ripulisce da solo.

Nato dopo aver trovato ~260 MB di backup manuali di eventi.db e file di
debug/scratch mai rimossi (2026-09-11): il progetto non aveva alcuna
procedura di pulizia, né automatica né a comando. Rimuove solo classi di
file riconoscibili per pattern esplicito, mai un elenco arbitrario di
estensioni: meglio lasciare un file dubbio che cancellare qualcosa di
utile per errore.
"""
from __future__ import annotations

import time
from pathlib import Path

# Pattern riconosciuti, ciascuno con la propria giustificazione:
# - eventi.db.bak-*: backup manuali presi prima di una modifica rischiosa,
#   mai automatizzati né mai ripuliti dopo l'uso.
# - scratch_*: file di debug temporanei creati durante una sessione di
#   investigazione (screenshot, dump HTML), utili solo mentre si caccia
#   un bug specifico.
_PATTERN_BACKUP_DB = "eventi.db.bak-*"
_PATTERN_SCRATCH = "scratch_*"


def trova_file_da_pulire(data_dir: Path, giorni_minimi: int = 7) -> list[Path]:
    """File candidati alla rimozione: backup DB e scratch più vecchi di N giorni.

    `giorni_minimi` protegge un backup o uno scratch appena creato (es. durante
    una sessione di debug ancora in corso) da una pulizia troppo aggressiva.
    """
    soglia = time.time() - giorni_minimi * 86400
    candidati: list[Path] = []
    for pattern in (_PATTERN_BACKUP_DB, _PATTERN_SCRATCH):
        for path in data_dir.glob(pattern):
            if path.is_file() and path.stat().st_mtime < soglia:
                candidati.append(path)
    return sorted(candidati)


def pulisci(data_dir: Path, giorni_minimi: int = 7, dry_run: bool = True) -> list[Path]:
    """Rimuove i file candidati (o li elenca soltanto, se dry_run=True).

    Ritorna sempre l'elenco dei file (rimossi o solo trovati), mai solo un
    conteggio: chi chiama deve poter mostrare esattamente cosa è successo.
    """
    candidati = trova_file_da_pulire(data_dir, giorni_minimi)
    if not dry_run:
        for path in candidati:
            path.unlink(missing_ok=True)
    return candidati
