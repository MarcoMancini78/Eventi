@echo off
REM Lancio schedulato del backup settimanale dello spreadsheet (17.2.2,
REM mitiga il rischio 11.1 "foglio corrotto da un bug di publish").
REM Da schedulare una volta a settimana in Utilita' di pianificazione
REM Windows (Task Scheduler) - stesso pattern di schedulazione_follow.bat
REM e ricerca_eventi_automatica.bat, nessuna configurazione qui dentro.

cd /d "%~dp0"

set PYTHON_EXE="C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"

echo ==== %date% %time% - avvio backup spreadsheet ==== >> data\log_backup_schedulato.txt
%PYTHON_EXE% run.py backup-sheets >> data\log_backup_schedulato.txt 2>&1

echo ==== %date% %time% - fine ==== >> data\log_backup_schedulato.txt
