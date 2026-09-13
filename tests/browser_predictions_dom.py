"""Prueba de DOM de Chromium con fetch -> TestClient; no navegación HTTP del navegador.
La política del entorno bloquea localhost en Chromium. No se desactiva esa política.
El HTML, CSS y JS reales se cargan en memoria; solo fetch y navegación se instrumentan.
"""
from pathlib import Path
import sys,os,tempfile,json,re,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from app import config,db,ai_service as ai,document_ai,security
from app.main import app
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'pruebas'
checks=[];errors=[]
with tempfile.TemporaryDirectory(prefix='c1-dom-') as temp:
    config.ENV_FILE=Path(temp)/'missing.env'
    os.environ.update(DB_BACKEND='sqlite',SQLITE_PATH=str(Path(temp)/'db.sqlite'),ALLOW_REGISTRATION='1',C1_PUBLIC_MODE='0')
    for k in ('AI_API_KEY','GEMINI_API_KEY'):os.environ.pop(k,None)
    db.get_engine.cache_clear();security.attempts.clear()
    def fake(system,context,schema):
        if 'question' in context:
            if context['question']=='fuerza error':raise ai.AssistantFailure('ERROR SIMULADO: el proveedor no respondió.',code='provider_failure',status=502)
            return {'answer':'**RESPUESTA SIMULADA PARA PRUEBAS**: el déficit es \\(D = U-L\\). <img src=x onerror="window.markdownXss=true"> Confirma para calcular.',
                 'proposal':{'horizonDays':None,'threshold':None,'eventId':'factura-principal','delayDays':7}},'gemini-simulado-qa'
        return {'title':'Informe de prueba · Gemini simulado','summary':'La narrativa es simulada; los cálculos son reales de Python.',
            'sections':[{'heading':'Lectura del riesgo','text':'Revise ambos riesgos, terminal e intermedio.',
                'sources':[next(k for k in context['sources'] if k.startswith('PREDICCION:'))]}],
            'limitations':['SQLite temporal. Gemini simulado.']},'gemini-simulado-qa'
    document_ai.request_json=fake
    ai.urlopen=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No external calls'))
    with TestClient(app,headers={'X-C1-Request':'1'}) as client:
        assert client.post('/api/auth/register',json={'email':'dom@example.test','password':'Prueba-solamente-123456','company':'Empresa de demostración · QA','currency':'MXN'}).status_code==200
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=shutil.which('chromium'),headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
            def bridge(url,opt):
                r=client.request(opt.get('method','GET'),url,content=opt.get('body'),headers=opt.get('headers') or {})
                return {'body':r.text,'status':r.status_code}
            page.expose_function('__api',bridge)
            content=(ROOT/'app/static/predictions.html').read_text()
            content=re.sub(r'<script.*?</script>','',content,flags=re.S)
            content=re.sub(r'<link[^>]*>','',content)
            def load_page():
                page.set_content(content)
                for name in ('workspace.css','predictions.css'):page.add_style_tag(content=(ROOT/'app/static/css'/name).read_text())
                page.add_style_tag(content=(ROOT/'app/static/vendor/katex/katex.min.css').read_text())
                page.evaluate('''window.fetch=async(url,opt={})=>{const r=await window.__api(String(url),{...opt,headers:Object.fromEntries(new Headers(opt.headers||{}).entries())});return new Response(r.body,{status:r.status});};''')
                session=(ROOT/'app/static/js/session.js').read_text().replace("localStorage.removeItem('c1_demo_session');location.assign('/');",'window.__loggedOut=true;')
                page.add_script_tag(content=session)
                for script in ('vendor/marked/marked.umd.js','vendor/dompurify/purify.min.js','vendor/katex/katex.min.js','js/rich-text.js'):
                    page.add_script_tag(content=(ROOT/'app/static'/script).read_text())
                page.add_script_tag(content=(ROOT/'app/static/js/predictions.js').read_text())
            load_page();expect(page.locator('#dbStatus')).to_contain_text('SQLite')
            checks.append('HTML+CSS+JS reales con API TestClient autenticada y SQLite explícito: OK')
            page.locator('#demoBtn').click();expect(page.locator('#coverage')).to_be_checked()
            expect(page.locator('#results')).to_be_visible(timeout=60000)
            expect(page.locator('#forecastChart svg')).to_have_count(1)
            assert page.locator('#terminal').inner_text() not in ('—','$NaN')
            assert not page.locator('#error').is_visible(),page.locator('#error').inner_text()
            checks.append('Ejemplo de un clic, cálculo REAL, persistencia y gráfica: OK')
            page.locator('#purchaseDemo').click();expect(page.locator('#purchaseResult')).to_be_visible(timeout=60000)
            expect(page.locator('#purchaseTable')).to_contain_text('Lámina de acero')
            expect(page.locator('#purchaseProducts')).to_contain_text('ACERO-01')
            expect(page.locator('#purchaseProducts')).to_contain_text('Proveedor de acero')
            expect(page.locator('#catalogList')).to_contain_text('ACERO-01')
            page.locator('#stockoutProduct').select_option(index=1);page.locator('#stockoutDate').fill('2026-09-11');page.locator('#stockoutUnits').fill('8');page.locator('#stockoutForm button').click()
            expect(page.locator('#catalogMessage')).to_contain_text('Nueva demanda estimada')
            expect(page.locator('#catalogList')).to_contain_text('1 reportes')
            checks.append('Compra, catálogo persistente y estimación por faltantes: OK')
            href=page.locator('#downloadJson').get_attribute('href');r=client.get(href);assert r.status_code==200
            data=r.json();assert data['result']['horizon']['days']==30
            (OUT/'resultado-navegador.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
            checks.append('Enlace de descarga JSON apunta al snapshot correcto: OK')
            page.locator('#googleConsent').check();page.locator('#chatMessage').fill('¿Qué pasa si el Cliente principal paga una semana tarde?');page.locator('#chatForm button').click()
            expect(page.locator('#proposalBox')).to_be_visible(timeout=20000);expect(page.locator('#proposalText')).to_contain_text('7')
            expect(page.locator('#chatLog .rich-message strong')).to_have_text('RESPUESTA SIMULADA PARA PRUEBAS')
            expect(page.locator('#chatLog .katex')).to_have_count(1)
            expect(page.locator('#chatLog img')).to_have_count(0)
            assert page.evaluate('window.markdownXss') is None
            assert not json.loads(page.locator('#inputJson').input_value())['scenario_actions']
            checks.append('Propuesta Gemini con Markdown/LaTeX sanitizado y sin aplicación automática: OK')
            page.locator('#applyProposal').click();expect(page.locator('#chatLog')).to_contain_text('MOTOR PYTHON',timeout=60000)
            assert json.loads(page.locator('#inputJson').input_value())['scenario_actions'][0]['days']==7
            expect(page.locator('#savedRuns [data-run]')).to_have_count(2)
            checks.append('Confirmación, recálculo REAL, nueva versión y gráfica actualizada: OK')
            page.locator('#chatMessage').fill('fuerza error');page.locator('#chatForm button').click();expect(page.locator('#error')).to_contain_text('ERROR SIMULADO')
            checks.append('Fallo de Gemini SIMULADO visible sin fallback: OK')
            page.locator('#reportConsent').check();page.locator('#reportBtn').click();expect(page.locator('#reportOutput')).to_contain_text('Gemini simulado')
            r=client.get(page.locator('#reportOutput a').get_attribute('href'));assert 'Predicción estadística' in r.text
            (OUT/'informe-navegador.html').write_text(r.text)
            checks.append('Informe simulado guardado y HTML con tablas calculadas: OK')
            page.screenshot(path=str(OUT/'prediccion-desktop.png'),full_page=True)
            load_page();expect(page.locator('#savedRuns [data-run]')).to_have_count(2);page.locator('#savedRuns [data-run]').first.click();expect(page.locator('#results')).to_be_visible()
            assert json.loads(page.locator('#inputJson').input_value())['scenario_actions'][0]['days']==7
            checks.append('Reconstrucción del DOM recupera versiones de la base: OK')
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'prediccion-movil.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'),'Desborde móvil'
            checks.append('Sin desborde horizontal de página a 390px: OK')
            page.locator('#logout').click();page.wait_for_function('window.__loggedOut===true');assert client.get('/api/predictions').status_code==401
            checks.append('Cierre de sesión revoca acceso, navegación instrumentada: OK')
            assert not errors,errors
            checks.append('Sin errores JavaScript no controlados: OK')
            browser.close()
    db.get_engine().dispose();db.get_engine.cache_clear()
(OUT/'dom.txt').write_text('\n'.join(['DOM REAL / fetch a TestClient / MOTOR REAL / SQLite temporal / GEMINI SIMULADO',*checks,'Navegación HTTP real de Chromium NO verificada: bloqueada por política. No se desactivó la política.'])+'\n')
print('\n'.join(checks));print(f'{len(checks)} comprobaciones DOM superadas.')
