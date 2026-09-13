"""Servidor Uvicorn y HTTP reales, sin navegador, SQLite temporal, sin Gemini."""
from pathlib import Path
import sys,os,tempfile,socket,threading,time,json,http.cookiejar
from urllib.request import Request,build_opener,HTTPCookieProcessor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from app import config,db,security,ai_service
from app.main import app
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='c1-http-') as tmp:
    config.ENV_FILE=Path(tmp)/'none.env'
    os.environ.update(DB_BACKEND='sqlite',SQLITE_PATH=str(Path(tmp)/'db.sqlite'),ALLOW_REGISTRATION='1',C1_PUBLIC_MODE='0')
    db.get_engine.cache_clear();security.attempts.clear()
    ai_service.urlopen=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No Gemini in HTTP test'))
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.listen(128)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    t=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);t.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    base=f'http://127.0.0.1:{port}'
    opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(path,data=None):
        req=Request(base+path,data=json.dumps(data).encode() if data is not None else None,
                    headers={'Content-Type':'application/json','X-C1-Request':'1'})
        with opener.open(req,timeout=120) as r:return json.load(r)
    try:
        assert call('/health')['version']=='6.0.0-web-integrada'
        call('/api/auth/register',{'email':'http@example.test','password':'Test-Password-for-HTTP','company':'HTTP','currency':'MXN'})
        data=call('/api/predictions/demo-input')['input'];data['config'].update(model='stl',simulations=1000)
        result=call('/api/predictions/analyze',{'input':data,'name':'Prueba HTTP','source':'synthetic'})
        assert len(result['result']['baseline']['projection'])==30
        assert call('/api/predictions/'+result['id'])['result']==result['result']
        assert call('/api/predictions')['items'][0]['id']==result['id']
        text='HTTP REAL con Uvicorn: health, registro/cookie, entrada demo, cálculo real, guardado y lectura: OK.\nSQLite temporal. Sin llamadas a Google ni conexión SQL Server.\n'
        (ROOT/'pruebas/http.txt').write_text(text);print(text)
    finally:
        server.should_exit=True;t.join(10);sock.close();db.get_engine().dispose();db.get_engine.cache_clear()
