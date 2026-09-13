(() => {


  const state = {
    demo: null,
    currency: "MXN",
    lastResult: null,
    lastPayload: null,
    rowCounter: 0,
    toastTimer: null,
    aiHistory: [],
    pendingAiUpdates: null,
    aiMode: "checking",
    aiBusy: false,
    pendingPreviewInput: null,
    pendingPreviewResult: null,
    pendingBase: null,
    lastPrompt: "",
    lockedControls: [],
  };

  const byId = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    bindGlobalControls();
    await loadAiStatus();
    const me = await fetch('/api/auth/me');
    if (!me.ok) { window.location.assign('/'); return; }
    const identity = await me.json();
    state.currency = identity.currency;
    byId('companyCurrency').textContent = identity.currency;
    const planId = new URLSearchParams(window.location.search).get('plan');
    if (planId) {
      try {
        const response = await fetch('/api/plans/' + encodeURIComponent(planId));
        const plan = await response.json();
        if (!response.ok) throw new Error(plan.detail || 'No se pudo abrir el plan.');
        populateDemo(plan.analysisInput);
        await runAnalysis({scroll:false});
      } catch (error) { setAnalysisError(error.message); }
    } else { await loadDemo(true); }
    byId('savePlanButton').addEventListener('click', async () => {
      const name = window.prompt('Nombre de esta versión del análisis:', 'Plan de tesorería');
      if (!name) return;
      try {
        const calculated = await runAnalysis({scroll:false});
        if (!calculated) throw new Error('No se guardó: corrige los errores del formulario.');
        if (!state.lastPayload || !state.lastResult) throw new Error('Completa un análisis válido antes de guardar.');
        const response = await fetch('/api/plans', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,analysisInput:state.lastPayload})});
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));
        byId('savePlanStatus').textContent = 'Análisis guardado. Disponible en Documentos e historial → Planes. ID: '+result.id;
      } catch (error) { byId('savePlanStatus').textContent=error.message; }
    });
  }

  function bindGlobalControls() {
    byId("logoutButton").addEventListener("click", () => {
      c1Logout();
    });

    const menuButton = document.querySelector(".mobile-menu-button");
    if (menuButton) {
      menuButton.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
    }

    document.addEventListener("click", (event) => {
      if (
        document.body.classList.contains("sidebar-open") &&
        !event.target.closest(".sidebar") &&
        !event.target.closest(".mobile-menu-button")
      ) {
        document.body.classList.remove("sidebar-open");
      }
    });

    byId("loadDemoButton").addEventListener("click", () => loadDemo(true));
    byId("addEventButton").addEventListener("click", addBlankEvent);
    byId("analyzeButton").addEventListener("click", () => runAnalysis({ scroll: true }));
    byId("exportButton").addEventListener("click", exportAnalysis);

    byId("assistantForm").addEventListener("submit", (event) => {
      event.preventDefault();
      sendAssistantMessage();
    });
    byId("assistantInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        sendAssistantMessage();
      }
    });
    document.querySelectorAll("[data-ai-question]").forEach((button) => {
      button.addEventListener("click", () => sendAssistantMessage(button.dataset.aiQuestion || ""));
    });
    byId("applyAiChangesButton").addEventListener("click", applyAiSuggestedChanges);
    byId("checkGeminiButton").addEventListener("click", checkGemini);
    byId("retryAssistantButton").addEventListener("click", () => sendAssistantMessage(state.lastPrompt));
    byId("importButton").addEventListener("click", () => byId("importInput").click());
    byId("importInput").addEventListener("change", importAnalysis);
  }

  async function loadDemo(autoAnalyze) {
    setAnalysisError("");
    try {
      const response = await fetch("/api/demo", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("No se pudieron cargar los datos de demostración.");
      const demo = await response.json();
      state.demo = demo;
      populateDemo(demo);
      showToast("Datos sintéticos de demostración cargados.");
      if (autoAnalyze) await runAnalysis({ scroll: false });
    } catch (error) {
      setAnalysisError(error.message || "No se pudieron cargar los datos de demostración.");
    }
  }

  function populateDemo(demo, resetChat = true) {
    byId("openingBalance").value = demo.openingBalance;
    byId("liquidityThreshold").value = demo.liquidityThreshold;
    byId("startDate").value = demo.startDate;
    byId("forecastDays").value = demo.days;

    renderEvents(demo.events);

    const scenario = demo.stressScenario || {enabled:false,eventId:"",delayDays:0};
    byId("stressEnabled").checked = scenario.enabled;
    byId("stressDelayDays").value = scenario.delayDays;

    const accelerate = demo.interventions.accelerateReceivable || {enabled:false,eventId:"",daysEarlier:0,discount:0,operationalImpact:1};
    byId("accelerateEnabled").checked = accelerate.enabled;
    byId("accelerateDays").value = accelerate.daysEarlier;
    byId("accelerateDiscount").value = accelerate.discount;
    byId("accelerateImpact").value = accelerate.operationalImpact;

    const defer = demo.interventions.deferPayable || {enabled:false,eventId:"",delayDays:0,financialCost:0,operationalImpact:2};
    byId("deferEnabled").checked = defer.enabled;
    byId("deferDays").value = defer.delayDays;
    byId("deferCost").value = defer.financialCost;
    byId("deferImpact").value = defer.operationalImpact;

    const credit = demo.interventions.creditLine || {enabled:false,amount:9000,daysFromStart:10,financialCost:120,operationalImpact:3};
    byId("creditEnabled").checked = credit.enabled;
    byId("creditAmount").value = credit.amount;
    byId("creditDays").value = credit.daysFromStart;
    byId("creditCost").value = credit.financialCost;
    byId("creditImpact").value = credit.operationalImpact;
    byId("maxActions").value = String(demo.maxActions);

    refreshEventSelectors();
    setSelectValue(byId("stressEventId"), scenario.eventId);
    setSelectValue(byId("accelerateEventId"), accelerate.eventId);
    setSelectValue(byId("deferEventId"), defer.eventId);
    if (resetChat) resetAssistantConversation();
  }

  function renderEvents(events) {
    const body = byId("eventsTableBody");
    body.innerHTML = "";
    events.forEach((event) => appendEventRow(event));
    refreshEventSelectors();
  }

  function appendEventRow(event) {
    const body = byId("eventsTableBody");
    const row = document.createElement("tr");
    const eventId = event.id || `custom-event-${Date.now()}-${state.rowCounter++}`;
    row.dataset.eventId = eventId;
    row.dataset.recurring = String(Boolean(event.recurring));

    row.innerHTML = `
      <td class="counterparty-cell"><input data-field="counterparty" type="text" value="${escapeAttribute(event.counterparty || "Nuevo evento de flujo de caja")}" aria-label="Contraparte"></td>
      <td><select data-field="direction" aria-label="Tipo de evento">
        <option value="inflow" ${event.direction === "inflow" ? "selected" : ""}>Entrada</option>
        <option value="outflow" ${event.direction === "outflow" ? "selected" : ""}>Salida</option>
      </select></td>
      <td class="amount-cell"><input data-field="amount" type="number" min="0.01" step="0.01" value="${escapeAttribute(event.amount || "1000.00")}" aria-label="Monto"></td>
      <td class="date-cell"><input data-field="expectedDate" type="date" value="${escapeAttribute(event.expectedDate || byId("startDate").value)}" aria-label="Fecha esperada"></td>
      <td class="confidence-cell"><input data-field="confidence" type="number" min="0" max="1" step="0.01" value="${escapeAttribute(event.confidence ?? "1.00")}" aria-label="Confianza"></td>
      <td class="category-cell"><input data-field="category" type="text" value="${escapeAttribute(event.category || "otro")}" aria-label="Categoría"></td>
      <td><button class="remove-row-button" type="button" aria-label="Eliminar evento">×</button></td>
    `;

    row.querySelector(".remove-row-button").addEventListener("click", () => {
      row.remove();
      refreshEventSelectors();
    });
    row.querySelector('[data-field="direction"]').addEventListener("change", refreshEventSelectors);
    row.querySelector('[data-field="counterparty"]').addEventListener("input", refreshEventSelectors);
    body.appendChild(row);
  }

  function addBlankEvent() {
    const startDate = byId("startDate").value || new Date().toISOString().slice(0, 10);
    appendEventRow({
      id: `custom-event-${Date.now()}-${state.rowCounter++}`,
      counterparty: "Nuevo evento de flujo de caja",
      amount: "1000.00",
      direction: "outflow",
      expectedDate: startDate,
      confidence: "1.00",
      category: "otro",
      recurring: false,
    });
    refreshEventSelectors();
    const rows = byId("eventsTableBody").querySelectorAll("tr");
    rows[rows.length - 1]?.querySelector("input")?.focus();
  }

  function collectEvents() {
    const rows = [...byId("eventsTableBody").querySelectorAll("tr")];
    if (!rows.length) throw new Error("Agrega al menos un evento de flujo de caja.");

    return rows.map((row) => {
      const value = (field) => row.querySelector(`[data-field="${field}"]`).value.trim();
      const amount = value("amount");
      const confidence = value("confidence");
      if (!value("counterparty") || !amount || Number(amount) <= 0 || !value("expectedDate")) {
        throw new Error("Completa cada evento con una contraparte, un monto positivo y una fecha.");
      }
      if (Number(confidence) < 0 || Number(confidence) > 1) {
        throw new Error("La confianza del evento debe estar entre 0 y 1.");
      }
      return {
        id: row.dataset.eventId,
        counterparty: value("counterparty"),
        amount,
        direction: value("direction"),
        expectedDate: value("expectedDate"),
        category: value("category") || "otro",
        confidence: confidence || "1",
        recurring: row.dataset.recurring === "true",
      };
    });
  }

  function getEventOptions() {
    return [...byId("eventsTableBody").querySelectorAll("tr")].map((row) => ({
      id: row.dataset.eventId,
      label: row.querySelector('[data-field="counterparty"]').value.trim() || row.dataset.eventId,
      direction: row.querySelector('[data-field="direction"]').value,
    }));
  }

  function refreshEventSelectors() {
    const options = getEventOptions();
    setSelectOptions(byId("stressEventId"), options.filter((item) => item.direction === "inflow"));
    setSelectOptions(byId("accelerateEventId"), options.filter((item) => item.direction === "inflow"));
    setSelectOptions(byId("deferEventId"), options.filter((item) => item.direction === "outflow"));
  }

  function setSelectOptions(select, options) {
    const previous = select.value;
    select.innerHTML = "";
    if (!options.length) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "No hay eventos elegibles";
      select.appendChild(empty);
      return;
    }
    options.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      select.appendChild(option);
    });
    if (options.some((item) => item.id === previous)) select.value = previous;
  }

  function setSelectValue(select, value) {
    if ([...select.options].some((option) => option.value === value)) select.value = value;
  }

  function collectPayload() {
    const events = collectEvents();
    const enabledCandidates = [
      byId("accelerateEnabled").checked,
      byId("deferEnabled").checked,
      byId("creditEnabled").checked,
    ].filter(Boolean).length;


    const openingBalance = byId("openingBalance").value;
    const liquidityThreshold = byId("liquidityThreshold").value;
    const startDate = byId("startDate").value;
    const days = Number(byId("forecastDays").value);
    if (Number(openingBalance) < 0 || Number(liquidityThreshold) < 0 || !startDate || days < 1) {
      throw new Error("Completa el saldo inicial, el umbral, la fecha inicial y el horizonte.");
    }

    return {
      openingBalance,
      liquidityThreshold,
      startDate,
      days,
      events,
      stressScenario: {
        enabled: byId("stressEnabled").checked,
        eventId: byId("stressEventId").value || "sin-cobro",
        delayDays: Number(byId("stressDelayDays").value),
      },
      interventions: {
        accelerateReceivable: {
          enabled: byId("accelerateEnabled").checked,
          eventId: byId("accelerateEventId").value || "sin-cobro",
          daysEarlier: Number(byId("accelerateDays").value),
          discount: byId("accelerateDiscount").value,
          operationalImpact: Number(byId("accelerateImpact").value),
        },
        deferPayable: {
          enabled: byId("deferEnabled").checked,
          eventId: byId("deferEventId").value || "sin-pago",
          delayDays: Number(byId("deferDays").value),
          financialCost: byId("deferCost").value,
          operationalImpact: Number(byId("deferImpact").value),
        },
        creditLine: {
          enabled: byId("creditEnabled").checked,
          amount: byId("creditAmount").value,
          daysFromStart: Number(byId("creditDays").value),
          financialCost: byId("creditCost").value,
          operationalImpact: Number(byId("creditImpact").value),
        },
      },
      maxActions: Number(byId("maxActions").value),
    };
  }

  async function runAnalysis({ scroll }) {
    setAnalysisError("");
    setLoading(true);
    try {
      const payload = collectPayload();
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(readApiError(body));

      state.lastPayload = payload;
      state.lastResult = body;
      renderResults(body);
      byId("resultsSection").hidden = false;
      byId("exportButton").disabled = false;
      if (scroll) byId("resultsSection").scrollIntoView({ behavior: "smooth", block: "start" });
      return body;
    } catch (error) {
      setAnalysisError(error.message || "No se pudo completar el análisis.");
      return null;
    } finally {
      setLoading(false);
    }
  }

  function readApiError(body) {
    if (!body) return "El servidor devolvió un error desconocido.";
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg || "Dato inválido").join(" ");
    }
    return "El servidor no pudo analizar esta configuración.";
  }

  function setLoading(loading) {
    const button = byId("analyzeButton");
    button.disabled = loading;
    button.querySelector(".button-label").hidden = loading;
    button.querySelector(".button-spinner").hidden = !loading;
  }

  function setAnalysisError(message) {
    const element = byId("analysisError");
    element.textContent = message;
    element.hidden = !message;
  }

  function renderResults(result) {
    const stressed = result.summary.stressed;
    const repaired = result.summary.repaired;
    const optimization = result.optimization;
    const explanation = result.explanation;

    byId("riskDateMetric").textContent = stressed.riskDate ? formatDate(stressed.riskDate) : "Sin riesgo";
    byId("minimumMetric").textContent = formatCurrency(stressed.minimumConservativeBalance);
    byId("shortfallMetric").textContent = formatCurrency(stressed.projectedShortfall);
    byId("repairedMetric").textContent = repaired
      ? formatCurrency(repaired.minimumConservativeBalance)
      : "No resuelto";

    const badge = byId("resultStatusBadge");
    badge.className = `result-status-badge ${explanation.status}`;
    badge.textContent = {
      safe: "Seguro sin intervención",
      repaired: "Riesgo corregido",
      unresolved: "Se requiere una acción",
    }[explanation.status] || "Análisis completado";

    byId("recommendationTitle").textContent = explanation.title;
    byId("recommendationSummary").textContent = explanation.summary;
    byId("totalCost").textContent = formatCurrency(optimization.totalFinancialCost);
    byId("totalImpact").textContent = String(optimization.totalOperationalImpact);
    byId("evaluatedCandidates").textContent = String(optimization.evaluatedCandidates);

    const selected = byId("selectedActions");
    selected.innerHTML = "";
    if (!optimization.selectedInterventions.length) {
      const empty = document.createElement("div");
      empty.className = "selected-action";
      empty.innerHTML = optimization.feasible
        ? "<strong>No se necesita una intervención</strong><small>El umbral configurado permanece protegido en este horizonte.</small>"
        : "<strong>No se encontró una solución factible</strong><small>Las acciones disponibles no eliminan el faltante. Ajusta los candidatos o las fechas.</small>";
      selected.appendChild(empty);
    } else {
      optimization.selectedInterventions.forEach((action, index) => {
        const item = document.createElement("div");
        item.className = "selected-action";
        item.innerHTML = `<strong>${index + 1}. ${escapeHtml(action.description)}</strong><small>Costo ${formatCurrency(action.financialCost)} · impacto ${action.operationalImpact}</small>`;
        selected.appendChild(item);
      });
    }

    byId("explanationTitle").textContent = explanation.title;
    byId("explanationSummary").textContent = explanation.summary;
    byId("explanationAction").textContent = explanation.action;
    byId("explanationComparison").textContent = explanation.comparison;

    renderAlternatives(optimization.alternatives);
    renderChart(result);
  }

  function renderAlternatives(alternatives) {
    const grid = byId("alternativesGrid");
    grid.innerHTML = "";
    alternatives.forEach((item) => {
      const card = document.createElement("article");
      card.className = "alternative-card";
      card.innerHTML = `
        <div class="alternative-card-head">
          <h4>${escapeHtml(typeLabel(item.type))}</h4>
          <span class="alternative-status ${item.feasibleAlone ? "feasible" : "insufficient"}">${item.feasibleAlone ? "Funciona por sí sola" : "Necesita otra acción"}</span>
        </div>
        <p>${escapeHtml(item.description)}</p>
        <div class="alternative-metrics">
          <span><small>Costo financiero</small><strong>${formatCurrency(item.financialCost)}</strong></span>
          <span><small>Faltante restante</small><strong>${formatCurrency(item.remainingShortfall)}</strong></span>
        </div>
      `;
      grid.appendChild(card);
    });
  }

  function renderChart(result) {
    const container = byId("forecastChart");
    const baseline = result.baseline.projection;
    const stressed = result.stressed.projection;
    const repaired = result.optimization.repaired?.projection || null;
    if (!baseline?.length || !stressed?.length) {
      container.textContent = "No hay datos de proyección disponibles.";
      return;
    }

    const width = 960;
    const height = 370;
    const margin = { top: 22, right: 28, bottom: 48, left: 76 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const threshold = Number(stressed[0].liquidityThreshold);

    const series = [
      { key: "baseline", data: baseline.map((point) => Number(point.conservativeBalance)) },
      { key: "stressed", data: stressed.map((point) => Number(point.conservativeBalance)) },
    ];
    if (repaired) series.push({ key: "repaired", data: repaired.map((point) => Number(point.conservativeBalance)) });

    const allValues = series.flatMap((item) => item.data).concat([threshold]);
    let minimum = Math.min(...allValues);
    let maximum = Math.max(...allValues);
    if (minimum === maximum) { minimum -= 1; maximum += 1; }
    const range = maximum - minimum;
    const yMin = minimum - range * 0.12;
    const yMax = maximum + range * 0.10;

    const x = (index) => margin.left + (index / Math.max(1, baseline.length - 1)) * plotWidth;
    const y = (value) => margin.top + ((yMax - value) / (yMax - yMin)) * plotHeight;
    const pathFor = (values) => values.map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)} ${y(value).toFixed(2)}`).join(" ");

    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Proyecciones conservadoras de flujo de caja: base, estrés y corregida");

    const thresholdY = y(threshold);
    if (thresholdY < margin.top + plotHeight) {
      svg.appendChild(svgElement("rect", {
        x: margin.left,
        y: Math.max(margin.top, thresholdY),
        width: plotWidth,
        height: Math.max(0, margin.top + plotHeight - Math.max(margin.top, thresholdY)),
        class: "chart-risk-zone",
      }));
    }

    const gridCount = 5;
    for (let index = 0; index <= gridCount; index += 1) {
      const value = yMax - ((yMax - yMin) * index) / gridCount;
      const yPosition = y(value);
      svg.appendChild(svgElement("line", { x1: margin.left, y1: yPosition, x2: margin.left + plotWidth, y2: yPosition, class: "chart-grid-line" }));
      const label = svgElement("text", { x: margin.left - 10, y: yPosition + 4, "text-anchor": "end", class: "chart-axis-label" });
      label.textContent = formatCompactCurrency(value);
      svg.appendChild(label);
    }

    const labelEvery = Math.max(1, Math.ceil(baseline.length / 6));
    baseline.forEach((point, index) => {
      if (index % labelEvery !== 0 && index !== baseline.length - 1) return;
      const label = svgElement("text", { x: x(index), y: height - 18, "text-anchor": index === 0 ? "start" : index === baseline.length - 1 ? "end" : "middle", class: "chart-axis-label" });
      label.textContent = shortDate(point.date);
      svg.appendChild(label);
    });

    svg.appendChild(svgElement("line", { x1: margin.left, y1: thresholdY, x2: margin.left + plotWidth, y2: thresholdY, class: "chart-threshold" }));
    const thresholdLabel = svgElement("text", { x: margin.left + plotWidth - 4, y: thresholdY - 7, "text-anchor": "end", class: "chart-threshold-label" });
    thresholdLabel.textContent = `Umbral de seguridad ${formatCompactCurrency(threshold)}`;
    svg.appendChild(thresholdLabel);

    series.forEach((item) => {
      svg.appendChild(svgElement("path", { d: pathFor(item.data), class: `chart-line chart-line-${item.key}` }));
    });

    const riskDate = result.stressed.riskDate;
    if (riskDate) {
      const riskIndex = stressed.findIndex((point) => point.date === riskDate);
      if (riskIndex >= 0) {
        svg.appendChild(svgElement("circle", { cx: x(riskIndex), cy: y(series[1].data[riskIndex]), r: 5, class: "chart-point-stressed" }));
      }
    }

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function svgElement(tag, attributes) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }


  async function apiJson(url, options = {}, timeout = 150000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
      let body;
      try { body = await response.json(); }
      catch { throw new Error("El servidor no devolvió JSON. Comprueba que abriste la versión 6.0.0-web-integrada."); }
      if (!response.ok) {
        const error = new Error(readApiError(body));
        error.code = body.code || `http_${response.status}`;
        throw error;
      }
      return body;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("La petición tardó demasiado. No se aplicaron cambios. Revisa el servidor antes de reintentar.");
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function loadAiStatus() {
    try {
      const status = await apiJson("/api/ai/status", {}, 15000);
      byId("appVersion").textContent = `Versión ${status.version || "desconocida"}`;
      if (status.version !== "6.0.0-web-integrada") throw new Error("Estás viendo otro servidor. Abre la dirección que muestra INICIAR.bat de la versión completa.");
      setAiStatus(status.mode, status.label, status.model);
      setAssistantWarning(status.error || (status.configured ? "" : "El chat requiere Gemini. Ejecuta CONFIGURAR_GEMINI.bat; el formulario y la gráfica funcionan sin IA."));
    } catch (error) {
      setAiStatus("error", "No se pudo verificar el servidor", null);
      setAssistantWarning(error.message);
    }
  }

  function setAiStatus(mode, label, model) {
    state.aiMode = mode;
    const badge = byId("aiStatusBadge");
    badge.className = `ai-status-badge ${mode}`;
    badge.textContent = model ? `${label} · ${model}` : label;
  }

  function resetAssistantConversation() {
    state.aiHistory = [];
    state.pendingAiUpdates = null;
    state.pendingPreviewInput = null;
    state.pendingPreviewResult = null;
    state.pendingBase = null;
    byId("aiSuggestedChanges").hidden = true;
    byId("assistantMessages").innerHTML = "";
    appendAssistantMessage("system", "Pregunta, por ejemplo: ¿qué pasa si mi cliente se tarda en pagar una semana? Gemini propone los parámetros; Python calcula la vista previa. Usa Aplicar escenario a la gráfica para confirmar. Los errores se muestran aquí y no se sustituyen por una guía local.");
  }

  async function checkGemini() {
    if (state.aiBusy) return;
    if (!window.confirm("Esta prueba envía datos sintéticos a Gemini y consume cuota (hasta 2 llamadas). ¿Continuar?")) return;
    setAssistantLoading(true);
    setAssistantWarning("");
    const loading = appendAssistantMessage("system", "Probando la conexión y el escenario de una semana…", true);
    try {
      const result = await apiJson("/api/ai/check", { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
      loading.remove();
      setAiStatus(result.mode, result.label, result.model);
      appendAssistantMessage("system", "Prueba superada: respuesta real de Gemini e interpretación válida de Cliente principal + 7 días. No se modificó la gráfica.");
    } catch (error) {
      loading.remove();
      setAiStatus("error", "Gemini: prueba fallida", null);
      setAssistantWarning(error.message);
      appendAssistantMessage("error", error.message + " No se utilizó un respaldo local.");
    } finally { setAssistantLoading(false); }
  }

  async function sendAssistantMessage(presetQuestion = "") {
    if (state.aiBusy) return;
    const input = byId("assistantInput");
    const message = String(presetQuestion || input.value).trim();
    if (!message) return;
    // Send current edited data, not a stale copy from the last calculation.
    let current;
    try { current = collectPayload(); }
    catch (error) { setAssistantWarning(error.message); return; }
    state.lastPrompt = message;
    byId("retryAssistantButton").hidden = true;
    const previousHistory = state.aiHistory.slice(-8);
    appendAssistantMessage("user", message);
    input.value = "";
    renderAiSuggestedChanges({});
    setAssistantWarning("");
    setAssistantLoading(true);
    const loading = appendAssistantMessage("system", "Consultando Gemini… puede tardar hasta dos minutos si necesita corregir su propuesta.", true);
    try {
      const body = await apiJson("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message, analysisInput: current, history: previousHistory }),
      });
      loading.remove();
      if (body.mode !== "external") throw new Error("Respuesta no generativa rechazada. Comprueba que usas esta versión del servidor.");
      appendAssistantMessage("assistant", body.answer);
      state.aiHistory.push({role:"user",content:message}, {role:"assistant",content:body.answer});
      state.aiHistory = state.aiHistory.slice(-10);
      setAiStatus(body.mode, body.label, body.model);
      renderAiSuggestedChanges(body.suggestedUpdates || {});
      state.pendingBase = JSON.stringify(current);
      state.pendingPreviewInput = body.previewInput;
      state.pendingPreviewResult = body.previewResult;
      if (body.previewResult) {
        appendAssistantMessage("engine", "Vista previa calculada; todavía no cambia la gráfica. " + summarizeScenarioResult(body.previewResult));
      }
    } catch (error) {
      loading.remove();
      setAiStatus("error", "Gemini: solicitud no completada", null);
      renderAiSuggestedChanges({});
      setAssistantWarning(error.message);
      appendAssistantMessage("error", error.message + " No se preparó ningún cambio ni se sustituyó la respuesta por texto local.");
      byId("retryAssistantButton").hidden = false;
    } finally {
      setAssistantLoading(false);
      input.focus();
    }
  }

  function appendAssistantMessage(role, content, loading = false) {
    const article = document.createElement("article");
    article.className = `assistant-message ${role}${loading ? " loading" : ""}`;
    const avatar = document.createElement("span");
    avatar.className = "assistant-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = {user:"TÚ", assistant:"G", engine:"PY", error:"!", system:"C1"}[role] || "C1";
    const body = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = {user:"Tú", assistant:"Gemini", engine:"Motor Python · cálculo verificable", error:"Error de conexión o validación", system:"Sistema"}[role] || "Sistema";
    const messageContent = document.createElement("div");
    const rich = role === "assistant" && !loading;
    messageContent.className = `assistant-content ${rich ? "rich-message" : "plain-message"}`;
    if (window.C1RichText) window.C1RichText.render(messageContent, content, {rich});
    else messageContent.textContent = String(content);
    body.append(name, messageContent);
    article.append(avatar, body);
    const messages = byId("assistantMessages");
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
    return article;
  }

  function renderAiSuggestedChanges(updates) {
    const entries = Object.entries(updates || {});
    state.pendingAiUpdates = entries.length ? { ...updates } : null;
    if (!entries.length) {
      state.pendingPreviewInput = null;
      state.pendingPreviewResult = null;
      state.pendingBase = null;
    }
    const container = byId("aiSuggestedChanges");
    const list = byId("aiSuggestedChangesList");
    list.innerHTML = "";

    if (!entries.length) {
      container.hidden = true;
      return;
    }

    entries.forEach(([key, value]) => {
      const item = document.createElement("li");
      item.textContent = `${aiUpdateLabel(key)}: ${aiUpdateValue(key, value)}`;
      list.appendChild(item);
    });
    container.hidden = false;
  }

  function aiUpdateLabel(key) {
    return {
      openingBalance: "Saldo inicial",
      liquidityThreshold: "Umbral de seguridad",
      days: "Horizonte",
      stressEnabled: "Escenario de retraso",
      stressEventId: "Cobro seleccionado",
      stressDelayDays: "Retraso del cobro",
      accelerateEnabled: "Acelerar cobro",
      accelerateEventId: "Cobro a acelerar",
      accelerateDays: "Días de adelanto",
      accelerateDiscount: "Descuento por pronto pago",
      deferEnabled: "Diferir pago",
      deferEventId: "Pago a diferir",
      deferDays: "Días de diferimiento",
      deferCost: "Costo de diferimiento",
      creditEnabled: "Línea de crédito",
      creditAmount: "Monto del crédito",
      creditDaysFromStart: "Día del desembolso",
      maxActions: "Máximo de acciones",
    }[key] || key;
  }

  function aiUpdateValue(key, value) {
    if (["openingBalance", "liquidityThreshold", "accelerateDiscount", "deferCost", "creditAmount"].includes(key)) {
      return formatCurrency(value);
    }
    if (["stressEnabled", "accelerateEnabled", "deferEnabled", "creditEnabled"].includes(key)) {
      return value ? "Activado" : "Desactivado";
    }
    if (["stressEventId", "accelerateEventId", "deferEventId"].includes(key)) {
      const option = [...document.querySelectorAll("select option")].find((item) => item.value === String(value));
      return option?.textContent || String(value);
    }
    if (["days", "stressDelayDays", "accelerateDays", "deferDays", "creditDaysFromStart"].includes(key)) {
      return `${value} días`;
    }
    return String(value);
  }

  async function applyAiSuggestedChanges() {
    if (state.aiBusy || !state.pendingPreviewInput) return;
    try {
      if (JSON.stringify(collectPayload()) !== state.pendingBase) {
        renderAiSuggestedChanges({});
        setAssistantWarning("Cambiaste los datos después de la consulta. Vuelve a preguntar para generar una propuesta con los datos actuales.");
        return;
      }
      const proposed = state.pendingPreviewInput;
      populateDemo(proposed, false);
      renderAiSuggestedChanges({});
      const result = await runAnalysis({scroll: false});
      if (result) {
        appendAssistantMessage("engine", "Escenario aplicado a la gráfica. " + summarizeScenarioResult(result));
        state.aiHistory.push({role:"assistant",content:"[Resultado del motor Python tras confirmar la simulación] " + summarizeScenarioResult(result)});
        showToast("Gráfica actualizada. No se movió dinero.");
      } else {
        appendAssistantMessage("error", "No se pudo recalcular. Revisa el error del análisis.");
      }
    } catch (error) { setAssistantWarning(error.message); }
  }

  function summarizeScenarioResult(result) {
    const stressed = result?.summary?.stressed || {};
    const repaired = result?.summary?.repaired || null;
    const optimization = result?.optimization || {};
    const selected = Array.isArray(optimization.selectedInterventions)
      ? optimization.selectedInterventions
      : [];

    let answer = `Resultado de la simulación: el saldo conservador mínimo es ${formatCurrency(stressed.minimumConservativeBalance)}, `
      + `el umbral es ${formatCurrency(stressed.liquidityThreshold)} y el faltante máximo es ${formatCurrency(stressed.projectedShortfall)}.`;

    if (stressed.riskDate) {
      answer += ` La primera fecha de riesgo es ${formatDate(stressed.riskDate)}.`;
    } else {
      answer += " No se detecta una fecha de riesgo dentro del horizonte.";
    }

    if (selected.length) {
      answer += ` Recomendación: ${selected.map((item) => item.description).join("; ")}.`;
      answer += ` Costo financiero estimado: ${formatCurrency(optimization.totalFinancialCost)}.`;
    }

    if (!optimization.feasible) answer += " Las intervenciones disponibles no resuelven el faltante.";
    if (repaired) {
      answer += ` Después de la recomendación, el saldo conservador mínimo sube a ${formatCurrency(repaired.minimumConservativeBalance)}.`;
    }
    return answer;
  }

  function setAssistantLoading(loading) {
    state.aiBusy = loading;
    if (loading) {
      state.lockedControls = [...document.querySelectorAll(".treasury-content input, .treasury-content select, .treasury-content button, .topbar-actions button")]
        .filter(control => !control.disabled);
      state.lockedControls.forEach(control => { control.disabled = true; });
    } else {
      state.lockedControls.forEach(control => { control.disabled = false; });
      state.lockedControls = [];
    }
    const button = byId("assistantSendButton");
    button.disabled = loading;
    button.querySelector("span:first-child").hidden = loading;
    button.querySelector(".assistant-send-spinner").hidden = !loading;
    byId("assistantInput").disabled = loading;
  }

  async function importAnalysis() {
    const file = byId("importInput").files[0];
    if (!file) return;
    try {
      if (file.size > 1000000) throw new Error("El archivo supera 1 MB.");
      const parsed = JSON.parse(await file.text());
      const data = parsed.inputs || parsed;
      const result = await apiJson("/api/analyze", {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify(data)},30000);
      populateDemo(data);
      state.lastPayload = collectPayload();
      state.lastResult = result;
      renderResults(result);
      byId("resultsSection").hidden = false;
      byId("exportButton").disabled = false;
      showToast("Plan JSON importado y recalculado.");
    } catch (error) { setAnalysisError(error.message); }
    finally { byId("importInput").value = ""; }
  }

  function setAssistantWarning(message) {
    const warning = byId("assistantWarning");
    warning.textContent = message;
    warning.hidden = !message;
  }

  function exportAnalysis() {
    if (!state.lastResult || !state.lastPayload) return;
    const exportBody = {
      generatedAt: new Date().toISOString(),
      inputs: state.lastPayload,
      analysis: state.lastResult,
      disclaimer: "Prototipo de hackathon con datos sintéticos. No constituye asesoría financiera.",
    };
    const blob = new Blob([JSON.stringify(exportBody, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `analisis-flujo-caja-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function typeLabel(type) {
    return {
      accelerate_receivable: "Acelerar cobro",
      defer_payable: "Diferir pago",
      draw_credit: "Usar crédito",
      delay_expense: "Retrasar gasto",
    }[type] || type;
  }

  function formatCurrency(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return new Intl.NumberFormat("es-MX", { style: "currency", currency: state.currency, maximumFractionDigits: 2 }).format(number);
  }

  function formatCompactCurrency(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    const absolute = Math.abs(number);
    if (absolute >= 1_000_000) return `${number < 0 ? "−" : ""}$${(absolute / 1_000_000).toFixed(1)}m`;
    if (absolute >= 1_000) return `${number < 0 ? "−" : ""}$${(absolute / 1_000).toFixed(0)}k`;
    return `${number < 0 ? "−" : ""}$${absolute.toFixed(0)}`;
  }

  function formatDate(isoDate) {
    const date = new Date(`${isoDate}T12:00:00`);
    return new Intl.DateTimeFormat("es-MX", { month: "short", day: "numeric", year: "numeric" }).format(date);
  }

  function shortDate(isoDate) {
    const date = new Date(`${isoDate}T12:00:00`);
    return new Intl.DateTimeFormat("es-MX", { month: "short", day: "numeric" }).format(date);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttribute(value) {
    return escapeHtml(value);
  }

  function showToast(message) {
    const toast = byId("toast");
    window.clearTimeout(state.toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    state.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2800);
  }
})();
