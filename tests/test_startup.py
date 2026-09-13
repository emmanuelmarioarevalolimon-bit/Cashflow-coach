import asyncio

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import main


def test_database_startup_retries_a_transient_connection_failure(monkeypatch):
    calls = 0
    delays = []

    def initialize():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SQLAlchemyError('database is still provisioning')

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(main, 'init_db', initialize)
    monkeypatch.setattr(main.asyncio, 'sleep', sleep)

    asyncio.run(main.initialize_database(attempts=2))

    assert calls == 2
    assert delays == [2]


def test_database_startup_reports_safe_configuration_error(monkeypatch):
    def initialize():
        raise RuntimeError('Completa DATABASE_URL para PostgreSQL.')

    monkeypatch.setattr(main, 'init_db', initialize)

    with pytest.raises(RuntimeError, match='Completa DATABASE_URL'):
        asyncio.run(main.initialize_database())
