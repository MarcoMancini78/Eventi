@echo off
REM Lancio dedicato (richiesto dall'utente 2026-09-17): quando si aggiunge
REM manualmente un nuovo follow FB/IG dall'app (fuori dal sistema), niente
REM lo censisce da solo in coda_follow finche' non gira "run.py sync-seguiti"
REM (sola lettura della lista "seguiti" reale, mai schedulato in automatico
REM finora). Questo comando incatena: sync-seguiti (acquisisce la fonte) ->
REM run-publish (la segue per davvero se e' 'da_seguire', gira le fonti,
REM legge i feed, pubblica su Sheets/JSON) -> git push dei JSON pubblici
REM (16, GitHub Pages), stesso blocco gia' usato in ricerca_eventi_automatica.bat.
REM
REM Il browser Playwright resta non-headless per design (14.3): le finestre
REM Chromium di sync-seguiti/follow/feed social compariranno visibilmente
REM sullo schermo ad ogni esecuzione.

cd /d "%~dp0"

set PYTHON_EXE="C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"

echo ==== %date% %time% - avvio sync-seguiti + acquisizione + pubblicazione ==== >> data\log_sync_seguiti_schedulato.txt

echo ==== %date% %time% - sync-seguiti Facebook ==== >> data\log_sync_seguiti_schedulato.txt
%PYTHON_EXE% run.py sync-seguiti --platform=facebook >> data\log_sync_seguiti_schedulato.txt 2>&1

echo ==== %date% %time% - sync-seguiti Instagram ==== >> data\log_sync_seguiti_schedulato.txt
%PYTHON_EXE% run.py sync-seguiti --platform=instagram >> data\log_sync_seguiti_schedulato.txt 2>&1

REM Timeout esplicito di 1 ora, stesso meccanismo/motivo di
REM ricerca_eventi_automatica.bat (2026-09-12): un run-publish rimasto
REM appeso bloccherebbe ogni trigger schedulato successivo.
echo ==== %date% %time% - run-publish (follow coda + fonti + feed + pubblica) ==== >> data\log_sync_seguiti_schedulato.txt
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0esegui_con_timeout.ps1" -PythonExe %PYTHON_EXE% -LogPath "%~dp0data\log_sync_seguiti_schedulato.txt" -TimeoutSecondi 3600

REM Pubblica i JSON pubblici su GitHub Pages (16, stesso blocco di
REM ricerca_eventi_automatica.bat): run-publish li scrive gia' in locale
REM (docs/*.json), ma la pagina online si aggiorna solo con un push. "git
REM diff --quiet" salta commit/push se il file non e' cambiato, per non
REM creare commit vuoti. Un fallimento qui non deve interrompere ne'
REM segnalare come fallito il resto del giro (15.1 regola 4, isolamento).
git diff --quiet -- docs\eventi_mappa.json
if errorlevel 1 (
    echo ==== %date% %time% - aggiorno mappa online (git push) ==== >> data\log_sync_seguiti_schedulato.txt
    git add docs\eventi_mappa.json >> data\log_sync_seguiti_schedulato.txt 2>&1
    git commit -m "Aggiorna dati mappa (automatico)" >> data\log_sync_seguiti_schedulato.txt 2>&1
    git push origin master >> data\log_sync_seguiti_schedulato.txt 2>&1
) else (
    echo ==== %date% %time% - mappa online gia' aggiornata, nessun push ==== >> data\log_sync_seguiti_schedulato.txt
)

git diff --quiet -- docs\perimetro.json
if errorlevel 1 (
    echo ==== %date% %time% - aggiorno perimetro online (git push) ==== >> data\log_sync_seguiti_schedulato.txt
    git add docs\perimetro.json >> data\log_sync_seguiti_schedulato.txt 2>&1
    git commit -m "Aggiorna dati perimetro (automatico)" >> data\log_sync_seguiti_schedulato.txt 2>&1
    git push origin master >> data\log_sync_seguiti_schedulato.txt 2>&1
) else (
    echo ==== %date% %time% - perimetro online gia' aggiornato, nessun push ==== >> data\log_sync_seguiti_schedulato.txt
)

git diff --quiet -- docs\fonti.json
if errorlevel 1 (
    echo ==== %date% %time% - aggiorno fonti online (git push) ==== >> data\log_sync_seguiti_schedulato.txt
    git add docs\fonti.json >> data\log_sync_seguiti_schedulato.txt 2>&1
    git commit -m "Aggiorna dati fonti (automatico)" >> data\log_sync_seguiti_schedulato.txt 2>&1
    git push origin master >> data\log_sync_seguiti_schedulato.txt 2>&1
) else (
    echo ==== %date% %time% - fonti online gia' aggiornato, nessun push ==== >> data\log_sync_seguiti_schedulato.txt
)

echo ==== %date% %time% - fine ==== >> data\log_sync_seguiti_schedulato.txt
