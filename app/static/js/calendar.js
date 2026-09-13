'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const iso=day=>day.toISOString().slice(0,10);
  const addDays=(day,count)=>{const next=new Date(day);next.setUTCDate(next.getUTCDate()+count);return next;};
  const money=(value,currency)=>new Intl.NumberFormat('es-MX',{style:'currency',currency,maximumFractionDigits:0}).format(Number(value));
  let month=new Date();month=new Date(Date.UTC(month.getFullYear(),month.getMonth(),1));
  const initialPrediction=new URLSearchParams(location.search).get('predictionId');
  let payload=null,filter='all',selectedDay=null,selectedPrediction=initialPrediction===null?'__latest__':initialPrediction==='none'?'':initialPrediction;

  function monthRange(){
    const first=new Date(Date.UTC(month.getUTCFullYear(),month.getUTCMonth(),1));
    const last=new Date(Date.UTC(month.getUTCFullYear(),month.getUTCMonth()+1,0));
    const start=addDays(first,-((first.getUTCDay()+6)%7));
    const end=addDays(last,6-((last.getUTCDay()+6)%7));
    return {first,last,start,end};
  }
  function group(type){
    if(['actual','receivable','payable'].includes(type))return 'confirmed';
    if(type.startsWith('purchase_'))return 'purchase';
    if(type==='non_working')return 'schedule';
    return 'forecast';
  }
  function visible(event){return filter==='all'||group(event.type)===filter;}
  function selectDay(day){selectedDay=day;render();renderDetail(day);}
  function renderDetail(day){
    const dateText=new Intl.DateTimeFormat('es-MX',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(day+'T00:00:00Z'));
    $('dayTitle').textContent=dateText.charAt(0).toUpperCase()+dateText.slice(1);
    const balance=payload.balances[day];
    $('dayBalance').textContent=balance?`Saldo mediano ${money(balance.median,payload.currency)} · conservador ${money(balance.low,payload.currency)} · riesgo ${new Intl.NumberFormat('es-MX',{style:'percent',maximumFractionDigits:1}).format(balance.breachProbability)}`:'Sin saldo proyectado para esta fecha.';
    const events=payload.events.filter(event=>event.date===day&&visible(event));
    $('dayEvents').innerHTML=events.length?events.map(event=>`<article class="day-event"><span class="day-event-dot"></span><div><strong>${esc(event.title)}</strong><small>${esc(event.status)} · ${esc(event.source)}</small></div><div class="day-event-amount ${esc(event.direction||'')}">${event.amount?esc((event.direction==='outflow'?'−':event.direction==='inflow'?'+':'')+money(event.amount,payload.currency)):'Sin movimiento de caja'}</div></article>`).join(''):'<p class="muted">No hay eventos visibles en esta fecha.</p>';
  }
  function render(){
    if(!payload)return;
    const range=monthRange(),today=iso(new Date(Date.now()-new Date().getTimezoneOffset()*60000));
    $('monthTitle').textContent=new Intl.DateTimeFormat('es-MX',{month:'long',year:'numeric',timeZone:'UTC'}).format(month);
    const cells=[];
    for(let day=range.start;day<=range.end;day=addDays(day,1)){
      const key=iso(day),events=payload.events.filter(event=>event.date===key&&visible(event));
      const nonWorking=payload.events.some(event=>event.date===key&&event.type==='non_working');
      const balance=payload.balances[key],risk=balance?Number(balance.breachProbability):0;
      cells.push(`<button class="calendar-day${day.getUTCMonth()!==month.getUTCMonth()?' outside':''}${nonWorking?' non-working':''}${key===today?' today':''}${key===selectedDay?' selected':''}" data-day="${key}" aria-label="${key}, ${events.length} eventos${nonWorking?', día sin operación':''}"><span class="day-head"><span class="day-number">${day.getUTCDate()}</span>${risk>0?`<span class="risk-dot${risk>=.2?' high':''}" title="Riesgo diario"></span>`:''}</span>${balance?`<span class="balance-label">Conservador ${esc(money(balance.low,payload.currency))}</span>`:''}${events.slice(0,3).map(event=>`<span class="calendar-event ${esc(event.type)}">${esc(event.title)}</span>`).join('')}${events.length>3?`<span class="more-events">+${events.length-3} eventos</span>`:''}</button>`);
    }
    $('calendarGrid').innerHTML=cells.join('');
    document.querySelectorAll('[data-day]').forEach(button=>button.onclick=()=>selectDay(button.dataset.day));
    if(selectedDay)renderDetail(selectedDay);
  }
  function totals(){
    const events=payload.events.filter(visible);
    const sum=direction=>events.filter(event=>event.direction===direction&&event.amount).reduce((total,event)=>total+Number(event.amount),0);
    $('eventCount').textContent=events.length.toLocaleString('es-MX');
    $('inflowTotal').textContent=money(sum('inflow'),payload.currency);
    $('outflowTotal').textContent=money(sum('outflow'),payload.currency);
    const risky=Object.entries(payload.balances).sort((a,b)=>Number(b[1].breachProbability)-Number(a[1].breachProbability))[0];
    $('riskDate').textContent=risky&&Number(risky[1].breachProbability)>0?`${risky[0].slice(8,10)}/${risky[0].slice(5,7)} · ${new Intl.NumberFormat('es-MX',{style:'percent',maximumFractionDigits:0}).format(risky[1].breachProbability)}`:'Sin alerta';
  }
  async function load(){
    $('calendarError').hidden=true;
    const range=monthRange(),query=new URLSearchParams({start:iso(range.start),end:iso(range.end)});
    if(selectedPrediction!=='__latest__')query.set('predictionId',selectedPrediction||'none');
    try{
      const response=await fetch('/api/calendar?'+query);const data=await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'No se pudo abrir el calendario.');
      payload=data;selectedPrediction=data.prediction?.id||'';
      $('predictionSelect').innerHTML='<option value="">Solo datos confirmados</option>'+data.predictions.map(plan=>`<option value="${esc(plan.id)}"${plan.id===selectedPrediction?' selected':''}>${esc(plan.name)}</option>`).join('');
      $('calendarNotice').textContent=data.notice;totals();render();
    }catch(error){$('calendarError').textContent=error.message;$('calendarError').hidden=false;}
  }
  $('previousMonth').onclick=()=>{month=new Date(Date.UTC(month.getUTCFullYear(),month.getUTCMonth()-1,1));selectedDay=null;load();};
  $('nextMonth').onclick=()=>{month=new Date(Date.UTC(month.getUTCFullYear(),month.getUTCMonth()+1,1));selectedDay=null;load();};
  $('todayButton').onclick=()=>{const now=new Date();month=new Date(Date.UTC(now.getFullYear(),now.getMonth(),1));selectedDay=iso(new Date(Date.UTC(now.getFullYear(),now.getMonth(),now.getDate())));load();};
  $('predictionSelect').onchange=event=>{selectedPrediction=event.target.value;const url=new URL(location.href);url.searchParams.set('predictionId',selectedPrediction||'none');history.replaceState({},'',url);load();};
  document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(item=>{const active=item===button;item.classList.toggle('active',active);item.setAttribute('aria-pressed',String(active));});totals();render();});
  $('logout').onclick=()=>window.c1Logout();
  load();
})();
