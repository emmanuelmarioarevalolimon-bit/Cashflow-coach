"""Extracción local acotada: no ejecuta macros, fórmulas ni instrucciones del documento.
No OCR. PDF escaneado se identifica; no se lo trata como un PDF vacío válido.
"""
from __future__ import annotations
import csv
import io
import json
import posixpath
import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from defusedxml import ElementTree as ET
from .document_models import Candidate

MAX_BYTES=10*1024*1024
MAX_TEXT=150000
MAX_ROWS=2000
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

class ExtractionError(ValueError): pass

def safe_zip(data):
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile: raise ExtractionError('El archivo Office no es un ZIP válido.') from None
    info=z.infolist()
    if len(info)>2048 or sum(i.file_size for i in info)>50*1024*1024:
        raise ExtractionError('El archivo Office descomprimido excede los límites.')
    if any(i.flag_bits & 1 for i in info): raise ExtractionError('No se aceptan documentos cifrados.')
    if any('vbaproject' in i.filename.lower() or i.filename.lower().endswith('.bin') for i in info):
        raise ExtractionError('Este piloto no acepta macros ni objetos binarios incrustados.')
    return z

def decode(data):
    try:
        if data.startswith((b'\xff\xfe',b'\xfe\xff')): return data.decode('utf-16')
        return data.decode('utf-8-sig')
    except UnicodeError:
        try: return data.decode('cp1252')
        except UnicodeError: raise ExtractionError('Guarda el archivo como UTF-8.') from None

def normalize_header(s):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s).lower().strip()) if not unicodedata.combining(c)).replace(' ','_')

HEADER={'fecha':'date','monto':'amount','contraparte':'counterparty','tipo':'direction','naturaleza':'kind',
        'moneda':'currency','categoria':'category','referencia':'reference','confianza':'confidence'}

def candidates_from_rows(rows, locations, warnings):
    if not rows:return []
    headers=[HEADER.get(normalize_header(h),normalize_header(h)) for h in rows[0]]
    required={'date','amount','counterparty','direction','kind','currency'}
    if not required.issubset(headers):
        warnings.append('Columnas no canónicas: usa Analizar con Gemini o la plantilla de importación. No se convirtió ninguna fila automáticamente.')
        return []
    if len(headers)!=len(set(headers)):
        raise ExtractionError('Hay nombres de columnas repetidos.')
    output=[]
    kinds={'realizado':'actual','por_cobrar':'receivable','por_pagar':'payable'}
    directions={'entrada':'inflow','salida':'outflow','ingreso':'inflow','egreso':'outflow'}
    for row,loc in zip(rows[1:],locations[1:]):
        if not any(str(x).strip() for x in row):continue
        v=dict(zip(headers,row)); k=normalize_header(v.get('kind',''));d=normalize_header(v.get('direction',''))
        # Decimal mark ambiguity must be corrected; never silently guess thousands/decimal.
        raw_amount=str(v.get('amount','')).strip()
        try:
            if ',' in raw_amount: raise ValueError('monto ambiguo')
            item=Candidate(kind=kinds.get(k,k),date=str(v.get('date',''))[:10],
                           counterparty=str(v.get('counterparty','')),amount=raw_amount,
                           direction=directions.get(d,d),currency=str(v.get('currency','')).upper(),
                           category=str(v.get('category') or 'sin_categoria'),reference=str(v.get('reference') or ''),
                           confidence=str(v.get('confidence') or '1'),source=loc,
                           quote=json.dumps(row,ensure_ascii=False)[:1500])
            output.append(item.model_dump(mode='json'))
        except (ValueError,TypeError):
            warnings.append(f'{loc}: fila no importada automáticamente; revisa fecha ISO, monto sin separadores, naturaleza y moneda.')
    return output

def extract_file(name: str, data: bytes):
    if not data or len(data)>MAX_BYTES: raise ExtractionError('Archivo vacío o mayor de 10 MB.')
    ext=name.rsplit('.',1)[-1].lower()
    if ext not in {'csv','xlsx','pdf','docx','txt'}: raise ExtractionError('Solo CSV, XLSX, PDF, DOCX y TXT. No XLS, XLSM ni ejecutables.')
    units=[];warnings=[];candidates=[]
    def unit(loc,text):
        if len(text)>12000: raise ExtractionError(f'{loc} es demasiado grande. Divide el documento.')
        if sum(len(x['text']) for x in units)+len(text)>MAX_TEXT: raise ExtractionError('Texto extraído mayor de 150.000 caracteres. Divide el documento; no se truncó silenciosamente.')
        units.append({'source':loc,'text':text})
    if ext in {'csv','txt'}:
        text=decode(data)
        if '\x00' in text: raise ExtractionError('El archivo no parece texto válido.')
        if ext=='csv':
            try: dialect=csv.Sniffer().sniff(text[:8000],delimiters=',;\t')
            except csv.Error: dialect=csv.excel
            rows=list(csv.reader(io.StringIO(text),dialect))
            if len(rows)>MAX_ROWS+1: raise ExtractionError('Máximo 2.000 filas por importación.')
            locations=[f'fila {n+1}' for n in range(len(rows))]
            for loc,row in zip(locations,rows): unit(loc,json.dumps(row,ensure_ascii=False))
            candidates=candidates_from_rows(rows,locations,warnings)
        else:
            for i,line in enumerate(text.splitlines()):
                if line.strip():unit(f'línea {i+1}',line)
    elif ext=='pdf':
        if not data.startswith(b'%PDF-'): raise ExtractionError('La firma no corresponde a PDF.')
        from pypdf import PdfReader
        try:
            pdf=PdfReader(io.BytesIO(data))
            if pdf.is_encrypted: raise ExtractionError('PDF protegido: exporta una copia sin contraseña.')
            if len(pdf.pages)>50: raise ExtractionError('Máximo 50 páginas por PDF.')
            for i,page in enumerate(pdf.pages):
                content=page.extract_text() or ''
                if content.strip():
                    for start in range(0,len(content),11000):unit(f'página {i+1}, bloque {start//11000+1}',content[start:start+11000])
                else: warnings.append(f'página {i+1}: no tiene texto extraíble. No se analizaron imágenes.')
        except ExtractionError: raise
        except Exception: raise ExtractionError('No se pudo leer el PDF. Puede estar dañado o tener una estructura no admitida.') from None
        if not units: raise ExtractionError('Este PDF parece escaneado. Exporta texto/CSV/XLSX o un PDF con texto seleccionable. OCR y tablas en imágenes no se incluyen en esta versión.')
        warnings.append('PDF: la extracción textual no interpreta gráficos ni garantiza conservar las columnas de una tabla; revisa las cifras antes de confirmar.')
    elif ext=='docx':
        with safe_zip(data) as z:
            if 'word/document.xml' not in z.namelist(): raise ExtractionError('No es un documento DOCX.')
            root=ET.fromstring(z.read('word/document.xml'))
            for i,p in enumerate(root.findall('.//w:p',NS)):
                t=''.join(n.text or '' for n in p.findall('.//w:t',NS))
                if t.strip():unit(f'párrafo {i+1}',t)
            warnings.append('DOCX: se leyó el texto y las celdas como párrafos; no imágenes, gráficos ni comentarios.')
    elif ext=='xlsx':
        with safe_zip(data) as z:
            if 'xl/workbook.xml' not in z.namelist():raise ExtractionError('No es un libro XLSX.')
            names=z.namelist();strings=[]
            if 'xl/sharedStrings.xml' in names:
                strings=[''.join(n.text or '' for n in item.findall('.//m:t',NS)) for item in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
            relroot=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            rels={r.attrib['Id']:r.attrib['Target'] for r in relroot if r.attrib.get('TargetMode')!='External'}
            workbook=ET.fromstring(z.read('xl/workbook.xml'))
            pr=workbook.find('m:workbookPr',NS);epoch=datetime(1904,1,1) if pr is not None and pr.attrib.get('date1904') in {'1','true'} else datetime(1899,12,30)
            date_styles=set()
            if 'xl/styles.xml' in names:
                st=ET.fromstring(z.read('xl/styles.xml'))
                num={int(n.attrib['numFmtId']):n.attrib.get('formatCode','') for n in st.findall('m:numFmts/m:numFmt',NS)}
                for idx,xf in enumerate(st.findall('m:cellXfs/m:xf',NS)):
                    fmt=int(xf.attrib.get('numFmtId','0'));fmttext=re.sub(r'"[^"]*"|\[[^]]*\]','',num.get(fmt,''))
                    if 14<=fmt<=22 or re.search('[yd]',fmttext,re.I):date_styles.add(idx)
            sheets=workbook.findall('m:sheets/m:sheet',NS)
            if len(sheets)>20:raise ExtractionError('Máximo 20 hojas por XLSX.')
            count=0
            for sheet in sheets:
                target=rels.get(sheet.attrib.get('{'+NS['r']+'}id'),'')
                path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
                if not path.startswith('xl/') or path not in names:raise ExtractionError('Relación de hoja inválida.')
                rows=[];locs=[]
                for row in ET.fromstring(z.read(path)).findall('m:sheetData/m:row',NS):
                    count+=1
                    if count>MAX_ROWS+len(sheets):raise ExtractionError('Máximo 2.000 filas por XLSX.')
                    cells={}
                    for c in row.findall('m:c',NS):
                        address=c.attrib.get('r',''); letters=re.match('[A-Z]+',address)
                        if not letters:continue
                        col=0
                        for ch in letters.group():col=col*26+ord(ch)-64
                        if col>100:raise ExtractionError('Máximo 100 columnas por hoja.')
                        kind=c.attrib.get('t');v=c.find('m:v',NS);value=v.text if v is not None else ''
                        if c.find('m:f',NS) is not None:
                            warnings.append(f'{sheet.attrib["name"]}!{address}: fórmula leída solo desde su valor guardado; no se recalculó.')
                            if v is None or not value:value='[FÓRMULA SIN VALOR: REQUIERE REVISIÓN]'
                        if kind=='s':value=strings[int(value)]
                        elif kind=='inlineStr':value=''.join(n.text or '' for n in c.findall('.//m:t',NS))
                        elif value and int(c.attrib.get('s','-1')) in date_styles:
                            try:value=(epoch+timedelta(days=float(value))).date().isoformat()
                            except ValueError:pass
                        cells[col-1]=value or ''
                    values=[cells.get(i,'') for i in range(max(cells,default=-1)+1)]
                    if not any(values):continue
                    loc=f'{sheet.attrib["name"]}!fila {row.attrib.get("r",count)}'
                    rows.append(values);locs.append(loc);unit(loc,json.dumps(values,ensure_ascii=False))
                candidates.extend(candidates_from_rows(rows,locs,warnings))
            warnings.append('XLSX: no se ejecutan fórmulas ni se analizan imágenes. Los valores de fórmula pueden estar desactualizados.')
    if not units:raise ExtractionError('No se encontró texto utilizable.')
    return {'units':units,'warnings':list(dict.fromkeys(warnings))[:200], 'candidates':candidates,'metrics':[],
            'coverage':'Solo texto / valores tabulares. Revisión humana obligatoria.'}
