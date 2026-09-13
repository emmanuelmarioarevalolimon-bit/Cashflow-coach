"""Calendario financiero unificado para historial, pronóstico y compras."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from . import db as store
from .predictions import ENGINE_TAG, info, prediction


router=APIRouter(prefix='/api/calendar',tags=['Calendario financiero'])


def _amount(value:Any)->str:
    return str(Decimal(str(value)).quantize(Decimal('.01')))


@router.get('')
def financial_calendar(start:date,end:date,request:Request,predictionId:str|None=None):
    if end<start or (end-start).days>92:
        raise HTTPException(422,'El calendario admite intervalos de 1 a 93 días.')
    user=request.state.user
    with store.session() as db:
        company=db.get(store.Company,user.company_id)
        rows=db.scalars(select(store.LedgerEntry).where(
            store.LedgerEntry.company_id==user.company_id,
            store.LedgerEntry.event_date>=start,store.LedgerEntry.event_date<=end
        ).order_by(store.LedgerEntry.event_date).limit(1001)).all()
        if len(rows)>1000:
            raise HTTPException(422,'Hay más de 1000 movimientos en el intervalo. Reduce la vista.')
        plans=db.scalars(select(store.Plan).where(store.Plan.company_id==user.company_id,
            store.Plan.engine_version==ENGINE_TAG).order_by(store.Plan.created_at.desc()).limit(100)).all()
        selected=None
        if predictionId and predictionId!='none':
            selected=info(prediction(db,predictionId,user))
        elif predictionId!='none' and plans:
            selected=info(plans[0])
        schedule=db.get(store.WorkSchedule,user.company_id)
        try:working_weekdays={int(day) for day in (schedule.working_weekdays if schedule else '0,1,2,3,4').split(',')}
        except (TypeError,ValueError):working_weekdays={0,1,2,3,4}
        closure_rows=db.scalars(select(store.NonWorkingDay).where(
            store.NonWorkingDay.company_id==user.company_id,
            store.NonWorkingDay.event_date>=start,store.NonWorkingDay.event_date<=end)).all()
        closures={row.event_date:row.label for row in closure_rows}

    events=[];ledger_ids=set()
    for row in rows:
        ledger_ids.add(row.id)
        events.append({'id':'ledger:'+row.id,'date':row.event_date.isoformat(),'title':row.counterparty,
            'type':'actual' if row.kind=='actual' else row.kind,'direction':row.direction,
            'amount':_amount(row.amount),'currency':row.currency,'category':row.category,
            'status':'Realizado' if row.kind=='actual' else 'Pendiente confirmado',
            'source':'Documentos e historial','url':'/workspace'})

    current=start
    while current<=end:
        label=closures.get(current)
        if label or current.weekday() not in working_weekdays:
            events.append({'id':'non-working:'+current.isoformat(),'date':current.isoformat(),
                'title':label or 'Día sin operación','type':'non_working','direction':None,'amount':None,
                'currency':company.currency,'category':'calendario_laboral','status':'Venta esperada: cero',
                'source':'Calendario laboral','url':'/predictions#workSchedule'})
        current=date.fromordinal(current.toordinal()+1)

    balances={}
    if selected:
        source_purchase=selected.get('sources',{}).get('purchaseAnalysis',{})
        for milestone in source_purchase.get('calendarEvents',[]):
            if milestone.get('type')=='purchase_payment':
                continue
            try:day=date.fromisoformat(milestone['date'])
            except (KeyError,TypeError,ValueError):continue
            if start<=day<=end:
                events.append({**milestone,'currency':company.currency,'status':'Recomendación de compra',
                    'source':'Análisis de mercancía','url':'/predictions?id='+selected['id']})
        for event in selected['result'].get('events',[]):
            try:day=date.fromisoformat(event['expectedDate'])
            except (KeyError,TypeError,ValueError):continue
            if not start<=day<=end or event.get('id') in ledger_ids:
                continue
            purchase=event.get('source')=='compra_mercancia'
            events.append({'id':'prediction:'+event['id'],'date':day.isoformat(),
                'title':event.get('counterparty') or 'Evento proyectado',
                'type':'purchase_payment' if purchase else ('forecast_inflow' if event.get('direction')=='inflow' else 'forecast_outflow'),
                'direction':event.get('direction'),'amount':event.get('amount'),'currency':company.currency,
                'category':'compra_mercancia' if purchase else 'proyeccion',
                'status':'Compra recomendada' if purchase else 'Proyectado',
                'source':'Predicción: '+selected['name'],'url':'/predictions?id='+selected['id']})
        for point in selected['result']['scenario'].get('projection',[]):
            if start.isoformat()<=point.get('date','')<=end.isoformat():
                balances[point['date']]={'median':point['qMedian'],'low':point['qLow'],
                    'threshold':point['liquidityThreshold'],'breachProbability':point['breachProbability']}

    events.sort(key=lambda event:(event['date'],event.get('type',''),event.get('title','')))
    counts={}
    for event in events:counts[event['type']]=counts.get(event['type'],0)+1
    options=[{'id':plan.id,'name':plan.name,'createdAt':plan.created_at.isoformat()} for plan in plans]
    if selected and all(option['id']!=selected['id'] for option in options):
        options.insert(0,{'id':selected['id'],'name':selected['name'],'createdAt':selected['createdAt']})
    return {'range':{'start':start.isoformat(),'end':end.isoformat()},'currency':company.currency,
        'prediction':None if not selected else {'id':selected['id'],'name':selected['name'],
            'horizon':selected['result']['horizon']},'predictions':options,
        'events':events,'balances':balances,'summary':{'totalEvents':len(events),'byType':counts},
        'workSchedule':{'workingWeekdays':sorted(working_weekdays),
            'nonWorkingDays':[{'date':day.isoformat(),'label':label} for day,label in sorted(closures.items())]},
        'notice':'El calendario reúne datos confirmados, eventos proyectados y días sin operación. En esos días la estimación de productos usa venta esperada cero. Una recomendación no es una orden ni un pago ejecutado.'}
