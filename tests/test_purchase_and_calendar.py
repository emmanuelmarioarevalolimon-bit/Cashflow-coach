from datetime import date, timedelta
from decimal import Decimal

from app import db
from app.engine.purchase_engine import MerchandiseItem, analyze_purchases
from app.engine.purchase_engine import PurchaseInputError


def curve(start=date(2026,9,12),days=10,low='10000',threshold='5000'):
    return [{'date':str(start+timedelta(days=i)),'qLow':low,
             'liquidityThreshold':threshold} for i in range(days)]


def item(**changes):
    values=dict(id='sku-1',name='Mercancía A',supplier='Proveedor A',
        stock_on_hand=Decimal('0'),average_daily_demand=Decimal('1'),
        unit_cost=Decimal('100'),lead_time_days=2,safety_stock_units=Decimal('1'),
        minimum_order_units=Decimal('2'),order_multiple=Decimal('2'),unit_price=Decimal('160'))
    values.update(changes)
    return MerchandiseItem(**values)


def test_purchase_engine_respects_inventory_multiples_and_cash_envelope():
    result=analyze_purchases([item()],curve(),analysis_date=date(2026,9,12),currency='MXN',
        coverage_days=5,available_budget='500',reserve_buffer='0')
    decision=result['items'][0]
    assert decision['requiredUnits']=='8'
    assert decision['recommendedUnits']=='4'
    assert decision['status']=='partial'
    assert result['summary']['recommendedCost']=='400.00'
    assert result['plannedEvents'][0]['source']=='compra_mercancia'
    assert {event['type'] for event in result['calendarEvents']}=={
        'purchase_order','purchase_delivery','purchase_payment'}


def test_purchase_outside_cashflow_horizon_requires_extension():
    result=analyze_purchases([item(payment_terms_days=30)],curve(days=7),
        analysis_date=date(2026,9,12),currency='MXN',coverage_days=5,
        available_budget='10000')
    assert result['items'][0]['status']=='extend_horizon'
    assert result['items'][0]['recommendedUnits']=='0'
    assert result['plannedEvents']==[]


def test_purchase_reports_existing_shortfall_and_uses_rounded_payment_cost():
    shortfall=analyze_purchases([item(stock_on_hand=Decimal('100'))],
        curve(days=2,low='4500',threshold='5000'),analysis_date=date(2026,9,12),
        currency='MXN',coverage_days=5,available_budget='10000')
    assert shortfall['cashEnvelope']['minimumHeadroom']=='-500.00'

    rounded=analyze_purchases([item(stock_on_hand=Decimal('0'),average_daily_demand=Decimal('1'),
        unit_cost=Decimal('1.005'),lead_time_days=0,safety_stock_units=Decimal('0'),
        minimum_order_units=Decimal('0'),order_multiple=Decimal('1'))],
        curve(days=2,low='5001.006',threshold='5000'),analysis_date=date(2026,9,12),
        currency='MXN',coverage_days=1,available_budget='10')
    assert rounded['items'][0]['recommendedUnits']=='0'
    assert rounded['plannedEvents']==[]
    assert any('egresos incrementales' in warning for warning in rounded['warnings'])


def test_purchase_rejects_subcent_order_increment():
    try:
        item(unit_cost=Decimal('0.01'),order_multiple=Decimal('0.1'))
    except PurchaseInputError as exc:
        assert 'al menos 0.01' in str(exc)
    else:
        raise AssertionError('Un múltiplo de compra subcentavo no puede convertirse en pago contable.')


def test_purchase_extreme_valid_inputs_do_not_overflow_decimal_context():
    huge=item(average_daily_demand=Decimal('1000000000000'),
        unit_cost=Decimal('1000000000000'),lead_time_days=365,
        safety_stock_units=Decimal('0'),minimum_order_units=Decimal('0'))
    result=analyze_purchases([huge],curve(days=2,low='1000000000000',threshold='0'),
        analysis_date=date(2026,9,12),currency='MXN',coverage_days=365,
        available_budget='1000000000000')
    assert result['summary']['requestedCost']=='730000000000000000000000000.00'
    assert result['summary']['recommendedCost']=='0.00'
    assert result['policy']['maximumPaymentAmount']=='1000000000.00'


def test_purchase_requires_contiguous_daily_projection():
    missing_day=[curve(days=3)[0],curve(days=3)[2]]
    try:
        analyze_purchases([item()],missing_day,analysis_date=date(2026,9,12),
            currency='MXN',coverage_days=5,available_budget='1000')
    except PurchaseInputError as exc:
        assert 'sin fechas faltantes' in str(exc)
    else:
        raise AssertionError('Una curva incompleta no protege todos los cierres posteriores.')


def test_purchase_requires_ascii_currency_code():
    try:
        analyze_purchases([item()],curve(),analysis_date=date(2026,9,12),
            currency='€€€',coverage_days=5,available_budget='1000')
    except PurchaseInputError as exc:
        assert 'ISO ASCII' in str(exc)
    else:
        raise AssertionError('La moneda debe usar un código ISO compatible con el motor.')


def demo_input(client):
    data=client.get('/api/predictions/demo-input').json()['input']
    data['config'].update(model='seasonal_mean',simulations=300)
    data['opening_balance']='100000'
    return data


def saved_prediction(client):
    response=client.post('/api/predictions/analyze',json={
        'input':demo_input(client),'name':'Base para compras','source':'synthetic'})
    assert response.status_code==200,response.text
    return response.json()


def purchase_payload():
    return {'items':[{'id':'sku-api','name':'Insumo API','supplier':'Proveedor API',
        'stockOnHand':'0','averageDailyDemand':'1','unitCost':'100','leadTimeDays':2,
        'incomingUnits':'0','safetyStockUnits':'1','minimumOrderUnits':'2',
        'orderMultiple':'2','unitPrice':'150','paymentTermsDays':0}],
        'coverageDays':5,'availableBudget':'1000','reserveBuffer':'0',
        'analysisDate':'2026-09-12','name':'Compra confirmada'}


def test_purchase_preview_then_apply_creates_linked_prediction(client,monkeypatch):
    base=saved_prediction(client)
    preview=client.post(f"/api/predictions/{base['id']}/purchases/preview",json=purchase_payload())
    assert preview.status_code==200,preview.text
    body=preview.json()['purchaseAnalysis']
    assert body['summary']['recommendedCost']=='600.00'
    assert body['policy']['workingWeekdays']==[0,1,2,3,4]
    assert body['cashFlowImpact']['after']['terminalMedian']!=body['cashFlowImpact']['before']['terminalMedian']
    assert len(client.get('/api/predictions').json()['items'])==1
    monkeypatch.setattr(__import__('app.predictions',fromlist=['_build_purchase_scenario']),
        '_build_purchase_scenario',lambda *args:(_ for _ in ()).throw(AssertionError('La confirmación debe reutilizar la vista previa.')))
    applied=client.post(f"/api/predictions/{base['id']}/purchases/apply",json=purchase_payload())
    assert applied.status_code==200,applied.text
    created=applied.json()['prediction']
    assert created['id']!=base['id']
    assert created['sources']['parentPrediction']==base['id']
    assert created['input']['planned_events'][-1]['source']=='compra_mercancia'
    assert len(client.get('/api/predictions').json()['items'])==2


def test_products_persist_and_stockout_reports_adjust_purchase_demand(client):
    base=saved_prediction(client);payload=purchase_payload()
    first=client.post(f"/api/predictions/{base['id']}/purchases/preview",json=payload)
    assert first.status_code==200,first.text
    catalog=client.get('/api/predictions/catalog').json()
    assert len(catalog['products'])==1
    product=catalog['products'][0]
    assert product['sku']=='SKU-API' and product['name']=='Insumo API'
    assert product['demandEstimate']['baseDailyDemand']=='1.000'
    report=client.post('/api/predictions/catalog/stockouts',json={
        'productId':product['id'],'occurredOn':'2026-09-11','missingUnits':'9',
        'note':'Clientes pidieron producto sin existencia.'})
    assert report.status_code==200,report.text
    assert Decimal(report.json()['demandEstimate']['recommendedDailyDemand'])>Decimal('1')
    adjusted=client.post(f"/api/predictions/{base['id']}/purchases/preview",json=payload)
    estimate=adjusted.json()['purchaseAnalysis']['items'][0]['demandEstimate']
    assert estimate['shortageReports']==1
    assert Decimal(estimate['recommendedDailyDemand'])>Decimal('1')


def test_work_schedule_marks_zero_sales_days_in_calendar(client):
    response=client.put('/api/predictions/work-schedule',json={
        'workingWeekdays':[0,1,2,3,4,5],
        'nonWorkingDays':[{'date':'2026-09-14','label':'Cierre de inventario'}]})
    assert response.status_code==200,response.text
    schedule=response.json()['workSchedule']
    assert schedule['workingWeekdays']==[0,1,2,3,4,5]
    calendar=client.get('/api/calendar',params={'start':'2026-09-12','end':'2026-09-15','predictionId':'none'})
    assert calendar.status_code==200,calendar.text
    closed={event['date']:event for event in calendar.json()['events'] if event['type']=='non_working'}
    assert closed['2026-09-13']['status']=='Venta esperada: cero'
    assert closed['2026-09-14']['title']=='Cierre de inventario'


def test_purchase_apply_rejects_noop_scenario(client):
    base=saved_prediction(client);payload=purchase_payload()
    payload['items'][0]['stockOnHand']='1000'
    preview=client.post(f"/api/predictions/{base['id']}/purchases/preview",json=payload)
    assert preview.status_code==200 and preview.json()['purchaseAnalysis']['summary']['orderNowItems']==0
    applied=client.post(f"/api/predictions/{base['id']}/purchases/apply",json=payload)
    assert applied.status_code==422
    assert 'No hay una compra viable' in applied.json()['detail']
    assert len(client.get('/api/predictions').json()['items'])==1


def test_calendar_combines_ledger_prediction_and_purchase_milestones(client):
    base=saved_prediction(client)
    created=client.post(f"/api/predictions/{base['id']}/purchases/apply",json=purchase_payload()).json()['prediction']
    with db.session() as session:
        company=session.query(db.Company).one();user=session.query(db.User).one()
        document=db.Document(id=db.uid(),company_id=company.id,user_id=user.id,name='agenda.csv',
            sha256='c'*64,extension='csv',content=b'demo',extraction_json='{}')
        session.add(document);session.flush()
        session.add(db.LedgerEntry(company_id=company.id,document_id=document.id,source_key='calendar-source',
            source_location='fila 1',source_quote='ejemplo',kind='payable',event_date=date(2026,9,13),
            counterparty='Proveedor confirmado',amount=500,direction='outflow',currency='MXN',
            category='proveedor',confidence=1,fingerprint='calendar-fingerprint'))
        session.commit()
    response=client.get('/api/calendar',params={'start':'2026-09-08','end':'2026-10-18','predictionId':created['id']})
    assert response.status_code==200,response.text
    data=response.json();types={event['type'] for event in data['events']}
    assert 'payable' in types and 'purchase_order' in types and 'purchase_payment' in types
    assert data['prediction']['id']==created['id']
    assert data['balances']


def test_calendar_range_and_ownership(client):
    base=saved_prediction(client)
    assert client.get('/api/calendar',params={'start':'2026-01-01','end':'2026-06-01'}).status_code==422
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app,headers={'X-C1-Request':'1'}) as other:
        assert other.post('/api/auth/register',json={'email':'calendar-two@example.test',
            'password':'Another-calendar-password','company':'Otra','currency':'MXN'}).status_code==200
        assert other.get('/api/calendar',params={'start':'2026-09-01','end':'2026-09-30',
            'predictionId':base['id']}).status_code==404
