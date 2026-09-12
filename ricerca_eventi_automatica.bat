@echo off
REM Lancio schedulato della voce 1 del menu (richiesto dall'utente 2026-08-29):
REM follow Facebook, follow Instagram, siti, feed social, pubblica su Sheets,
REM tutto in un solo comando (run.py run-publish), senza passare dal menu
REM interattivo.
REM Il browser Playwright resta non-headless per design (14.3): le finestre
REM Chromium del follow e del feed social compariranno visibilmente sullo
REM schermo ad ogni esecuzione.
REM Conseguenza nota del vincolo 14.5b (mai follow e lettura feed nella
REM stessa sessione): il feed social di QUESTA esecuzione risultera' quasi
REM sempre "saltato per troppa vicinanza al follow" nel log - non e' un
REM errore, viene letto al giro schedulato successivo.

cd /d "%~dp0"

set PYTHON_EXE="C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"

echo ==== %date% %time% - avvio ricerca eventi (follow + siti + social + pubblica) ==== >> data\log_ricerca_eventi_schedulata.txt
REM Timeout esplicito di 1 ora (2026-09-12, secondo livello di sicurezza
REM oltre a ExecutionTimeLimit del Task Scheduler, vedi esegui_con_timeout.ps1
REM per il perche': un run rimasto appeso, osservato piu' volte, bloccava
REM ogni trigger schedulato successivo per MultipleInstances=IgnoreNew).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0esegui_con_timeout.ps1" -PythonExe %PYTHON_EXE% -LogPath "%~dp0data\log_ricerca_eventi_schedulata.txt" -TimeoutSecondi 3600

REM Pubblica anche docs/eventi_mappa.json (16, richiesto dall'utente
REM 2026-08-31): run-publish/publish lo scrive gia' in locale, ma la mappa
REM online (GitHub Pages) si aggiorna solo con un push. "git diff --quiet"
REM salta commit/push se il file non e' cambiato (nessun evento nuovo/scaduto
REM da un giro all'altro), per non creare commit vuoti. Un fallimento qui non
REM deve interrompere ne' segnalare come fallita l'intera ricerca eventi
REM (15.1 regola 4, isolamento totale): loggato, non propagato.
git diff --quiet -- docs\eventi_mappa.json
if errorlevel 1 (
    echo ==== %date% %time% - aggiorno mappa online (git push) ==== >> data\log_ricerca_eventi_schedulata.txt
    git add docs\eventi_mappa.json >> data\log_ricerca_eventi_schedulata.txt 2>&1
    git commit -m "Aggiorna dati mappa (automatico)" >> data\log_ricerca_eventi_schedulata.txt 2>&1
    git push origin master >> data\log_ricerca_eventi_schedulata.txt 2>&1
) else (
    echo ==== %date% %time% - mappa online gia' aggiornata, nessun push ==== >> data\log_ricerca_eventi_schedulata.txt
)

echo ==== %date% %time% - fine ==== >> data\log_ricerca_eventi_schedulata.txt
