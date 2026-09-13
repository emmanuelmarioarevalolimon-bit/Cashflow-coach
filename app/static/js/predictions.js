'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let current=null,source='manual',currency='MXN',proposal=null,chatHistory=[],busy=false,purchasePreview=null,itemSequence=0,catalog=[];
  const money=value=>new Intl.NumberFormat('es-MX',{style:'currency',currency,maximumFractionDigits:0}).format(Number(value));
  const percent=value=>new Intl.NumberFormat('es-MX',{style:'percent',maximumFractionDigits:2}).format(Number(value));
  const fieldNames={id:'código / SKU',name:'producto',supplier:'proveedor',stockOnHand:'existencia actual',averageDailyDemand:'venta diaria',unitCost:'costo unitario',leadTimeDays:'días de entrega',availableBudget:'presupuesto',analysisDate:'fecha de orden'};

  function table(head,rows){return '<div class="table-wrap"><table><thead><tr>'+head.map(value=>'<th>'+esc(value)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(value=>'<td>'+esc(value)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
  function errorMessage(detail){if(typeof detail==='string')return detail;if(Array.isArray(detail))return detail.map(item=>{const field=item.loc?.at(-1);return `${fieldNames[field]||field||'dato'}: ${item.msg}`;}).join('\n');return 'La operación no pudo completarse con los datos enviados.';}
  async function api(path,data,method='POST'){const response=await fetch(path,data===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let result;try{result=await response.json();}catch{throw new Error('El servidor no devolvió JSON. Revisa que esté abierto y usa esta versión.');}if(!response.ok)throw new Error(errorMessage(result.detail));return result;}
  async function task(action,label){if(busy)return;busy=true;$('error').hidden=true;$('progress').textContent=label||'Procesando…';document.querySelectorAll('button').forEach(button=>button.disabled=true);try{await action();$('progress').textContent='Listo.';}catch(error){$('error').textContent=error.message;$('error').hidden=false;$('progress').textContent='No se completó la operación. No se sustituyó por una respuesta local.';$('error').scrollIntoView({behavior:'smooth',block:'center'});}finally{busy=false;document.querySelectorAll('button').forEach(button=>button.disabled=false);}}

  function setInput(data){$('inputJson').value=JSON.stringify(data,null,2);const config=data.config;$('historyStart').value=config.history_start;$('startDate').value=config.start_date;$('days').value=config.days;$('simulations').value=config.simulations;$('model').value=config.model;$('opening').value=data.opening_balance;$('threshold').value=data.liquidity_threshold;$('coverage').checked=config.history_complete===true;}
  function readInput(){let value;try{value=JSON.parse($('inputJson').value);}catch{throw new Error('Carga datos antes de calcular o corrige el JSON avanzado.');}if(!$('coverage').checked)throw new Error('Revisa y confirma la cobertura completa del historial antes de calcular.');const start=$('startDate').value;const end=new Date(start+'T12:00:00Z');end.setUTCDate(end.getUTCDate()-1);value.config={...value.config,history_start:$('historyStart').value,start_date:start,history_end:end.toISOString().slice(0,10),days:Number($('days').value),simulations:Number($('simulations').value),model:$('model').value,history_complete:true};value.opening_balance=$('opening').value;value.liquidity_threshold=$('threshold').value;return value;}
  function appendChat(who,text){const node=document.createElement('div');node.className='chat-message'+(who==='TÚ'?' user':'');const name=document.createElement('small');name.textContent=who;const content=document.createElement('div');const rich=who.startsWith('GEMINI');content.className='chat-content '+(rich?'rich-message':'plain-message');if(window.C1RichText)window.C1RichText.render(content,text,{rich});else content.textContent=String(text);node.append(name,content);$('chatLog').append(node);node.scrollIntoView({block:'nearest'});}
  function clearProposal(){proposal=null;$('proposalBox').hidden=true;}
  async function saved(){const data=await api('/api/predictions');$('savedRuns').innerHTML=data.items.length?data.items.map(item=>`<div class="file-row"><button data-run="${esc(item.id)}"><strong>${esc(item.name)}</strong><small>${esc(item.createdAt.replace('T',' ').slice(0,16))}</small></button></div>`).join(''):'<p class="muted">Todavía no hay versiones guardadas.</p>';document.querySelectorAll('[data-run]').forEach(button=>button.onclick=()=>task(async()=>show(await api('/api/predictions/'+button.dataset.run)),'Abriendo versión guardada…'));}

  function draw(result){const baseline=result.baseline.projection,scenario=result.scenario.projection,fixed=result.recommendedScenario?.projection;const W=840,H=320,L=74,R=20,T=22,B=46;const values=[...baseline,...scenario,...(fixed||[])].flatMap(point=>[Number(point.qLow),Number(point.qHigh),Number(point.liquidityThreshold)]);const low=Math.min(...values),high=Math.max(...values),range=high-low||1,ymin=low-range*.08,ymax=high+range*.08;const x=index=>L+(W-L-R)*index/Math.max(1,scenario.length-1),y=value=>T+(H-T-B)*(ymax-Number(value))/(ymax-ymin);const line=(points,key)=>points.map((point,index)=>(index?'L':'M')+x(index).toFixed(2)+' '+y(point[key]).toFixed(2)).join(' ');const band=scenario.map((point,index)=>[x(index),y(point.qHigh)]).concat(scenario.map((point,index)=>[x(index),y(point.qLow)]).reverse()).map(point=>point.join(',')).join(' ');const ticks=Array.from({length:5},(_,index)=>{const value=ymin+(ymax-ymin)*index/4;return `<line x1="${L}" x2="${W-R}" y1="${y(value)}" y2="${y(value)}" stroke="#dfe7f2"/><text x="${L-8}" y="${y(value)+4}" text-anchor="end" font-size="11" fill="#61718a">${esc(new Intl.NumberFormat('es-MX',{notation:'compact',maximumFractionDigits:1}).format(value))}</text>`;}).join('');const labels=[0,Math.floor((scenario.length-1)/2),scenario.length-1].filter((value,index,list)=>list.indexOf(value)===index).map(index=>`<text x="${x(index)}" y="${H-14}" text-anchor="${index===0?'start':index===scenario.length-1?'end':'middle'}" font-size="11" fill="#61718a">${esc(scenario[index].date)}</text>`).join('');$('forecastChart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" aria-label="Medianas de saldo y banda de cuantiles diarios" role="img"><title>Proyección de caja · ${esc(result.currency)}</title>${ticks}<polygon points="${band}" fill="#dbe8fb" opacity=".85"/><path d="${line(baseline,'qMedian')}" fill="none" stroke="#6597d4" stroke-width="2"/><path d="${line(scenario,'qMedian')}" fill="none" stroke="#102447" stroke-width="3"/>${fixed?`<path d="${line(fixed,'qMedian')}" fill="none" stroke="#15775a" stroke-width="2.5"/>`:''}<line x1="${L}" x2="${W-R}" y1="${y(scenario[0].liquidityThreshold)}" y2="${y(scenario[0].liquidityThreshold)}" stroke="#bd3a4a" stroke-dasharray="6 4"/>${labels}</svg>`;}

  function show(data){
    current=data;clearProposal();chatHistory=[];$('chatLog').replaceChildren();$('reportOutput').replaceChildren();setInput(data.input);source=data.sources?.type||'manual';
    const result=data.result,risk=result.scenario.risk,optimization=result.optimization;currency=result.currency;
    $('emptyState').hidden=true;$('results').hidden=false;$('resultTitle').textContent=data.name;
    $('resultMeta').textContent=`${result.horizon.startDate} → ${result.horizon.endDate} · ${result.horizon.days} días · ${result.simulation.count.toLocaleString('es-MX')} simulaciones · ${result.backgroundModel.selected}`;
    const purchaseSource=data.sources?.operation==='merchandise_purchase_analysis';
    $('sourceLabel').textContent=purchaseSource?'COMPRA EVALUADA · escenario guardado':source==='synthetic'?'DATOS SINTÉTICOS · no son datos de tu empresa':'Snapshot revisado · '+source;
    $('terminal').textContent=money(risk.terminalBalance.median);$('terminalRange').textContent=`Rango conservador: ${money(risk.terminalBalance.qLow)} a ${money(risk.terminalBalance.qHigh)}`;$('anyDay').textContent=percent(risk.pdAnyDay.probability);$('terminalRisk').textContent=percent(risk.pdTerminal.probability);
    $('downloadJson').href='/api/predictions/'+data.id+'/download';$('calendarLink').href='/calendar?predictionId='+encodeURIComponent(data.id);draw(result);
    const localToday=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);$('purchaseOrderDate').value=data.sources?.purchaseAnalysis?.analysisDate||(localToday<result.horizon.startDate?result.horizon.startDate:localToday);
    $('bandNote').textContent=`Área sombreada: cuantiles ${result.scenario.band.quantiles.map(percent).join('–')}. ${result.scenario.band.note}`;
    $('dailyTable').innerHTML=table(['Fecha','Mediana','Conservador bajo','Conservador alto','Riesgo diario'],result.scenario.projection.map(point=>[point.date,money(point.qMedian),money(point.qLow),money(point.qHigh),percent(point.breachProbability)]));
    $('recommendation').textContent=optimization.reason;$('recommendationValues').innerHTML=table(['Acciones seleccionadas','Costo financiero','Validación independiente'],[[optimization.feasible?(optimization.selectedActions.join(', ')||'Sin acción necesaria'):'No hay acción validada',money(optimization.totalFinancialCost||0),optimization.validationCheck?percent(optimization.validationCheck.probability):'No disponible']]);
    $('outsideObligations').innerHTML=optimization.outsideHorizonObligations?.length?'<div class="notice warning"><strong>Obligaciones posteriores al horizonte: no desaparecen.</strong>'+table(['Fecha','Obligación','Monto'],optimization.outsideHorizonObligations.map(item=>[item.date,item.id,money(item.amount)]))+'</div>':'';
    $('alternatives').innerHTML=table(['Acciones','Costo','Probabilidad estimada','Criterio','Cumple'],optimization.candidates.map(item=>[item.actions.join(', ')||'Ninguna',money(item.cost),percent(item.probability),percent(item.criterionValue),item.passes?'Sí':'No']));
    $('riskDetails').innerHTML=table(['Métrica','Valor'],[['VaR · pérdida desde saldo inicial',money(risk.changeFromOpening.VaR)],['ES · pérdida desde saldo inicial',money(risk.changeFromOpening.ES)],['Buffer adicional al umbral',money(risk.workingCapitalBuffer.additionalCashToThresholdQuantile)],['Runway',risk.runway.days===null?'Sin quema neta prevista':Number(risk.runway.days).toFixed(1)+' días']]);
    $('recurrences').innerHTML=table(['Contraparte','Período','Monto medio'],result.recurrences.map(item=>[item.counterparty||item.name||item.key,item.period||item.period_days,item.mean_amount??item.mean]));$('diagnostics').textContent=JSON.stringify(result.backgroundModel.diagnostics,null,2);$('warnings').innerHTML=result.warnings.map(item=>'<p>'+esc(item)+'</p>').join('');
    purchasePreview=null;$('purchaseResult').hidden=true;
    if(data.sources?.purchaseAnalysis){restorePurchaseRequest(data.sources.purchaseAnalysis.request);renderPurchase(data.sources.purchaseAnalysis,true);}
    $('results').scrollIntoView({behavior:'smooth',block:'start'});
  }

  function invalidatePurchase(){purchasePreview=null;$('purchaseResult').hidden=true;}
  function itemCard(values={}){
    itemSequence+=1;const id=values.id||`sku-${itemSequence}`;
    const card=document.createElement('article');card.className='purchase-item';card.dataset.item=id;
    card.innerHTML=`<div class="purchase-item-head"><div><span class="item-index">PRODUCTO ${itemSequence}</span><strong data-item-title>${esc(values.name||'Nuevo producto')}</strong></div><button class="remove-item secondary" type="button" aria-label="Quitar producto">Quitar</button></div><div class="item-core-grid"><label>Nombre del producto<input data-field="name" maxlength="160" value="${esc(values.name||'')}"></label><label>Código / SKU<input data-field="id" maxlength="80" value="${esc(id)}"></label><label>Existencia actual<input data-field="stockOnHand" type="number" min="0" step="0.001" value="${esc(values.stockOnHand??0)}"></label><label>Venta diaria promedio<input data-field="averageDailyDemand" type="number" min="0" step="0.001" value="${esc(values.averageDailyDemand??0)}"></label><label>Costo unitario<input data-field="unitCost" type="number" min="0.01" step="0.01" value="${esc(values.unitCost??0)}"></label><label>Entrega del proveedor<input data-field="leadTimeDays" type="number" min="0" max="365" value="${esc(values.leadTimeDays??0)}"><small>días</small></label></div><details><summary>Proveedor, margen y reglas de pedido</summary><div class="item-advanced-grid"><label>Proveedor<input data-field="supplier" maxlength="160" value="${esc(values.supplier||'Proveedor')}"></label><label>Unidades en camino<input data-field="incomingUnits" type="number" min="0" step="0.001" value="${esc(values.incomingUnits??0)}"></label><label>Stock de seguridad<input data-field="safetyStockUnits" type="number" min="0" step="0.001" value="${esc(values.safetyStockUnits??0)}"></label><label>Pedido mínimo<input data-field="minimumOrderUnits" type="number" min="0" step="0.001" value="${esc(values.minimumOrderUnits??0)}"></label><label>Múltiplo de compra<input data-field="orderMultiple" type="number" min="0.001" step="0.001" value="${esc(values.orderMultiple??1)}"></label><label>Precio de venta<input data-field="unitPrice" type="number" min="0" step="0.01" value="${esc(values.unitPrice??'')}"></label><label>Plazo de pago<input data-field="paymentTermsDays" type="number" min="0" max="365" value="${esc(values.paymentTermsDays??0)}"><small>días desde la orden</small></label></div></details>`;
    card.querySelector('[data-field="name"]').addEventListener('input',event=>card.querySelector('[data-item-title]').textContent=event.target.value||'Nuevo producto');
    card.querySelector('.remove-item').onclick=()=>{card.remove();if(!$('purchaseItems').children.length)addItem();invalidatePurchase();};
    return card;
  }
  function addItem(values={}){$('purchaseItems').append(itemCard(values));invalidatePurchase();}
  function restorePurchaseRequest(request){if(!request)return;itemSequence=0;$('purchaseItems').replaceChildren();request.items.forEach(addItem);$('purchaseCoverage').value=request.coverageDays;$('purchaseBudget').value=request.availableBudget;$('purchaseReserve').value=request.reserveBuffer;$('purchaseOrderDate').value=request.analysisDate;}
  function purchasePayload(){
    if(!current)throw new Error('Calcula o abre una predicción antes de analizar mercancía.');
    const numeric=new Set(['stockOnHand','averageDailyDemand','unitCost','leadTimeDays','incomingUnits','safetyStockUnits','minimumOrderUnits','orderMultiple','unitPrice','paymentTermsDays']);
    const integer=new Set(['leadTimeDays','paymentTermsDays']);
    const items=[...document.querySelectorAll('.purchase-item')].map(card=>{const item={};card.querySelectorAll('[data-field]').forEach(input=>{let value=input.value.trim();if(numeric.has(input.dataset.field))value=value===''?(input.dataset.field==='unitPrice'?null:0):(integer.has(input.dataset.field)?Number.parseInt(value,10):Number(value));item[input.dataset.field]=value;});return item;});
    return {items,coverageDays:Number($('purchaseCoverage').value),availableBudget:$('purchaseBudget').value,reserveBuffer:$('purchaseReserve').value,analysisDate:$('purchaseOrderDate').value,name:current.name+' · compra de mercancía'};
  }
  function renderPurchase(analysis,stored=false){
    const summary=analysis.summary,impact=analysis.cashFlowImpact;
    $('purchaseKpis').innerHTML=`<article><span>Compra recomendada</span><strong>${esc(money(summary.recommendedCost))}</strong><small>${summary.orderNowItems} de ${summary.itemCount} productos</small></article><article><span>Necesidad sin financiar</span><strong>${esc(money(summary.unfundedCost))}</strong><small>Después de presupuesto y reserva</small></article><article><span>Margen bruto potencial</span><strong>${esc(money(summary.potentialGrossMargin))}</strong><small>Antes de otros costos</small></article><article><span>Holgura conservadora mínima</span><strong>${esc(money(analysis.cashEnvelope.minimumHeadroom))}</strong><small>${esc(analysis.cashEnvelope.limitingDate)}</small></article>`;
    const productsToBuy=analysis.items.filter(item=>Number(item.recommendedUnits)>0);
    $('purchaseProducts').innerHTML=productsToBuy.length
      ?`<div class="purchase-products-heading"><div><span>PRODUCTOS IDENTIFICADOS</span><strong>Qué comprar</strong></div><b>${productsToBuy.length} ${productsToBuy.length===1?'producto':'productos'}</b></div><div class="purchase-product-list">${productsToBuy.map(item=>`<article><strong>${esc(item.name)}</strong><span>Código / SKU: ${esc(item.id)}</span><span>Proveedor: ${esc(item.supplier)}</span><span>Demanda estimada: ${esc(item.demandEstimate?.recommendedDailyDemand??'—')} unidades por día laborable</span><span>${esc(item.demandEstimate?.shortageReports??0)} reportes de faltante · rango ${esc(item.demandEstimate?.fluctuationLow??'—')}–${esc(item.demandEstimate?.fluctuationHigh??'—')}</span><b>${esc(item.recommendedUnits)} unidades · ${esc(money(item.recommendedCost))}</b></article>`).join('')}</div>`
      :'<div class="purchase-products-heading"><div><span>PRODUCTOS IDENTIFICADOS</span><strong>Ningún producto aprobado para compra</strong></div></div>';
    $('purchaseImpact').innerHTML=`<div><span>Flujo de caja sin compra</span><strong>${esc(percent(impact.before.pdAnyDay))}</strong><small>riesgo en algún día</small></div><span class="impact-arrow">→</span><div><span>Flujo de caja con compra</span><strong>${esc(percent(impact.after.pdAnyDay))}</strong><small>${impact.deltaPdAnyDay>0?'Aumenta '+esc(percent(impact.deltaPdAnyDay)):'Sin incremento medido'}</small></div><p>${esc(impact.note)}</p>`;
    const statuses={recommended:'Comprar',partial:'Compra parcial',no_order:'No comprar',deferred_cash:'Esperar por caja',extend_horizon:'Ampliar horizonte'};
    $('purchaseTable').innerHTML=table(['Producto','Código / SKU','Proveedor','Demanda estimada / día laborable','Decisión','Unidades','Costo','Ordenar','Recibir','Pagar'],analysis.items.map(item=>[item.name,item.id,item.supplier,item.demandEstimate?.recommendedDailyDemand??'—',statuses[item.status]||item.status,item.recommendedUnits,money(item.recommendedCost),item.orderDate,item.deliveryDate,item.paymentDate]));
    $('purchaseWarnings').innerHTML=analysis.warnings.map(item=>'<p>• '+esc(item)+'</p>').join('');
    const hasPurchase=Number(summary.orderNowItems)>0;
    purchasePreview=stored||!hasPurchase?null:analysis;$('confirmPurchase').hidden=stored||!hasPurchase;
    const confirmation=$('confirmPurchase').closest('.confirmation-action');
    confirmation.querySelector('strong').textContent=hasPurchase?'¿Quieres conservar este escenario?':'No hay una compra viable para guardar';
    confirmation.querySelector('small').textContent=hasPurchase?'Se crea una versión nueva; no se emite ninguna orden ni se modifica el historial.':'Ajusta el presupuesto, la reserva, las fechas o amplía el horizonte de la predicción.';
    $('purchaseResult').hidden=false;
  }

  function productValues(product){return {id:product.sku,name:product.name,supplier:product.supplier,
    stockOnHand:product.stockOnHand,averageDailyDemand:product.averageDailyDemand,unitCost:product.unitCost,
    leadTimeDays:product.leadTimeDays,incomingUnits:product.incomingUnits,safetyStockUnits:product.safetyStockUnits,
    minimumOrderUnits:product.minimumOrderUnits,orderMultiple:product.orderMultiple,unitPrice:product.unitPrice,
    paymentTermsDays:product.paymentTermsDays};}

  function useCatalogProduct(product){
    [...document.querySelectorAll('.purchase-item')].filter(card=>card.querySelector('[data-field="id"]').value.trim().toUpperCase()===product.sku).forEach(card=>card.remove());
    addItem(productValues(product));
    $('catalogMessage').textContent=`${product.name} (${product.sku}) está listo para analizar. El motor aplicará la estimación ajustada por faltantes.`;
    $('purchaseItems').scrollIntoView({behavior:'smooth',block:'center'});
  }

  function renderCatalog(data){
    catalog=data.products||[];
    $('catalogList').innerHTML=catalog.length?catalog.map((product,index)=>{const estimate=product.demandEstimate;return `<article><div><strong>${esc(product.name)}</strong><span>${esc(product.sku)} · ${esc(product.supplier)}</span></div><div class="catalog-demand"><small>Demanda base</small><b>${esc(estimate.baseDailyDemand)}</b></div><div class="catalog-demand emphasized"><small>Estimación con faltantes</small><b>${esc(estimate.recommendedDailyDemand)}</b><span>Rango ${esc(estimate.fluctuationLow)}–${esc(estimate.fluctuationHigh)} · ${esc(estimate.shortageReports)} reportes</span></div><button class="secondary" type="button" data-use-product="${index}">Usar en compra</button></article>`;}).join(''):'<p class="muted">Aún no hay productos. Agrega uno abajo y pulsa “Analizar compra” para guardarlo en el catálogo.</p>';
    $('stockoutProduct').innerHTML='<option value="">Selecciona un producto</option>'+catalog.map(product=>`<option value="${esc(product.id)}">${esc(product.name)} · ${esc(product.sku)}</option>`).join('');
    document.querySelectorAll('[data-use-product]').forEach(button=>button.onclick=()=>useCatalogProduct(catalog[Number(button.dataset.useProduct)]));
    const schedule=data.workSchedule||{workingWeekdays:[0,1,2,3,4],nonWorkingDays:[]};
    document.querySelectorAll('[data-workday]').forEach(input=>input.checked=schedule.workingWeekdays.includes(Number(input.value)));
    $('nonWorkingDates').value=schedule.nonWorkingDays.map(item=>`${item.date} | ${item.label}`).join('\n');
  }

  async function loadCatalog(){renderCatalog(await api('/api/predictions/catalog'));}

  async function runDemoPrediction(){
    const data=await api('/api/predictions/demo-input');
    setInput(data.input);source=data.source;
    $('inputNotice').textContent=data.notice;$('inputNotice').classList.add('ready');
    $('runName').value='Demostración sintética';
    const result=await api('/api/predictions/analyze',{name:$('runName').value,input:readInput(),source});
    show(result);await saved();
  }

  function loadPurchaseDemoItems(){
    itemSequence=0;$('purchaseItems').replaceChildren();[
      {id:'ACERO-01',name:'Lámina de acero',supplier:'Proveedor de acero',stockOnHand:2,averageDailyDemand:.2,unitCost:310,unitPrice:475,leadTimeDays:8,safetyStockUnits:3,minimumOrderUnits:10,orderMultiple:10,paymentTermsDays:25},
      {id:'EMPAQUE-02',name:'Caja de empaque',supplier:'Proveedor de empaques',stockOnHand:20,averageDailyDemand:1,unitCost:22,unitPrice:39,leadTimeDays:5,safetyStockUnits:10,minimumOrderUnits:25,orderMultiple:25,paymentTermsDays:25}
    ].forEach(addItem);$('purchaseBudget').value='50000';$('purchaseCoverage').value='30';$('purchaseReserve').value='0';
  }

  async function previewPurchase(){
    const data=await api('/api/predictions/'+current.id+'/purchases/preview',purchasePayload());
    renderPurchase(data.purchaseAnalysis,false);
    $('catalogMessage').textContent=data.notice;
    await loadCatalog();
    $('purchaseResult').scrollIntoView({behavior:'smooth',block:'start'});
  }

  $('logout').onclick=()=>window.c1Logout();
  $('demoBtn').onclick=()=>task(runDemoPrediction,'Cargando y calculando el ejemplo sintético…');
  $('emptyDemoBtn').onclick=()=>task(runDemoPrediction,'Cargando y calculando el ejemplo sintético…');
  $('loadHistory').onclick=()=>task(async()=>{const data=await api('/api/predictions/from-history',{startDate:$('startDate').value,historyStart:$('historyStart').value,days:Number($('days').value),openingBalance:$('opening').value,liquidityThreshold:$('threshold').value});setInput(data.input);source=data.source;$('inputNotice').textContent=data.notice;$('inputNotice').classList.add('ready');},'Preparando historial de la empresa…');
  $('runBtn').onclick=()=>task(async()=>{const result=await api('/api/predictions/analyze',{name:$('runName').value,input:readInput(),source:['synthetic','confirmed_history'].includes(source)?source:'manual'});show(result);await saved();},'Python está calculando modelos y simulaciones. Puede tardar; no cierres la ventana.');
  $('checkGemini').onclick=()=>task(async()=>{await api('/api/ai/check',{});const status=await api('/api/ai/status');$('aiStatus').textContent=status.label;if(!status.verified)throw new Error(status.error||'No se verificó Gemini.');},'Probando conexión real con Gemini. Consume cuota…');

  $('addPurchaseItem').onclick=()=>addItem();
  $('purchaseDemo').onclick=()=>task(async()=>{loadPurchaseDemoItems();await previewPurchase();},'Cargando artículos y analizando la compra de ejemplo…');
  $('purchaseItems').addEventListener('input',invalidatePurchase);
  ['purchaseOrderDate','purchaseCoverage','purchaseBudget','purchaseReserve'].forEach(id=>$(id).addEventListener('input',invalidatePurchase));
  $('purchasePreviewBtn').onclick=()=>task(previewPurchase,'Calculando inventario, calendario de pagos y efecto sobre la caja…');
  $('confirmPurchase').onclick=()=>task(async()=>{if(!purchasePreview)throw new Error('Primero genera una vista previa vigente.');const data=await api('/api/predictions/'+current.id+'/purchases/apply',purchasePayload());show(data.prediction);renderPurchase(data.purchaseAnalysis,true);await saved();},'Validando y guardando el escenario de compra…');
  $('stockoutForm').onsubmit=event=>{event.preventDefault();task(async()=>{const data=await api('/api/predictions/catalog/stockouts',{productId:$('stockoutProduct').value,occurredOn:$('stockoutDate').value,missingUnits:$('stockoutUnits').value,note:$('stockoutNote').value});$('catalogMessage').textContent=`Faltante registrado. Nueva demanda estimada: ${data.demandEstimate.recommendedDailyDemand} unidades por día laborable.`;$('stockoutUnits').value='';$('stockoutNote').value='';await loadCatalog();},'Actualizando la estimación por faltantes…');};
  $('workScheduleForm').onsubmit=event=>{event.preventDefault();task(async()=>{const workingWeekdays=[...document.querySelectorAll('[data-workday]:checked')].map(input=>Number(input.value));const nonWorkingDays=$('nonWorkingDates').value.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{const [day,...label]=line.split('|');return {date:day.trim(),label:label.join('|').trim()||'Día no laborable'};});const data=await api('/api/predictions/work-schedule',{workingWeekdays,nonWorkingDays},'PUT');renderCatalog(data);$('catalogMessage').textContent='Calendario laboral guardado. La próxima compra usará venta esperada cero en los días no laborables.';},'Guardando el calendario laboral…');};

  document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('chatMessage').value=button.dataset.prompt;$('chatMessage').focus();});
  $('chatForm').onsubmit=event=>{event.preventDefault();task(async()=>{if(!current)throw new Error('Calcula o abre una predicción primero.');if(!$('googleConsent').checked)throw new Error('Autoriza el envío a Google antes de consultar.');clearProposal();const text=$('chatMessage').value.trim();if(!text)throw new Error('Escribe una pregunta.');appendChat('TÚ',text);const data=await api('/api/predictions/'+current.id+'/assistant',{message:text,consentToGoogle:true,history:chatHistory.slice(-6)});appendChat('GEMINI · '+data.model,data.answer);chatHistory.push({role:'user',content:text},{role:'assistant',content:data.answer});$('aiStatus').textContent='Gemini respondió · '+data.model;$('chatMessage').value='';if(Object.keys(data.proposal).length){proposal=data.proposal;$('proposalText').textContent=JSON.stringify(proposal,null,2);$('proposalBox').hidden=false;}},'Consultando Gemini sobre la versión guardada…');};
  $('applyProposal').onclick=()=>task(async()=>{if(!proposal||!current)throw new Error('No hay propuesta pendiente.');const data=await api('/api/predictions/'+current.id+'/apply',{proposal,name:current.name+' · escenario'});show(data);appendChat('MOTOR PYTHON','Nuevo escenario calculado y guardado. La gráfica y las métricas corresponden a esta nueva versión. El historial no se modificó.');await saved();},'Calculando el escenario confirmado con Python…');
  $('cancelProposal').onclick=clearProposal;
  $('reportBtn').onclick=()=>task(async()=>{if(!current)throw new Error('Calcula o abre una predicción primero.');if(!$('reportConsent').checked)throw new Error('Autoriza el informe con Google.');const data=await api('/api/predictions/'+current.id+'/report',{consentToGoogle:true});const narrative=data.content.narrative;$('reportOutput').innerHTML='<h3>'+esc(narrative.title)+'</h3><p>'+esc(narrative.summary)+'</p><a class="button secondary" href="/api/reports/'+encodeURIComponent(data.id)+'/download">Descargar informe HTML</a><p class="muted">Borrador guardado; tablas numéricas de Python. Puedes imprimir el HTML como PDF.</p>'+narrative.sections.map(section=>'<h3>'+esc(section.heading)+'</h3><p>'+esc(section.text)+'</p><small>Fuentes: '+esc(section.sources.join(', '))+'</small>').join('');},'Generando informe en Gemini a partir del resultado guardado…');

  addItem();
  task(async()=>{const me=await api('/api/auth/me');currency=me.currency;$('identity').textContent=me.company+' · '+currency;const [database,ai]=await Promise.all([api('/api/database/status'),api('/api/ai/status')]);$('dbStatus').textContent=database.label;$('aiStatus').textContent=ai.label;const today=new Date(),start=new Date(today.getTime()-today.getTimezoneOffset()*60000);$('startDate').value=start.toISOString().slice(0,10);$('stockoutDate').value=$('startDate').value;start.setUTCDate(start.getUTCDate()-180);$('historyStart').value=start.toISOString().slice(0,10);await Promise.all([saved(),loadCatalog()]);const id=new URLSearchParams(location.search).get('id');if(id)show(await api('/api/predictions/'+encodeURIComponent(id)));},'Conectando con el servidor de esta página…');
})();
