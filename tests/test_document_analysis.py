from decimal import Decimal

from app.document_analysis import analyze_financial_document
from app.document_models import Candidate, MetricCandidate
from app import document_ai
from app import workspace
from app.config import AIConfig, DEFAULT_MODEL, DEFAULT_URL
from app.extract import extract_file


def candidate(**changes):
    data = {
        'kind': 'receivable',
        'date': '2026-09-02',
        'counterparty': 'Cliente',
        'amount': '80.00',
        'direction': 'inflow',
        'currency': 'MXN',
        'category': 'clientes',
        'reference': 'F-1',
        'confidence': '0.5',
        'source': 'fila 2',
        'quote': 'Cliente, 80.00',
    }
    data.update(changes)
    return Candidate.model_validate(data)


def test_document_tools_calculate_scenarios_and_probabilities():
    rows = [
        candidate(),
        candidate(kind='payable', date='2026-09-01', counterparty='Proveedor', amount='100.00',
                  direction='outflow', confidence='1', source='fila 1', quote='Proveedor, 100.00'),
    ]
    result = analyze_financial_document(rows, [], [], 2, Decimal('100'), Decimal('50'), 5000)

    assert result['cashSummary']['receivables'] == '80.00'
    assert result['cashSummary']['payables'] == '100.00'
    assert [row['netCashChange'] for row in result['scenarios']] == ['-100.00', '-60.00', '-20.00']
    assert result['probability']['available'] is True
    assert 0.45 < result['probability']['terminalBelowThreshold']['probability'] < 0.55
    assert result['probability']['anyDateBelowThreshold']['probability'] == 1
    assert 'monte_carlo_liquidity' in result['toolTrace']


def test_contextual_document_remains_analyzable_without_fake_cash_metrics():
    signals = [{'type': 'operational_driver', 'title': 'Inventario', 'detail': 'Puede afectar compras.'}]
    result = analyze_financial_document([], [], signals, 3)

    assert result['dataMode'] == 'contextual'
    assert result['cashSummary']['actualNet'] == '0.00'
    assert result['probability']['available'] is False
    assert result['quality']['score'] > 0
    assert any('movimientos de caja' in gap for gap in result['quality']['gaps'])


def test_metric_comparison_uses_only_non_overlapping_periods():
    def metric(start, end, value):
        return MetricCandidate.model_validate({'name': 'Margen bruto', 'period_start': start,
            'period_end': end, 'value': value, 'unit': '%', 'source': 'tabla 1', 'quote': str(value)})
    result = analyze_financial_document([], [
        metric('2025-01-01', '2025-12-31', '20'),
        metric('2026-01-01', '2026-12-31', '25'),
    ], [], 1)
    trend = result['metricAnalysis']['series'][0]
    assert trend['latestChange']['absolute'] == '5'
    assert trend['latestChange']['percent'] == 25.0
    assert 'metric_period_comparison' in result['toolTrace']


def test_probability_requires_opening_balance_and_threshold_together_at_api(client):
    assert client.get('/api/database/status').json()['documentAnalysisVersion'] == 2
    document = client.post('/api/documents', files={'file': ('contexto.txt', b'Politica de inventario sin cifras.', 'text/plain')}).json()['document']
    response = client.post('/api/documents/'+document['id']+'/analyze', json={
        'consentToGoogle': True,
        'revision': document['revision'],
        'openingBalance': '100.00',
    })
    assert response.status_code == 422
    response = client.post('/api/documents/'+document['id']+'/analyze', json={
        'consentToGoogle': True,
        'revision': document['revision'],
        'openingBalance': '100.00',
        'liquidityThreshold': '20.00',
        'defaultCollectionProbability': '1.2',
    })
    assert response.status_code == 422


def test_document_analysis_route_accepts_extended_browser_contract(client, monkeypatch):
    captured = {}

    def fake(extraction, currency):
        captured.update(extraction['_financial_analysis_options'])
        return {'summary': 'Analisis simulado', 'warnings': [],
                'candidates': extraction['candidates'], 'metrics': []}, 'gemini-mock'

    monkeypatch.setattr(workspace, 'analyze_document', fake)
    document = client.post('/api/documents', files={
        'file': ('flujo.csv', b'fecha,contraparte,monto,tipo,naturaleza,moneda,categoria\n2026-09-01,A,10,entrada,realizado,MXN,venta\n', 'text/csv')
    }).json()['document']
    response = client.post('/api/documents/'+document['id']+'/analyze', json={
        'consentToGoogle': True, 'revision': 1, 'includeExternalContext': False,
        'openingBalance': '100.00', 'liquidityThreshold': '20.00',
        'defaultCollectionProbability': '0.8', 'simulations': 1000,
    })

    assert response.status_code == 200, response.text
    assert captured['include_external_context'] is False
    assert captured['opening_balance'] == Decimal('100.00')
    assert captured['liquidity_threshold'] == Decimal('20.00')
    assert captured['default_collection_probability'] == Decimal('0.8')
    assert captured['simulations'] == 1000


def test_gemini_pipeline_keeps_contextual_files_and_uses_local_tools(monkeypatch):
    extraction = extract_file('contrato.txt', b'El contrato exige revisar inventario cada mes y renovar el servicio en diciembre.')
    unit = extraction['units'][0]

    def fake_request(system, context, schema):
        if schema is document_ai.EXTRACT_SCHEMA:
            return {
                'summary': 'Contrato operativo con impacto financiero indirecto.',
                'warnings': [],
                'profile': {'document_type': 'Contrato', 'financial_usefulness': 'indirect',
                            'focus': 'legal', 'rationale': 'Contiene obligaciones sin montos.'},
                'candidates': [],
                'metrics': [],
                'signals': [{
                    'type': 'obligation', 'title': 'Renovacion',
                    'detail': 'La renovacion puede requerir una salida futura, sin monto explicito.',
                    'cash_flow_relevance': 'indirect', 'direction': 'outflow',
                    'horizon': 'long_term', 'source': unit['source'],
                    'quote': 'renovar el servicio en diciembre',
                }],
            }, 'gemini-mock'
        return {
            'executiveSummary': 'El archivo aporta una obligacion operativa, pero no permite cuantificar caja.',
            'resourceAssessment': {'classification': 'indirecta', 'immediateUse': 'agenda',
                                   'indirectValue': 'detectar compromisos'},
            'findings': [{'title': 'Compromiso no cuantificado', 'explanation': 'Solicita el monto.',
                          'severity': 'watch', 'basis': 'document',
                          'sourceIds': ['DOC:'+unit['source']]}],
            'nextActions': [{'priority': 'next', 'action': 'Solicitar monto y fecha completa',
                             'why': 'Son necesarios para proyectar caja.',
                             'requiredInputs': ['monto', 'fecha']}],
            'limitations': ['No existe un monto explicito.'],
        }, 'gemini-mock'

    monkeypatch.setattr(document_ai, 'request_json', fake_request)
    proposal, model = document_ai.analyze_document(extraction, 'MXN')

    assert model == 'gemini-mock'
    assert proposal['financialAnalysis']['dataMode'] == 'contextual'
    assert proposal['financialAnalysis']['signals'][0]['sourceId'].startswith('DOC:')
    assert proposal['financialAnalysis']['probability']['available'] is False
    assert 'descriptive_statistics' in proposal['financialAnalysis']['toolTrace']


def test_external_grounding_sends_only_generic_context_and_keeps_citations(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return b'{"output_text":"Contexto publico.","steps":[{"type":"google_search_call","arguments":{"queries":["tasa oficial MXN"]}},{"type":"model_output","content":[{"type":"text","text":"Fuente vigente.","annotations":[{"type":"url_citation","title":"Banco central","url":"https://example.test/indicador"}]}]}]}'

    def fake_open(request, timeout):
        captured['url'] = request.full_url
        captured['body'] = request.data.decode()
        return Response()

    config = AIConfig(DEFAULT_URL, 'TEST_KEY_NOT_A_REAL_SECRET', DEFAULT_MODEL, 60)
    monkeypatch.setattr(document_ai, 'get_ai_config', lambda: config)
    monkeypatch.setattr(document_ai.ai, 'urlopen', fake_open)
    monkeypatch.setattr(document_ai, 'reserve_provider_call', lambda: None)

    result = document_ai.request_grounded_context('operations', 'MXN')

    assert captured['url'].endswith('/v1beta/interactions')
    assert 'google_search' in captured['body']
    assert 'Cliente Secreto' not in captured['body']
    assert result['sources'] == [{'title': 'Banco central', 'url': 'https://example.test/indicador'}]
    assert result['queries'] == ['tasa oficial MXN']
