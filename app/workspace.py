"""Rutas con alcance de empresa derivado SOLO de la sesión autenticada."""
from __future__ import annotations
from datetime import date,timedelta
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Response
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from .db import (session,Company,Document,LedgerEntry,Metric,Plan,Report,Audit,audit,uid,now,
                 dumps,loads,check_db)
from .models import AnalyzeRequest
from .document_models import Approval, Consent, PlanSave, LedgerPlan, ReportRequest
from .extract import extract_file, ExtractionError, MAX_BYTES
from .document_ai import analyze_document,narrate_report
from .service import analyze
from .version import VERSION

router=APIRouter(prefix='/api',tags=['Documentos e historial'])

def owned(db,model,ident,user):
    obj=db.scalar(select(model).where(model.id==ident,model.company_id==user.company_id))
    if not obj:raise HTTPException(404,'El recurso no existe en tu empresa.')
    return obj

def doc_info(doc,full=False):
    result={'id':doc.id,'name':doc.name,'state':doc.state,'revision':doc.revision,
            'createdAt':doc.created_at.isoformat(),'model':doc.ai_model,'bytes':len(doc.content)}
    if full:result.update(extraction=loads(doc.extraction_json),proposal=loads(doc.proposal_json),confirmed=loads(doc.confirmed_json))
    return result

@router.get('/database/status')
def database_status(request: Request):
    return {**check_db(),'version':VERSION,'documentAnalysisVersion':2}

@router.get('/documents')
def list_docs(request: Request):
    with session() as db:
        docs=db.scalars(select(Document).where(Document.company_id==request.state.user.company_id).order_by(Document.created_at.desc()).limit(100)).all()
        return {'items':[doc_info(x) for x in docs],'limit':100}

@router.post('/documents')
def upload(request: Request,file: UploadFile=File(...)):
    user=request.state.user
    content=file.file.read(MAX_BYTES+1)
    name=Path((file.filename or 'archivo').replace('\\','/')).name
    if not name or len(name)>180:raise HTTPException(400,'Nombre de archivo inválido o demasiado largo.')
    try:extraction=extract_file(name,content)
    except ExtractionError as exc:raise HTTPException(422,str(exc)) from None
    except Exception:raise HTTPException(422,'No se pudo extraer este documento; revisa formato y límites.') from None
    sha=hashlib.sha256(content).hexdigest()
    with session() as db:
        duplicate=db.scalar(select(Document).where(Document.company_id==user.company_id,Document.sha256==sha))
        if duplicate:return {'duplicate':True,'document':doc_info(duplicate,True)}
        if db.scalar(select(func.count()).select_from(Document).where(Document.company_id==user.company_id))>=100:
            raise HTTPException(422,'Límite del piloto: 100 documentos por empresa. Archiva fuera del piloto o amplía el almacenamiento antes de continuar.')
        proposal={'summary':'Extracción local: pendiente de revisión; no se consultó a Gemini.',
                  'warnings':extraction['warnings'],'candidates':extraction['candidates'],'metrics':[]}
        doc=Document(id=uid(),company_id=user.company_id,user_id=user.id,name=name,sha256=sha,
                     extension=name.rsplit('.',1)[-1].lower(),content=content,
                     extraction_json=dumps(extraction),proposal_json=dumps(proposal))
        db.add(doc);db.flush();audit(db,user,'document_uploaded',doc.id,{'sha256':sha,'bytes':len(content)})
        try:db.commit()
        except IntegrityError:raise HTTPException(409,'Ese documento ya se está importando. Actualiza la lista.') from None
        return {'duplicate':False,'document':doc_info(doc,True)}

@router.get('/documents/{ident}')
def document_detail(ident: str,request: Request):
    with session() as db:return doc_info(owned(db,Document,ident,request.state.user),True)

@router.post('/documents/{ident}/analyze')
def analyze_doc(ident:str,payload:Consent,request:Request):
    user=request.state.user
    with session() as db:
        doc=owned(db,Document,ident,user)
        if doc.revision!=payload.revision or doc.state=='confirmed':raise HTTPException(409,'Documento confirmado o modificado. Recarga antes de continuar.')
        extraction=loads(doc.extraction_json);currency=db.get(Company,user.company_id).currency
    analysis_input=dict(extraction)
    analysis_input['_financial_analysis_options']={
        'include_external_context':payload.include_external_context,
        'opening_balance':payload.opening_balance,
        'liquidity_threshold':payload.liquidity_threshold,
        'default_collection_probability':payload.default_collection_probability,
        'simulations':payload.simulations,
    }
    proposal,model=analyze_document(analysis_input,currency)
    with session() as db:
        result=db.execute(update(Document).where(Document.id==ident,Document.company_id==user.company_id,
              Document.revision==payload.revision,Document.state!='confirmed').values(
              proposal_json=dumps(proposal),ai_model=model,state='analyzed',revision=payload.revision+1))
        if result.rowcount!=1:raise HTTPException(409,'El documento cambió durante el análisis. No se sobrescribió.')
        financial=proposal.get('financialAnalysis',{})
        audit(db,user,'document_ai_analyzed',ident,{'model':model,'consentToGoogle':True,
              'externalContext':payload.include_external_context,
              'tools':financial.get('toolTrace',[])})
        db.commit();return doc_info(owned(db,Document,ident,user),True)


def fingerprint(item):
    # Coincidencias son POSIBLES duplicados. Nunca se borran filas automáticamente.
    values=[str(item.date),item.counterparty.strip().lower(),format(item.amount,'f'),
            item.direction,item.kind,item.currency,item.reference.strip().lower()]
    values[2]=str(item.amount.quantize(Decimal('.01')))
    return hashlib.sha256(dumps(values).encode()).hexdigest()

@router.post('/documents/{ident}/confirm')
def confirm_doc(ident:str,payload:Approval,request:Request):
    user=request.state.user
    if not payload.candidates and not payload.metrics:raise HTTPException(422,'No hay movimientos ni métricas para confirmar.')
    with session() as db:
        doc=owned(db,Document,ident,user)
        if doc.state=='confirmed':return {'alreadyConfirmed':True,'id':ident}
        if doc.revision!=payload.revision:raise HTTPException(409,'La propuesta cambió. Recarga el documento.')
        currency=db.get(Company,user.company_id).currency
        source_locations={u['source'] for u in loads(doc.extraction_json)['units']}
        for item in [*payload.candidates,*payload.metrics]:
            if item.source not in source_locations:raise HTTPException(422,'Una referencia no pertenece a este documento.')
        if any(item.currency!=currency for item in payload.candidates):
            raise HTTPException(422,'La moneda de todos los movimientos debe coincidir con la empresa. No se convierte moneda automáticamente.')
        fps=[fingerprint(x) for x in payload.candidates]
        existing=set()
        # SQL Server tiene un máximo de parámetros; evitar IN con miles de entradas.
        for start in range(0,len(fps),500):
            existing.update(db.scalars(select(LedgerEntry.fingerprint).where(LedgerEntry.company_id==user.company_id,LedgerEntry.fingerprint.in_(fps[start:start+500]))).all())
        possible=bool(existing) or len(fps)!=len(set(fps))
        if possible and not payload.allowPossibleDuplicates:
            raise HTTPException(409,'Hay posibles duplicados por fecha, monto, naturaleza, contraparte y referencia. Revisa las filas y confirma la excepción solo si son operaciones distintas.')
        result=db.execute(update(Document).where(Document.id==ident,Document.company_id==user.company_id,
            Document.revision==payload.revision,Document.state!='confirmed').values(state='confirmed',
            revision=payload.revision+1,confirmed_json=dumps(payload.model_dump(mode='json'))))
        if result.rowcount!=1:raise HTTPException(409,'El documento ya cambió. Recarga.')
        for i,item in enumerate(payload.candidates):
            db.add(LedgerEntry(company_id=user.company_id,document_id=ident,source_key=f'{ident}:{i}',
                source_location=item.source,source_quote=item.quote,reference=item.reference,kind=item.kind,
                event_date=item.date,counterparty=item.counterparty,amount=item.amount,direction=item.direction,
                currency=item.currency,category=item.category,confidence=item.confidence,fingerprint=fps[i]))
        for item in payload.metrics:
            db.add(Metric(company_id=user.company_id,document_id=ident,name=item.name,
                period_start=item.period_start,period_end=item.period_end,value=item.value,unit=item.unit,
                source_location=item.source,source_quote=item.quote))
        audit(db,user,'document_confirmed',ident,{'entries':len(payload.candidates),'metrics':len(payload.metrics),'duplicateOverride':possible})
        db.commit()
        return {'id':ident,'entries':len(payload.candidates),'metrics':len(payload.metrics),'alreadyConfirmed':False}


def entry_dict(x):
    return {'id':x.id,'documentId':x.document_id,'date':x.event_date.isoformat(),'kind':x.kind,
            'counterparty':x.counterparty,'amount':format(x.amount.quantize(Decimal('.01')),'f'),
            'direction':x.direction,'currency':x.currency,'source':x.source_location,'reference':x.reference}


def historical_summary(db,user):
    all_entries=db.scalars(select(LedgerEntry).where(LedgerEntry.company_id==user.company_id).order_by(LedgerEntry.event_date)).all()
    buckets={};pending={'receivable':Decimal(0),'payable':Decimal(0)}
    for x in all_entries:
        if x.kind!='actual':pending[x.kind]+=x.amount;continue
        k=x.event_date.strftime('%Y-%m');v=buckets.setdefault(k,{'inflow':Decimal(0),'outflow':Decimal(0)})
        v[x.direction]+=x.amount
    months=[{'month':k,'inflows':format(v['inflow'],'.2f'),'outflows':format(v['outflow'],'.2f'),
             'netCashFlow':format(v['inflow']-v['outflow'],'.2f')} for k,v in sorted(buckets.items())]
    return {'months':months,'pending':{k:format(v,'.2f') for k,v in pending.items()},'totalEntries':len(all_entries),
            'currency':db.get(Company,user.company_id).currency,
            'notice':'Flujo neto, no saldo bancario. Solo registros confirmados. Los indicadores contables no se suman a la caja.'}

@router.get('/history')
def history(request:Request):
    user=request.state.user
    with session() as db:
        rows=db.scalars(select(LedgerEntry).where(LedgerEntry.company_id==user.company_id).order_by(LedgerEntry.event_date.desc()).limit(500)).all()
        metrics=db.scalars(select(Metric).where(Metric.company_id==user.company_id).order_by(Metric.period_end.desc()).limit(300)).all()
        metric_count=db.scalar(select(func.count()).select_from(Metric).where(Metric.company_id==user.company_id))
        return {'summary':historical_summary(db,user),'entries':[entry_dict(x) for x in rows],'displayLimit':500,
                'metricDisplayLimit':300,'metricCount':metric_count,
                'metrics':[{'name':m.name,'periodStart':str(m.period_start),'periodEnd':str(m.period_end),
                            'value':str(m.value),'unit':m.unit,'documentId':m.document_id,'source':m.source_location} for m in metrics]}


def save_plan(db,user,name,source,sources):
    result=analyze(source)
    plan=Plan(id=uid(),company_id=user.company_id,user_id=user.id,name=name,
              input_json=dumps(source.model_dump(by_alias=True,mode='json')),result_json=dumps(result),
              sources_json=dumps(sources),engine_version=VERSION)
    db.add(plan);audit(db,user,'analysis_saved',plan.id,{'source':sources.get('type')});db.commit()
    return {'id':plan.id,'name':plan.name,'analysisInput':loads(plan.input_json),'result':result,'sources':sources}

@router.post('/plans')
def save_analysis(payload:PlanSave,request:Request):
    with session() as db:return save_plan(db,request.state.user,payload.name,payload.analysisInput,{'type':'manual_snapshot'})

@router.post('/plans/from-ledger')
def plan_from_ledger(payload:LedgerPlan,request:Request):
    user=request.state.user;end=payload.startDate+timedelta(days=payload.days-1)
    with session() as db:
        rows=db.scalars(select(LedgerEntry).where(LedgerEntry.company_id==user.company_id,LedgerEntry.kind!='actual',
                        LedgerEntry.event_date>=payload.startDate,LedgerEntry.event_date<=end).order_by(LedgerEntry.event_date)).all()
        if not rows:raise HTTPException(422,'No hay cobros/pagos pendientes confirmados en ese horizonte. La historia realizada no se repite como pronóstico.')
        if len(rows)>500:raise HTTPException(422,'Más de 500 eventos pendientes: reduce el horizonte.')
        source=AnalyzeRequest.model_validate({'openingBalance':str(payload.openingBalance),'liquidityThreshold':str(payload.liquidityThreshold),
            'startDate':str(payload.startDate),'days':payload.days,'maxActions':2,'interventions':{},
            'events':[{'id':x.id,'counterparty':x.counterparty,'amount':str(x.amount),'direction':x.direction,
                       'expectedDate':str(x.event_date),'category':x.category,'confidence':str(x.confidence),'recurring':False} for x in rows],
            'stressScenario':None})
        return save_plan(db,user,payload.name,source,{'type':'confirmed_pending','documents':list(set(x.document_id for x in rows)),
                'ledgerIds':[x.id for x in rows],
                'notice':'Saldo inicial declarado antes de los movimientos de la fecha de inicio. Históricos y vencidos anteriores se excluyen; no se infieren recurrencias. Configura las intervenciones en el planificador.'})

@router.get('/plans')
def list_plans(request:Request):
    with session() as db:
        rows=db.scalars(select(Plan).where(Plan.company_id==request.state.user.company_id,Plan.engine_version!='predictive-6.0-web').order_by(Plan.created_at.desc()).limit(100)).all()
        return {'items':[{'id':x.id,'name':x.name,'createdAt':str(x.created_at),'engineVersion':x.engine_version} for x in rows]}

@router.get('/plans/{ident}')
def get_plan(ident:str,request:Request):
    with session() as db:
        p=owned(db,Plan,ident,request.state.user)
        if p.engine_version=='predictive-6.0-web':raise HTTPException(422,'Abre este análisis en Predicción avanzada.')
        return {'id':p.id,'name':p.name,'analysisInput':loads(p.input_json),'result':loads(p.result_json),'sources':loads(p.sources_json)}

@router.post('/reports')
def build_report(payload:ReportRequest,request:Request):
    user=request.state.user
    with session() as db:
        docs=[owned(db,Document,ident,user) for ident in dict.fromkeys(payload.documentIds)]
        summary=historical_summary(db,user)
        plan=owned(db,Plan,payload.planId,user) if payload.planId else None
        if plan and plan.engine_version=='predictive-6.0-web':raise HTTPException(422,'Genera el informe desde Predicción avanzada.')
        # Recalcular desde entradas almacenadas, nunca confiar en cifras enviadas por el cliente.
        result=analyze(AnalyzeRequest.model_validate(loads(plan.input_json))) if plan else None
        sources={'HISTORIAL':'Registros confirmados de caja, agrupados por mes por Python.'}
        doc_context=[]
        for d in docs:
            key='DOC:'+d.id;sources[key]=d.name+' (estado: '+d.state+')'
            # Las unidades se conservan con localizador; sin recortes silenciosos.
            doc_context.append({'sourceId':key,'name':d.name,'state':d.state,'units':loads(d.extraction_json)['units']})
        if len(dumps(doc_context))>120000:
            raise HTTPException(422,'Los documentos elegidos exceden el contexto de este informe. Selecciona menos documentos.')
        metrics=db.scalars(select(Metric).where(Metric.company_id==user.company_id).order_by(Metric.period_end.desc()).limit(300)).all()
        metric_count=db.scalar(select(func.count()).select_from(Metric).where(Metric.company_id==user.company_id))
        metric_rows=[{'name':m.name,'value':str(m.value),'unit':m.unit,'period':f'{m.period_start} / {m.period_end}',
                     'documentId':m.document_id,'source':m.source_location} for m in metrics]
        if metrics:sources['METRICAS']='Observaciones confirmadas; no sumadas entre periodos/documentos.'
        if plan:sources['PLAN:'+plan.id]=plan.name
        if not docs and not summary['totalEntries'] and not plan:raise HTTPException(422,'Carga documentos, confirma registros o guarda un plan antes de crear un informe.')
        context={'sources':sources,'quantitative':summary,'metrics':metric_rows,'documents':doc_context,
                 'metricNotice':f'Se incluyen {len(metrics)} de {metric_count} observaciones confirmadas, ordenadas por fecha final descendente. No se suman ni concilian documentos.',
                 'plan':result,'planId':plan.id if plan else None,
                 'toolTrace':['historical_cash_totals']+(['forecast_cash_flow','configured_delay_scenario','optimize_interventions'] if plan else [])}
        # Retener evidencia exacta del informe: referencias a registros y versiones.
        context['snapshotAt']=now().isoformat()
        context['documentVersions']={d.id:d.revision for d in docs}
    narrative,model=narrate_report(context)
    with session() as db:
        report=Report(id=uid(),company_id=user.company_id,user_id=user.id,
            content_json=dumps({'narrative':narrative,'context':context,'reviewStatus':'Borrador de IA: requiere revisión humana'}),model=model)
        db.add(report);audit(db,user,'report_created',report.id,{'model':model,'consentToGoogle':True,'tools':context['toolTrace']});db.commit()
        return {'id':report.id,'content':loads(report.content_json),'model':model}

@router.get('/reports')
def list_reports(request:Request):
    with session() as db:
        rows=db.scalars(select(Report).where(Report.company_id==request.state.user.company_id).order_by(Report.created_at.desc()).limit(100)).all()
        return {'items':[{'id':x.id,'title':loads(x.content_json)['narrative']['title'],'createdAt':str(x.created_at),'model':x.model} for x in rows]}

@router.get('/reports/{ident}')
def get_report(ident:str,request:Request):
    with session() as db:
        r=owned(db,Report,ident,request.state.user)
        return {'id':r.id,'content':loads(r.content_json),'model':r.model}

@router.get('/reports/{ident}/download')
def download_report(ident:str,request:Request):
    with session() as db:
        r=owned(db,Report,ident,request.state.user);data=loads(r.content_json)
    e=lambda s:html.escape(str(s)); n=data['narrative'];c=data['context']
    sections=''.join('<h2>'+e(s['heading'])+'</h2><p>'+e(s['text'])+'</p><small>Fuentes: '+e(', '.join(s['sources']))+'</small>' for s in n['sections'])
    rows=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in (m['month'],m['inflows'],m['outflows'],m['netCashFlow']))+'</tr>' for m in c['quantitative']['months'])
    metric_rows=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in (m['name'],m['period'],m['value'],m['unit'],m['documentId']+' / '+m['source']))+'</tr>' for m in c['metrics'])
    metric_block='<h2>Indicadores confirmados</h2><p>'+e(c.get('metricNotice',''))+'</p><table><tr><th>Indicador</th><th>Periodo</th><th>Valor</th><th>Unidad</th><th>Fuente</th></tr>'+metric_rows+'</table>'
    plan_block=''
    if c['plan']:
        p=c['plan'];o=p.get('optimization',{});summaries=p.get('summary',{})
        scenario_rows=[]
        for key,label in (('baseline','Base'),('stressed','Con escenario'),('repaired','Con recomendación')):
            values=summaries.get(key)
            if values:scenario_rows.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in (label,values['minimumConservativeBalance'],values['riskDate'] or 'Sin fecha de riesgo',values['projectedShortfall']))+'</tr>')
        plan_block='<h2>Pronóstico calculado por Python · '+e(c['quantitative']['currency'])+'</h2><table><tr><th>Escenario</th><th>Saldo conservador mínimo</th><th>Primera fecha de riesgo</th><th>Faltante</th></tr>'+''.join(scenario_rows)+'</table><p>'+e('Solución factible entre candidatos configurados.' if o.get('feasible') else 'Las opciones configuradas no resuelven todo el faltante.')+'</p>'+''.join('<p>'+e(x['description'])+'</p>' for x in o.get('selectedInterventions',[]))+'<p>Costo financiero usado por el optimizador: '+e(o.get('totalFinancialCost','0'))+'</p>'
    if c.get('prediction'):
        from .predictions import report_table
        plan_block+=report_table(c['prediction'])
    text='<!doctype html><html lang="es"><meta charset="utf-8"><title>'+e(n['title'])+'</title><style>body{font:16px Arial;max-width:960px;margin:40px auto;padding:24px;line-height:1.55;color:#142744}h1,h2{color:#142744}small{color:#555}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:right}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}table{width:100%}@media print{body{margin:0;padding:15px}h2{break-after:avoid}tr{break-inside:avoid}}</style><h1>'+e(n['title'])+'</h1><p>'+e(data['reviewStatus'])+' · '+e(c['snapshotAt'])+'</p><p>'+e(n['summary'])+'</p>'+sections+'<h2>Caja histórica · '+e(c['quantitative']['currency'])+'</h2><p>'+e(c['quantitative']['notice'])+'</p><table><tr><th>Mes</th><th>Entradas</th><th>Salidas</th><th>Flujo neto</th></tr>'+rows+'</table>'+metric_block+plan_block+'<h2>Limitaciones</h2>'+''.join('<p>'+e(s)+'</p>' for s in n['limitations'])+'<h2>Fuentes y herramientas</h2><pre>'+e(json.dumps({'sources':c['sources'],'tools':c['toolTrace']},ensure_ascii=False,indent=2))+'</pre><p>Prototipo independiente. No ejecuta pagos ni constituye asesoría financiera personalizada.</p></html>'
    return Response(text,media_type='text/html',headers={'Content-Disposition':f'attachment; filename="informe-{ident}.html"'})

@router.get('/audit')
def audit_list(request:Request):
    with session() as db:
        rows=db.scalars(select(Audit).where(Audit.company_id==request.state.user.company_id).order_by(Audit.created_at.desc()).limit(100)).all()
        return {'items':[{'date':str(x.created_at),'action':x.action,'target':x.target} for x in rows]}
