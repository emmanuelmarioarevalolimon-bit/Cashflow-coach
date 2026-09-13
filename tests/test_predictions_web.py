"""Pruebas de integración: SQLite temporal, motor real y respuestas Gemini simuladas."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import predictions as p, document_ai, db
from app.main import app
from app.version import VERSION


def demo_input(client):
    data=client.get('/api/predictions/demo-input').json()['input']
    data['config'].update(model='seasonal_mean',simulations=300)
    return data


def run(client,data=None):
    r=client.post('/api/predictions/analyze',json={'input':data or demo_input(client),'name':'Prueba histórica','source':'synthetic'})
    assert r.status_code==200,r.text
    return r.json()


def test_predictions_require_login(client):
    with TestClient(app,headers={'X-C1-Request':'1'}) as anon:
        assert anon.get('/api/predictions').status_code==401
        assert anon.post('/api/predictions/analyze',json={}).status_code==401


def test_demo_does_not_modify_ledger_or_call_gemini(client):
    d=client.get('/api/predictions/demo-input').json()
    assert d['source']=='synthetic'
    assert d['input']['scenario_actions']==[]
    assert client.get('/api/history').json()['summary']['totalEntries']==0


def test_real_engine_saved_and_reopened(client):
    d=run(client)
    assert d['result']['horizon']['days']==30
    assert len(d['result']['scenario']['projection'])==30
    assert 0<=d['result']['scenario']['risk']['pdAnyDay']['probability']<=1
    assert client.get('/api/predictions/'+d['id']).json()['result']==d['result']
    assert client.get('/api/predictions').json()['items'][0]['id']==d['id']
    assert client.get('/api/plans').json()['items']==[]
    download=client.get('/api/predictions/'+d['id']+'/download')
    assert download.status_code==200 and download.json()['id']==d['id']
    assert client.get('/api/plans/'+d['id']).status_code==422


@pytest.mark.parametrize('field,value',[('history_complete',False),('simulations',True),('simulations',50000),('days',366),('model','arbitrary-code'),('max_actions','bad')])
def test_invalid_configuration_not_saved(client,field,value):
    data=demo_input(client);data['config'][field]=value
    r=client.post('/api/predictions/analyze',json={'input':data})
    assert r.status_code==422,r.text
    assert client.get('/api/predictions').json()['items']==[]


def test_currency_mismatch(client):
    d=demo_input(client);d['config']['currency']='EUR'
    assert client.post('/api/predictions/analyze',json={'input':d}).status_code==422


def test_no_cross_company_access(client):
    d=run(client)
    with TestClient(app,headers={'X-C1-Request':'1'}) as other:
        assert other.post('/api/auth/register',json={'email':'two@example.test','password':'Another-good-password','company':'Dos','currency':'MXN'}).status_code==200
        for suffix in ('','/download'):
            assert other.get('/api/predictions/'+d['id']+suffix).status_code==404
        assert other.post('/api/predictions/'+d['id']+'/report',json={'consentToGoogle':True}).status_code==404
        assert other.get('/api/predictions').json()['items']==[]


def test_provider_missing_shows_error_not_fake_reply(client):
    d=run(client)
    r=client.post('/api/predictions/'+d['id']+'/assistant',json={'message':'Hola','consentToGoogle':True})
    assert r.status_code==503
    assert r.json()['mode']=='error' and r.json()['code']=='not_configured'


def test_gemini_proposes_and_confirmed_engine_recalculates(client,monkeypatch):
    d=run(client)
    def fake(system,context,schema):
        assert context['result']['horizon']['days']==30
        return {'answer':'Propongo un retraso de siete días. Confirma para calcular.',
                'proposal':{'horizonDays':None,'threshold':None,'eventId':'factura-principal','delayDays':7}},'gemini-simulado-test'
    monkeypatch.setattr(document_ai,'request_json',fake)
    r=client.post('/api/predictions/'+d['id']+'/assistant',json={'message':'mi cliente se tarda una semana','consentToGoogle':True})
    assert r.status_code==200,r.text
    assert len(client.get('/api/predictions').json()['items'])==1
    proposal=r.json()['proposal'];assert proposal['delayDays']==7
    r=client.post('/api/predictions/'+d['id']+'/apply',json={'proposal':proposal,'name':'Escenario confirmado'})
    assert r.status_code==200,r.text
    new=r.json()
    assert new['id']!=d['id']
    assert new['input']['scenario_actions'][0]['days']==7
    assert new['result']['inputHash']!=d['result']['inputHash']
    assert client.get('/api/predictions/'+d['id']).json()['input']['scenario_actions']==[]
    assert client.get('/api/history').json()['summary']['totalEntries']==0


def test_atomic_gemini_proposal(client,monkeypatch):
    d=run(client)
    monkeypatch.setattr(document_ai,'request_json',lambda *args:({'answer':'Son siete días','proposal':{'eventId':'factura-principal'}},'mock'))
    r=client.post('/api/predictions/'+d['id']+'/assistant',json={'message':'una semana','consentToGoogle':True})
    assert r.status_code==422 and r.json()['mode']=='error'
    assert len(client.get('/api/predictions').json()['items'])==1


def test_consent_and_unknown_actions_rejected(client):
    d=run(client)
    assert client.post('/api/predictions/'+d['id']+'/assistant',json={'message':'hola','consentToGoogle':False}).status_code==422
    assert client.post('/api/predictions/'+d['id']+'/apply',json={'proposal':{'sql':'DROP TABLE companies'}}).status_code==422
    assert client.post('/api/predictions/'+d['id']+'/apply',json={'proposal':{'eventId':'renta-pendiente','delayDays':7}}).status_code==422


def test_predictive_report_saved_download_escaped(client,monkeypatch):
    d=run(client)
    def fake(system,context,schema):
        assert context['prediction']['horizon']['days']==30
        assert context['predictionSource']['type']=='synthetic'
        return {'title':'Informe <script>alert(1)</script>','summary':'Resumen simulado; cálculos reales de Python.',
         'sections':[{'heading':'Liquidez','text':'Revise el riesgo intermedio.','sources':['PREDICCION:'+d['id']]}],
         'limitations':['Datos sintéticos; no es una garantía.']},'gemini-simulado-test'
    monkeypatch.setattr(document_ai,'request_json',fake)
    r=client.post('/api/predictions/'+d['id']+'/report',json={'consentToGoogle':True})
    assert r.status_code==200,r.text
    ident=r.json()['id'];html=client.get('/api/reports/'+ident+'/download').text
    assert 'Predicción estadística' in html
    assert '<script>alert' not in html
    assert '&lt;script&gt;' in html
    assert 'Riesgo algún día' in html


def test_history_snapshot_and_coverage(client):
    from app.db import Company,Document,LedgerEntry,uid
    with db.session() as s:
        company=s.query(Company).one();user=s.query(db.User).one();doc=Document(id=uid(),company_id=company.id,user_id=user.id,name='historia.csv',sha256='t'*64,extension='csv',content=b'demo',extraction_json='{}')
        s.add(doc);s.flush()
        for i,(kind,day) in enumerate([('actual',date(2026,8,1)),('actual',date(2026,8,31)),('receivable',date(2026,9,10))]):
            s.add(LedgerEntry(company_id=company.id,document_id=doc.id,source_key=str(i),source_location='fila',source_quote='ejemplo',kind=kind,event_date=day,counterparty='Cliente',amount=1000,direction='inflow',currency='MXN',category='ventas',confidence=0.7,fingerprint=str(i)))
        s.commit()
    r=client.post('/api/predictions/from-history',json={'historyStart':'2026-08-01','startDate':'2026-09-01','openingBalance':'10000','liquidityThreshold':'2000','days':30})
    assert r.status_code==200,r.text
    data=r.json()['input']
    assert len(data['history'])==2 and len(data['planned_events'])==1
    assert data['config']['history_complete'] is False
    assert data['planned_events'][0]['collection_probability']==1
    assert data['planned_events'][0]['history_series_key']
    assert client.post('/api/predictions/analyze',json={'input':data}).status_code==422


def test_single_calculation_slot(client):
    with p.SLOT:
        assert client.post('/api/predictions/analyze',json={'input':demo_input(client)}).status_code==429


def test_page_links_version_and_no_secrets(client):
    r=client.get('/predictions')
    assert r.status_code==200 and r.headers['x-c1-version']==VERSION
    assert 'inputJson' in r.text and 'Gemini' in r.text
    assert 'AI_API_KEY=' not in r.text
    for path in ['/workspace','/dashboard','/treasury']:assert '/predictions' in client.get(path).text
