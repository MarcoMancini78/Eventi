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
%PYTHON_EXE% run.py run-publish >> data\log_ricerca_eventi_schedulata.txt 2>&1

echo ==== %date% %time% - fine ==== >> data\log_ricerca_eventi_schedulata.txt
