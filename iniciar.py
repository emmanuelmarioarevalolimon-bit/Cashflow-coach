"""Windows/macOS/Linux launcher, standard library only until .venv is ready."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
VENV = ROOT / '.venv'
PYTHON = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def configure() -> None:
    """Editor visible: no getpass, no claves en argumentos ni pérdida de opciones SQL."""
    env = ROOT / '.env'
    if not env.exists():
        import shutil
        shutil.copyfile(ROOT / '.env.example', env)
    print('Edita .env en ESTA carpeta: SQL Server y Gemini. No lo compartas.')
    if os.name == 'nt':
        subprocess.run(['notepad.exe', str(env)], check=True)
    else:
        print('Abre el archivo con tu editor: ' + str(env))
    print('Guarda y vuelve a ejecutar: python iniciar.py')


def ensure_environment() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError('Se necesita Python 3.10 o superior. Instala Python y vuelve a abrir INICIAR.bat.')
    if not PYTHON.exists():
        print('Creando el entorno de Python en esta carpeta...')
        subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check=True)
    subprocess.run([str(PYTHON), '-c', 'import sys; assert sys.version_info >= (3,10)'], check=True)
    req = ROOT / 'requirements.txt'
    fingerprint = hashlib.sha256(req.read_bytes()).hexdigest()
    marker = VENV / '.c1-requirements'
    needed = not marker.exists() or marker.read_text().strip() != fingerprint
    probe = subprocess.run([str(PYTHON), '-c', 'import fastapi,uvicorn,pydantic,sqlalchemy,pypdf,multipart,defusedxml,numpy,scipy,pandas,statsmodels; assert pydantic.__version__.startswith("2.")'], capture_output=True)
    if needed or probe.returncode:
        print('Instalando dependencias. La primera vez requiere internet...')
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', str(req)], check=True)
        marker.write_text(fingerprint, encoding='ascii')


def main() -> int:
    # Configuration does not need dependency installation or a terminal secret prompt.
    if '--configure' in sys.argv:
        configure()
        return 0
    if '--demo-local' in sys.argv:
        env=ROOT/'.env'
        if not env.exists():
            import shutil
            shutil.copyfile(ROOT/'CONFIGURACION_LOCAL_PRUEBA.txt', env)
            print('Modo SQLite de prueba elegido explícitamente. NO se usará SQL Server.')
        else:
            print('Se conserva .env existente; --demo-local no reemplaza opciones SQL ni claves.')
    ensure_environment()
    if Path(sys.prefix).resolve() != VENV.resolve():
        return subprocess.call([str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    from app.config import get_ai_config
    from app.version import VERSION
    print(f'\nC1 TESORERIA {VERSION}\nCarpeta activa: {ROOT}')
    if '--configure' in sys.argv:
        configure()
        return 0
    if '--check' in sys.argv:
        return subprocess.call([str(PYTHON), '-m', 'app.ai_service', '--check'])
    if '--check-db' in sys.argv:
        return subprocess.call([str(PYTHON), '-m', 'app.db', '--init'])
    if not (ROOT / '.env').exists():
        configure()
        print('Configuración creada. Define la instancia y crea la base con sql/01_crear_base.sql. Luego reinicia.')
        return 0
    if not get_ai_config().configured:
        print('Gemini sin configurar. Puedes importar, confirmar y planificar manualmente.')
    from app.db import init_db, check_db
    try:
        init_db()
        print('Base conectada: ' + check_db()['label'])
    except Exception as exc:
        raise RuntimeError('No se pudo inicializar la base. Revisa .env, ODBC y sql/01_crear_base.sql. No se cambió a otra base. Tipo: ' + type(exc).__name__) from None
    # Select a free loopback port; never open an older process accidentally.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for port in range(8765, 8786):
        try:
            sock.bind(('127.0.0.1', port))
            break
        except OSError:
            continue
    else:
        sock.close()
        raise RuntimeError('Los puertos 8765–8785 estan ocupados. Cierra otras versiones.')
    sock.listen(128)
    from app.main import app, INSTANCE
    import uvicorn
    url = f'http://127.0.0.1:{port}'
    print(f'Abriendo {url}\nDeja esta ventana abierta. Ctrl+C detiene el servidor.')
    def open_when_ready():
        for _ in range(60):
            try:
                with urlopen(url + '/health', timeout=1) as response:
                    status = json.load(response)
                if status.get('instance') == INSTANCE:
                    webbrowser.open(url)
                    return
            except Exception:
                time.sleep(.25)
    threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='info'))
        server.run(sockets=[sock])
    finally:
        sock.close()
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print('\nNo se pudo iniciar. Revisa el mensaje anterior y tu instalacion de Python.\n' + str(exc))
        raise SystemExit(1)
