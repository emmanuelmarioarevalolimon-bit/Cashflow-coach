"""Transport recovery uses Google and preserves existing proposal validation."""
import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app import ai_service as ai, document_ai, limits


@pytest.fixture
def attempts(monkeypatch):
    calls = []
    monkeypatch.setattr(limits, 'reserve_provider_call', lambda: calls.append('reserved'))
    monkeypatch.setattr(ai, 'sleep', lambda seconds: None)
    return calls


def unavailable(configured, status=503):
    return HTTPError(configured.api_url, status, 'failure', {},
                     BytesIO(json.dumps({'error': {'message': configured.api_key}}).encode()))


def native_response(value, *, reason='STOP', parts=None):
    return BytesIO(json.dumps({'candidates': [{
        'finishReason': reason,
        'content': {'parts': parts if parts is not None else [{'text': json.dumps(value)}]},
    }]}).encode())


def test_503_recovers_same_model_schema_and_conversation(configured, payload, attempts, monkeypatch):
    sent = []
    updates = {'stressEnabled': True, 'stressEventId': 'receivable-main', 'stressDelayDays': 7}

    def transport(request, timeout):
        sent.append(request)
        assert 0 < timeout <= configured.timeout_seconds
        if len(sent) == 1:
            raise unavailable(configured)
        return native_response({'answer': 'Retrasa el cobro siete días.', 'suggestedUpdates': updates})

    monkeypatch.setattr(ai, 'urlopen', transport)
    answer, actual = ai._provider_request(configured, payload)
    assert actual == updates
    assert answer == 'Retrasa el cobro siete días.'
    assert len(attempts) == len(sent) == 2
    original = json.loads(sent[0].data)
    native = json.loads(sent[1].data)
    assert sent[1].full_url == f'https://generativelanguage.googleapis.com/v1beta/models/{configured.model}:generateContent'
    assert sent[1].get_header('X-goog-api-key') == configured.api_key
    assert configured.api_key not in sent[1].full_url
    assert native['systemInstruction']['parts'][0]['text'] == original['messages'][0]['content']
    assert native['contents'][0]['parts'][0]['text'] == original['messages'][1]['content']
    assert native['generationConfig']['responseJsonSchema'] == original['response_format']['json_schema']['schema']
    assert native['generationConfig']['maxOutputTokens'] == original['max_tokens']


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429])
def test_auth_configuration_and_quota_errors_are_not_retried(status, configured, payload, attempts, monkeypatch):
    def transport(*args, **kwargs):
        raise unavailable(configured, status)
    monkeypatch.setattr(ai, 'urlopen', transport)
    with pytest.raises(RuntimeError) as error:
        ai._provider_request(configured, payload)
    assert len(attempts) == 1
    assert str(status) in str(error.value)
    assert configured.api_key not in str(error.value)


@pytest.mark.parametrize('status', [502, 503, 504])
def test_both_routes_failing_is_not_reported_as_success(status, configured, payload, attempts, monkeypatch):
    monkeypatch.setattr(ai, 'urlopen', lambda *args, **kwargs: (_ for _ in ()).throw(unavailable(configured, status)))
    with pytest.raises(RuntimeError) as error:
        ai._provider_request(configured, payload)
    assert len(attempts) == 2
    assert str(status) in str(error.value)
    assert configured.api_key not in str(error.value)


def test_native_request_preserves_history_roles(configured):
    body = {'max_tokens': 4000, 'response_format': {'json_schema': {'schema': {'type': 'object'}}},
            'messages': [{'role': 'system', 'content': 'Instructions'},
                         {'role': 'user', 'content': 'Previous question'},
                         {'role': 'assistant', 'content': 'Previous answer'},
                         {'role': 'user', 'content': 'Current question'}]}
    native = json.loads(ai._native_gemini_request(configured, body).data)
    assert [item['role'] for item in native['contents']] == ['user', 'model', 'user']
    assert [item['parts'][0]['text'] for item in native['contents']] == ['Previous question', 'Previous answer', 'Current question']


@pytest.mark.parametrize('reason', ['MAX_TOKENS', 'SAFETY', 'RECITATION', None])
def test_incomplete_or_blocked_native_output_is_rejected(reason):
    data = json.loads(native_response({'answer': 'Partial'}, reason=reason).read())
    with pytest.raises(RuntimeError):
        ai._extract_provider_text(data)


def test_native_thoughts_are_not_used_as_the_answer():
    data = json.loads(native_response(None, parts=[{'thought': True, 'text': 'Private reasoning'},
                                                 {'text': '{"answer":"Visible"}'}]).read())
    assert ai._extract_provider_text(data) == '{"answer":"Visible"}'
    data['candidates'][0]['content']['parts'].pop()
    with pytest.raises(RuntimeError):
        ai._extract_provider_text(data)


def test_no_recovery_when_time_budget_exhausted(configured, payload, attempts, monkeypatch):
    ticks = iter([0, 0, 56])
    monkeypatch.setattr(ai, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(ai, 'urlopen', lambda *args, **kwargs: (_ for _ in ()).throw(unavailable(configured)))
    with pytest.raises(RuntimeError, match='503'):
        ai._provider_request(configured, payload)
    assert len(attempts) == 1


def test_second_attempt_respects_local_quota(configured, payload, attempts, monkeypatch):
    def reserve():
        attempts.append('reserved')
        if len(attempts) == 2:
            raise RuntimeError('Límite local alcanzado')
    sent = []
    def transport(*args, **kwargs):
        sent.append(1)
        raise unavailable(configured)
    monkeypatch.setattr(limits, 'reserve_provider_call', reserve)
    monkeypatch.setattr(ai, 'urlopen', transport)
    with pytest.raises(RuntimeError, match='Límite local'):
        ai._provider_request(configured, payload)
    assert len(sent) == 1


def test_documents_share_native_recovery(configured, attempts, monkeypatch):
    monkeypatch.setattr(document_ai, 'get_ai_config', lambda: configured)
    monkeypatch.setattr(document_ai, 'reserve_provider_call', lambda: attempts.append('reserved'))
    sent = []
    def transport(request, timeout):
        sent.append(request)
        if len(sent) == 1:
            raise unavailable(configured)
        return native_response({'summary': 'Resumen recibido de Gemini'})
    monkeypatch.setattr(ai, 'urlopen', transport)
    value, model = document_ai.request_json('Instructions', {'example': True}, {'type': 'object'})
    assert value == {'summary': 'Resumen recibido de Gemini'}
    assert model == configured.model
    assert len(attempts) == 2
