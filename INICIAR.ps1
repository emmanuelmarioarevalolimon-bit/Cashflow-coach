param([switch]$Configurar,[switch]$ProbarSQL)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8='1'
$arguments=@('iniciar.py')
if ($Configurar) { $arguments += '--configure' }
if ($ProbarSQL) { $arguments += '--check-db' }
if (Test-Path '.\.venv\Scripts\python.exe') { & '.\.venv\Scripts\python.exe' @arguments }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python @arguments }
elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3 @arguments }
else { throw 'No se encontró Python. Instala Python 3.10 o superior y vuelve a abrir PowerShell.' }
if ($LASTEXITCODE -ne 0) { throw 'El programa no pudo iniciar. Revisa el mensaje anterior.' }
