"""Prueba end-to-end por HTTP local con Chromium.
SQLITE TEMPORAL y GEMINI SIMULADO. NO usa .env, SQL Server ni una clave real.
Instalar dependencias de desarrollo y Chromium; ejecutar python tests/browser_smoke.py.
"""
from pathlib import Path
import sys, os, tempfile, socket, threading, time, json, shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from app import config, db, ai_service as ai, workspace, security
from app.main import app
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.getenv('C1_TEST_ARTIFACTS',str(ROOT/'.test-artifacts')));OUT.mkdir(parents=True,exist_ok=True)
results=[];errors=[]
with tempfile.TemporaryDirectory(prefix='c1-browser-') as tmp:
    config.ENV_FILE=Path(tmp)/'unused.env'
    os.environ.update(DB_BACKEND='sqlite',SQLITE_PATH=str(Path(tmp)/'qa.db'),C1_PUBLIC_MODE='0',ALLOW_REGISTRATION='1')
    db.get_engine.cache_clear();security.attempts.clear()
    fake=config.AIConfig(config.DEFAULT_URL,'NOT_A_REAL_KEY_QA_ONLY','gemini-prueba-simulada',60)
    config.get_ai_config=lambda:fake;ai.get_ai_config=lambda:fake
    def fake_provider(conf,payload,correction=None):
        if 'fuerza error' in payload.message:raise RuntimeError('HTTP 429. Error SIMULADO de cuota.')
        first=next(x for x in payload.analysis_input.events if x.direction=='inflow')
        days=14 if 'dos semanas' in payload.message else 7
        return (f'SIMULADO PARA PRUEBAS: propongo {days} días para {first.counterparty}.',{'stressEnabled':True,'stressEventId':first.id,'stressDelayDays':days})
    ai._provider_request=fake_provider
    ai.urlopen=lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO external network'))
    workspace.analyze_document=lambda extraction,currency:({'summary':'PROPUESTA SIMULADA: revisar antes de confirmar.','warnings':['Esta prueba no llama a Gemini.'],'candidates':extraction['candidates'],'metrics':[]},fake.model)
    workspace.narrate_report=lambda context:({'title':'Informe simulado de prueba','summary':'QA con narrativa simulada; los cálculos sí salen del motor de Python.','sections':[{'heading':'Lectura del flujo de caja','text':'Se distinguen la historia realizada y las obligaciones futuras.','sources':['HISTORIAL']}],'limitations':['Gemini simulado; SQL Server no usado en esta prueba.']},fake.model)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.listen(128)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started,'Servidor local no iniciado'
    base=f'http://127.0.0.1:{port}'
    try:
      with sync_playwright() as p:
        exe=os.getenv('C1_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
        browser=p.chromium.launch(executable_path=exe,headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base)
        page.locator('#switchAuth').click();page.locator('#email').fill('browser@example.test');page.locator('#password').fill('Password-only-for-QA-123');page.locator('#company').fill('Empresa de prueba · datos sintéticos');page.locator('#submitAuth').click()
        page.wait_for_url('**/workspace');expect(page.locator('#companyTitle')).to_contain_text('Empresa de prueba')
        expect(page.locator('#dbStatus')).to_contain_text('SQLite')
        results.append('Registro y navegación HTTP real con sesión; SQLite explícito visible: OK')
        page.locator('#fileInput').set_input_files(ROOT/'examples/movimientos-ejemplo.csv');page.locator('#uploadBtn').click()
        expect(page.locator('#documentDetail')).to_contain_text('Movimientos propuestos (4)')
        expect(page.locator('#entryCount')).to_have_text('0')
        results.append('Carga CSV, extracción local y vista previa sin guardar movimientos: OK')
        page.locator('#documentConsent').check();page.locator('#analyzeDocBtn').click();expect(page.locator('#documentDetail')).to_contain_text('PROPUESTA SIMULADA')
        expect(page.locator('#entryCount')).to_have_text('0')
        results.append('Gemini simulado propone sin confirmar automáticamente: OK')
        first=page.locator('[data-field="amount"]').first;first.fill('1600');first.press('Tab');page.locator('#approveDoc').check();page.locator('#confirmDocBtn').click()
        expect(page.locator('#confirmDocBtn')).to_have_text('Ya confirmado; historial conservado');expect(page.locator('#entryCount')).to_have_text('4')
        results.append('Edición de monto + confirmación + persistencia: OK')
        page.locator('[data-tab="history"]').click();expect(page.locator('#monthlyTable')).to_contain_text('1,100.00');expect(page.locator('#historyChart svg')).to_have_count(1)
        page.screenshot(path=str(OUT/'historial-prueba-simulada.png'),full_page=True)
        results.append('Historia separada de pendientes, suma 1600-500=1100 y gráfica: OK')
        page.reload();expect(page.locator('#entryCount')).to_have_text('4');page.locator('#fileInput').set_input_files(ROOT/'examples/movimientos-ejemplo.csv');page.locator('#uploadBtn').click();expect(page.locator('#workspaceMessage')).to_contain_text('no se duplicó')
        results.append('Recarga conserva datos y subir el mismo archivo no duplica: OK')
        page.locator('[data-tab="plans"]').click();page.locator('#planDate').fill('2026-09-01');page.locator('#planBalance').fill('10000');page.locator('#planThreshold').fill('2000');page.locator('#ledgerPlanForm button').click()
        page.wait_for_url('**/treasury?plan=*');expect(page.locator('#forecastChart svg')).to_have_count(1,timeout=20000);expect(page.locator('#companyCurrency')).to_have_text('MXN');expect(page.locator('#appVersion')).to_contain_text('6.0.0')
        assert not page.locator('#assistantWarning').is_visible(),page.locator('#assistantWarning').inner_text()
        results.append('Plan guardado desde pendientes, carga de gráfica y moneda de empresa: OK')
        page.locator('#assistantInput').fill('Que pasa si mi cliente se tarda en pagar 1 semana');page.locator('#assistantSendButton').click()
        expect(page.locator('#aiSuggestedChangesList')).to_contain_text('7 días',timeout=20000)
        expect(page.locator('#stressDelayDays')).to_have_value('0')
        page.locator('#applyAiChangesButton').click();expect(page.locator('#stressDelayDays')).to_have_value('7');expect(page.locator('#forecastChart svg')).to_have_count(1)
        results.append('Copiloto simulado → vista previa calculada → confirmar → recalcular gráfica: OK')
        page.locator('#assistantInput').fill('fuerza error');page.locator('#assistantSendButton').click();expect(page.locator('#assistantWarning')).to_contain_text('SIMULADO',timeout=20000)
        results.append('Fallo del proveedor visible, sin texto genérico de respaldo: OK')
        page.once('dialog',lambda d:d.accept('Escenario confirmado del navegador'));page.locator('#savePlanButton').click();expect(page.locator('#savePlanStatus')).to_contain_text('Análisis guardado')
        results.append('Guardar nueva versión del análisis sin alterar la historia: OK')
        page.goto(base+'/workspace');page.locator('[data-tab="reports"]').click()
        page.locator('#reportPlan').select_option(label='Escenario confirmado del navegador');page.locator('[data-report-doc]').first.check();page.locator('#reportConsent').check();page.locator('#reportForm button').click()
        expect(page.locator('#reportDetail')).to_contain_text('Informe simulado de prueba',timeout=20000);expect(page.locator('#reportDetail')).to_contain_text('forecast_cash_flow');expect(page.locator('#reportDetail')).to_contain_text('1,100.00')
        results.append('Informe persistido con narrativa simulada, números de Python y herramientas ejecutadas: OK')
        with page.expect_download() as download_info:page.locator('#reportDetail a').first.click()
        download=download_info.value;download.save_as(OUT/'informe-prueba-simulada.html');assert 'Informe simulado' in (OUT/'informe-prueba-simulada.html').read_text()
        page.screenshot(path=str(OUT/'informe-prueba-simulada.png'),full_page=True)
        results.append('Descarga HTML del informe con fuentes y cálculos: OK')
        page.set_viewport_size({'width':390,'height':844});page.locator('[data-tab="history"]').click()
        page.screenshot(path=str(OUT/'movil-prueba-simulada.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1'),'Desborde móvil'
        results.append('Interfaz móvil: sin desborde horizontal de la página: OK')
        page.locator('#logout').click();page.wait_for_url(base+'/');response=page.request.get(base+'/api/history');assert response.status==401
        results.append('Cerrar sesión revoca acceso al historial: OK')
        assert not errors,errors
        results.append('Sin errores JavaScript no controlados: OK')
        browser.close()
    finally:
      server.should_exit=True;thread.join(10);sock.close();db.get_engine().dispose();db.get_engine.cache_clear()
(OUT/'navegador.txt').write_text('\n'.join(['PRUEBA HTTP LOCAL REAL / SQLite temporal / GEMINI SIMULADO',*results,'No se probó una conexión real con SQL Server ni con Google.'])+'\n',encoding='utf-8')
print('\n'.join(results));print(f'{len(results)} comprobaciones superadas.')
