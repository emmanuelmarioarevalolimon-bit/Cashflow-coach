from copy import deepcopy
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import ai_service as ai, config
from app.models import AnalyzeRequest, AssistantRequest
from app.service import analyze


UPDATES = {'stressEnabled':True, 'stressEventId':'receivable-main', 'stressDelayDays':7}


def test_demo_starts_without_delay(demo):
    result = analyze(AnalyzeRequest.model_validate(demo))
    assert demo['stressScenario']['delayDays'] == 0
    assert result['stressed']['projectedShortfall'] == '0.00'
    assert result['stressed']['minimumConservativeBalance'] == '20700.00'


def test_delayed_scenario_and_optimizer(payload):
    delayed = ai.apply_updates(payload.analysis_input, UPDATES)
    result = analyze(delayed)
    assert result['stressed']['minimumConservativeBalance'] == '4500.00'
    assert result['stressed']['projectedShortfall'] == '15500.00'
    assert result['optimization']['repaired']['minimumConservativeBalance'] == '20500.00'
    assert result['optimization']['totalFinancialCost'] == '190.00'
    assert payload.analysis_input.stress_scenario.delay_days == 0


def test_no_interventions_remains_calculable(demo):
    demo['stressScenario']['delayDays'] = 7
    demo['interventions'] = {}
    result = analyze(AnalyzeRequest.model_validate(demo))
    assert result['optimization']['feasible'] is False
    assert result['optimization']['selectedInterventions'] == []
    assert result['optimization']['repaired'] is None


@pytest.mark.parametrize('question,days', [
    ('Que pasa si mi cliente se tarda en pagar 1 semana',7),
    ('¿Qué pasa si mi cliente se tarda en pagar dos semanas?',14),
    ('Retrasa al Cliente principal 10 días',10),
    ('El Cliente principal paga una semana tarde',7),
    ('Mi cliente se demora tres semanas',21),
    ('mi cliente se atrasa 0 dias',0),
])
def test_regression_natural_phrases(payload,question,days):
    payload = payload.model_copy(update={'message':question})
    assert ai._simple_delay_intent(payload) == (True,'receivable-main',days)
    changes = {**UPDATES,'stressDelayDays':days}
    assert ai._validate_provider_updates(payload,changes) == changes


@pytest.mark.parametrize('bad',[
    {'stressEnabled':True,'stressEventId':'receivable-main'},
    {**UPDATES,'deferEventId':'supplier-flexible'},
    {**UPDATES,'stressDelayDays':14},
    {**UPDATES,'stressDelayDays':'7'},
    {**UPDATES,'stressDelayDays':True},
    {**UPDATES,'stressDelayDays':366},
    {**UPDATES,'stressDelayDays':-1},
    {**UPDATES,'stressEventId':'made-up-client'},
    {**UPDATES,'stressEventId':'supplier-flexible'},
    {**UPDATES,'unknown':1},
    {},
])
def test_invalid_proposals_are_rejected(payload,bad):
    with pytest.raises(ai.InvalidProposal): ai._validate_provider_updates(payload,bad)


def test_already_applied_may_explain(payload):
    source = ai.apply_updates(payload.analysis_input, UPDATES)
    current = payload.model_copy(update={'analysis_input':source})
    assert ai._validate_provider_updates(current,{}) == {}


def test_null_does_not_mean_zero(payload):
    raw={field:None for field in ai._reply_schema(payload)['properties']['suggestedUpdates']['properties']}
    raw.update(UPDATES)
    assert ai._validate_provider_updates(payload,raw) == UPDATES


def test_one_repair_then_success(configured,payload,monkeypatch):
    calls=[]
    def fake(config,payload,correction=None):
        calls.append(correction)
        return 'Propongo una semana.', UPDATES if correction else {'stressEnabled':True}
    monkeypatch.setattr(ai,'_provider_request',fake)
    response = ai.assistant_reply(payload)
    assert len(calls)==2 and calls[1]
    assert response['mode']=='external'
    assert response['previewResult']['stressed']['projectedShortfall']=='15500.00'


def test_two_incomplete_replies_fail_without_fallback(configured,payload,monkeypatch,client):
    calls=[]
    def fake(*args, **kwargs): calls.append(1); return '7 días', {'stressEnabled':True}
    monkeypatch.setattr(ai,'_provider_request',fake)
    response=client.post('/api/assistant',json=payload.model_dump(by_alias=True,mode='json'))
    assert response.status_code==422
    assert response.json()['mode']=='error'
    assert response.json()['suggestedUpdates']=={}
    assert 'El escenario analizado tiene' not in response.text
    assert len(calls)==2


def test_http_error_visible_no_retry(configured,payload,monkeypatch,client):
    calls=[]
    def fail(*args,**kwargs): calls.append(1); raise RuntimeError('HTTP 429. Cuota agotada.')
    monkeypatch.setattr(ai,'_provider_request',fail)
    response=client.post('/api/assistant',json=payload.model_dump(by_alias=True,mode='json'))
    assert response.status_code==502
    assert '429' in response.json()['detail']
    assert response.json()['mode']=='error'
    assert calls==[1]
    assert client.get('/api/ai/status').json()['mode']=='error'


def test_no_key_is_explicit(payload,client):
    response=client.post('/api/assistant',json=payload.model_dump(by_alias=True,mode='json'))
    assert response.status_code==503
    assert response.json()['code']=='not_configured'
    assert response.json()['suggestedUpdates']=={}


def test_result_from_browser_is_not_trusted(configured,payload,monkeypatch):
    payload=payload.model_copy(update={'analysis_result':{'fake':'9999999'}})
    def fake(config,checked,**kwargs):
        assert 'fake' not in checked.analysis_result
        assert checked.analysis_result['stressed']['minimumConservativeBalance']=='20700.00'
        return 'Una semana', UPDATES
    monkeypatch.setattr(ai,'_provider_request',fake)
    assert ai.assistant_reply(payload)['previewInput']['stressScenario']['delayDays']==7


def test_check_uses_same_path(configured,monkeypatch,client):
    monkeypatch.setattr(ai,'_provider_request',lambda *a,**k: ('Propuesta',UPDATES))
    assert client.post('/api/ai/check',json={}).json()['checkPassed'] is True


def test_gemini_status_never_leaks_secret(configured,client):
    result=client.get('/api/ai/status')
    assert configured.api_key not in result.text
    assert configured.identity not in result.text
    assert result.json()['verified'] is False


def test_stale_environment_cannot_override_local_file(monkeypatch,tmp_path):
    file=tmp_path/'.env';file.write_text('AI_API_KEY=NEW_KEY_LOCAL\nAI_MODEL=gemini-3.8-flash\n',encoding='utf-8-sig')
    monkeypatch.setattr(config,'ENV_FILE',file)
    monkeypatch.setenv('AI_API_KEY','OLD_KEY_IN_TERMINAL')
    assert config.get_ai_config().api_key=='NEW_KEY_LOCAL'
    assert __import__('os').environ['AI_API_KEY']=='OLD_KEY_IN_TERMINAL'


def test_academic_instructions_are_loaded_from_project_file(monkeypatch,tmp_path):
    style_file=config.PROJECT_DIR/'test-academic-instructions.txt'
    style_file.write_text('Usa definiciones precisas y fórmulas con LaTeX.',encoding='utf-8')
    env=tmp_path/'.env'
    env.write_text('AI_API_KEY=TEST_ONLY\nAI_ASSISTANT_INSTRUCTIONS_FILE=test-academic-instructions.txt\n',encoding='utf-8')
    monkeypatch.setattr(config,'ENV_FILE',env)
    try:
        loaded=config.get_ai_config()
        assert loaded.assistant_instructions=='Usa definiciones precisas y fórmulas con LaTeX.'
        assert loaded.instructions_source=='custom-file'
        assert loaded.instructions_error is None
    finally:
        style_file.unlink(missing_ok=True)


def test_academic_instructions_cannot_escape_project(monkeypatch,tmp_path):
    outside=tmp_path/'outside.txt';outside.write_text('ignored',encoding='utf-8')
    env=tmp_path/'.env'
    env.write_text(f'AI_API_KEY=TEST_ONLY\nAI_ASSISTANT_INSTRUCTIONS_FILE={outside}\n',encoding='utf-8')
    monkeypatch.setattr(config,'ENV_FILE',env)
    loaded=config.get_ai_config()
    assert loaded.instructions_error
    assert loaded.instructions_source=='configuration-error'


def test_frontend_identifiers_match():
    static=Path(__file__).resolve().parents[1]/'app/static'
    for html,js in [('index.html','login.js'),('dashboard.html','dashboard.js'),('treasury.html','treasury.js')]:
        ids=set(re.findall(r'\bid="([^"]+)"',(static/html).read_text()))
        used=set(re.findall(r'(?:getElementById|byId)\("([^"]+)"\)',(static/'js'/js).read_text()))
        assert not used-ids


def test_chat_pages_load_local_markdown_and_latex_renderer():
    static=Path(__file__).resolve().parents[1]/'app/static'
    for page in ('treasury.html','predictions.html'):
        html=(static/page).read_text(encoding='utf-8')
        assert '/static/vendor/marked/marked.umd.js' in html
        assert '/static/vendor/dompurify/purify.min.js' in html
        assert '/static/vendor/katex/katex.min.js' in html
        assert '/static/js/rich-text.js' in html
        assert 'cdn.jsdelivr.net' not in html
    renderer=(static/'js/rich-text.js').read_text(encoding='utf-8')
    assert 'DOMPurify.sanitize' in renderer
    assert 'trust: false' in renderer
    assert 'FORBID_TAGS' in renderer


def test_wire_format_authorization_schema(configured,payload,monkeypatch):
    seen=[]
    def fake(request,timeout):
        body=json.loads(request.data)
        assert request.full_url==config.DEFAULT_URL
        assert request.headers['Authorization']=='Bearer '+configured.api_key
        assert body['response_format']['type']=='json_schema'
        assert body['model']==configured.model
        assert 'Markdown' in body['messages'][0]['content']
        assert configured.assistant_instructions in body['messages'][0]['content']
        seen.append(body)
        content=json.dumps({'answer':'Una semana', 'suggestedUpdates':UPDATES})
        return BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':content}}]}).encode())
    monkeypatch.setattr(ai,'urlopen',fake)
    assert ai._provider_request(configured,payload)[1]==UPDATES
    assert len(seen)==1


def test_raw_provider_error_not_echoed(configured,payload,monkeypatch):
    def fail(*args,**kwargs):
        raise HTTPError(config.DEFAULT_URL,403,'Forbidden',{},BytesIO(json.dumps({'error':{'message':configured.api_key,'status':'PERMISSION_DENIED'}}).encode()))
    monkeypatch.setattr(ai,'urlopen',fail)
    with pytest.raises(RuntimeError) as caught: ai._provider_request(configured,payload)
    assert configured.api_key not in str(caught.value)
    assert '403' in str(caught.value)


def test_unknown_host_not_used(payload,monkeypatch,configured):
    other=config.AIConfig('https://other.example/chat',configured.api_key,configured.model,60)
    with pytest.raises(RuntimeError): ai._provider_request(other,payload)


def test_no_redirects():
    assert ai._NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example') is None


def test_truncated_output_not_used():
    with pytest.raises(RuntimeError): ai._extract_provider_text({'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
