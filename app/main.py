from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from .ai_service import AssistantFailure, assistant_reply, check_connection
from .config import ai_status
from .models import AnalyzeRequest, AssistantRequest
from .service import analyze, demo_payload
from .version import VERSION
from .db import init_db, setting, session, audit
from .security import router as auth_router, get_actor, bootstrap_initial_admin
from .workspace import router as workspace_router
from .predictions import router as predictions_router
from .calendar_api import router as calendar_router

STATIC_DIR=Path(__file__).resolve().parent/'static'
INSTANCE=uuid.uuid4().hex[:10]

@asynccontextmanager
async def lifespan(app):
    try:
        init_db()
        bootstrap_initial_admin()
    except Exception as exc:
        raise RuntimeError('No se pudo inicializar SQL. Revisa instancia, permisos, ODBC y certificado. Ejecuta python -m app.db --init. No se usó otra base de datos.') from None
    yield

app=FastAPI(title='COMPRIA',version=VERSION,lifespan=lifespan,
    description='Piloto con SQL Server, identidad de aplicación, revisión documental y Gemini. No es una conexión bancaria.')
app.mount('/static',StaticFiles(directory=STATIC_DIR),name='static')
app.include_router(auth_router);app.include_router(workspace_router);app.include_router(predictions_router);app.include_router(calendar_router)

@app.middleware('http')
async def guardrails(request:Request,call_next):
    path=request.url.path
    unsafe=request.method in ('POST','PUT','PATCH','DELETE')
    if unsafe:
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail':'Origen no permitido.'},status_code=403)
        if request.headers.get('x-c1-request')!='1':
            return JSONResponse({'detail':'Falta el encabezado de protección X-C1-Request.'},status_code=403)
        multipart=path=='/api/documents' and request.method=='POST'
        content_type=request.headers.get('content-type','').lower()
        if ('multipart/form-data' if multipart else 'application/json') not in content_type:
            return JSONResponse({'detail':'Tipo de contenido no admitido.'},status_code=415)
        limit=10*1024*1024+65536 if multipart else 4*1024*1024
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>limit:return JSONResponse({'detail':'Solicitud mayor que el límite permitido.'},status_code=413)
        request._body=bytes(data)
    public=(path in ('/','/health','/api/auth/login','/api/auth/register') or path.startswith('/static/'))
    if not public:
        try:actor=get_actor(request)
        except SQLAlchemyError:return JSONResponse({'detail':'Base de datos no disponible.'},status_code=503)
        if not actor:
            if path in ('/workspace','/dashboard','/treasury','/predictions','/calendar'):return RedirectResponse('/')
            return JSONResponse({'detail':'Inicia sesión en esta aplicación.'},status_code=401)
        request.state.user=actor
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-C1-Version']=VERSION
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    if path not in ('/docs','/redoc'):
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,exc:RequestValidationError):
    return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg']} for e in exc.errors()]},status_code=422)

@app.exception_handler(SQLAlchemyError)
async def database_error(request:Request,exc:SQLAlchemyError):
    return JSONResponse({'detail':'La operación de base de datos falló. No se expusieron credenciales; revisa la conexión y los permisos.'},status_code=503)

@app.exception_handler(AssistantFailure)
async def assistant_error(request:Request,exc:AssistantFailure):
    return JSONResponse({'version':VERSION,'mode':'error','code':exc.code,'label':'Gemini: solicitud no completada',
                         'detail':str(exc),'suggestedUpdates':{}},status_code=exc.status)

@app.get('/',include_in_schema=False)
def login_page():return FileResponse(STATIC_DIR/'index.html')
@app.get('/dashboard',include_in_schema=False)
def dashboard_page():return FileResponse(STATIC_DIR/'dashboard.html')
@app.get('/treasury',include_in_schema=False)
def treasury_page():return FileResponse(STATIC_DIR/'treasury.html')
@app.get('/workspace',include_in_schema=False)
def workspace_page():return FileResponse(STATIC_DIR/'workspace.html')
@app.get('/predictions',include_in_schema=False)
def predictions_page():return FileResponse(STATIC_DIR/'predictions.html')
@app.get('/calendar',include_in_schema=False)
def calendar_page():return FileResponse(STATIC_DIR/'calendar.html')
@app.get('/health')
def health():return {'status':'ok','version':VERSION,'instance':INSTANCE}
@app.get('/api/demo')
def get_demo():return demo_payload(date.today())
@app.get('/api/ai/status')
def get_ai_status():return ai_status()
@app.post('/api/ai/check')
def check_ai():return check_connection()
@app.post('/api/assistant')
def post_assistant(payload:AssistantRequest,request:Request):
    from .db import Company
    with session() as db:
        currency = db.get(Company, request.state.user.company_id).currency
    payload = payload.model_copy(update={"currency": currency})
    try:
        answer=assistant_reply(payload)
        with session() as db:
            audit(db,request.state.user,'chat_tools_preview','current-plan',{'changedFields':list(answer.get('suggestedUpdates',{})),
                 'hasPreview':bool(answer.get('previewResult')),'model':answer.get('model')});db.commit()
        return answer
    except (ValueError,KeyError):raise HTTPException(400,'Revisa las fechas y eventos enviados.') from None
@app.post('/api/analyze')
def post_analyze(payload:AnalyzeRequest):
    try:return analyze(payload)
    except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc)) from None
