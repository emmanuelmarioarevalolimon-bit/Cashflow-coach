"""Small, process-local limits for a single-process demonstration, not production quotas."""
from collections import deque
from datetime import datetime, timezone
from threading import Lock, BoundedSemaphore
import time

_lock = Lock()
_recent: deque[float] = deque()
_day = ''
_used = 0
REQUEST_SLOT = BoundedSemaphore(2)


def reserve_provider_call() -> None:
    global _day, _used
    now = time.monotonic()
    day = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        if _day != day:
            _day, _used = day, 0
        while _recent and now - _recent[0] >= 60:
            _recent.popleft()
        if len(_recent) >= 12:
            raise RuntimeError('Límite local: 12 llamadas por minuto. Espera un minuto antes de volver a intentar.')
        if _used >= 100:
            raise RuntimeError('Límite local diario alcanzado: 100 llamadas a Gemini. No se enviaron más peticiones.')
        _recent.append(now)
        _used += 1
