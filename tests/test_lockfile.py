"""Lock file per evitare run.py run sovrapposti (M11). Nessuna dipendenza
esterna reale: il 'processo vivo' è simulato usando il PID di questo stesso
processo di test (sempre vivo) o un PID inesistente."""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lockfile import RunGiaInCorsoError, lock_run


def test_lock_run_crea_e_rimuove_il_file(tmp_path):
    lock_path = tmp_path / "run.lock"
    assert not lock_path.exists()

    with lock_run(lock_path):
        assert lock_path.exists()
        assert lock_path.read_text().strip() == str(os.getpid())

    assert not lock_path.exists()


def test_lock_run_rimuove_il_file_anche_se_il_blocco_solleva(tmp_path):
    lock_path = tmp_path / "run.lock"

    try:
        with lock_run(lock_path):
            raise ValueError("errore dentro il blocco")
    except ValueError:
        pass

    assert not lock_path.exists()


def test_lock_run_blocca_se_un_processo_vivo_ha_gia_il_lock(tmp_path):
    lock_path = tmp_path / "run.lock"
    lock_path.write_text(str(os.getpid()))  # il processo di test è certamente vivo

    try:
        with lock_run(lock_path):
            assert False, "doveva sollevare RunGiaInCorsoError"
    except RunGiaInCorsoError as exc:
        assert str(os.getpid()) in str(exc)


def test_lock_run_rimuove_da_solo_un_lock_stantio(tmp_path):
    """Un PID che certamente non esiste più (crash, riavvio) non deve
    bloccare per sempre i run successivi."""
    lock_path = tmp_path / "run.lock"
    pid_inesistente = 999999
    lock_path.write_text(str(pid_inesistente))

    with lock_run(lock_path):
        assert lock_path.read_text().strip() == str(os.getpid())


def test_lock_run_blocca_un_pid_esterno_vivo_non_solo_se_stesso(tmp_path):
    """Bug reale (2026-08-27): os.kill(pid, 0) su un PID esterno vivo
    solleva SystemError su Windows, non PermissionError come su Unix —
    catturato erroneamente come 'processo morto', permettendo a un secondo
    run.py run di partire mentre il primo era ancora attivo. Verificato con
    un vero processo esterno (non self), il caso che il bug non copriva."""
    processo_esterno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        time.sleep(0.3)  # dà tempo al processo di partire davvero
        lock_path = tmp_path / "run.lock"
        lock_path.write_text(str(processo_esterno.pid))

        try:
            with lock_run(lock_path):
                assert False, "doveva sollevare RunGiaInCorsoError per il processo esterno vivo"
        except RunGiaInCorsoError:
            pass
    finally:
        processo_esterno.kill()
        processo_esterno.wait()


def test_lock_run_gestisce_contenuto_illeggibile(tmp_path):
    """Un lock corrotto (contenuto non numerico) non deve bloccare per
    sempre: va trattato come stantio, non come errore fatale."""
    lock_path = tmp_path / "run.lock"
    lock_path.write_text("non-un-pid")

    with lock_run(lock_path):
        assert lock_path.read_text().strip() == str(os.getpid())
