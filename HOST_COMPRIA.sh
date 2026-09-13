#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

python_bin="$project_dir/.venv/bin/python"
cloudflared_bin="$project_dir/.tools/cloudflared"
tunnel_token_file="$project_dir/.cloudflare-tunnel-token"
port="${COMPRIA_PORT:-8765}"

if [[ ! -x "$python_bin" ]]; then
  echo "Falta el entorno de Python. Ejecuta primero: python3 iniciar.py --demo-local" >&2
  exit 1
fi
if [[ ! -x "$cloudflared_bin" ]]; then
  echo "Falta .tools/cloudflared. Consulta docs/HOST_DESDE_LAPTOP.md." >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Falta .env. Ejecuta primero: python3 iniciar.py --demo-local" >&2
  exit 1
fi

app_pid=""
tunnel_pid=""
cleanup() {
  if [[ -n "$tunnel_pid" ]]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
  if [[ -n "$app_pid" ]]; then
    kill "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ready=0
if curl --silent --fail "http://127.0.0.1:$port/health" | grep --quiet '"status":"ok"'; then
  ready=1
  echo "Se reutiliza la instancia de COMPRIA que ya está activa."
else
  "$python_bin" -m uvicorn app.main:app --host 127.0.0.1 --port "$port" &
  app_pid=$!
  for _ in {1..40}; do
    if curl --silent --fail "http://127.0.0.1:$port/health" | grep --quiet '"status":"ok"'; then
      ready=1
      break
    fi
    if ! kill -0 "$app_pid" 2>/dev/null; then
      wait "$app_pid"
    fi
    sleep 0.25
  done
fi
if [[ "$ready" != "1" ]]; then
  echo "COMPRIA no respondió en el puerto $port." >&2
  exit 1
fi

echo "COMPRIA está activa localmente en http://127.0.0.1:$port"
if [[ "${1:-}" == "--quick" ]]; then
  "$cloudflared_bin" tunnel --protocol http2 --url "http://127.0.0.1:$port" &
else
  if [[ ! -s "$tunnel_token_file" ]]; then
    echo "Falta .cloudflare-tunnel-token. Consulta docs/HOST_DESDE_LAPTOP.md." >&2
    exit 1
  fi
  "$cloudflared_bin" tunnel --protocol http2 run --token-file "$tunnel_token_file" &
fi
tunnel_pid=$!
wait "$tunnel_pid"
