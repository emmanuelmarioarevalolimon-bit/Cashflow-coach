import io
import json
import zipfile
from pathlib import Path
from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,text
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateTable
from app.main import app
from app import db,workspace,document_ai,ai_service,config
from app.extract import extract_file,ExtractionError
from app.document_models import Candidate

CSV='''fecha,contraparte,monto,tipo,naturaleza,moneda,categoria,referencia
2026-08-10,Venta ya cobrada,1500.00,entrada,realizado,MXN,ventas,MOV-001
2026-08-12,Gasto ya pagado,500.00,salida,realizado,MXN,operacion,MOV-002
2026-09-20,Cliente principal,8000.00,entrada,por_cobrar,MXN,clientes,FAC-101
2026-09-24,Proveedor,3500.00,salida,por_pagar,MXN,proveedores,FAC-202
'''.encode()

def upload(client,data=CSV,name='historia.csv'):
    r=client.post('/api/documents',files={'file':(name,data,'text/csv')})
    assert r.status_code==200,r.text
    return r.json()['document']

def approve(client,doc,**kwargs):
    return client.post('/api/documents/'+doc['id']+'/confirm',json={
        'revision':doc['revision'],'confirm':True,'candidates':doc['proposal']['candidates'],'metrics':doc['proposal']['metrics'],**kwargs})


def test_upload_is_not_confirmation_or_api_call(client):
    doc=upload(client)
    assert len(doc['proposal']['candidates'])==4
    assert client.get('/api/history').json()['summary']['totalEntries']==0
    assert doc['model'] is None
    assert doc['state']=='uploaded'


def test_confirm_and_persist_history(client):
    doc=upload(client);r=approve(client,doc);assert r.status_code==200,r.text
    summary=client.get('/api/history').json()['summary']
    assert summary['totalEntries']==4
    assert summary['months']==[{'month':'2026-08','inflows':'1500.00','outflows':'500.00','netCashFlow':'1000.00'}]
    assert summary['pending']=={'receivable':'8000.00','payable':'3500.00'}
    with db.session() as s:
        assert s.scalar(select(db.Document).where(db.Document.id==doc['id'])).content==CSV
        assert s.query(db.Audit).count()>=3


def test_upload_and_confirm_idempotent(client):
    doc=upload(client);again=upload(client);assert doc['id']==again['id']
    assert approve(client,doc).status_code==200
    assert approve(client,doc).json()['alreadyConfirmed'] is True
    assert client.get('/api/history').json()['summary']['totalEntries']==4


def test_possible_duplicates_require_explicit_override(client):
    doc=upload(client);approve(client,doc)
    other=upload(client,CSV+b'\n','otra.csv')
    r=approve(client,other);assert r.status_code==409,r.text
    assert approve(client,other,allowPossibleDuplicates=True).status_code==200
    assert client.get('/api/history').json()['summary']['totalEntries']==8


def test_revision_conflict_no_writes(client):
    doc=upload(client)
    assert approve(client,doc,revision=9).status_code==409
    assert client.get('/api/history').json()['summary']['totalEntries']==0


def test_forecast_uses_only_pending_not_actual(client):
    doc=upload(client);approve(client,doc)
    r=client.post('/api/plans/from-ledger',json={'name':'Plan A','startDate':'2026-09-01','openingBalance':'10000','liquidityThreshold':'2000','days':30})
    assert r.status_code==200,r.text
    plan=r.json();assert len(plan['analysisInput']['events'])==2
    assert set(x['counterparty'] for x in plan['analysisInput']['events'])=={'Cliente principal','Proveedor'}
    assert plan['analysisInput']['interventions']=={'accelerateReceivable':None,'deferPayable':None,'creditLine':None}
    assert plan['sources']['documents']==[doc['id']]
    get=client.get('/api/plans/'+plan['id']);assert get.status_code==200
    assert get.json()['analysisInput']==plan['analysisInput']


def test_history_does_not_invent_future(client):
    doc=upload(client);approve(client,doc)
    r=client.post('/api/plans/from-ledger',json={'startDate':'2027-09-01','openingBalance':'10000','liquidityThreshold':'2000'})
    assert r.status_code==422


def test_cross_company_isolation(client,demo,monkeypatch):
    doc=upload(client);approve(client,doc)
    plan=client.post('/api/plans',json={'name':'Privado','analysisInput':demo}).json()
    # Same email cannot be used to gain access to the company; register a separate account.
    r=client.post('/api/auth/register',json={'email':'two@example.test','password':'A-long-test-password-02','company':'Empresa Dos','currency':'MXN'})
    assert r.status_code==200,r.text
    assert client.get('/api/documents/'+doc['id']).status_code==404
    assert client.get('/api/plans/'+plan['id']).status_code==404
    assert client.get('/api/documents').json()['items']==[]
    assert client.get('/api/history').json()['summary']['totalEntries']==0
    assert client.post('/api/documents/'+doc['id']+'/confirm',json={'revision':1,'confirm':True,'candidates':doc['proposal']['candidates'],'metrics':[]}).status_code==404
    assert client.post('/api/reports',json={'consentToGoogle':True,'documentIds':[doc['id']]}).status_code==404


def test_authentication_not_fake_and_logout(client):
    with db.session() as s:
        user=s.scalar(select(db.User))
        assert user.password_hash.startswith('pbkdf2-sha256$600000$')
        assert 'A-long-test-password' not in user.password_hash
    assert client.post('/api/auth/logout',json={}).status_code==200
    assert client.get('/api/history').status_code==401
    assert client.post('/api/auth/login',json={'email':'one@example.test','password':'Not-the-password-001'}).status_code==401
    r=client.post('/api/auth/login',json={'email':'one@example.test','password':'A-long-test-password-01'})
    assert r.status_code==200
    assert 'httponly' in r.headers['set-cookie'].lower()


def test_origin_and_custom_header_required(client,demo):
    assert client.post('/api/analyze',json=demo,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/analyze',json=demo,headers={'X-C1-Request':'0'}).status_code==403
    assert client.post('/api/analyze',json=demo).status_code==200


def test_http_input_validation(client,demo):
    assert client.post('/api/analyze',content=b' '*4194305,headers={'Content-Type':'application/json'}).status_code==413
    demo['events'][0]['amount']='NaN'
    assert client.post('/api/analyze',json=demo).status_code==422


def test_private_files_not_served(client):
    for path in ['/.env','/app/db.py','/local-demo.db']:
        assert client.get(path).status_code==404
    for path in ['/','/workspace','/treasury','/dashboard','/health']:
        r=client.get(path);assert r.status_code==200
        assert r.headers['cache-control']=='no-store'
        assert __import__('app.version',fromlist=['VERSION']).VERSION == r.headers['x-c1-version']


def test_not_a_valid_extension_and_signature(client):
    for name,data in [('x.exe',b'hi'),('x.pdf',b'not a pdf'),('x.xlsx',b'not a zip')]:
        assert client.post('/api/documents',files={'file':(name,data)}).status_code==422


def test_mixed_currencies_never_added(client):
    doc=upload(client,CSV.replace(b'MXN',b'USD'))
    assert approve(client,doc).status_code==422
    assert client.get('/api/history').json()['summary']['totalEntries']==0


def test_no_missing_fields_silently_imported():
    bad=b'fecha,contraparte,monto,tipo,naturaleza,moneda\n2026-08-01,A,20,entrada,realizado,MXN\nfecha_invalida,B,30,entrada,realizado,MXN\n'
    r=extract_file('x.csv',bad)
    assert len(r['candidates'])==1
    assert any('fila 3' in w for w in r['warnings'])


def test_source_quote_validation():
    item=Candidate(kind='actual',date='2026-09-01',counterparty='A',amount='10',direction='inflow',currency='MXN',category='venta',source='fila 1',quote='inventado')
    with pytest.raises(ai_service.AssistantFailure):document_ai.validate_sources([item],[{'source':'fila 1','text':'dato real'}])


def test_gemini_extraction_staged_only(client,monkeypatch):
    doc=upload(client)
    def fake(extraction,currency):
        return {'summary':'Documento de prueba','warnings':[],'candidates':extraction['candidates'],'metrics':[]},'MODELO_SIMULADO'
    monkeypatch.setattr(workspace,'analyze_document',fake)
    r=client.post('/api/documents/'+doc['id']+'/analyze',json={'consentToGoogle':True,'revision':1})
    assert r.status_code==200,r.text
    assert r.json()['revision']==2 and r.json()['state']=='analyzed'
    assert client.get('/api/history').json()['summary']['totalEntries']==0
    assert approve(client,doc).status_code==409


def test_document_ai_consent_required(client):
    doc=upload(client)
    assert client.post('/api/documents/'+doc['id']+'/analyze',json={'consentToGoogle':False,'revision':1}).status_code==422
    assert client.post('/api/reports',json={'consentToGoogle':False}).status_code==422


def test_report_uses_python_plan_and_persists_sources(client,demo,monkeypatch):
    doc=upload(client);approve(client,doc)
    plan=client.post('/api/plans',json={'name':'Plan guardado','analysisInput':demo}).json()
    seen=[]
    def fake(context):
        seen.append(context)
        return {'title':'Informe simulado','summary':'Texto de prueba, no respuesta real de Gemini.','sections':[{'heading':'Caja','text':'Revisar los pendientes.','sources':['HISTORIAL']}],'limitations':['Prueba con proveedor simulado.']},'MODELO_SIMULADO'
    monkeypatch.setattr(workspace,'narrate_report',fake)
    r=client.post('/api/reports',json={'consentToGoogle':True,'documentIds':[doc['id']],'planId':plan['id']})
    assert r.status_code==200,r.text
    assert seen[0]['plan'] is not None
    assert 'optimize_interventions' in seen[0]['toolTrace']
    result=r.json();assert 'DOC:'+doc['id'] in result['content']['context']['sources']
    download=client.get('/api/reports/'+result['id']+'/download')
    assert download.status_code==200 and 'attachment' in download.headers['content-disposition']
    assert '1000.00' in download.text
    assert '<h2>Pronóstico calculado por Python · MXN</h2>' in download.text


def test_report_provider_error_not_hidden(client,monkeypatch):
    doc=upload(client)
    def fail(*a,**k):raise ai_service.AssistantFailure('Prueba: sin cuota')
    monkeypatch.setattr(workspace,'narrate_report',fail)
    r=client.post('/api/reports',json={'consentToGoogle':True,'documentIds':[doc['id']]})
    assert r.status_code==502
    assert 'sin cuota' in r.text
    assert client.get('/api/reports').json()['items']==[]


def test_ai_extraction_schema_missing_and_evidence(monkeypatch):
    extraction=extract_file('x.csv',CSV)
    candidate=dict(extraction['candidates'][0]);candidate.pop('confidence')
    monkeypatch.setattr(document_ai,'request_json',lambda *a:({'summary':'s','warnings':[],'candidates':[candidate],'metrics':[]},'fake'))
    r,_=document_ai.analyze_document(extraction,'MXN');assert len(r['candidates'])==1
    candidate['source']='página que no existe'
    with pytest.raises(ai_service.AssistantFailure):document_ai.analyze_document(extraction,'MXN')


def test_report_rejects_invented_citations(monkeypatch):
    monkeypatch.setattr(document_ai,'request_json',lambda *a:({'title':'t','summary':'s','sections':[{'heading':'h','text':'t','sources':['NO_EXISTE']}],'limitations':[]},'fake'))
    with pytest.raises(ai_service.AssistantFailure):document_ai.narrate_report({'sources':{'HISTORIAL':'yes'}})


def test_pdf_text_and_scan_errors():
    from reportlab.pdfgen import canvas
    stream=io.BytesIO();c=canvas.Canvas(stream);c.drawString(50,750,'Caja realizada: 1000.00 MXN.');c.save()
    out=extract_file('texto.pdf',stream.getvalue());assert '1000.00' in out['units'][0]['text']
    stream=io.BytesIO();c=canvas.Canvas(stream);c.showPage();c.save()
    with pytest.raises(ExtractionError,match='escaneado'):extract_file('blanco.pdf',stream.getvalue())


def test_docx_text_without_office_execution():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Venta documentada de prueba</w:t></w:r></w:p></w:body></w:document>')
    assert 'Venta' in extract_file('simple.docx',stream.getvalue())['units'][0]['text']


def test_xlsx_macro_rejection():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('xl/vbaProject.bin',b'no execution')
    with pytest.raises(ExtractionError,match='macros'):extract_file('macro.xlsx',stream.getvalue())


def test_mssql_schema_compilation_and_connection_options(monkeypatch):
    dialect=mssql.dialect(deprecate_large_types=True)
    sql='\n'.join(str(CreateTable(t).compile(dialect=dialect)) for t in db.Base.metadata.sorted_tables)
    assert 'VARBINARY(max)' in sql
    assert 'NVARCHAR(max)' in sql
    assert 'NUMERIC(19, 4)' in sql
    monkeypatch.setenv('DB_BACKEND','mssql');monkeypatch.setenv('DB_SERVER','localhost\\SQLEXPRESS')
    monkeypatch.setenv('DB_AUTH','sql');monkeypatch.setenv('DB_USER','app');monkeypatch.setenv('DB_PASSWORD','fake;not_a_secret}')
    url=db.build_url();connection=url.query['odbc_connect']
    assert url.drivername=='mssql+pyodbc'
    assert 'Encrypt=yes' in connection and 'TrustServerCertificate=no' in connection
    assert 'PWD={fake;not_a_secret}}}' in connection


def test_mssql_configuration_never_falls_back(monkeypatch):
    monkeypatch.setenv('DB_BACKEND','mssql');monkeypatch.setenv('DB_SERVER','')
    with pytest.raises(RuntimeError,match='DB_SERVER'):db.build_url()


def test_generated_xlsx_template_and_csv_have_same_events():
    root=Path(__file__).resolve().parents[1]/'examples'
    a=extract_file('ejemplo.xlsx',(root/'movimientos-ejemplo.xlsx').read_bytes())
    b=extract_file('ejemplo.csv',(root/'movimientos-ejemplo.csv').read_bytes())
    assert len(a['candidates'])==len(b['candidates'])==4
    keys=['date','kind','amount','direction','counterparty','currency']
    assert [{k:x[k] for k in keys} for x in a['candidates']]==[{k:x[k] for k in keys} for x in b['candidates']]


def test_chat_company_currency_overrides_browser(client,monkeypatch):
    from app import main
    captured={}
    def fake(payload):
        captured['currency']=payload.currency
        return {'answer':'test','suggestedUpdates':{},'mode':'external','model':'test'}
    monkeypatch.setattr(main,'assistant_reply',fake)
    demo=client.get('/api/demo').json()
    r=client.post('/api/assistant',json={'message':'Explica','analysisInput':demo,'currency':'USD'})
    assert r.status_code==200,r.text
    assert captured['currency']=='MXN'


def test_current_version_guard_and_no_hardcoded_planner_currency(client):
    js=client.get('/static/js/treasury.js').text
    assert '3.0.0-integrada' not in js
    assert 'currency: state.currency' in js
    assert '4.0.0-sqlserver-piloto' not in js
    assert '6.0.0-web-integrada' in js
