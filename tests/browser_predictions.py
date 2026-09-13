"""HTTP y navegador reales; SQLite temporal; respuestas de Gemini simuladas explícitas."""
from pathlib import Path
import sys, os, tempfile, socket, threading, time, json, shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app import config,db,ai_service as ai,document_ai,security
from app.main import app
from app.version import VERSION
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'pruebas';OUT.mkdir(exist_ok=True)
results=[];errors=[]
with tempfile.TemporaryDirectory(prefix='c1-web-browser-') as tmp:
    config.ENV_FILE=Path(tmp)/'not-used.env'
    os.environ.update(DB_BACKEND='sqlite',SQLITE_PATH=str(Path(tmp)/'test.db'),C1_PUBLIC_MODE='0',ALLOW_REGISTRATION='1')
    for k in ('AI_API_KEY','GEMINI_API_KEY'):os.environ.pop(k,None)
    db.get_engine.cache_clear();security.attempts.clear()
    def fake(system,context,schema):
        if 'question' in context:
            if context['question']=='fuerza error':raise ai.AssistantFailure('ERROR SIMULADO: el proveedor no respondió.',code='provider_failure',status=502)
            return {'answer':'RESPUESTA SIMULADA PARA PRUEBAS: propongo siete días; confirma para calcular.',
                'proposal':{'horizonDays':None,'threshold':None,'eventId':'factura-principal','delayDays':7}},'gemini-simulado-qa'
        return {'title':'Informe de prueba · Gemini simulado','summary':'La narrativa es simulada; las tablas y las curvas se calcularon con Python.',
          'sections':[{'heading':'Lectura de liquidez','text':'Revise tanto el riesgo al cierre final como durante el horizonte.',
                       'sources':[next(k for k in context['sources'] if k.startswith('PREDICCION:'))]}],
          'limitations':['Datos sintéticos, SQLite temporal. No se llamó a Google.']},'gemini-simulado-qa'
    document_ai.request_json=fake
    ai.urlopen=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Red externa bloqueada en esta prueba'))
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.listen(128)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    base=f'http://127.0.0.1:{port}'
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1040})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base)
        page.locator('#switchAuth').click();page.locator('#email').fill('web-integrada@example.test');page.locator('#password').fill('Password-de-prueba-12345');page.locator('#company').fill('Empresa de demostración · QA');page.locator('#submitAuth').click(no_wait_after=True)
        page.wait_for_url('**/workspace',wait_until='domcontentloaded',timeout=60000);expect(page.locator('#companyTitle')).to_contain_text('Empresa')
        page.get_by_role('link',name='Predicciones',exact=True).click(no_wait_after=True);page.wait_for_url('**/predictions',wait_until='domcontentloaded',timeout=60000)
        expect(page.locator('#dbStatus')).to_contain_text('SQLite')
        results.append('Registro, sesión, navegación y estado SQLite explícito: OK')
        page.locator('#demoBtn').click();expect(page.locator('#coverage')).to_be_checked();expect(page.locator('#inputJson')).to_contain_text('')
        expect(page.locator('#results')).to_be_visible(timeout=60000)
        expect(page.locator('#forecastChart svg')).to_have_count(1)
        assert page.locator('#terminal').inner_text() not in ('—','$NaN')
        results.append('Ejemplo de un clic, motor estadístico REAL, persistencia y gráfica SVG: OK')
        direct_download=page.request.get(base+page.locator('#downloadJson').get_attribute('href'))
        assert direct_download.status==200 and direct_download.headers.get('content-disposition','').startswith('attachment;')
        with page.expect_download() as download:page.locator('#downloadJson').click()
        assert download.value.failure() is None
        (OUT/'resultado-navegador.json').write_bytes(direct_download.body())
        data=json.loads((OUT/'resultado-navegador.json').read_text());assert data['result']['horizon']['days']==30
        results.append('Descarga del JSON con resultados del motor real: OK')
        page.locator('#googleConsent').check();page.locator('#chatMessage').fill('¿Qué pasa si el Cliente principal paga una semana tarde?');page.locator('#chatForm button').click()
        expect(page.locator('#proposalBox')).to_be_visible(timeout=20000);expect(page.locator('#proposalText')).to_contain_text('7')
        assert len(json.loads(page.locator('#inputJson').input_value())['scenario_actions'])==0
        results.append('Gemini SIMULADO propone pero no aplica automáticamente: OK')
        page.locator('#applyProposal').click();expect(page.locator('#chatLog')).to_contain_text('MOTOR PYTHON',timeout=60000)
        updated=json.loads(page.locator('#inputJson').input_value());assert updated['scenario_actions'][0]['days']==7
        expect(page.locator('#forecastChart svg')).to_have_count(1)
        results.append('Confirmación recalcula, guarda nueva versión y actualiza gráfica: OK')
        page.locator('#chatMessage').fill('fuerza error');page.locator('#chatForm button').click();expect(page.locator('#error')).to_contain_text('ERROR SIMULADO',timeout=10000)
        results.append('Error de proveedor visible; no respuesta local fingida: OK')
        page.locator('#reportConsent').check();page.locator('#reportBtn').click();expect(page.locator('#reportOutput')).to_contain_text('Gemini simulado',timeout=10000)
        report_response=page.request.get(base+page.locator('#reportOutput a').get_attribute('href'))
        assert report_response.status==200 and report_response.headers.get('content-disposition','').startswith('attachment;')
        with page.expect_download() as download:page.locator('#reportOutput a').click()
        assert download.value.failure() is None
        (OUT/'informe-navegador.html').write_bytes(report_response.body())
        assert 'Predicción estadística' in (OUT/'informe-navegador.html').read_text()
        results.append('Informe narrativo simulado, tablas Python y descarga HTML: OK')
        page.screenshot(path=str(OUT/'prediccion-desktop.png'),full_page=True)
        page.reload();expect(page.locator('#savedRuns [data-run]')).to_have_count(2)
        page.locator('#savedRuns [data-run]').first.click();expect(page.locator('#results')).to_be_visible(timeout=10000)
        assert len(json.loads(page.locator('#inputJson').input_value())['scenario_actions'])==1
        results.append('Recarga recupera los análisis de la base: OK')
        page.goto(base+'/purchases',wait_until='domcontentloaded');expect(page.locator('#predictionSummary')).to_be_visible(timeout=10000)
        page.locator('#purchaseDemo').click();expect(page.locator('#purchaseResult')).to_be_visible(timeout=60000)
        expect(page.locator('#purchaseTable')).to_contain_text('Lámina de acero');expect(page.locator('#purchaseProducts')).to_contain_text('ACERO-01');expect(page.locator('#purchaseProducts')).to_contain_text('Proveedor de acero');expect(page.locator('#catalogList')).to_contain_text('ACERO-01')
        page.locator('#stockoutProduct').select_option(index=1);page.locator('#stockoutDate').fill('2026-09-11');page.locator('#stockoutUnits').fill('8');page.locator('#stockoutNote').fill('Cliente solicitó producto sin existencia.');page.locator('#stockoutForm button').click();expect(page.locator('#catalogMessage')).to_contain_text('Nueva demanda estimada',timeout=10000);expect(page.locator('#catalogList')).to_contain_text('1 reportes')
        page.locator('#workSchedule summary').click();page.locator('#nonWorkingDates').fill('2026-09-16 | Cierre de inventario');page.locator('#workScheduleForm button').click();expect(page.locator('#catalogMessage')).to_contain_text('Calendario laboral guardado',timeout=10000)
        results.append('Compras separadas: predicción base, catálogo y estimación por faltantes: OK')
        assert not page.locator('#error').is_visible(),page.locator('#error').inner_text()
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'prediccion-movil.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1'),'Desborde horizontal móvil'
        results.append('Vista móvil sin desborde de página: OK')
        page.goto(base+'/calendar?predictionId=none',wait_until='domcontentloaded')
        expect(page.locator('.calendar-event.non_working')).to_have_count(11)
        expect(page.locator('#calendarGrid')).to_contain_text('Cierre de inventario')
        page.locator('[data-filter="schedule"]').click();expect(page.locator('#eventCount')).to_have_text('11')
        results.append('Calendario laboral y días con venta esperada cero: OK')
        page.locator('#logout').click();page.wait_for_url(base+'/');assert page.request.get(base+'/api/predictions').status==401
        results.append('Cerrar sesión revoca acceso a predicciones: OK')
        assert not errors,errors
        results.append('Sin errores JavaScript no controlados: OK')
        browser.close()
    finally:
        server.should_exit=True;thread.join(10);sock.close();db.get_engine().dispose();db.get_engine.cache_clear()
(OUT/'navegador.txt').write_text('\n'.join(['NAVEGADOR HTTP REAL / MOTOR REAL / SQLite temporal / GEMINI SIMULADO',*results,'No se usaron cuentas reales de Gemini ni SQL Server.'])+'\n')
print('\n'.join(results));print(f'{len(results)} comprobaciones superadas.')
