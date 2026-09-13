import pytest
from datetime import date
from app import ai_service as ai
from app import config
from app.service import demo_payload
from app.models import AssistantRequest

@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    # Tests never use actual .env files or actual credentials.
    monkeypatch.setattr(config, 'ENV_FILE', __import__('pathlib').Path('/nonexistent-test-env'))
    for name in ('AI_API_KEY', 'GEMINI_API_KEY', 'AI_API_URL', 'AI_MODEL'):
        monkeypatch.delenv(name, raising=False)
    def block(*args, **kwargs):
        raise AssertionError('External network disabled in automated tests')
    monkeypatch.setattr(ai, 'urlopen', block)

@pytest.fixture
def demo(): return demo_payload(date(2026, 9, 12))

@pytest.fixture
def payload(demo):
    return AssistantRequest(message='Que pasa si mi cliente se tarda en pagar 1 semana', analysisInput=demo)

@pytest.fixture
def configured(monkeypatch):
    value = config.AIConfig(config.DEFAULT_URL, 'TEST_KEY_NOT_A_REAL_SECRET', config.DEFAULT_MODEL, 60)
    monkeypatch.setattr(ai, 'get_ai_config', lambda: value)
    monkeypatch.setattr(config, 'get_ai_config', lambda: value)
    config.record_status(value, verified=False)
    return value

@pytest.fixture
def client(monkeypatch,tmp_path):
    from app import db,security
    from app.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setenv('DB_BACKEND','sqlite')
    monkeypatch.setenv('SQLITE_PATH',str(tmp_path/'test.db'))
    monkeypatch.setenv('ALLOW_REGISTRATION','1')
    monkeypatch.setenv('C1_PUBLIC_MODE','0')
    security.attempts.clear();db.get_engine.cache_clear()
    with TestClient(app,headers={'X-C1-Request':'1'}) as c:
        r=c.post('/api/auth/register',json={'email':'one@example.test','password':'A-long-test-password-01','company':'Empresa Uno','currency':'MXN'})
        assert r.status_code==200,r.text
        yield c
    db.get_engine().dispose();db.get_engine.cache_clear()
