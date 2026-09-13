"""Configuration is read afresh. A local .env takes precedence over inherited AI_* values.
No keys, hashes of keys, provider bodies or filesystem paths are returned by status().
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from threading import Lock
from urllib.parse import urlsplit
from .version import VERSION

PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_DIR / '.env'
DEFAULT_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
DEFAULT_MODEL = 'gemini-3.8-flash'
DEFAULT_INSTRUCTIONS_FILE = PROJECT_DIR / 'assistant_instructions.txt'
DEFAULT_ASSISTANT_INSTRUCTIONS = (
    'Responde con un registro académico, riguroso y pedagógico. Distingue datos calculados, '
    'supuestos e interpretación. Usa Markdown con moderación y LaTeX entre \\( \\) o \\[ \\].'
)
_PLACEHOLDERS = {'', 'TU_CLAVE_NUEVA', 'PEGA_AQUI_TU_CLAVE_NUEVA_DE_GEMINI', 'tu_clave_nueva', 'reemplaza_con_una_clave_nueva', 'replace_with_your_key'}
_lock = Lock()
_last: dict[str, object] = {}


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class AIConfig:
    api_url: str
    api_key: str
    model: str
    timeout_seconds: int
    assistant_instructions: str = DEFAULT_ASSISTANT_INSTRUCTIONS
    instructions_source: str = 'academic-default'
    instructions_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_url and self.model and self.api_key not in _PLACEHOLDERS)

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            f'{self.api_url}\0{self.model}\0{self.api_key}\0{self.assistant_instructions}'.encode()
        ).hexdigest()


def _load_assistant_instructions(values: dict[str, str]) -> tuple[str, str, str | None]:
    configured_path = values.get(
        'AI_ASSISTANT_INSTRUCTIONS_FILE', os.getenv('AI_ASSISTANT_INSTRUCTIONS_FILE', '')
    ).strip()
    candidate = Path(configured_path) if configured_path else DEFAULT_INSTRUCTIONS_FILE
    if not candidate.is_absolute():
        candidate = PROJECT_DIR / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(PROJECT_DIR.resolve())
        if not candidate.is_file():
            if not configured_path:
                return DEFAULT_ASSISTANT_INSTRUCTIONS, 'academic-default', None
            raise ValueError('no existe')
        if candidate.stat().st_size > 16_000:
            raise ValueError('supera 16 KB')
        instructions = candidate.read_text(encoding='utf-8-sig').strip()
        if not instructions:
            raise ValueError('está vacío')
        source = 'custom-file' if configured_path else 'academic-file'
        return instructions, source, None
    except (OSError, UnicodeError, ValueError):
        message = (
            'AI_ASSISTANT_INSTRUCTIONS_FILE debe apuntar a un archivo UTF-8 no vacío, de hasta '
            '16 KB y ubicado dentro de la carpeta de la aplicación.'
        )
        return DEFAULT_ASSISTANT_INSTRUCTIONS, 'configuration-error', message


def get_ai_config() -> AIConfig:
    values = read_env()
    def get(name: str, default: str = '') -> str:
        return values.get(name, os.getenv(name, default)).strip()
    try:
        timeout = max(5, min(60, int(get('AI_TIMEOUT_SECONDS', '60'))))
    except ValueError:
        timeout = 60
    key = get('AI_API_KEY') or get('GEMINI_API_KEY')
    instructions, source, instructions_error = _load_assistant_instructions(values)
    return AIConfig(get('AI_API_URL', DEFAULT_URL), key,
                    get('AI_MODEL', DEFAULT_MODEL), timeout,
                    instructions, source, instructions_error)


def _is_gemini(config: AIConfig) -> bool:
    try:
        return config.api_url.rstrip('/') == DEFAULT_URL
    except ValueError:
        return False


def record_status(config: AIConfig, *, verified: bool, error: str | None = None) -> None:
    with _lock:
        _last.clear()
        _last.update(identity=config.identity, verified=verified, error=error)


def ai_status() -> dict[str, object]:
    config = get_ai_config()
    missing = []
    if config.api_key in _PLACEHOLDERS: missing.append('AI_API_KEY')
    if not config.api_url: missing.append('AI_API_URL')
    if not config.model: missing.append('AI_MODEL')
    error = None
    if config.configured and not _is_gemini(config):
        error = 'AI_API_URL no es el endpoint oficial admitido de Gemini.'
    if config.model and not re.fullmatch(r'gemini-[a-zA-Z0-9_.-]+', config.model):
        error = 'AI_MODEL debe ser un identificador de modelo Gemini válido.'
    if config.instructions_error:
        error = config.instructions_error
    with _lock:
        last = _last.copy() if _last.get('identity') == config.identity else {}
    error = error or last.get('error')
    verified = bool(last.get('verified')) and not error
    mode = 'error' if error else 'external' if verified else 'configured' if config.configured else 'unconfigured'
    labels = {'error': 'Gemini: error visible', 'external': 'Gemini verificado',
              'configured': 'Gemini configurado · pendiente de prueba',
              'unconfigured': 'Gemini sin configurar · chat desactivado'}
    return {'version': VERSION, 'configured': config.configured, 'mode': mode,
            'label': labels[mode], 'verified': verified,
            'model': config.model if re.fullmatch(r'gemini-[a-zA-Z0-9_.-]+', config.model or '') else None,
            'assistantStyle': config.instructions_source,
            'missing': missing, 'error': error}
