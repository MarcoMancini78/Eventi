"""cleanup.py: rimozione di backup DB e file scratch accumulati in data/."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import cleanup


def _tocca_vecchio(path: Path, giorni_fa: int) -> None:
    path.write_text("contenuto di prova")
    vecchio = time.time() - giorni_fa * 86400
    import os

    os.utime(path, (vecchio, vecchio))


def test_trova_solo_backup_e_scratch_vecchi(tmp_path):
    _tocca_vecchio(tmp_path / "eventi.db.bak-20260101-000000", giorni_fa=10)
    _tocca_vecchio(tmp_path / "scratch_debug.png", giorni_fa=10)
    _tocca_vecchio(tmp_path / "eventi.db.bak-recente", giorni_fa=1)
    (tmp_path / "eventi.db").write_text("db vero, non deve mai essere toccato")
    (tmp_path / "log_qualcosa.txt").write_text("log, non deve mai essere toccato")

    trovati = cleanup.trova_file_da_pulire(tmp_path, giorni_minimi=7)

    nomi = {p.name for p in trovati}
    assert nomi == {"eventi.db.bak-20260101-000000", "scratch_debug.png"}


def test_pulisci_dry_run_non_cancella_nulla(tmp_path):
    bersaglio = tmp_path / "eventi.db.bak-vecchio"
    _tocca_vecchio(bersaglio, giorni_fa=30)

    trovati = cleanup.pulisci(tmp_path, giorni_minimi=7, dry_run=True)

    assert trovati == [bersaglio]
    assert bersaglio.exists()


def test_pulisci_esegue_rimuove_davvero(tmp_path):
    bersaglio = tmp_path / "scratch_vecchio.html"
    _tocca_vecchio(bersaglio, giorni_fa=30)

    trovati = cleanup.pulisci(tmp_path, giorni_minimi=7, dry_run=False)

    assert trovati == [bersaglio]
    assert not bersaglio.exists()


def test_nessun_file_vecchio_ritorna_lista_vuota(tmp_path):
    _tocca_vecchio(tmp_path / "eventi.db.bak-oggi", giorni_fa=0)

    assert cleanup.trova_file_da_pulire(tmp_path, giorni_minimi=7) == []
