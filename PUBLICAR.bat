@echo off
setlocal
cd /d "%~dp0"
echo Publicador de COMPRIA - entrega original, sin mejoras posteriores.
echo Extrae TODO el ZIP antes de ejecutar este archivo. No requiere administrador.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0PUBLICAR.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%
