@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" iniciar.py %*
  goto end
)
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
  python iniciar.py %*
  goto end
)
py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
  py -3 iniciar.py %*
  goto end
)
echo No se encuentra Python 3.10 o superior.
echo Instala Python desde python.org y vuelve a abrir este archivo.
:end
pause
