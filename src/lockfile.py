"""Lock file per evitare run sovrapposti (M11, 15.1 regola 4 estesa
all'orchestrazione: due `run.py run` in parallelo raddoppierebbero le
chiamate LLM e rischierebbero scritture concorrenti su SQLite).

Un lock stantio (processo del PID salvato non più in esecuzione, es. dopo
un crash o un riavvio) non deve bloccare per sempre i run successivi: si
rileva e si rimuove da solo.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psutil


class RunGiaInCorsoError(Exception):
    pass


def _processo_vivo(pid: int) -> bool:
    """os.kill(pid, 0) non è affidabile su Windows per verificare un PID
    esterno: solleva SystemError anche quando il processo esiste (bug reale
    trovato in collaudo, 2026-08-27) — psutil interroga l'elenco processi
    del sistema operativo direttamente, portabile e corretto."""
    return psutil.pid_exists(pid)


@contextmanager
def lock_run(lock_path: Path):
    """Solleva RunGiaInCorsoError se un altro run con lock attivo è già in
    esecuzione. Rimuove da solo un lock stantio (processo non più vivo)."""
    if lock_path.exists():
        pid_salvato = None
        try:
            pid_salvato = int(lock_path.read_text().strip())
        except (ValueError, OSError):
            pass

        if pid_salvato is not None and _processo_vivo(pid_salvato):
            raise RunGiaInCorsoError(
                f"Un altro run è già in corso (PID {pid_salvato}, lock {lock_path}). "
                "Attendi che finisca o, se sei certo che sia terminato in modo anomalo, rimuovi il file di lock."
            )
        lock_path.unlink(missing_ok=True)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
