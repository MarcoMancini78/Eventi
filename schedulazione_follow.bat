@echo off
REM Lancio schedulato del follow M9 (Facebook + Instagram).
REM Il browser Playwright resta non-headless per design (14.3): questa
REM finestra Chromium comparira' visibilmente sullo schermo ad ogni esecuzione.
REM Le precondizioni/circuito (14.5) fermano da sole il lotto se non e' il
REM momento giusto (circuito aperto, intervallo minimo tra lotti non passato):
REM un fallimento qui e' normale e non richiede intervento.

cd /d "%~dp0"

set PYTHON_EXE="C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"

echo ==== %date% %time% - avvio lotto Facebook ==== >> data\log_follow_schedulato.txt
%PYTHON_EXE% run.py follow --platform=facebook >> data\log_follow_schedulato.txt 2>&1

echo ==== %date% %time% - avvio lotto Instagram ==== >> data\log_follow_schedulato.txt
%PYTHON_EXE% run.py follow --platform=instagram >> data\log_follow_schedulato.txt 2>&1

echo ==== %date% %time% - fine ==== >> data\log_follow_schedulato.txt
