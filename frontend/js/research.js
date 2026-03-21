(function () {
  const state = {
    meta: null,
    budget: null,
    depth: "quick",
    focus: "all-around",
    customAgents: new Set(),
    sessionPolling: null,
    startedAt: null,
    lastEventCount: 0,
    currentPhase: 0,
    targetValidation: null,
    targetValidationNonce: 0,
  };

  const POPULAR = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "GOOGL", "META", "NFLX", "OPENAI", "ANTHROPIC"];

  function depthCalls(depth) {
    if (depth === "custom") {
      let total = 0;
      for (const id of state.customAgents) {
        const a = state.meta.agents.find((x) => x.id === id);
        total += a ? a.compound_searches : 0;
      }
      return total;
    }
    return state.meta.depth_config[depth].total_compound_calls;
  }

  function depthAgents(depth) {
    if (depth === "custom") return [...state.customAgents];
    return state.meta.depth_config[depth].agents;
  }

  function setTargetValidationMessage(text, kind) {
    const el = document.getElementById("target-validation-msg");
    if (!el) return;
    el.textContent = text || "";
    el.className = "target-validation-msg";
    if (kind === "ok") el.classList.add("target-val-ok");
    if (kind === "error") el.classList.add("target-val-error");
  }

  async function validateTarget(target, showSuccess = true) {
    const clean = (target || "").trim();
    if (!clean) {
      state.targetValidation = null;
      setTargetValidationMessage("", null);
      return null;
    }
    const nonce = ++state.targetValidationNonce;
    try {
      const res = await fetch(`/api/target/validate?target=${encodeURIComponent(clean)}`, { cache: "no-store" });
      const data = await res.json();
      if (nonce !== state.targetValidationNonce) return null;
      state.targetValidation = data;
      if (!res.ok || !data.is_valid) {
        setTargetValidationMessage(data.reason || "Target could not be validated.", "error");
        return data;
      }
      if (showSuccess) {
        const visibility = data.is_public ? `Public (${data.ticker || "N/A"})` : "Private";
        setTargetValidationMessage(`${visibility} company verified. ${data.reason || ""}`.trim(), "ok");
      }
      return data;
    } catch (_) {
      if (nonce !== state.targetValidationNonce) return null;
      const fallback = { is_valid: false, reason: "Validation check failed. Please try again." };
      state.targetValidation = fallback;
      setTargetValidationMessage(fallback.reason, "error");
      return fallback;
    }
  }

  function recalcHome() {
    const calls = depthCalls(state.depth);
    const remaining = state.budget.remaining;
    document.getElementById("run-btn").textContent = `Run Research (${calls} compound calls)`;
    document.getElementById("run-help").textContent = `~${state.depth === "quick" ? 2 : state.depth === "standard" ? 6 : state.depth === "deep" ? 12 : 4} minutes estimated · Technical chart analysis included (free)`;
    document.getElementById("budget-line").textContent = `Today: ${state.budget.used} compound calls used (${remaining} remaining)`;
    const btn = document.getElementById("run-btn");
    btn.disabled = calls > remaining || calls <= 0;
    btn.title = btn.disabled ? "Insufficient daily budget" : "";
    const pills = document.getElementById("depth-agent-pills");
    pills.innerHTML = depthAgents(state.depth).map((id) => `<span class="tag">${id}</span>`).join("");
    const customSummary = document.getElementById("custom-summary");
    if (customSummary) customSummary.textContent = `Selected: ${state.customAgents.size} agents | ${calls} calls | ~${Math.max(remaining - calls, 0)} remaining after`;
  }

  function renderDepthCards() {
    const grid = document.getElementById("depth-grid");
    const base = ["quick", "standard", "deep"];
    const rows = base.map((key) => {
      const cfg = state.meta.depth_config[key];
      return `<div class="depth-card ${state.depth === key ? "active" : ""}" data-depth="${key}">
        <b>${key[0].toUpperCase() + key.slice(1)}</b>
        <p style="margin:5px 0;color:var(--muted)">${cfg.agents.length} agents | ${cfg.total_compound_calls} calls</p>
        <small style="color:var(--muted)">${cfg.description} | ~${cfg.est_minutes}m + chart</small>
      </div>`;
    });
    rows.push(`<div class="depth-card ${state.depth === "custom" ? "active" : ""}" data-depth="custom"><b>Custom</b><p style="margin:5px 0;color:var(--muted)">Pick your own agent mix</p><small style="color:var(--muted)">1 call per agent + chart analysis</small></div>`);
    grid.innerHTML = rows.join("");
    grid.querySelectorAll(".depth-card").forEach((card) => {
      card.addEventListener("click", () => {
        state.depth = card.dataset.depth;
        if (state.depth !== "custom") state.customAgents = new Set(depthAgents(state.depth));
        document.getElementById("custom-agent-box").style.display = state.depth === "custom" || state.focus === "custom" ? "block" : "none";
        renderDepthCards();
        recalcHome();
      });
    });
  }

  function renderCustomList() {
    const root = document.getElementById("custom-agent-list");
    if (!root) return;
    root.innerHTML = state.meta.agents.map((a) => {
      const checked = state.customAgents.has(a.id) ? "checked" : "";
      return `<label class="row"><span><input type="checkbox" data-agent="${a.id}" ${checked} /> ${a.name}</span><small>${a.compound_searches} call</small></label>`;
    }).join("");
    root.querySelectorAll("input[data-agent]").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) state.customAgents.add(cb.dataset.agent);
        else state.customAgents.delete(cb.dataset.agent);
        recalcHome();
      });
    });
  }

  function initTickerStrip() {
    const strip = document.getElementById("ticker-strip");
    if (!strip) return;
    strip.innerHTML = POPULAR.map((x) => `<button class="pill" data-ticker="${x}">${x}</button>`).join(" ");
    strip.querySelectorAll("button[data-ticker]").forEach((b) => {
      b.addEventListener("click", () => {
        const t = document.getElementById("target");
        t.value = b.dataset.ticker;
        setTargetValidationMessage("", null);
      });
    });
  }

  async function initHome() {
    const meta = await fetch("/api/meta").then((r) => r.json());
    const budget = await fetch("/api/budget").then((r) => r.json());
    state.meta = meta;
    state.budget = budget;
    state.customAgents = new Set(meta.depth_config.quick.agents);
    document.getElementById("hero-start").onclick = () => document.getElementById("new-research").scrollIntoView({ behavior: "smooth" });
    document.getElementById("hero-sample").onclick = () => { location.hash = "#/history"; };
    renderDepthCards();
    renderCustomList();
    initTickerStrip();
    document.getElementById("focus-row").querySelectorAll(".pill").forEach((p) => {
      p.addEventListener("click", () => {
        document.getElementById("focus-row").querySelectorAll(".pill").forEach((x) => x.classList.remove("active"));
        p.classList.add("active");
        state.focus = p.dataset.focus;
        document.getElementById("custom-agent-box").style.display = state.focus === "custom" || state.depth === "custom" ? "block" : "none";
      });
    });
    const context = document.getElementById("context");
    const targetInput = document.getElementById("target");
    targetInput.addEventListener("blur", async () => {
      await validateTarget(targetInput.value.trim(), true);
    });
    context.addEventListener("input", () => { document.getElementById("context-count").textContent = `${context.value.length} / 2000`; });
    document.getElementById("run-btn").addEventListener("click", async () => {
      const target = document.getElementById("target").value.trim();
      if (!target) return;
      const targetCheck = await validateTarget(target, true);
      if (!targetCheck || !targetCheck.is_valid) return;
      const payload = { target, depth: state.depth, focus: state.focus, context: context.value, specific_questions: document.getElementById("specific_questions").value, agent_ids: [...state.customAgents], force_refresh: true };
      const btn = document.getElementById("run-btn");
      btn.disabled = true;
      btn.textContent = "Dispatching agents...";
      const res = await fetch("/api/research/start", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!res.ok) { const err = await res.json(); alert(err.detail || "Failed to start research"); btn.disabled = false; recalcHome(); return; }
      const data = await res.json();
      location.hash = `#/research?session_id=${encodeURIComponent(data.session_id)}&run_id=${Date.now()}`;
    });
    recalcHome();
  }

  const KIND_CLASS = { phase:"terminal-phase", agent:"terminal-agent", ai:"terminal-ai", warn:"terminal-warn", memo:"terminal-memo", research:"terminal-sys", info:"terminal-info" };
  function escapeHtml(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function termLine(evt) {
    const t = (evt.timestamp||"").replace("T"," ").slice(11,19);
    const kind = (evt.kind||"info").toLowerCase();
    const cls = KIND_CLASS[kind]||"terminal-info";
    const tag = kind.toUpperCase().padEnd(8);
    return `<div class="terminal-line ${cls}"><span class="terminal-ts">${t}</span><span class="terminal-tag">[${tag}]</span><span class="terminal-msg">${escapeHtml(evt.message||"")}</span></div>`;
  }
  function appendToTerminal(paneId, events) {
    const pane = document.getElementById(paneId);
    if (!pane) return;
    events.forEach((evt) => pane.insertAdjacentHTML("beforeend", termLine(evt)));
    pane.scrollTop = pane.scrollHeight;
  }
  function getTerminalPaneForPhase(phase) {
    if (phase === 1) return "terminal-pane";
    if (phase === 2) return "terminal-pane-2";
    if (phase === 3) return "terminal-pane-3";
    return "terminal-pane-4";
  }

  function showPhasePage(phase) {
    [1,2,3,4,5].forEach((p) => { const pg = document.getElementById(`page-phase-${p}`); if (pg) pg.classList.toggle("hidden", p !== phase); });
    [1,2,3,4,5].forEach((p) => { const step = document.getElementById(`pstep-${p}`); if (!step) return; step.classList.remove("active","done"); if (p < phase) step.classList.add("done"); else if (p === phase) step.classList.add("active"); });
    [1,2,3,4].forEach((p) => { const conn = document.getElementById(`pconn-${p}`); if (conn) conn.classList.toggle("done", p < phase); });
    state.currentPhase = phase;
  }

  const STATUS_META = { pending:{cls:"status-pending",icon:"○"}, searching:{cls:"status-searching",icon:"◎"}, running:{cls:"status-writing",icon:"◈"}, complete:{cls:"status-complete",icon:"●"}, error:{cls:"status-error",icon:"✕"} };

  function renderAgentCard(agent) {
    const sm = STATUS_META[agent.status] || STATUS_META.pending;
    const pct = agent.searches_total ? Math.round((agent.searches_completed/agent.searches_total)*100) : 0;
    const sourcesStr = agent.sources&&agent.sources.length ? `${agent.sources.length} sources` : "0 sources";
    const preview = (agent.findings_preview||"").replace(/\*\*/g,"").replace(/#{1,6} /g,"").slice(0,180);
    return `<div class="agent-card-v ${sm.cls}" id="acard-${agent.id}">
      <div class="acard-header"><span class="acard-icon">${sm.icon}</span><span class="acard-name">${escapeHtml(agent.name||agent.id)}</span><span class="acard-status ${sm.cls}">${agent.status}</span></div>
      <div class="acard-query">${escapeHtml(agent.current_search_query||"Waiting...")}</div>
      <div class="acard-progress-row"><div class="acard-progress-bar"><div style="width:${pct}%"></div></div><span class="acard-srcs">${sourcesStr}</span></div>
      ${preview ? `<div class="acard-preview">${escapeHtml(preview)}</div>` : ""}
    </div>`;
  }
  function updateAgentGrid(agents) {
    const grid = document.getElementById("agent-grid");
    if (!grid) return;
    agents.forEach((agent) => { const existing = document.getElementById(`acard-${agent.id}`); const html = renderAgentCard(agent); if (existing) existing.outerHTML = html; else grid.insertAdjacentHTML("beforeend", html); });
  }
  function updateSynthesisSummary(agents) {
    const list = document.getElementById("synthesis-findings-list");
    if (!list) return;
    list.innerHTML = agents.map((a) => { const sm = STATUS_META[a.status]||STATUS_META.pending; const srcs = a.sources?a.sources.length:0; return `<div class="synth-agent-row"><span class="acard-icon ${sm.cls}">${sm.icon}</span><span style="flex:1;font-weight:500">${escapeHtml(a.name||a.id)}</span><span class="tag" style="font-size:11px">${srcs} src</span><span class="acard-status ${sm.cls}" style="font-size:11px">${a.status}</span></div>`; }).join("");
  }
  function updateCrossPairs(crossNotes) {
    const grid = document.getElementById("cross-pairs-grid");
    if (!grid||!crossNotes) return;
    if (crossNotes.length&&crossNotes[0].skipped) { grid.innerHTML = `<div class="cross-skipped-card"><span>⟳</span> Cross-examination skipped.<div style="color:var(--muted);font-size:12px;margin-top:4px;">${escapeHtml(crossNotes[0].reason||"")}</div></div>`; return; }
    grid.innerHTML = crossNotes.map((n) => `<div class="cross-pair-card"><div class="cross-pair-agents"><b>${escapeHtml(n.agent_a)}</b> ↔ <b>${escapeHtml(n.agent_b)}</b></div><div class="cross-pair-note">${escapeHtml(n.note||"Processing...")}</div></div>`).join("");
  }

  function updateTaSignalsLive(taData) {
    const panel = document.getElementById("ta-signals-live");
    if (!panel || !taData) return;
    if (!taData.is_public) { panel.innerHTML = `<div style="padding:20px;text-align:center;color:var(--muted);"><div style="font-size:24px;margin-bottom:8px;">🔒</div><b>Private Company</b><br><small>No public market data available</small></div>`; return; }
    if (taData.error === "data_fetch_failed") { panel.innerHTML = `<div style="padding:20px;text-align:center;color:#f87171;"><div style="font-size:24px;margin-bottom:8px;">⚠</div>Could not fetch price data for <b>${escapeHtml(taData.ticker||"")}</b></div>`; return; }
    const signals = taData.signals||[];
    const patterns = taData.patterns||[];
    const dir = taData.technical_direction||"NEUTRAL";
    const score = taData.technical_score||5.0;
    const sr = taData.support_resistance||{};
    const dirColor = dir==="BULLISH"?"#22c55e":dir==="BEARISH"?"#ef4444":"#f59e0b";
    const cp = sr.current_price ? `$${sr.current_price.toFixed(2)}` : "N/A";
    const wkHigh = sr.wk52_high ? `$${sr.wk52_high.toFixed(2)}` : "N/A";
    const wkLow = sr.wk52_low ? `$${sr.wk52_low.toFixed(2)}` : "N/A";
    panel.innerHTML = `
      <div style="padding:10px 12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);margin-bottom:8px;">
        <div><span style="font-weight:700;font-size:15px;">${escapeHtml(taData.ticker||"")}</span><span style="margin-left:8px;color:var(--muted);font-size:12px;">${cp}</span></div>
        <div style="display:flex;align-items:center;gap:10px;"><span style="color:${dirColor};font-weight:700;font-size:13px;">${dir}</span><span style="border:1px solid ${dirColor};color:${dirColor};border-radius:999px;padding:2px 10px;font-size:12px;">${score}/10</span></div>
      </div>
      <div style="padding:0 12px 6px;font-size:11px;color:var(--muted);">52w: ${wkHigh} high / ${wkLow} low</div>
      ${signals.map((s)=>{ const ic=s.type==="bullish"?"↑":s.type==="bearish"?"↓":"→"; const col=s.type==="bullish"?"#22c55e":s.type==="bearish"?"#ef4444":"#94a3b8"; const str=s.strength==="strong"?"●●●":s.strength==="moderate"?"●●○":"●○○"; return `<div style="padding:7px 12px;border-bottom:1px solid rgba(31,42,61,0.5);display:flex;gap:8px;align-items:flex-start;"><span style="color:${col};min-width:14px;margin-top:1px;">${ic}</span><div style="flex:1;"><div style="font-size:12px;font-weight:600;color:${col};">${escapeHtml(s.signal)}</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">${escapeHtml(s.detail)}</div></div><span style="font-size:10px;color:#475569;letter-spacing:1px;margin-top:2px;">${str}</span></div>`; }).join("")}
      ${patterns.length ? `<div style="padding:8px 12px;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:4px;">Candlestick Patterns</div>${patterns.map((p)=>{ const col=p.type==="bullish"?"#22c55e":p.type==="bearish"?"#ef4444":"#94a3b8"; return `<div style="padding:5px 12px;font-size:11px;display:flex;gap:6px;"><span style="color:${col};">${p.type==="bullish"?"↑":p.type==="bearish"?"↓":"→"}</span><span style="font-weight:600;color:${col};">${escapeHtml(p.name)}</span><span style="color:var(--muted);">${escapeHtml(p.desc)}</span></div>`; }).join("")}` : ""}`;
  }

  async function initResearch(sessionId) {
    if (!sessionId) { location.hash = "#/"; return; }
    // Kill any previous polling loop before starting a new one
    if (state.sessionPolling) { clearInterval(state.sessionPolling); state.sessionPolling = null; }
    state.startedAt = Date.now();
    state.lastEventCount = 0;
    state.currentPhase = 0;
    const proceedBtn = document.getElementById("proceed-btn");
    proceedBtn.onclick = async () => { proceedBtn.disabled = true; proceedBtn.textContent = "Proceeding..."; try { await fetch(`/api/research/${sessionId}/proceed`, { method: "POST" }); } catch (_) {} };
    const clearBtn = document.getElementById("clear-log-btn");
    if (clearBtn) clearBtn.onclick = () => { const pane = document.getElementById("terminal-pane"); if (pane) pane.innerHTML = ""; };
    showPhasePage(1);

    async function tick() {
      const data = await fetch(`/api/research/${sessionId}/status`).then((r) => r.json());
      document.getElementById("research-target").textContent = data.target || "–";
      document.getElementById("phase-text").textContent = `Phase ${data.phase}: ${data.phase_name}`;
      document.getElementById("calls-used-badge").textContent = `${data.budget_used || 0} calls used`;
      const pct = data.agents_total ? Math.round((data.agents_complete/data.agents_total)*100) : 0;
      document.getElementById("overall-progress").style.width = `${pct}%`;
      const phase = Number(data.phase) || 0;
      const displayPhase = phase >= 5 ? 5 : Math.max(phase, 1);
      if (displayPhase !== state.currentPhase) showPhasePage(displayPhase);
      const allEvents = data.event_log || [];
      const newEvents = allEvents.slice(state.lastEventCount);
      if (newEvents.length) { appendToTerminal(getTerminalPaneForPhase(displayPhase), newEvents); state.lastEventCount = allEvents.length; }
      if (phase <= 2) updateAgentGrid(data.agents || []);
      // New phase order: 1=Research, 2=Technical, 3=Cross-Exam, 4=Synthesis, 5=Complete
      if (phase === 2) {
        const c = document.getElementById("phase2-chip");
        if (c) { c.textContent="Running"; c.style.background="rgba(0,229,204,0.15)"; c.style.color="var(--accent)"; }
        if (data.technical_analysis) updateTaSignalsLive(data.technical_analysis);
      }
      if (phase === 3) {
        const c = document.getElementById("phase3-chip");
        if (c) { c.textContent="Running"; c.style.background="rgba(0,229,204,0.15)"; c.style.color="var(--accent)"; }
        updateCrossPairs(data.cross_exam_notes||[]);
      }
      if (phase === 4) {
        updateSynthesisSummary(data.agents||[]);
        const c = document.getElementById("phase4-chip");
        if (c) { c.textContent="Running"; c.style.background="rgba(0,229,204,0.15)"; c.style.color="var(--accent)"; }
      }
      const doneChips = [{n:"phase1-chip",threshold:2},{n:"phase2-chip",threshold:3},{n:"phase3-chip",threshold:4},{n:"phase4-chip",threshold:5}];
      doneChips.forEach(({n,threshold}) => { if (phase >= threshold) { const c=document.getElementById(n); if (c) { c.textContent="Complete"; c.style.background="rgba(34,197,94,0.15)"; c.style.color="#22c55e"; } } });
      if (data.cross_exam_notes&&data.cross_exam_notes.length&&phase>=2) updateCrossPairs(data.cross_exam_notes);
      const awaiting = data.awaiting_user_phase;
      const awaitingPill = document.getElementById("awaiting-pill");
      const awaitingMsg = document.getElementById("phase-subtext");
      if (awaiting) {
        awaitingPill.classList.remove("hidden"); proceedBtn.classList.remove("hidden"); proceedBtn.disabled = false;
        proceedBtn.textContent = awaiting===3?"Start Cross-Examination →":awaiting===4?"Start Synthesis →":"Proceed →";
        if (awaitingMsg) awaitingMsg.textContent = data.awaiting_user_message||"Phase complete — proceed when ready.";
      } else { awaitingPill.classList.add("hidden"); proceedBtn.classList.add("hidden"); if (awaitingMsg) awaitingMsg.textContent=""; }
      if (phase===4&&data.memo) { const preview=document.getElementById("synthesis-verdict-preview"); const inner=document.getElementById("verdict-preview-inner"); if (preview&&inner) { preview.classList.remove("hidden"); const vc=data.memo.verdict==="BULLISH"?"#22c55e":data.memo.verdict==="BEARISH"?"#ef4444":"#f59e0b"; inner.innerHTML=`<div style="font-size:22px;font-weight:700;color:${vc}">${data.memo.verdict}</div><div style="font-size:13px;color:var(--muted);margin-top:4px;">Score: ${data.memo.overall_score}/10 | ${data.memo.confidence} confidence</div><div style="font-size:13px;margin-top:6px;">${escapeHtml(data.memo.summary||"")}</div>`; } }
      if (data.status === "complete") {
        clearInterval(state.sessionPolling);
        showPhasePage(5);
        const totalSources = (data.agents||[]).reduce((a,ag)=>a+(ag.sources?ag.sources.length:0),0);
        document.getElementById("cs-agents").textContent = data.agents_total||"–";
        document.getElementById("cs-sources").textContent = totalSources;
        document.getElementById("cs-calls").textContent = data.budget_used||0;
        document.getElementById("cs-verdict").textContent = data.memo?.verdict||"–";
        document.getElementById("cs-score").textContent = data.memo?.overall_score ? `${data.memo.overall_score}/10` : "–";
        const taScore = data.technical_analysis?.technical_score;
        const taDir = data.technical_analysis?.technical_direction;
        const csTech = document.getElementById("cs-tech-score");
        if (csTech) { if (taScore && taDir && taDir !== "NEUTRAL") { csTech.textContent=`${taScore}/10`; csTech.style.color=taDir==="BULLISH"?"#22c55e":"#ef4444"; } else if (taScore) { csTech.textContent=`${taScore}/10`; } else { csTech.textContent="N/A"; } }
        document.getElementById("to-memo").href = `#/memo?session_id=${sessionId}`;
        proceedBtn.classList.add("hidden"); awaitingPill.classList.add("hidden");
      }
    }
    await tick();
    state.sessionPolling = setInterval(tick, 2000);
  }

  async function initHistory() {
    const rows = await fetch("/api/history").then((r) => r.json());
    const body = document.getElementById("history-body");
    const search = document.getElementById("history-search");
    const verdict = document.getElementById("history-verdict");
    const dateFrom = document.getElementById("history-date-from");
    const dateTo = document.getElementById("history-date-to");
    function applyFilters() {
      const q = search.value.toLowerCase(); const v = verdict.value; const from = dateFrom.value; const to = dateTo.value;
      const filtered = rows.filter((r) => { if (q&&!(r.target||"").toLowerCase().includes(q)) return false; if (v&&r.verdict!==v) return false; const d=(r.created_at||"").slice(0,10); if (from&&d<from) return false; if (to&&d>to) return false; return true; });
      body.innerHTML = filtered.map((r) => `<tr><td>${r.target||"-"}</td><td>${(r.created_at||"").slice(0,10)}</td><td>${r.depth||"-"}</td><td>${r.verdict||"-"}</td><td>${r.overall_score||"-"}</td><td>${r.agents_total||"-"}</td><td>${r.calls_used||0}</td><td><button class="btn btn-outline" onclick="location.hash='#/memo?session_id=${r.session_id}'">View</button> <button class="btn btn-outline" onclick="window.AlphaResearch.rerun('${r.session_id}')">Re-run</button> <button class="btn btn-outline" onclick="window.AlphaResearch.remove('${r.session_id}')">Delete</button></td></tr>`).join("");
      const avg=filtered.length?(filtered.reduce((a,b)=>a+Number(b.overall_score||0),0)/filtered.length).toFixed(1):"0.0";
      const callsMonth=filtered.reduce((a,b)=>a+Number(b.calls_used||0),0);
      const freq={}; filtered.forEach((r)=>{freq[r.target]=(freq[r.target]||0)+1;});
      const top=Object.entries(freq).sort((a,b)=>b[1]-a[1])[0];
      document.getElementById("history-stats").textContent = `Total runs: ${filtered.length} | Avg score: ${avg} | Calls used: ${callsMonth} | Most researched: ${top?`${top[0]} (${top[1]}x)`:"n/a"}`;
    }
    [search,verdict,dateFrom,dateTo].forEach((el)=>el.addEventListener("input",applyFilters));
    applyFilters();
  }

  async function rerun(sessionId) {
    const old = await fetch(`/api/history/${sessionId}`).then((r) => r.json());
    const payload = { target:old.target, depth:old.depth, focus:old.focus, context:old.context||"", specific_questions:old.specific_questions||"", agent_ids:old.agent_ids||[], force_refresh:true };
    const res = await fetch("/api/research/start", { method:"POST", cache:"no-store", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
    const data = await res.json();
    if (data.session_id) location.hash = `#/research?session_id=${encodeURIComponent(data.session_id)}&run_id=${Date.now()}`;
  }

  async function remove(sessionId) { await fetch(`/api/history/${sessionId}`,{method:"DELETE"}); initHistory(); }

  function stopPolling() {
    if (state.sessionPolling) { clearInterval(state.sessionPolling); state.sessionPolling = null; }
  }

  window.AlphaResearch = { initHome, initResearch, initHistory, rerun, remove, stopPolling };
})();
