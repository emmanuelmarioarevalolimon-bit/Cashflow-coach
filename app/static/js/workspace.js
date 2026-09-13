(() => {
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let documents=[],plans=[],selected=null,currency='MXN',documentAnalysisApi=0;
  const money=x=>`${Number(x).toLocaleString('es-MX',{minimumFractionDigits:2,maximumFractionDigits:2})} ${currency}`;
  const types={actual:'Realizado',receivable:'Por cobrar',payable:'Por pagar'};
  const directions={inflow:'Entrada',outflow:'Salida'};
  const docStates={uploaded:'Cargado',analyzed:'Analizado',confirmed:'Confirmado'};
  function error(e){$('workspaceError').textContent=e.message||String(e);$('workspaceError').hidden=false;}
  function message(t){$('workspaceMessage').textContent=t;$('workspaceError').hidden=true;}
  async function api(url,body){
    const opt=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
    const r=await fetch(url,opt);const d=await r.json();
    if(!r.ok){const details=Array.isArray(d.detail)?d.detail:[],fields=new Set(details.flatMap(x=>x.loc||[]));if(fields.has('includeExternalContext')||fields.has('defaultCollectionProbability'))throw new Error('El navegador cargó el modo analista nuevo, pero el servidor Python sigue usando la versión anterior. Detén la aplicación, vuelve a iniciarla con INICIAR.bat o python iniciar.py y recarga esta página.');throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));}return d;
  }
  async function run(fn){
    $('workspaceError').hidden=true;
    const buttons=Array.from(document.querySelectorAll('button')).filter(b=>!b.disabled);buttons.forEach(b=>b.disabled=true);
    try{await fn();}catch(e){error(e);}finally{buttons.forEach(b=>{if(b.isConnected)b.disabled=false;});}
  }
  function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
  function switchTab(name){document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));['documents','history','plans','reports'].forEach(n=>$('tab-'+n).hidden=n!==name);}
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));
  $('logout').addEventListener('click',()=>c1Logout());
  async function refresh(){
    const previousPlan=$('reportPlan').value;
    const previousDocs=new Set(Array.from(document.querySelectorAll('[data-report-doc]:checked')).map(x=>x.dataset.reportDoc));
    const [d,p,r,h]=await Promise.all([api('/api/documents'),api('/api/plans'),api('/api/reports'),api('/api/history')]);
    documents=d.items;plans=p.items;
    $('documentList').innerHTML=documents.length?documents.map(x=>`<div class="file-row"><button class="secondary" data-doc="${esc(x.id)}">Revisar</button><strong>${esc(x.name)}</strong><br><small>${esc(docStates[x.state]||x.state)} · ${Math.ceil(x.bytes/1024)} KB · rev. ${x.revision}</small></div>`).join(''):'<p class="muted">No hay documentos todavía.</p>';
    $('documentList').querySelectorAll('[data-doc]').forEach(b=>b.addEventListener('click',()=>run(async()=>renderDoc(await api('/api/documents/'+b.dataset.doc)))));
    $('planList').innerHTML=plans.length?plans.map(x=>`<div class="file-row"><a class="button secondary" href="/treasury?plan=${encodeURIComponent(x.id)}">Abrir</a> <strong>${esc(x.name)}</strong><br><small>${esc(x.createdAt)}</small></div>`).join(''):'<p class="muted">Aún no hay planes guardados.</p>';
    $('reportPlan').innerHTML='<option value="">Sin pronóstico; solo documentos e historia</option>'+plans.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');
    $('reportDocuments').innerHTML=documents.map(x=>`<label><input type="checkbox" data-report-doc="${esc(x.id)}"> ${esc(x.name)} <small>${esc(docStates[x.state]||x.state)}</small></label>`).join('')||'<p>No hay documentos.</p>';
    $('reportList').innerHTML=r.items.map(x=>`<div class="file-row"><button class="secondary" data-report="${esc(x.id)}">Ver</button><strong>${esc(x.title)}</strong><br><small>${esc(x.createdAt)}</small></div>`).join('');
    $('reportList').querySelectorAll('[data-report]').forEach(b=>b.addEventListener('click',()=>run(async()=>renderReport(await api('/api/reports/'+b.dataset.report)))));
    if(plans.some(x=>x.id===previousPlan))$('reportPlan').value=previousPlan;
    document.querySelectorAll('[data-report-doc]').forEach(x=>x.checked=previousDocs.has(x.dataset.reportDoc));
    const status=await api('/api/ai/status');$('aiStatus').textContent=status.label;
    renderHistory(h);
  }
  function renderHistory(data){
    const s=data.summary;currency=s.currency;
    $('entryCount').textContent=s.totalEntries;$('pendingIn').textContent=money(s.pending.receivable);$('pendingOut').textContent=money(s.pending.payable);
    $('monthlyTable').innerHTML=table(['Mes','Entradas','Salidas','Flujo neto'],s.months.map(x=>[x.month,money(x.inflows),money(x.outflows),money(x.netCashFlow)]));
    $('historyEntries').innerHTML=table(['Fecha','Naturaleza','Contraparte','Tipo','Monto','Referencia','Documento / origen'],data.entries.map(x=>[x.date,types[x.kind],x.counterparty,directions[x.direction],money(x.amount),x.reference,x.documentId.slice(0,8)+' / '+x.source]));
    $('metricLimit').textContent=`Mostrando ${data.metrics.length} de ${data.metricCount} observaciones (máximo ${data.metricDisplayLimit}), sin agregarlas entre periodos.`;
    $('metricEntries').innerHTML=table(['Indicador','Periodo inicial','Periodo final','Valor','Unidad','Documento / origen'],data.metrics.map(x=>[x.name,x.periodStart,x.periodEnd,x.value,x.unit,x.documentId.slice(0,8)+' / '+x.source]));
    drawHistory(s.months);
  }
  function drawHistory(months){
    if(!months.length){$('historyChart').innerHTML='<p class="muted">Confirma movimientos realizados para ver la gráfica mensual.</p>';return;}
    const data=months.slice(-12),values=data.map(x=>Number(x.netCashFlow));const hi=Math.max(...values,0),lo=Math.min(...values,0),span=hi-lo||1;
    const y=v=>25+(hi-v)/span*160,step=720/data.length;
    const bars=data.map((x,i)=>{const v=values[i],start=y(Math.max(v,0)),height=Math.max(1,Math.abs(y(v)-y(0)));return `<rect x="${65+i*step}" y="${start}" width="${step*.6}" height="${height}" fill="${v>=0?'#186bc5':'#b32836'}"><title>${esc(x.month)}: ${esc(money(v))}</title></rect><text x="${65+i*step}" y="215" font-size="11">${esc(x.month)}</text>`;}).join('');
    $('historyChart').innerHTML=`<p><strong>Flujo neto realizado por mes</strong> · últimos 12 meses con datos · no equivale al saldo bancario</p><svg viewBox="0 0 830 240" role="img" aria-label="Flujo neto mensual"><line x1="55" y1="${y(0)}" x2="805" y2="${y(0)}" stroke="#9aacc5"/><text x="8" y="20" font-size="11">${esc(currency)}</text>${bars}</svg>`;
  }
  function financialTimeline(points){
    if(!points.length)return '<p class="muted">El archivo no contiene movimientos de caja fechados; las señales contextuales siguen disponibles.</p>';
    const values=points.flatMap(x=>[Number(x.cumulativeActual),Number(x.cumulativeExpected),Number(x.cumulativeNominal)]);const hi=Math.max(...values,0),lo=Math.min(...values,0),span=hi-lo||1;
    const x=i=>55+(points.length===1?350:i*720/(points.length-1)),y=v=>25+(hi-v)/span*170;
    const line=key=>points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(Number(p[key])).toFixed(1)}`).join(' ');
    const labels=points.length===1?`<text x="55" y="225" font-size="11">${esc(points[0].date)}</text>`:`<text x="55" y="225" font-size="11">${esc(points[0].date)}</text><text x="775" y="225" text-anchor="end" font-size="11">${esc(points.at(-1).date)}</text>`;
    return `<div class="chart-wrap"><svg viewBox="0 0 830 245" role="img" aria-label="Cambio de caja acumulado extraído"><line x1="45" y1="${y(0)}" x2="790" y2="${y(0)}" stroke="#a8b5c8"/><path d="${line('cumulativeActual')}" fill="none" stroke="#186bc5" stroke-width="3"/><path d="${line('cumulativeExpected')}" fill="none" stroke="#d08312" stroke-width="3" stroke-dasharray="7 5"/><path d="${line('cumulativeNominal')}" fill="none" stroke="#6f50b5" stroke-width="2" stroke-dasharray="2 5"/>${labels}</svg></div><div class="legend"><span class="legend-blue">Realizado</span><span class="legend-amber">Ponderado</span><span class="legend-purple">Nominal</span></div>`;
  }
  function scenarioChart(rows){
    if(!rows.length)return '';
    const values=rows.map(x=>Number(x.netCashChange)),max=Math.max(...values.map(Math.abs),1);
    return `<div class="scenario-chart">${rows.map((row,i)=>{const value=values[i],width=Math.max(2,Math.abs(value)/max*48);return `<div class="scenario-row"><div><strong>${esc(row.name)}</strong>${row.receivableRealization===null?'':`<small>${(row.receivableRealization*100).toFixed(0)}% cobro</small>`}</div><div class="scenario-track"><span class="scenario-zero"></span><span class="scenario-bar ${value<0?'negative':''}" style="width:${width}%;${value<0?'right:50%':'left:50%'}"></span></div><span>${esc(money(value))}</span></div>`;}).join('')}</div>`;
  }
  function renderFinancialAnalysis(a){
    if(!a)return '<div class="analysis-empty"><h3>Análisis adaptable</h3><p>Autoriza Gemini para clasificar el archivo, ejecutar herramientas cuantitativas y detectar valor financiero directo o indirecto.</p></div>';
    const cash=a.cashSummary,d=a.descriptive,q=a.quality,prob=a.probability,n=a.interpretation||{},assessment=n.resourceAssessment||{},external=a.externalContext||{status:'not_requested',sources:[]};
    const probability=prob.available?`<div class="analysis-grid probability-grid"><div class="metric-card"><span>Riesgo al cierre</span><strong>${(prob.terminalBelowThreshold.probability*100).toFixed(1)}%</strong><small>Wilson: ${(prob.terminalBelowThreshold.wilsonLower*100).toFixed(1)}%–${(prob.terminalBelowThreshold.wilsonUpper*100).toFixed(1)}%</small></div><div class="metric-card"><span>Riesgo en cualquier fecha</span><strong>${(prob.anyDateBelowThreshold.probability*100).toFixed(1)}%</strong><small>${prob.anyDateBelowThreshold.breaches} de ${prob.simulations} simulaciones</small></div><div class="metric-card"><span>Saldo final mediano</span><strong>${esc(money(prob.finalBalance.median))}</strong><small>P5 ${esc(money(prob.finalBalance.p05))} · P95 ${esc(money(prob.finalBalance.p95))}</small></div></div><p class="muted">${esc(prob.probabilitySource)}</p><details><summary>Supuestos de la simulación</summary><ul>${prob.assumptions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:`<div class="notice warning"><strong>Probabilidad no disponible.</strong> ${esc(prob.reason)}</div>`;
    const signals=(a.signals||[]).map(s=>`<article class="signal-card"><div><span class="signal-type">${esc(s.type.replaceAll('_',' '))}</span><span class="signal-relevance">${esc(s.cash_flow_relevance)} · ${esc(s.horizon)}</span></div><h4>${esc(s.title)}</h4><p>${esc(s.detail)}</p><small>${esc(s.source)} · “${esc(s.quote)}”</small></article>`).join('')||'<p class="muted">No se encontraron señales explícitas con evidencia suficiente.</p>';
    const findings=(n.findings||[]).map(x=>`<article class="finding ${esc(x.severity)}"><span>${esc(x.severity)}</span><h4>${esc(x.title)}</h4><p>${esc(x.explanation)}</p><small>Base: ${esc(x.basis)} · ${esc(x.sourceIds.join(', '))}</small></article>`).join('');
    const actions=(n.nextActions||[]).map(x=>`<li><strong>${esc(x.action)}</strong> <span class="priority">${esc(x.priority)}</span><br>${esc(x.why)}${x.requiredInputs.length?`<small> Datos necesarios: ${esc(x.requiredInputs.join(' · '))}</small>`:''}</li>`).join('');
    const links=(external.sources||[]).map(x=>`<a class="resource-link" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer"><strong>${esc(x.title)}</strong><small>${esc(new URL(x.url).hostname)}</small></a>`).join('');
    const metricSeries=(a.metricAnalysis||{}).series||[],metricTrends=metricSeries.length?`<h4>Comparación de indicadores documentales</h4><p class="muted">${esc(a.metricAnalysis.notice)}</p>${table(['Indicador','Último periodo','Último valor','Variación comparable'],metricSeries.map(x=>[x.name,x.latestPeriod,x.latestValue+' '+x.unit,x.latestChange?(x.latestChange.percent===null?x.latestChange.absolute+' '+x.unit:(x.latestChange.percent>=0?'+':'')+x.latestChange.percent.toFixed(1)+'%'):'Sin periodo previo no superpuesto']))}`:'';
    return `<section class="financial-analysis"><div class="analysis-heading"><div><p class="eyebrow">MODO ANALISTA · PROPUESTA SIN CONFIRMAR</p><h3>Diagnóstico financiero adaptable</h3></div><div class="quality"><strong>${q.score}/100</strong><span>Suficiencia ${esc(q.label)}</span></div></div><p class="lead">${esc(n.executiveSummary||'Cálculos disponibles; la interpretación narrativa no fue generada.')}</p><p class="analysis-mode"><strong>${esc((a.profile||{}).document_type||'Documento')}</strong> · utilidad ${esc((a.profile||{}).financial_usefulness||a.dataMode)} · foco ${esc((a.profile||{}).focus||'general')}</p><p>${esc((a.profile||{}).rationale||'')}</p>${assessment.immediateUse?`<div class="resource-assessment"><p><strong>Uso inmediato:</strong> ${esc(assessment.immediateUse)}</p><p><strong>Valor indirecto:</strong> ${esc(assessment.indirectValue)}</p></div>`:''}
      <div class="analysis-grid"><div class="metric-card"><span>Flujo realizado neto</span><strong>${esc(money(cash.actualNet))}</strong><small>Entradas ${esc(money(cash.actualInflows))} · salidas ${esc(money(cash.actualOutflows))}</small></div><div class="metric-card"><span>Neto pendiente nominal</span><strong>${esc(money(cash.nominalPendingNet))}</strong><small>Por cobrar ${esc(money(cash.receivables))} · por pagar ${esc(money(cash.payables))}</small></div><div class="metric-card"><span>Exposición bruta</span><strong>${esc(money(cash.grossExposure))}</strong><small>${a.counts.cashMovements} movimientos · ${a.counts.metrics} indicadores</small></div></div>
      <h4>Cambio acumulado extraído</h4><p class="muted">Parte de cero; no es el saldo de una cuenta bancaria.</p>${financialTimeline(a.timeline)}
      <div class="analysis-split"><div><h4>Escenarios de realización</h4>${scenarioChart(a.scenarios)}</div><div><h4>Estadística descriptiva</h4>${table(['Medida','Valor'],[['Media',money(d.mean)],['Mediana',money(d.median)],['Desv. estándar',money(d.standardDeviation)],['P25 / P75',money(d.p25)+' / '+money(d.p75)],['Mayor contraparte',(d.largestCounterpartyShare*100).toFixed(1)+'%'],['HHI',d.counterpartyHHI.toFixed(3)]])}</div></div>${metricTrends}
      <h4>Probabilidades condicionadas</h4>${probability}
      <h4>Señales del documento, incluso no contables</h4><div class="signal-grid">${signals}</div>
      ${findings?`<h4>Lectura de Gemini sobre resultados calculados</h4><div class="finding-grid">${findings}</div>`:''}
      ${actions?`<h4>Próximos pasos para el analista</h4><ol class="action-list">${actions}</ol>`:''}
      <h4>Recursos externos</h4>${external.status==='available'?`<p class="muted">Contexto público fundamentado por Google Search. No se enviaron nombres, montos ni texto del archivo.</p><div class="resource-grid">${links||'<p>No se recibieron enlaces citables.</p>'}</div>`:external.status==='unavailable'?`<div class="notice warning">La búsqueda externa no estuvo disponible: ${esc(external.error||'sin detalle')}. Los cálculos locales sí se completaron.</div>`:'<p class="muted">No solicitados. Activa la opción de contexto externo al volver a analizar.</p>'}
      <details><summary>Calidad, límites y herramientas</summary><p>${esc(q.meaning)}</p><ul>${q.gaps.map(x=>`<li>${esc(x)}</li>`).join('')}${(n.limitations||[]).map(x=>`<li>${esc(x)}</li>`).join('')}${a.notices.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p><strong>Herramientas:</strong> ${esc(a.toolTrace.join(' · '))}</p></details></section>`;
  }
  function renderDoc(doc){
    selected=doc;const done=doc.state==='confirmed',staleServer=documentAnalysisApi<2;const p={...(doc.proposal||{candidates:[],metrics:[],summary:''})};if(done&&doc.confirmed){p.candidates=doc.confirmed.candidates;p.metrics=doc.confirmed.metrics;}
    $('documentDetail').innerHTML=`<p class="eyebrow">DOCUMENTO · ${esc(docStates[doc.state]||doc.state)} · REVISIÓN ${doc.revision}</p><h2>${esc(doc.name)}</h2><p>${esc(p.summary)}</p><div class="notice">${esc((p.warnings||doc.extraction.warnings||[]).join('\n'))}</div><details><summary>Texto extraído y localizadores</summary><pre>${esc(doc.extraction.units.map(u=>`[${u.source}]\n${u.text}`).join('\n\n'))}</pre></details>
      <div class="analysis-options"><h3>Configurar análisis complejo</h3>${staleServer?'<div class="notice warning"><strong>Servidor pendiente de reinicio.</strong> Detén la aplicación, vuelve a iniciarla y recarga la página para activar este contrato.</div>':''}<p>Gemini clasifica y extrae evidencia; Python calcula estadísticas, concentración, escenarios y probabilidades. Saldo y umbral son opcionales, pero se requieren juntos para Monte Carlo. La probabilidad común es un supuesto del analista, no una estimación de Gemini.</p><div class="option-grid"><label>Saldo antes del primer movimiento del archivo<input id="analysisOpening" type="number" min="0" step="0.01" placeholder="Opcional" ${done||staleServer?'disabled':''}></label><label>Umbral de liquidez<input id="analysisThreshold" type="number" min="0" step="0.01" placeholder="Opcional" ${done||staleServer?'disabled':''}></label><label>Probabilidad común de cobro<input id="analysisCollectionProbability" type="number" min="0" max="1" step="0.01" placeholder="1.00 si se omite" ${done||staleServer?'disabled':''}></label><label>Simulaciones<select id="analysisSimulations" ${done||staleServer?'disabled':''}><option value="1000">1,000 · rápido</option><option value="2000" selected>2,000 · equilibrado</option><option value="5000">5,000 · detallado</option><option value="10000">10,000 · máximo</option></select></label></div><label><input id="externalContext" type="checkbox" ${done||staleServer?'disabled':''}> Añadir contexto externo vigente con Google Search. Solo se comparte moneda y foco genérico; puede consumir cuota adicional.</label><label><input id="documentConsent" type="checkbox" ${done||staleServer?'disabled':''}> Autorizo enviar el texto extraído a Google para analizarlo. Puede requerir dos consultas; no confirma movimientos.</label><button id="analyzeDocBtn" ${done||staleServer?'disabled':''}>${staleServer?'Reinicia el servidor para continuar':'Ejecutar análisis financiero con Gemini + Python'}</button></div>
      ${renderFinancialAnalysis(p.financialAnalysis)}
      <h3>Movimientos propuestos (${p.candidates.length})</h3><p class="action-guide">Revisa fechas, montos, moneda, naturaleza y fuente. La confianza es un supuesto manual (1 = importe nominal), no una probabilidad calculada por Gemini.</p><div id="candidateEditor"></div><button id="addCandidate" class="secondary" ${done?'disabled':''}>Añadir movimiento manual</button>
      <h3>Indicadores propuestos (${p.metrics.length})</h3><div id="metricsPreview"></div><details><summary>Edición avanzada de la propuesta (JSON)</summary><textarea id="proposalEditor" rows="14" ${done?'readonly':''}></textarea></details>
      <label><input id="approveDoc" type="checkbox" ${done?'disabled':''}> Revisé los datos y autorizo incorporarlos al historial de mi empresa.</label><label><input id="duplicateOverride" type="checkbox" ${done?'disabled':''}> Verifiqué los posibles duplicados: son operaciones distintas (solo si el sistema lo advierte).</label><button id="confirmDocBtn" ${done?'disabled':''}>${done?'Ya confirmado; historial conservado':'Confirmar y guardar en la base de datos'}</button>`;
    $('proposalEditor').value=JSON.stringify({candidates:p.candidates,metrics:p.metrics},null,2);
    renderCandidates();$('metricsPreview').innerHTML=table(['Indicador','Periodo','Valor','Unidad','Fuente'],p.metrics.map(x=>[x.name,x.period_start+' / '+x.period_end,x.value,x.unit,x.source]));
    $('analyzeDocBtn').addEventListener('click',()=>run(async()=>{
      if(!$('documentConsent').checked)throw new Error('Confirma el envío del texto a Google antes de analizar.');
      const opening=$('analysisOpening').value,threshold=$('analysisThreshold').value,collectionProbability=$('analysisCollectionProbability').value;if(Boolean(opening)!==Boolean(threshold))throw new Error('Para probabilidades, indica juntos el saldo inicial y el umbral de liquidez.');
      message('Gemini está clasificando la evidencia y Python ejecutará las herramientas financieras. No se confirmarán datos automáticamente.');
      const d=await api('/api/documents/'+doc.id+'/analyze',{consentToGoogle:true,revision:doc.revision,includeExternalContext:$('externalContext').checked,openingBalance:opening||null,liquidityThreshold:threshold||null,defaultCollectionProbability:collectionProbability||null,simulations:Number($('analysisSimulations').value)});await refresh();renderDoc(d);message('Análisis completo recibido. Revisa evidencia, supuestos y propuestas; aún no se agregó al historial.');
    }));
    $('confirmDocBtn').addEventListener('click',()=>run(async()=>{
      if(!$('approveDoc').checked)throw new Error('Marca la revisión y autorización de los datos.');
      const values=JSON.parse($('proposalEditor').value);
      const result=await api('/api/documents/'+doc.id+'/confirm',{...values,revision:doc.revision,confirm:true,allowPossibleDuplicates:$('duplicateOverride').checked});
      await refresh();renderDoc(await api('/api/documents/'+doc.id));message(result.alreadyConfirmed?'Este documento ya estaba confirmado.':'Datos guardados. El historial y sus fuentes ya están disponibles.');
    }));
    $('addCandidate').addEventListener('click',()=>{
      try{const v=JSON.parse($('proposalEditor').value),u=doc.extraction.units[0];v.candidates.push({kind:'actual',date:new Date().toISOString().slice(0,10),counterparty:'Revisar contraparte',amount:'1.00',direction:'inflow',currency,category:'sin_categoria',reference:'',confidence:'1',source:u.source,quote:u.text.slice(0,1500)});$('proposalEditor').value=JSON.stringify(v,null,2);renderCandidates();}catch(e){error(e);}
    });
    $('proposalEditor').addEventListener('change',()=>{try{renderCandidates();}catch(e){error(e);}});
  }
  function renderCandidates(){
    const values=JSON.parse($('proposalEditor').value);const done=selected.state==='confirmed';const options=(map,val)=>Object.entries(map).map(([k,v])=>`<option value="${esc(k)}" ${val===k?'selected':''}>${esc(v)}</option>`).join('');
    $('candidateEditor').innerHTML=`<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Contraparte</th><th>Monto</th><th>Naturaleza</th><th>Tipo</th><th>Moneda</th><th>Confianza</th><th>Fuente</th><th></th></tr></thead><tbody>${values.candidates.map((x,i)=>`<tr data-row="${i}"><td><input data-field="date" type="date" value="${esc(x.date)}" ${done?'disabled':''}></td><td><input data-field="counterparty" value="${esc(x.counterparty)}" ${done?'disabled':''}></td><td><input data-field="amount" type="number" min="0.01" step="0.01" value="${esc(x.amount)}" ${done?'disabled':''}></td><td><select data-field="kind" ${done?'disabled':''}>${options(types,x.kind)}</select></td><td><select data-field="direction" ${done?'disabled':''}>${options(directions,x.direction)}</select></td><td>${esc(x.currency)}</td><td><input data-field="confidence" type="number" min="0" max="1" step=".01" value="${esc(x.confidence??1)}" ${done?'disabled':''}></td><td><small title="${esc(x.quote)}">${esc(x.source)}</small></td><td><button data-remove="${i}" class="secondary" ${done?'disabled':''}>Quitar</button></td></tr>`).join('')}</tbody></table></div>`;
    $('candidateEditor').querySelectorAll('[data-field]').forEach(el=>el.addEventListener('change',()=>{const v=JSON.parse($('proposalEditor').value);v.candidates[Number(el.closest('[data-row]').dataset.row)][el.dataset.field]=el.value;$('proposalEditor').value=JSON.stringify(v,null,2);}));
    $('candidateEditor').querySelectorAll('[data-remove]').forEach(el=>el.addEventListener('click',()=>{const v=JSON.parse($('proposalEditor').value);v.candidates.splice(Number(el.dataset.remove),1);$('proposalEditor').value=JSON.stringify(v,null,2);renderCandidates();}));
  }
  $('uploadForm').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    const f=$('fileInput').files[0];if(!f)throw new Error('Selecciona un archivo.');if(f.size>10*1024*1024)throw new Error('Máximo 10 MB.');
    const body=new FormData();body.append('file',f);const r=await fetch('/api/documents',{method:'POST',body});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));
    await refresh();renderDoc(d.document);message(d.duplicate?'Ese archivo ya estaba cargado; no se duplicó.':'Archivo guardado y extraído localmente. Revisa los datos o solicita el análisis de Gemini.');
  });});
  $('ledgerPlanForm').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    const p=await api('/api/plans/from-ledger',{name:$('planName').value,startDate:$('planDate').value,openingBalance:$('planBalance').value,liquidityThreshold:$('planThreshold').value,days:Number($('planDays').value)});location.assign('/treasury?plan='+encodeURIComponent(p.id));
  });});
  $('reportForm').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
    if(!$('reportConsent').checked)throw new Error('Debes autorizar el envío de datos a Google.');
    const documentIds=Array.from(document.querySelectorAll('[data-report-doc]:checked')).map(x=>x.dataset.reportDoc);
    message('Generando informe con Gemini y cálculos de Python…');
    const r=await api('/api/reports',{consentToGoogle:true,documentIds,planId:$('reportPlan').value||null});await refresh();renderReport(r);message('Informe guardado como borrador revisable, con fuentes y cálculos.');
  });});
  function planTable(plan){
    const summary=plan.summary||{};const keys=[['baseline','Base'],['stressed','Con escenario'],['repaired','Con recomendación']];
    const rows=keys.filter(([k])=>summary[k]).map(([k,label])=>[label,money(summary[k].minimumConservativeBalance),summary[k].riskDate||'Sin fecha de riesgo',money(summary[k].projectedShortfall)]);
    const opt=plan.optimization||{};
    return '<h3>Resultado del plan calculado por Python</h3>'+table(['Escenario','Saldo conservador mínimo','Primera fecha de riesgo','Faltante'],rows)+'<p>'+esc(opt.feasible?'Existe una solución dentro de las opciones configuradas.':'Las opciones configuradas no resuelven todo el faltante.')+'</p>'+((opt.selectedInterventions||[]).map(x=>'<p>'+esc(x.description)+'</p>').join(''))+'<p>Costo financiero usado por el optimizador: '+esc(money(opt.totalFinancialCost||0))+'</p>';
  }
  function predictionTable(p){
    return '<h3>Predicción histórica calculada por Python</h3>'+table(['Escenario','Saldo final mediano','Riesgo al final','Riesgo algún día'],[['baseline','Base'],['scenario','Escenario'],['recommended','Con recomendación']].filter(([k])=>p[k]).map(([k,n])=>[n,money(p[k].terminalBalance.median),(p[k].pdTerminal.probability*100).toFixed(2)+'%',(p[k].pdAnyDay.probability*100).toFixed(2)+'%']))+'<p class="muted">Probabilidades bajo supuestos del modelo. No son garantías.</p>';
  }
  function renderReport(report){
    const n=report.content.narrative,c=report.content.context;
    $('reportDetail').innerHTML=`<p class="eyebrow">${esc(report.model)} · BORRADOR PARA REVISIÓN</p><h2>${esc(n.title)}</h2><p>${esc(n.summary)}</p><a class="button" href="/api/reports/${encodeURIComponent(report.id)}/download">Descargar informe HTML</a><p class="muted">Abre el HTML descargado y usa Imprimir → Guardar como PDF para una copia en PDF.</p>${n.sections.map(s=>`<h3>${esc(s.heading)}</h3><p>${esc(s.text)}</p><small>Fuentes: ${esc(s.sources.join(', '))}</small>`).join('')}<h3>Herramientas ejecutadas</h3><p>${esc(c.toolTrace.join(' · '))}</p><h3>Caja histórica calculada por Python</h3>${table(['Mes','Entradas','Salidas','Flujo neto'],c.quantitative.months.map(x=>[x.month,money(x.inflows),money(x.outflows),money(x.netCashFlow)]))}<h3>Indicadores confirmados</h3><p>${esc(c.metricNotice||'')}</p>${table(['Indicador','Periodo','Valor','Unidad','Origen'],c.metrics.map(x=>[x.name,x.period,x.value,x.unit,x.documentId.slice(0,8)+' / '+x.source]))}${c.plan?planTable(c.plan):''}${c.prediction?predictionTable(c.prediction):''}<h3>Limitaciones</h3>${n.limitations.map(s=>`<p>${esc(s)}</p>`).join('')}<details><summary>Fuentes y fecha del análisis</summary><pre>${esc(JSON.stringify({sources:c.sources,snapshot:c.snapshotAt},null,2))}</pre></details>`;
  }
  run(async()=>{
    const me=await api('/api/auth/me');currency=me.currency;$('companyTitle').textContent=me.company;$('identity').textContent=me.email+' · Moneda base '+me.currency;
    const [db,ai]=await Promise.all([api('/api/database/status'),api('/api/ai/status')]);documentAnalysisApi=Number(db.documentAnalysisVersion||0);$('dbStatus').textContent=db.label;$('aiStatus').textContent=ai.label;
    const date=new Date();$('planDate').value=new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,10);await refresh();if(documentAnalysisApi<2)error(new Error('El servidor Python está desactualizado respecto a la interfaz. Detén la aplicación, vuelve a ejecutar INICIAR.bat o python iniciar.py y recarga esta página.'));
  });
})();
