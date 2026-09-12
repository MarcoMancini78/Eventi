# Avvia run.py run-publish con un timeout esplicito di 1 ora (2026-09-12).
#
# Secondo livello di sicurezza oltre a ExecutionTimeLimit del Task
# Scheduler: un run rimasto appeso (osservato piu' volte, es. 03:25-13:29
# del 12/09, 10 ore senza terminare) bloccava ogni trigger schedulato
# successivo per MultipleInstances=IgnoreNew. Il limite del Task Scheduler
# misura il tempo dell'istanza cmd.exe che lui stesso traccia, non sempre
# propagato in modo affidabile al vero processo figlio python.exe -
# Wait-Process con -Timeout e la terminazione esplicita qui non dipendono
# da quel tracciamento.

param(
    [string]$PythonExe,
    [string]$LogPath,
    [int]$TimeoutSecondi = 3600
)

$stdout = Join-Path (Split-Path $LogPath) "log_run_publish_stdout_tmp.txt"
$stderr = Join-Path (Split-Path $LogPath) "log_run_publish_stderr_tmp.txt"

$processo = Start-Process -FilePath $PythonExe -ArgumentList "run.py", "run-publish" `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -NoNewWindow

# Wait-Process -Timeout non e' affidabile (segnala timeout anche quando il
# processo e' gia' terminato regolarmente, verificato empiricamente
# 2026-09-12): $Process.WaitForExit(ms), il metodo .NET diretto, e' il
# meccanismo che risulta corretto nei test.
$completato = $processo.WaitForExit($TimeoutSecondi * 1000)

if (-not $completato) {
    Add-Content -Path $LogPath -Value "==== TIMEOUT ${TimeoutSecondi}s superato: termino il processo appeso (PID $($processo.Id)) ===="
    Stop-Process -Id $processo.Id -Force -ErrorAction SilentlyContinue
}

if (Test-Path $stdout) {
    Get-Content $stdout | Add-Content -Path $LogPath
    Remove-Item $stdout -ErrorAction SilentlyContinue
}
if (Test-Path $stderr) {
    Get-Content $stderr | Add-Content -Path $LogPath
    Remove-Item $stderr -ErrorAction SilentlyContinue
}
