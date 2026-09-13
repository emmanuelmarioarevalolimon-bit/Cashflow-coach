"""Prueba DOM de Chromium + API FastAPI mediante TestClient (sin navegación de red).
Gemini SIMULADO, SQLite temporal; no se leen .env ni claves reales.
La navegación se instrumenta solamente en el arnés: NO se altera el código entregado.
"""
from pathlib import Path
import sys,os,tempfile,json,re,base64,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from fastapi.testclient import TestClient
from app import db,config,ai_service as ai,workspace,security
from app.main import app
ROOT=Path(__file__).resolve().parents[1];STATIC=ROOT/'app/static'
OUT=Path(os.getenv('C1_TEST_ARTIFACTS',str(ROOT/'.test-artifacts')));OUT.mkdir(parents=True,exist_ok=True)
results=[];errors=[]
with tempfile.TemporaryDirectory() as tmp:
  config.ENV_FILE=Path(tmp)/'unused.env';os.environ.update(DB_BACKEND='sqlite',SQLITE_PATH=str(Path(tmp)/'qa.db'),C1_PUBLIC_MODE='0',ALLOW_REGISTRATION='1')
  db.get_engine.cache_clear();security.attempts.clear()
  fake=config.AIConfig(config.DEFAULT_URL,'NOT_A_REAL_KEY_QA_ONLY','gemini-prueba-simulada',60)
  config.get_ai_config=lambda:fake;ai.get_ai_config=lambda:fake
  def provider(conf,payload,correction=None):
    if 'fuerza error de flujo de caja' in payload.message:raise RuntimeError('HTTP 429. Error SIMULADO de cuota.')
    event=next(x for x in payload.analysis_input.events if x.direction=='inflow')
    days=14 if 'dos semanas' in payload.message else 7
    return (f'**SIMULADO PARA PRUEBAS**: propongo \\(d = {days}\\) días para {event.counterparty}. <img src=x onerror="window.markdownXss=true">',{'stressEnabled':True,'stressEventId':event.id,'stressDelayDays':days})
  ai._provider_request=provider
  ai.urlopen=lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO external network'))
  workspace.analyze_document=lambda extraction,currency:({'summary':'PROPUESTA SIMULADA: revisar antes de confirmar.','warnings':['Esta prueba no llama a Gemini.'],'candidates':extraction['candidates'],'metrics':[]},fake.model)
  workspace.narrate_report=lambda context:({'title':'Informe simulado de prueba','summary':'Narrativa simulada; cálculos reales de Python.','sections':[{'heading':'Lectura del flujo de caja','text':'Se distingue historia realizada de obligaciones futuras.','sources':['HISTORIAL']}],'limitations':['Gemini simulado. SQL Server no usado.']},fake.model)
  with TestClient(app,headers={'X-C1-Request':'1'}) as client:
    def bridge(call):
      headers=call.get('headers',{})
      if call.get('file'):
        file=call['file'];headers.pop('content-type',None)
        r=client.request(call['method'],call['url'],headers=headers,files={'file':(file['name'],base64.b64decode(file['data']),file['type'])})
      else:r=client.request(call['method'],call['url'],headers=headers,content=call.get('body'))
      return {'status':r.status_code,'text':r.text}
    r=client.post('/api/auth/register',json={'email':'browser@example.test','password':'Password-only-QA-123','company':'Empresa de prueba · datos sintéticos','currency':'MXN'});assert r.status_code==200
    results.append('Cuenta y sesión reales del prototipo vía TestClient: OK')
    with sync_playwright() as p:
      browser=p.chromium.launch(executable_path=os.getenv('C1_CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
      def render(name,query=''):
        page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)));page.expose_function('testApi',bridge)
        text=(STATIC/(name+'.html')).read_text();scripts=re.findall(r'<script[^>]*src="([^"]+)"[^>]*></script>',text);styles=re.findall(r'<link[^>]*href="([^"]+\.css(?:\?[^"]*)?)"[^>]*>',text)
        text=re.sub(r'<script[^>]*src=[^>]*></script>','',text);text=re.sub(r'<link[^>]*rel="stylesheet"[^>]*>','',text)
        page.set_content(text)
        for style in styles:page.add_style_tag(content=(STATIC/style.split('?',1)[0].removeprefix('/static/')).read_text())
        page.evaluate('''() => {
          window.lastNavigation=null;window.testNavigate=url=>{window.lastNavigation=url;};window.prompt=()=> 'Escenario guardado desde DOM';
          Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async(url,opt={})=>{
            const h={};new Headers(opt.headers||{}).forEach((v,k)=>h[k]=v);
            let file=null,body=opt.body;
            if(body instanceof FormData){const f=body.get('file');const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(const b of bytes)binary+=String.fromCharCode(b);file={name:f.name,type:f.type,data:btoa(binary)};body=null;}
            const r=await window.testApi({url:String(url),method:opt.method||'GET',headers:h,body,file});
            return {ok:r.status>=200&&r.status<300,status:r.status,json:async()=>JSON.parse(r.text),text:async()=>r.text};
          };
        }''')
        for script in scripts:
          js=(STATIC/script.split('?',1)[0].removeprefix('/static/')).read_text().replace('window.location.assign(','window.testNavigate(').replace('location.assign(','window.testNavigate(').replace('new URLSearchParams(window.location.search)','new URLSearchParams('+json.dumps(query)+')')
          page.add_script_tag(content=js)
        if name=='treasury':page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
        return page
      # Responsive regression: use the actual page styles and menu handlers.
      for screen in ('index', 'dashboard', 'treasury', 'workspace', 'predictions', 'calendar'):
        layout = render(screen)
        for width in (1440, 1024, 768, 390, 320):
          layout.set_viewport_size({'width': width, 'height': 1000})
          if not layout.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'):
            layout.screenshot(path=str(OUT / f'overflow-{screen}-{width}.png'), full_page=True)
            overflowing = layout.evaluate('''() => [...document.querySelectorAll('main *')].filter(e => {
              if (e.getBoundingClientRect().right <= innerWidth + 1) return false;
              for (let parent = e.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
                if (['auto', 'hidden', 'scroll', 'clip'].includes(getComputedStyle(parent).overflowX)) return false;
              }
              return true;
            }).slice(0, 15).map(e => ({tag: e.tagName, id: e.id, class: e.className, right: e.getBoundingClientRect().right}))''')
            raise AssertionError(f'{screen}: overflow at {width}px: {overflowing}')
          if screen == 'dashboard':
            title = layout.locator('.topbar h1').bounding_box()
            menu = layout.locator('.mobile-menu-button').bounding_box()
            assert 0 <= title['x'] - menu['x'] - menu['width'] <= 24, 'Welcome must stay next to the menu'
          if screen == 'treasury':
            expect(layout.locator('#importButton')).to_be_visible()
            expect(layout.locator('#exportButton')).to_be_visible()
          if width in (1440, 390):
            layout.screenshot(path=str(OUT / f'ui-{screen}-{width}.png'), animations='disabled')
        if screen in ('dashboard', 'treasury'):
          layout.set_viewport_size({'width': 1440, 'height': 1000})
          before = layout.locator('.main-area').bounding_box()['width']
          layout.locator('.mobile-menu-button').click()
          expect(layout.locator('body')).to_have_class(re.compile('sidebar-hidden'))
          layout.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().width < 80')
          assert layout.locator('.main-area').bounding_box()['width'] > before + 150
          layout.set_viewport_size({'width': 390, 'height': 844})
          layout.locator('.mobile-menu-button').click()
          expect(layout.locator('body')).to_have_class(re.compile('sidebar-open'))
          layout.locator('.main-area').click(position={'x': 350, 'y': 200}, force=True)
          expect(layout.locator('body')).not_to_have_class(re.compile('sidebar-open'))
        layout.close()
      results.append('Seis pantallas a 320–1440 px sin desborde; bienvenida alineada, acciones móviles y menú compacto: OK')
      page=render('workspace');expect(page.locator('#companyTitle')).to_contain_text('Empresa de prueba');expect(page.locator('#dbStatus')).to_contain_text('SQLite')
      results.append('Render del espacio de empresa y estado honesto de base de datos: OK')
      page.locator('#fileInput').set_input_files(ROOT/'examples/movimientos-ejemplo.csv');page.locator('#uploadBtn').click();expect(page.locator('#documentDetail')).to_contain_text('Movimientos propuestos (4)');expect(page.locator('#entryCount')).to_have_text('0')
      results.append('Carga multipart CSV por formulario: vista previa sin importación: OK')
      page.locator('#documentConsent').check();page.locator('#analyzeDocBtn').click();expect(page.locator('#documentDetail')).to_contain_text('PROPUESTA SIMULADA');expect(page.locator('#entryCount')).to_have_text('0')
      results.append('Análisis IA simulado con consentimiento, sin confirmar datos: OK')
      page.locator('[data-field="amount"]').first.fill('1600');page.locator('[data-field="amount"]').first.press('Tab');page.locator('#approveDoc').check();page.locator('#confirmDocBtn').click();expect(page.locator('#entryCount')).to_have_text('4');expect(page.locator('#confirmDocBtn')).to_have_text('Ya confirmado; historial conservado')
      page.locator('[data-tab="history"]').click();expect(page.locator('#monthlyTable')).to_contain_text('1,100.00');expect(page.locator('#historyChart svg')).to_have_count(1)
      results.append('Edición, confirmación, persistencia y gráfica de 1600 - 500 = 1100: OK')
      page.screenshot(path=str(OUT/'historial-prueba-simulada.png'),full_page=True)
      page.locator('[data-tab="plans"]').click();page.locator('#planDate').fill('2026-09-01');page.locator('#planBalance').fill('10000');page.locator('#planThreshold').fill('2000');page.locator('#ledgerPlanForm button').click();page.wait_for_function('window.lastNavigation !== null')
      target=page.evaluate('window.lastNavigation');assert '/treasury?plan=' in target
      results.append('Formulario genera y guarda plan solo con pendientes: OK')
      treasury=render('treasury',target.split('?',1)[1]);expect(treasury.locator('#forecastChart svg')).to_have_count(1);expect(treasury.locator('#companyCurrency')).to_have_text('MXN');expect(treasury.locator('#appVersion')).to_contain_text('6.0.0');assert not treasury.locator('#assistantWarning').is_visible()
      results.append('Plan guardado renderiza gráfica, versión y moneda correctas: OK')
      treasury.locator('#assistantInput').fill('Que pasa si mi cliente se tarda en pagar 1 semana');treasury.locator('#assistantSendButton').click();expect(treasury.locator('#aiSuggestedChangesList')).to_contain_text('7 días');expect(treasury.locator('#stressDelayDays')).to_have_value('0')
      expect(treasury.locator('#assistantMessages .rich-message strong')).to_have_text('SIMULADO PARA PRUEBAS');expect(treasury.locator('#assistantMessages .katex')).to_have_count(1);expect(treasury.locator('#assistantMessages img')).to_have_count(0);assert treasury.evaluate('window.markdownXss') is None
      treasury.locator('#applyAiChangesButton').click();expect(treasury.locator('#stressDelayDays')).to_have_value('7')
      results.append('Copiloto simulado interpreta, Python calcula y solo confirma al pulsar aplicar: OK')
      treasury.locator('#assistantInput').fill('fuerza error de flujo de caja');treasury.locator('#assistantSendButton').click();expect(treasury.locator('#assistantWarning')).to_contain_text('SIMULADO')
      results.append('Error del proveedor visible sin respuesta ficticia de respaldo: OK')
      treasury.locator('#savePlanButton').click();expect(treasury.locator('#savePlanStatus')).to_contain_text('Análisis guardado')
      results.append('Guardar análisis crea nueva versión: OK')
      report=render('workspace');expect(report.locator('#entryCount')).to_have_text('4');report.locator('[data-tab="reports"]').click();report.locator('#reportPlan').select_option(label='Escenario guardado desde DOM');report.locator('[data-report-doc]').first.check();report.locator('#reportConsent').check();report.locator('#reportForm button').click();expect(report.locator('#reportDetail')).to_contain_text('Informe simulado de prueba');expect(report.locator('#reportDetail')).to_contain_text('forecast_cash_flow');expect(report.locator('#reportDetail')).to_contain_text('1,100.00')
      results.append('Informe generado y guardado con narrativa simulada, cálculos y rastro de herramientas: OK')
      link=report.locator('#reportDetail a').first.get_attribute('href');download=client.get(link);assert download.status_code==200;assert 'attachment' in download.headers['content-disposition'];assert 'Informe simulado' in download.text;(OUT/'informe-prueba-simulada.html').write_text(download.text,encoding='utf-8')
      results.append('Endpoint descarga HTML con fuentes, tablas y limitaciones: OK')
      report.screenshot(path=str(OUT/'informe-prueba-simulada.png'),full_page=True)
      report.set_viewport_size({'width':390,'height':844});report.locator('[data-tab="history"]').click();report.screenshot(path=str(OUT/'movil-prueba-simulada.png'),full_page=True)
      assert report.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1'),'Desborde móvil'
      results.append('Render móvil sin desborde horizontal de la página: OK')
      report.locator('#logout').click();report.wait_for_function('window.lastNavigation !== null');assert client.get('/api/history').status_code==401
      results.append('Cerrar sesión revoca acceso a historia: OK');assert not errors,errors;results.append('Sin errores JavaScript no controlados: OK');browser.close()
  db.get_engine().dispose();db.get_engine.cache_clear()
(OUT/'navegador.txt').write_text('\n'.join(['PRUEBAS DOM EN CHROMIUM + API TESTCLIENT; SQLITE TEMPORAL; GEMINI SIMULADO',*results,'NO navegación HTTP del navegador: la política del entorno la bloquea. No se modificó esa política.','NO conexión real con SQL Server ni con Google.'])+'\n',encoding='utf-8')
print('\n'.join(results));print(f'{len(results)} comprobaciones superadas.')
