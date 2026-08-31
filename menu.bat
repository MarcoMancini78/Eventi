@echo off
REM Menu interattivo per lanciare i comandi di run.py senza ricordare la
REM sintassi esatta (richiesto dall'utente, 2026-08-27). Nessuna logica di
REM dominio qui dentro: e' solo un front-end che compone la riga di comando
REM e chiama run.py, che resta l'unico punto d'ingresso vero (15.1).
REM Ristrutturato 2026-08-28: la ricerca eventi copre siti+social insieme,
REM con un sottomenu per lanciare solo un pezzo. Anagrafica diventata
REM Utilita' (comandi usati raramente, non nel giro quotidiano).

setlocal enabledelayedexpansion
cd /d "%~dp0"

set PYTHON_EXE="C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"

:MENU_PRINCIPALE
cls
echo ================================================================
echo   Eventi Langhe - Menu comandi
echo ================================================================
echo.
echo   1. Ricerca eventi (follow + siti + social + pubblica)
echo   2. Dettaglio ricerche (solo siti, solo social, sola pubblicazione)
echo   3. Social - Follow (login, follow, sync-seguiti)
echo   4. Utilita' (perimetro, coda follow, fingerprinting - uso raro)
echo   5. Apri mappa eventi (webapp/mappa.html)
echo   0. Esci
echo.
set /p SCELTA="Scelta: "

if "%SCELTA%"=="1" (
    %PYTHON_EXE% run.py run-publish
    goto FINE_COMANDO
)
if "%SCELTA%"=="2" goto MENU_RICERCA
if "%SCELTA%"=="3" goto MENU_FOLLOW
if "%SCELTA%"=="4" goto MENU_UTILITA
if "%SCELTA%"=="5" goto APRI_MAPPA
if "%SCELTA%"=="0" goto FINE
goto MENU_PRINCIPALE


:MENU_RICERCA
cls
echo ================================================================
echo   Dettaglio ricerche
echo ================================================================
echo.
echo   1. Solo siti - giro completo (run.py run)
echo   2. Solo siti - giro di test limitato, senza LLM
echo   3. Solo siti - riciclo mirato sulle fonti in errore
echo   4. Solo social - feed Facebook
echo   5. Solo social - feed Instagram
echo   6. Discovery pagine eventi (run.py prober)
echo   7. Sola pubblicazione su Google Sheets (run.py publish)
echo   0. Indietro
echo.
set /p SCELTA="Scelta: "

if "%SCELTA%"=="1" (
    %PYTHON_EXE% run.py run
    goto FINE_COMANDO
)
if "%SCELTA%"=="2" (
    set /p LIMITE="Quante fonti (es. 5): "
    %PYTHON_EXE% run.py run --no-llm --limite=!LIMITE!
    goto FINE_COMANDO
)
if "%SCELTA%"=="3" (
    %PYTHON_EXE% run.py run --solo-errori
    goto FINE_COMANDO
)
if "%SCELTA%"=="4" (
    %PYTHON_EXE% run.py feed-social --platform=facebook
    goto FINE_COMANDO
)
if "%SCELTA%"=="5" (
    %PYTHON_EXE% run.py feed-social --platform=instagram
    goto FINE_COMANDO
)
if "%SCELTA%"=="6" (
    %PYTHON_EXE% run.py prober
    goto FINE_COMANDO
)
if "%SCELTA%"=="7" (
    %PYTHON_EXE% run.py publish
    goto FINE_COMANDO
)
if "%SCELTA%"=="0" goto MENU_PRINCIPALE
goto MENU_RICERCA


:MENU_FOLLOW
cls
echo ================================================================
echo   Social - Follow (M9)
echo ================================================================
echo.
echo   1. Login manuale (una tantum)
echo   2. Lotto di follow - anteprima (--dry-run)
echo   3. Lotto di follow - reale
echo   4. Sincronizza seguiti reali (sync-seguiti)
echo   0. Indietro
echo.
set /p SCELTA="Scelta: "

if "%SCELTA%"=="1" (
    call :CHIEDI_PIATTAFORMA
    %PYTHON_EXE% run.py login --platform=!PIATTAFORMA!
    goto FINE_COMANDO
)
if "%SCELTA%"=="2" (
    call :CHIEDI_PIATTAFORMA
    %PYTHON_EXE% run.py follow --platform=!PIATTAFORMA! --dry-run
    goto FINE_COMANDO
)
if "%SCELTA%"=="3" (
    call :CHIEDI_PIATTAFORMA
    %PYTHON_EXE% run.py follow --platform=!PIATTAFORMA!
    goto FINE_COMANDO
)
if "%SCELTA%"=="4" (
    call :CHIEDI_PIATTAFORMA
    %PYTHON_EXE% run.py sync-seguiti --platform=!PIATTAFORMA!
    goto FINE_COMANDO
)
if "%SCELTA%"=="0" goto MENU_PRINCIPALE
goto MENU_FOLLOW


:MENU_UTILITA
cls
echo ================================================================
echo   Utilita' (comandi usati raramente)
echo ================================================================
echo.
echo   1. Importa perimetro (senza pubblicare) - solo se cambia l'elenco comuni
echo   2. Importa perimetro e pubblica su Sheets
echo   3. Import fonti da Comuni.csv/ProLoco.csv - solo per aggiungere nuove fonti
echo   4. Popola coda follow (senza pubblicare) - solo con nuovi dati anagrafici
echo   5. Popola coda follow e pubblica su Sheets
echo   6. Fingerprinting comuni (tutti) - solo se cambiano molti siti comunali
echo   7. Aggiorna da Google Sheets: Fonti e DaVerificare (pull-fonti)
echo   8. Verifica configurazione (database, credenziali Google, .env)
echo   0. Indietro
echo.
set /p SCELTA="Scelta: "

if "%SCELTA%"=="1" (
    %PYTHON_EXE% run.py import-perimetro
    goto FINE_COMANDO
)
if "%SCELTA%"=="2" (
    %PYTHON_EXE% run.py import-perimetro --publish
    goto FINE_COMANDO
)
if "%SCELTA%"=="3" (
    %PYTHON_EXE% run.py import-fonti
    goto FINE_COMANDO
)
if "%SCELTA%"=="4" (
    %PYTHON_EXE% run.py populate-coda-follow
    goto FINE_COMANDO
)
if "%SCELTA%"=="5" (
    %PYTHON_EXE% run.py populate-coda-follow --publish
    goto FINE_COMANDO
)
if "%SCELTA%"=="6" (
    %PYTHON_EXE% run.py fingerprint-comuni
    goto FINE_COMANDO
)
if "%SCELTA%"=="7" (
    %PYTHON_EXE% run.py pull-fonti
    goto FINE_COMANDO
)
if "%SCELTA%"=="8" (
    %PYTHON_EXE% run.py doctor
    goto FINE_COMANDO
)
if "%SCELTA%"=="0" goto MENU_PRINCIPALE
goto MENU_UTILITA


:APRI_MAPPA
REM Webapp mappa (16): Google Drive non esegue mappa.html come pagina ne'
REM serve eventi_mappa.json via fetch (bloccato da CORS - collaudo 2026-08-31,
REM vedi Documentazione/16-webapp-mappa.md, T8) - va servita da un webserver
REM locale. Avviato in una finestra separata cosi' resta attivo mentre si usa
REM la mappa, senza bloccare questo menu.
cls
echo ================================================================
echo   Mappa eventi
echo ================================================================
echo.
if not exist "%~dp0webapp\mappa.html" (
    echo webapp\mappa.html non trovato.
    echo Copia webapp\mappa.template.html in webapp\mappa.html e inserisci
    echo la tua API key Google Maps prima di usare questa voce
    echo ^(Documentazione\16-webapp-mappa.md, 16.2.2/T4^).
    goto FINE_COMANDO
)
echo Avvio del webserver locale su http://localhost:8000/ ...
echo (si apre in una finestra separata: chiuderla per fermarlo)
echo.
echo Dopo l'apertura della pagina nel browser, usa il pulsante
echo "Carica eventi_mappa.json..." per selezionare data\eventi_mappa.json
echo (rigenerato a ogni "run.py publish").
echo.
pushd "%~dp0webapp"
start "Mappa eventi - webserver locale" cmd /k %PYTHON_EXE% -m http.server 8000
popd
timeout /t 1 /nobreak >nul
start "" "http://localhost:8000/mappa.html"
goto FINE_COMANDO


:CHIEDI_PIATTAFORMA
set PIATTAFORMA=
:CHIEDI_PIATTAFORMA_LOOP
set /p PIATTAFORMA="Piattaforma (facebook/instagram): "
if /i "%PIATTAFORMA%"=="facebook" exit /b
if /i "%PIATTAFORMA%"=="instagram" exit /b
echo Valore non valido, scrivi 'facebook' o 'instagram'.
goto CHIEDI_PIATTAFORMA_LOOP


:FINE_COMANDO
echo.
pause
goto MENU_PRINCIPALE


:FINE
endlocal
exit /b 0
