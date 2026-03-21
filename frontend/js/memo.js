(function () {
  let chart = null;

  // ── Utility ─────────────────────────────────────────────────────────────────
  function scoreBar(label, value) {
    const v = (value !== null && value !== undefined) ? Number(value) : null;
    // Show N/A for zero or missing — zero means the LLM had no data for this subscore
    if (v === null || isNaN(v) || v <= 0) {
      return `<div style="margin-bottom:8px;opacity:0.45;"><div class="row"><span>${label}</span><span style="font-size:11px;color:var(--muted);">N/A</span></div><div class="progress"><div style="width:0%"></div></div></div>`;
    }
    const pct = Math.min(100, v * 10);
    const col = v >= 7 ? '#22c55e' : v >= 5 ? '#00e5cc' : '#ef4444';
    return `<div style="margin-bottom:8px;"><div class="row"><span>${label}</span><span style="color:${col};">${v.toFixed(1)}</span></div><div class="progress"><div style="width:${pct}%;background:${col};"></div></div></div>`;
  }
  function verdictColor(v) {
    if (v === "BULLISH") return "#22c55e";
    if (v === "BEARISH") return "#ef4444";
    return "#f59e0b";
  }
  function trustBadge(risk) {
    if (risk === "HIGH") return "⛔ Unverified";
    if (risk === "MEDIUM") return "⚠ Review";
    return "✓ Verified";
  }
  function escHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── MEMO INIT ────────────────────────────────────────────────────────────────
  async function initMemo(sessionId) {
    if (!sessionId) { location.hash = "#/history"; return; }

    const data = await fetch(`/api/history/${sessionId}`).then((r) => r.json());
    const memo = data.memo || {};

    document.getElementById("memo-target").textContent = data.target || "Untitled";
    document.getElementById("memo-meta").textContent = `Last researched: ${(data.updated_at || "").replace("T", " ").slice(0, 19)} | ${(data.agent_ids || []).length} agents | ${Object.values(data.agent_results || {}).reduce((a, b) => a + (b.sources || []).length, 0)} sources`;

    const verdict = memo.verdict || "NEUTRAL";
    document.getElementById("verdict-badge").textContent = verdict;
    document.getElementById("confidence-badge").textContent = `${memo.confidence || "LOW"} confidence`;
    document.getElementById("verdict-badge").style.borderColor = verdictColor(verdict);
    document.getElementById("summary-card").style.borderColor = verdictColor(verdict);

    document.getElementById("summary-card").innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
        <h3 style="margin:0;">Executive Summary</h3>
        <span style="margin-left:auto;font-size:12px;color:var(--muted);">${memo.time_horizon || ""} horizon</span>
      </div>
      <div style="color:#cbd5e1;line-height:1.85;font-size:14px;white-space:pre-line;">${memo.summary || ""}</div>
    `;

    const predCard = document.getElementById("prediction-text");
    if (predCard) predCard.innerHTML = `<div style="line-height:1.85;white-space:pre-line;">${memo.final_prediction || "No prediction available."}</div>`;

    const actionInline = document.getElementById("action-inline-badge");
    if (actionInline) {
      const actionColors = { BUY: "#22c55e", STRONG_BUY: "#16a34a", SELL: "#ef4444", STRONG_SELL: "#b91c1c", HOLD: "#f59e0b" };
      const act = memo.investment_action || "HOLD";
      actionInline.textContent = act;
      actionInline.style.color = actionColors[act] || "#f59e0b";
      actionInline.style.borderColor = actionColors[act] || "#f59e0b";
    }

    const findingsList = document.getElementById("key-findings-list");
    if (findingsList) {
      findingsList.innerHTML = (memo.key_findings || []).map((f, i) => `
        <div style="display:flex;gap:14px;padding:12px 0;border-bottom:1px solid #1f2a3d;">
          <div style="color:var(--accent);font-weight:700;font-size:13px;min-width:22px;padding-top:1px;">${i + 1}</div>
          <div style="color:#cbd5e1;line-height:1.75;font-size:13.5px;">${f}</div>
        </div>`).join("");
    }

    const bullList = document.getElementById("bull-thesis-list");
    if (bullList) {
      bullList.innerHTML = (memo.bull_thesis || []).map((b) => `
        <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid rgba(22,101,52,0.3);">
          <span style="color:#4ade80;font-size:16px;padding-top:1px;">&#8679;</span>
          <div style="color:#d1fae5;line-height:1.75;font-size:13.5px;">${b}</div>
        </div>`).join("");
    }

    const bearList = document.getElementById("bear-thesis-list");
    if (bearList) {
      bearList.innerHTML = (memo.bear_thesis || []).map((b) => `
        <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid rgba(127,29,29,0.3);">
          <span style="color:#f87171;font-size:16px;padding-top:1px;">&#8681;</span>
          <div style="color:#fee2e2;line-height:1.75;font-size:13.5px;">${b}</div>
        </div>`).join("");
    }

    const risksList = document.getElementById("key-risks-list");
    if (risksList) {
      const severityColor = { HIGH: "#ef4444", MEDIUM: "#f59e0b", LOW: "#22c55e" };
      risksList.innerHTML = (memo.key_risks || []).map((r) => {
        const sev = r.severity || "MEDIUM";
        const col = severityColor[sev] || "#f59e0b";
        return `<div style="padding:10px 0;border-bottom:1px solid rgba(124,58,237,0.2);">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">
            <span style="font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid ${col};color:${col};">${sev}</span>
            <span style="font-size:11px;color:#64748b;">${r.category || ""}</span>
          </div>
          <div style="color:#ddd6fe;line-height:1.7;font-size:13.5px;">${r.risk || ""}</div>
        </div>`;
      }).join("");
    }

    const catalystsList = document.getElementById("key-catalysts-list");
    if (catalystsList) {
      catalystsList.innerHTML = (memo.key_catalysts || []).map((cat) => `
        <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid rgba(14,116,144,0.2);">
          <span style="color:#22d3ee;font-size:15px;padding-top:2px;">&#9889;</span>
          <div style="color:#cffafe;line-height:1.75;font-size:13.5px;">${cat}</div>
        </div>`).join("");
    }

    const risks = Object.values(data.agent_results || {}).map((r) => (r.hallucination_check || {}).risk_level || "LOW");
    const hasHigh = risks.includes("HIGH");
    const hasMedium = risks.includes("MEDIUM");
    const quality = document.getElementById("data-quality-banner");
    if (hasHigh) { quality.style.borderColor = "#ef4444"; quality.innerHTML = "⛔ One or more agents returned high-risk findings. Treat highlighted sections as unverified."; }
    else if (hasMedium) { quality.style.borderColor = "#f59e0b"; quality.innerHTML = "⚠ Some findings contain unverified claims. See agent details for specifics."; }
    else { quality.style.borderColor = "#22c55e"; quality.innerHTML = "✓ High data confidence - all findings sourced"; }

    document.getElementById("overall-score").textContent = `${Number(memo.overall_score || 0).toFixed(1)}/10`;

    const subs = memo.subscores || {};
    const taSum = data.technical_analysis || {};
    const taBars = taSum.technical_score != null
      ? [scoreBar("Technical Score", taSum.technical_score)]
      : [];
    const subsHtml = [
      scoreBar("Financial Health", subs.financial_health),
      scoreBar("Growth Quality", subs.growth_quality),
      scoreBar("Competitive Position", subs.competitive_position),
      scoreBar("Management Quality", subs.management_quality),
      scoreBar("Risk Profile", subs.risk_profile),
      scoreBar("Innovation Signal", subs.innovation_signal),
      scoreBar("Revenue Quality", subs.revenue_quality),
      ...taBars,
    ].join("");
    const naCount = [subs.financial_health, subs.growth_quality, subs.competitive_position,
      subs.management_quality, subs.risk_profile, subs.innovation_signal, subs.revenue_quality]
      .filter(v => !v || Number(v) <= 0).length;
    const naNote = naCount > 0
      ? `<p style="font-size:11px;color:var(--muted);margin-top:6px;">N/A = insufficient agent data at this depth. Run Standard or Deep for full subscores.</p>`
      : '';
    document.getElementById("subscores").innerHTML = subsHtml + naNote;

    // ── Technical Analysis Summary Card ──────────────────────────────────────
    const taSection = document.getElementById("ta-summary-section");
    if (taSection && taSum.technical_score != null) {
      taSection.style.display = "";
      const dir = taSum.technical_direction || "NEUTRAL";
      const dirCol = dir === "BULLISH" ? "#22c55e" : dir === "BEARISH" ? "#ef4444" : "#f59e0b";
      const dirBadge = document.getElementById("ta-summary-direction");
      if (dirBadge) { dirBadge.textContent = dir; dirBadge.style.color = dirCol; dirBadge.style.borderColor = dirCol; }

      const score = document.getElementById("ta-summary-score");
      if (score) { score.textContent = `${taSum.technical_score}/10`; const sc = taSum.technical_score >= 7 ? "#22c55e" : taSum.technical_score >= 5 ? "#00e5cc" : "#ef4444"; score.style.color = sc; }

      const tickerEl = document.getElementById("ta-summary-ticker");
      if (tickerEl) tickerEl.textContent = taSum.ticker || "–";

      // RSI from signals
      const rsiSig = (taSum.signals || []).find(s => s.signal && s.signal.toLowerCase().includes("rsi"));
      const rsiEl = document.getElementById("ta-summary-rsi");
      if (rsiEl && rsiSig) {
        const rsiMatch = rsiSig.detail && rsiSig.detail.match(/(\d+\.?\d*)/);
        rsiEl.textContent = rsiMatch ? rsiMatch[1] : "–";
      } else if (rsiEl) { rsiEl.textContent = "–"; }

      // Trend from signals
      const trendSig = (taSum.signals || []).find(s => s.signal && s.signal.toLowerCase().includes("trend"));
      const trendEl = document.getElementById("ta-summary-trend");
      if (trendEl) trendEl.textContent = trendSig ? (trendSig.type === "bullish" ? "UP" : trendSig.type === "bearish" ? "DOWN" : "MIXED") : "–";

      const bullCount = (taSum.signals || []).filter(s => s.type === "bullish").length;
      const bearCount = (taSum.signals || []).filter(s => s.type === "bearish").length;
      const bullEl = document.getElementById("ta-summary-bullish");
      const bearEl = document.getElementById("ta-summary-bearish");
      if (bullEl) bullEl.textContent = bullCount;
      if (bearEl) bearEl.textContent = bearCount;

      const textEl = document.getElementById("ta-summary-text");
      if (textEl) textEl.textContent = taSum.findings || "Technical analysis data not available.";
    }

    const fin = memo.financial_snapshot || {};
    const finRows = [["Revenue", fin.revenue], ["Growth Rate", fin.growth_rate], ["Gross Margin", fin.gross_margin], ["P/E", fin.pe_ratio], ["EV/Revenue", fin.ev_revenue], ["FCF", fin.fcf], ["Valuation", fin.valuation_verdict]];
    document.getElementById("financial-table").innerHTML = finRows.map((r) => `<tr><td>${r[0]}</td><td>${r[1] || "-"}</td></tr>`).join("");

    const social = memo.social_signal || {};
    const socialPanel = document.getElementById("social-panel");
    const socialRanAgents = (data.agent_ids || []).includes("social_sentiment");
    if (!socialRanAgents || social.buzz_level === "UNKNOWN") {
      if (socialPanel) socialPanel.style.display = "none";
    } else {
      if (socialPanel) socialPanel.style.display = "";
      document.getElementById("social-body").innerHTML = `
        <p>Buzz Level: <b>${social.buzz_level || "MINIMAL"}</b> &mdash; Trend: ${social.buzz_trend || "STABLE"}</p>
        <p>Retail Direction: <b>${social.retail_direction || "NEUTRAL"}</b> &mdash; Intensity: ${social.intensity || "MILD"}</p>
        <p>Market Impact: <b>${social.market_impact || "MINOR"}</b></p>
        <p style="color:#fcd34d;">&#9432; Social signal is a secondary indicator. Fundamental analysis takes precedence.</p>
      `;
    }

    document.getElementById("agent-accordions").innerHTML = Object.entries(data.agent_results || {}).map(([id, result]) => {
      const risk = (result.hallucination_check || {}).risk_level || "LOW";
      const noSourcesWarn = result.status === "complete" && (result.sources || []).length === 0
        ? `<p style="color:#f87171;">⚠ No web sources returned. Findings may rely on training data. Treat with caution.</p>` : "";
      return `<details style="margin-bottom:8px;">
        <summary>[${result.status === "complete" ? "✓" : "!"}] ${result.name || id} | ${(result.sources || []).length} sources | ${trustBadge(risk)}</summary>
        <pre style="white-space:pre-wrap">${result.findings || ""}</pre>
        <p>${(result.search_queries || []).join(" | ")}</p>
        ${noSourcesWarn}
        ${(result.sources || []).map((s) => `<div><a target="_blank" href="${s.url || "#"}">${s.url || s.query}</a> - ${s.query || ""}</div>`).join("")}
      </details>`;
    }).join("");

    const cross = data.cross_exam_notes || [];
    if (cross.length && cross[0].skipped) {
      document.getElementById("cross-notes").innerHTML = `<div class="card" style="padding:10px;border-color:#334155;background:rgba(30,41,59,0.45);margin-top:8px;">Cross-examination was skipped for this depth.<div style="color:var(--muted);margin-top:6px;">${cross[0].reason || ""}</div></div>`;
    } else {
      document.getElementById("cross-notes").innerHTML = cross.map((n) => `<p><b>${n.agent_a}</b> vs <b>${n.agent_b}</b>: ${n.note}</p>`).join("");
    }

    const sourceRows = [];
    Object.entries(data.agent_results || {}).forEach(([id, result]) => {
      const risk = (result.hallucination_check || {}).risk_level || "LOW";
      const mark = risk === "LOW" ? "✓" : "?";
      (result.sources || []).forEach((s) => sourceRows.push(`<div>${mark} [${id}] - <a target="_blank" href="${s.url || "#"}">${s.url || s.query}</a> - ${s.query || ""}</div>`));
    });
    document.getElementById("sources").innerHTML = sourceRows.join("");

    const notes = memo.validation_warnings || [];
    document.getElementById("validation-notes").innerHTML = notes.length ? notes.map((n) => `<p>⚠ ${n}</p>`).join("") : "<p>✓ No validation warnings.</p>";

    document.getElementById("export-pdf").onclick = () => {
      const btn = document.getElementById("export-pdf");
      btn.textContent = "Generating…";
      btn.disabled = true;
      fetch(`/api/research/${sessionId}/export/pdf`)
        .then((res) => { if (!res.ok) return res.json().then((e) => { throw new Error(e.detail || "Export failed"); }); return res.blob(); })
        .then((blob) => { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `AlphaSwarm_${sessionId}_research.pdf`; a.click(); URL.revokeObjectURL(url); })
        .catch((err) => alert("PDF export failed: " + err.message))
        .finally(() => { btn.textContent = "Export PDF"; btn.disabled = false; });
    };
    document.getElementById("rerun").onclick = () => window.AlphaResearch.rerun(sessionId);

    drawGauge(memo.overall_score || 0);
    initChatbot(data);

    // ── Load technical chart ─────────────────────────────────────────────────
    initTechnicalChart(sessionId);
  }

  function drawGauge(score) {
    const ctx = document.getElementById("gauge");
    if (!ctx || !window.Chart) return;
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: "doughnut",
      data: { labels: ["Score", "Remaining"], datasets: [{ data: [Number(score || 0), 10 - Number(score || 0)], backgroundColor: ["#00e5cc", "#1f2a3d"], borderWidth: 0 }] },
      options: { cutout: "75%", plugins: { legend: { display: false } } },
    });
  }

  // ── ANALYST CHATBOT ──────────────────────────────────────────────────────────
  function initChatbot(sessionData) {
    const target = sessionData.target || "this company";
    const sessionId = sessionData.session_id || "";
    const chatSubtitle = document.getElementById("chat-subtitle");
    const chatTargetName = document.getElementById("chat-target-name");
    if (chatSubtitle) chatSubtitle.textContent = `Ask anything about ${target}`;
    if (chatTargetName) chatTargetName.textContent = target;
    const memo = sessionData.memo || {};
    const agentResults = sessionData.agent_results || {};
    const agentSummaries = Object.entries(agentResults).filter(([, r]) => r.status === "complete" && r.findings).map(([id, r]) => `[${id.toUpperCase()}]\n${(r.findings || "").slice(0, 500)}`).join("\n\n");
    const systemPrompt = [
      `You are an expert financial analyst with full access to a completed research session on ${target}.`,
      "", `VERDICT: ${memo.verdict || "N/A"} | CONFIDENCE: ${memo.confidence || "N/A"} | SCORE: ${memo.overall_score || "N/A"}/10`,
      `ACTION: ${memo.investment_action || "N/A"} | HORIZON: ${memo.time_horizon || "N/A"}`,
      `SUMMARY: ${memo.summary || "N/A"}`, "",
      "KEY FINDINGS:", ...(memo.key_findings || []).map((f, i) => `${i + 1}. ${f}`), "",
      "BULL THESIS: " + (memo.bull_thesis || []).join(" | "),
      "BEAR THESIS: " + (memo.bear_thesis || []).join(" | "), "",
      "KEY RISKS:", ...(memo.key_risks || []).map((r) => `- ${r.risk} (${r.severity}, ${r.category})`), "",
      "FINANCIALS: " + JSON.stringify(memo.financial_snapshot || {}),
      "SUBSCORES: " + JSON.stringify(memo.subscores || {}), "",
      "TECHNICAL: " + JSON.stringify(memo.technical_analysis_summary || {}), "",
      "AGENT FINDINGS (truncated):", agentSummaries, "",
      `DEPTH: ${sessionData.depth || "unknown"} | AGENTS: ${(sessionData.agent_ids || []).join(", ")}`, "",
      "Answer questions directly and specifically using the research data above. Be concise but thorough.",
    ].join("\n");
    const messages = [];
    const input = document.getElementById("chat-input");
    const sendBtn = document.getElementById("chat-send-btn");
    const messagesEl = document.getElementById("chat-messages");
    const suggestions = document.getElementById("chat-suggestions");
    const collapseBtn = document.getElementById("chat-collapse-btn");
    const chatBody = document.getElementById("chat-body");
    if (collapseBtn && chatBody) {
      collapseBtn.addEventListener("click", () => { const h = chatBody.style.display === "none"; chatBody.style.display = h ? "flex" : "none"; collapseBtn.textContent = h ? "−" : "+"; });
    }
    if (suggestions) {
      suggestions.querySelectorAll(".chat-suggestion").forEach((btn) => {
        btn.addEventListener("click", () => { if (!input) return; input.value = btn.dataset.q; suggestions.style.display = "none"; sendMessage(); });
      });
    }
    if (input) {
      input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    }
    if (sendBtn) sendBtn.addEventListener("click", sendMessage);
    function scrollToBottom() { if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight; }
    const USER_STYLE = "padding:11px 15px;border-radius:14px;border-bottom-right-radius:4px;background:linear-gradient(135deg,rgba(0,229,204,0.18),rgba(0,200,216,0.12));border:1px solid rgba(0,229,204,0.3);color:#f1f5f9;font-size:13.5px;line-height:1.65;white-space:pre-wrap;word-break:break-word;max-width:82%;";
    const ASST_STYLE = "padding:11px 15px;border-radius:14px;border-bottom-left-radius:4px;background:rgba(15,23,42,0.9);border:1px solid #1e2d45;color:#e2e8f0;font-size:13.5px;line-height:1.65;white-space:pre-wrap;word-break:break-word;max-width:82%;";
    function appendMessage(role, text) {
      const wrap = document.createElement("div");
      wrap.style.cssText = "display:flex;margin-bottom:2px;" + (role === "user" ? "justify-content:flex-end;" : "");
      const bubble = document.createElement("div");
      bubble.style.cssText = role === "user" ? USER_STYLE : ASST_STYLE;
      if (text) bubble.textContent = text;
      wrap.appendChild(bubble);
      messagesEl.appendChild(wrap);
      scrollToBottom();
      return bubble;
    }
    function setLoading(on) { if (sendBtn) { sendBtn.disabled = on; sendBtn.textContent = on ? "…" : "▶"; } if (input) input.disabled = on; }
    async function sendMessage() {
      if (!input) return;
      const text = input.value.trim();
      if (!text) return;
      input.value = ""; input.style.height = "auto";
      if (suggestions) suggestions.style.display = "none";
      appendMessage("user", text);
      messages.push({ role: "user", content: text });
      setLoading(true);
      const bubble = appendMessage("assistant", "");
      bubble.innerHTML = `<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 2px;"><span style="width:7px;height:7px;border-radius:50%;background:#00e5cc;display:inline-block;animation:chat-bounce 1.3s ease-in-out infinite;opacity:0.6;"></span><span style="width:7px;height:7px;border-radius:50%;background:#00e5cc;display:inline-block;animation:chat-bounce 1.3s ease-in-out 0.18s infinite;opacity:0.6;"></span><span style="width:7px;height:7px;border-radius:50%;background:#00e5cc;display:inline-block;animation:chat-bounce 1.3s ease-in-out 0.36s infinite;opacity:0.6;"></span></span>`;
      try {
        const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, messages, system_prompt: systemPrompt }) });
        if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || `HTTP ${res.status}`); }
        const d = await res.json();
        const reply = d.reply || "No response received.";
        bubble.textContent = reply;
        messages.push({ role: "assistant", content: reply });
      } catch (err) {
        bubble.innerHTML = `<span style="color:#f87171;">⚠ Error: ${err.message}</span>`;
      } finally { setLoading(false); scrollToBottom(); }
    }
  }

  // ── TECHNICAL CHART ──────────────────────────────────────────────────────────
  function initTechnicalChart(sessionId) {
    const C = {
      bull:'#22c55e', bear:'#ef4444', neutral:'#f59e0b',
      sma20:'#3b82f6', sma50:'#facc15', sma200:'#f87171',
      bb:'rgba(168,85,247,0.55)', bbFill:'rgba(168,85,247,0.05)',
      vol_up:'rgba(34,197,94,0.55)', vol_dn:'rgba(239,68,68,0.55)',
      rsi:'#67e8f9', macd:'#00e5cc', signal:'#f59e0b',
      histPos:'rgba(34,197,94,0.65)', histNeg:'rgba(239,68,68,0.65)',
      grid:'rgba(31,42,61,0.55)', text:'#64748b',
    };

    let _cd = null, _ta = null, _range = null, _charts = {};
    let _vis = { sma20:true, sma50:true, sma200:true, bb:true };

    function tsLabel(ms) { const d = new Date(ms); return `${d.toLocaleString('default',{month:'short'})} ${d.getDate()}`; }
    function fmtNum(v, dp=2, pre='', su='') { return v!=null&&!isNaN(v)?`${pre}${Number(v).toFixed(dp)}${su}`:'N/A'; }

    function sliceCd(candles, range) {
      if (!range || range==='1y') return candles;
      const days = {  '6m':126, '3m':63, '1m':21 };
      return candles.slice(-(days[range]||candles.length));
    }

    // Custom candlestick plugin — draws before default dataset render
    const CandlePlugin = {
      id: 'candlePlugin',
      beforeDatasetDraw(chart, args) {
        if (args.index !== 0) return;
        const { ctx, scales:{ x, y } } = chart;
        const raw = chart.data._raw;
        if (!raw) return;
        const bw = Math.max(1.5, (x.getPixelForValue(1)-x.getPixelForValue(0)) - 2);
        const hw = Math.max(0.8, bw/2 - 0.5);
        ctx.save();
        raw.forEach((c, i) => {
          const px = x.getPixelForValue(i);
          const oY=y.getPixelForValue(c.o), cY=y.getPixelForValue(c.c);
          const hY=y.getPixelForValue(c.h), lY=y.getPixelForValue(c.l);
          const bull = c.c >= c.o;
          ctx.strokeStyle = bull ? C.bull : C.bear;
          ctx.fillStyle   = bull ? 'rgba(34,197,94,0.72)' : 'rgba(239,68,68,0.72)';
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px,hY); ctx.lineTo(px,lY); ctx.stroke();
          const top = Math.min(oY,cY), h = Math.max(1, Math.abs(oY-cY));
          ctx.fillRect(px-hw, top, hw*2, h);
          ctx.strokeRect(px-hw, top, hw*2, h);
        });
        ctx.restore();
        return false;
      }
    };

    function destroyCharts() { Object.values(_charts).forEach(c=>{ try{c.destroy();}catch(_){} }); _charts={}; }

    function render() {
      if (!_cd) return;
      const raw  = sliceCd(_cd.candles, _range);
      const n    = raw.length;
      const lbls = raw.map(c=>tsLabel(c.t));
      const inds = _cd.indicators;

      function si(key) {
        const arr = inds[key]||[];
        return arr.slice(-n).map(d=>(d&&d.v!=null)?d.v:null);
      }

      const sma20=si('SMA20'), sma50=si('SMA50'), sma200=si('SMA200');
      const bbU=si('BB_upper'), bbL=si('BB_lower');
      const rsi=si('RSI14'), macd=si('MACD'), macdS=si('MACD_signal'), macdH=si('MACD_hist');
      const volSma=si('Vol_SMA20');
      const volRaw=(inds['Volume']||[]).slice(-n).map(d=>(d&&d.v!=null)?d.v:0);
      const volColors=raw.map(c=>c.c>=c.o?C.vol_up:C.vol_dn);
      const prices=raw.flatMap(c=>[c.h,c.l]).filter(v=>v!=null&&!isNaN(v));
      const pMin=Math.min(...prices)*0.986, pMax=Math.max(...prices)*1.014;
      const maxVol=Math.max(...volRaw.filter(v=>v>0))*1.1||1;
      const macdVals=[...macdH,...macd,...macdS].filter(v=>v!=null&&!isNaN(v));
      const macdAbs=Math.max(...macdVals.map(Math.abs))*1.2||1;

      // Shared axis helpers
      const mkX=(show)=>({type:'category',labels:lbls,
        grid:{color:show?C.grid:'transparent',drawBorder:false},
        ticks:{display:show,color:C.text,maxTicksLimit:8,maxRotation:0,font:{size:9}}});
      const rY=(extra={})=>({position:'right',grid:{color:C.grid,drawBorder:false},
        ticks:{color:C.text,font:{size:9},...extra}});
      const noLegend={legend:{display:false},tooltip:{enabled:false}};

      // Get the actual rendered width of the container so we can size canvases explicitly
      const wrap = document.getElementById('ta-canvas-wrap');
      const W = wrap ? wrap.clientWidth - 24 : 700; // subtract horizontal padding

      destroyCharts();

      // Helper: create chart with responsive:false and explicit pixel size
      // This is the ONLY reliable way to prevent Chart.js resize loops
      function mkChart(id, h, cfg) {
        const el = document.getElementById(id);
        if (!el) return null;
        el.width  = W;
        el.height = h;
        el.style.width  = W + 'px';
        el.style.height = h + 'px';
        cfg.options = cfg.options || {};
        cfg.options.responsive = false;
        cfg.options.maintainAspectRatio = false;
        cfg.options.animation = false;
        return new Chart(el, cfg);
      }

      // 1 — Candlestick
      const cds=[
        {data:raw.map(c=>({x:lbls[raw.indexOf(c)],y:(c.h+c.l)/2})),pointRadius:0,borderWidth:0,
         backgroundColor:'transparent',borderColor:'transparent',type:'line'},
      ];
      if(_vis.sma20)  cds.push({type:'line',data:sma20, borderColor:C.sma20, borderWidth:1.5,pointRadius:0,tension:0.3});
      if(_vis.sma50)  cds.push({type:'line',data:sma50, borderColor:C.sma50, borderWidth:1.5,pointRadius:0,tension:0.3});
      if(_vis.sma200) cds.push({type:'line',data:sma200,borderColor:C.sma200,borderWidth:1.5,pointRadius:0,tension:0.3});
      if(_vis.bb) {
        cds.push({type:'line',data:bbU,borderColor:C.bb,borderWidth:1,pointRadius:0,fill:'+1',backgroundColor:C.bbFill});
        cds.push({type:'line',data:bbL,borderColor:C.bb,borderWidth:1,pointRadius:0,fill:false});
      }
      _charts.candle = mkChart('ta-candle-chart', 300, {
        type:'line', plugins:[CandlePlugin],
        data:{labels:lbls,datasets:cds,_raw:raw},
        options:{
          scales:{x:mkX(false),y:{...rY(),min:pMin,max:pMax,
            ticks:{...rY().ticks,callback:v=>`$${Number(v).toFixed(0)}`}}},
          plugins:{...noLegend},
          onHover:(evt,items)=>handleHover(evt,items,raw,lbls),
        }
      });
      if (_charts.candle) _charts.candle.data._raw = raw;

      // 2 — Volume
      _charts.vol = mkChart('ta-volume-chart', 60, {
        type:'bar',
        data:{labels:lbls,datasets:[
          {data:volRaw,backgroundColor:volColors,borderWidth:0},
          {type:'line',data:volSma,borderColor:'rgba(255,200,0,0.6)',borderWidth:1,pointRadius:0,tension:0.3},
        ]},
        options:{
          scales:{x:mkX(false),y:{...rY(),min:0,max:maxVol,
            ticks:{...rY().ticks,maxTicksLimit:3,
              callback:v=>v>=1e9?`${(v/1e9).toFixed(1)}B`:v>=1e6?`${(v/1e6).toFixed(0)}M`:`${(v/1e3).toFixed(0)}K`}}},
          plugins:noLegend,
        }
      });

      // 3 — RSI (hard 0–100 + dashed 70/30 lines)
      _charts.rsi = mkChart('ta-rsi-chart', 60, {
        type:'line',
        data:{labels:lbls,datasets:[
          {data:rsi,borderColor:C.rsi,borderWidth:1.5,pointRadius:0,tension:0.3,fill:false},
          {data:Array(n).fill(70),borderColor:'rgba(239,68,68,0.35)',borderWidth:1,pointRadius:0,borderDash:[4,4]},
          {data:Array(n).fill(30),borderColor:'rgba(34,197,94,0.35)',borderWidth:1,pointRadius:0,borderDash:[4,4]},
        ]},
        options:{
          scales:{x:mkX(false),y:{...rY(),min:0,max:100,ticks:{...rY().ticks,stepSize:30}}},
          plugins:noLegend,
        }
      });

      // 4 — MACD (symmetric bounds, date labels on bottom)
      _charts.macd = mkChart('ta-macd-chart', 60, {
        type:'bar',
        data:{labels:lbls,datasets:[
          {type:'bar', data:macdH,backgroundColor:macdH.map(v=>v!=null&&v>=0?C.histPos:C.histNeg),borderWidth:0},
          {type:'line',data:macd, borderColor:C.macd,  borderWidth:1.5,pointRadius:0,tension:0.3},
          {type:'line',data:macdS,borderColor:C.signal,borderWidth:1.2,pointRadius:0,tension:0.3},
        ]},
        options:{
          scales:{x:mkX(true),y:{...rY(),min:-macdAbs,max:macdAbs,ticks:{...rY().ticks,maxTicksLimit:3}}},
          plugins:noLegend,
        }
      });
    }

    // TradingView-style hover: top-left OHLC overlay + x-axis date + floating tooltip
    function handleHover(evt, items, raw, lbls) {
      const overlay=document.getElementById('ta-ohlc-overlay');
      const xhair  =document.getElementById('ta-xhair-label');
      const tip    =document.getElementById('ta-tooltip');
      const wrap   =document.getElementById('ta-canvas-wrap');
      const hide   =()=>{if(overlay)overlay.style.display='none';if(xhair)xhair.style.display='none';if(tip)tip.style.display='none';};
      if(!items||!items.length){hide();return;}
      const idx=items[0].index;
      if(idx===undefined||!raw[idx]){hide();return;}
      const c=raw[idx], bull=c.c>=c.o, col=bull?C.bull:C.bear;
      const chg=c.o?((c.c-c.o)/c.o*100):0;
      const chgStr=(bull?'+':'')+chg.toFixed(2)+'%';
      const date=lbls[idx]||'';

      // Top-left persistent OHLC overlay
      if(overlay){
        overlay.style.display='block';
        overlay.innerHTML=`<span style="color:#64748b;font-size:10px;margin-right:8px;">${date}</span>`+
          `<span style="color:#64748b;">O </span><span style="color:#e2e8f0;">$${c.o.toFixed(2)}</span> `+
          `<span style="color:#64748b;margin-left:4px;">H </span><span style="color:#22c55e;">$${c.h.toFixed(2)}</span> `+
          `<span style="color:#64748b;margin-left:4px;">L </span><span style="color:#ef4444;">$${c.l.toFixed(2)}</span> `+
          `<span style="color:#64748b;margin-left:4px;">C </span><span style="color:${col};font-weight:700;">$${c.c.toFixed(2)}</span> `+
          `<span style="color:${col};margin-left:6px;font-weight:600;">${chgStr}</span>`;
      }

      if(!wrap||!evt.native){return;}
      const wRect=wrap.getBoundingClientRect();
      const mx=evt.native.clientX-wRect.left;
      const my=evt.native.clientY-wRect.top;

      // X-axis date label that follows cursor horizontally
      if(xhair){
        const candleH=300+10; // candle pane height + top padding
        xhair.style.display='block';
        xhair.style.left=mx+'px';
        xhair.style.top=(candleH-14)+'px';
        xhair.textContent=date;
      }

      // Floating detail tooltip follows cursor
      if(tip){
        tip.style.display='block';
        tip.style.left=Math.min(mx+16,wrap.offsetWidth-190)+'px';
        tip.style.top=Math.max(8,my-60)+'px';
        tip.innerHTML=`<div style="font-weight:700;color:#e2e8f0;margin-bottom:5px;">${date}</div>`+
          `<div style="display:grid;grid-template-columns:auto auto;gap:2px 12px;font-size:11px;">`+
          `<span style="color:#64748b;">Open</span><span>$${c.o.toFixed(2)}</span>`+
          `<span style="color:#64748b;">High</span><span style="color:#22c55e;">$${c.h.toFixed(2)}</span>`+
          `<span style="color:#64748b;">Low</span><span style="color:#ef4444;">$${c.l.toFixed(2)}</span>`+
          `<span style="color:#64748b;">Close</span><span style="color:${col};font-weight:700;">$${c.c.toFixed(2)}</span>`+
          `<span style="color:#64748b;">Change</span><span style="color:${col};">${chgStr}</span>`+
          `</div>`;
      }
    }

    // Signals + S/R panel
    function renderPanel(ta) {
      const signals  = ta.signals  || [];
      const patterns = ta.patterns || [];
      const sr       = ta.support_resistance || {};

      document.getElementById('ta-signals-list').innerHTML = signals.map(s=>{
        const col = s.type==='bullish'?C.bull:s.type==='bearish'?C.bear:'#94a3b8';
        const ic  = s.type==='bullish'?'↑':s.type==='bearish'?'↓':'→';
        const str = s.strength==='strong'?'●●●':s.strength==='moderate'?'●●○':'●○○';
        return `<div style="padding:7px 0;border-bottom:1px solid rgba(31,42,61,0.6);display:flex;gap:8px;">
          <span style="color:${col};font-size:13px;min-width:13px;">${ic}</span>
          <div style="flex:1;">
            <div style="font-size:12px;font-weight:600;color:${col};">${escHtml(s.signal)}</div>
            <div style="font-size:11px;color:var(--muted);margin-top:1px;line-height:1.5;">${escHtml(s.detail)}</div>
          </div>
          <span style="font-size:9px;color:#475569;letter-spacing:1px;flex-shrink:0;padding-top:2px;">${str}</span>
        </div>`;
      }).join('');

      const cp = sr.current_price;
      document.getElementById('ta-sr-levels').innerHTML = `
        <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:12px;">
          ${[['Price', cp?`$${cp.toFixed(2)}`:'N/A','#e2e8f0'],['52w High',sr.wk52_high?`$${sr.wk52_high.toFixed(2)}`:'N/A',C.bull],['52w Low',sr.wk52_low?`$${sr.wk52_low.toFixed(2)}`:'N/A',C.bear],['Pivot',sr.pivot?`$${sr.pivot.toFixed(2)}`:'N/A','#94a3b8'],['R1',sr.r1?`$${sr.r1.toFixed(2)}`:'N/A','#fbbf24'],['R2',sr.r2?`$${sr.r2.toFixed(2)}`:'N/A','#f59e0b'],['S1',sr.s1?`$${sr.s1.toFixed(2)}`:'N/A','#34d399'],['S2',sr.s2?`$${sr.s2.toFixed(2)}`:'N/A',C.bull]].map(([l,v,c])=>`<span style="color:var(--muted);">${l}</span><span style="color:${c};font-weight:600;">${v}</span>`).join('')}
        </div>
        ${cp&&sr.dist_from_52w_high_pct!=null?`<div style="margin-top:8px;font-size:10px;color:var(--muted);">${sr.dist_from_52w_high_pct.toFixed(1)}% from 52w high · +${sr.dist_from_52w_low_pct?sr.dist_from_52w_low_pct.toFixed(1):'?'}% from 52w low</div>`:''}
      `;

      const patEl = document.getElementById('ta-patterns-list');
      if (patterns.length) {
        patEl.innerHTML = `<div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:7px;">Recent Patterns</div>`+
          patterns.map(p=>{ const col=p.type==='bullish'?C.bull:p.type==='bearish'?C.bear:'#94a3b8'; return `<div style="display:flex;gap:6px;padding:4px 0;font-size:11px;border-bottom:1px solid rgba(31,42,61,0.4);"><span style="color:${col};">${p.type==='bullish'?'↑':p.type==='bearish'?'↓':'→'}</span><span style="font-weight:600;color:${col};">${escHtml(p.name)}</span><span style="color:var(--muted);flex:1;">${escHtml(p.desc)}</span></div>`; }).join('');
      } else {
        patEl.innerHTML = '<div style="font-size:11px;color:var(--muted);">No significant patterns detected recently.</div>';
      }
    }

    function setHeaderBadges(ta) {
      const tb=document.getElementById('ta-ticker-badge'), db=document.getElementById('ta-direction-badge'), sb=document.getElementById('ta-score-badge'), sub=document.getElementById('ta-header-sub');
      if (!tb||!db||!sb) return;
      tb.textContent=ta.ticker||''; tb.style.display='';
      const dir=ta.technical_direction||'NEUTRAL';
      const dc=dir==='BULLISH'?C.bull:dir==='BEARISH'?C.bear:C.neutral;
      db.textContent=dir; db.style.display=''; db.style.color=dc; db.style.borderColor=dc;
      db.style.background=dir==='BULLISH'?'rgba(34,197,94,0.1)':dir==='BEARISH'?'rgba(239,68,68,0.1)':'rgba(245,158,11,0.1)';
      sb.textContent=`Score: ${ta.technical_score}/10`; sb.style.display='';
      const sr=ta.support_resistance||{};
      if (sub&&sr.current_price) sub.textContent=`${ta.ticker} · $${sr.current_price.toFixed(2)} · 52w ${sr.wk52_high?'$'+sr.wk52_high.toFixed(0):'?'} / ${sr.wk52_low?'$'+sr.wk52_low.toFixed(0):'?'} · 1-Year Daily`;
    }

    function bindControls() {
      document.querySelectorAll('.ta-toggle').forEach(btn=>{
        btn.addEventListener('click',()=>{
          const layer=btn.dataset.layer;
          _vis[layer]=!_vis[layer];
          btn.style.opacity=_vis[layer]?'1':'0.38';
          render();
        });
      });
      document.querySelectorAll('.ta-range').forEach(btn=>{
        btn.addEventListener('click',()=>{
          document.querySelectorAll('.ta-range').forEach(b=>{ b.style.borderColor='var(--border)'; b.style.background='transparent'; b.style.color='var(--muted)'; });
          btn.style.borderColor='var(--accent)'; btn.style.background='rgba(0,229,204,0.1)'; btn.style.color='var(--accent)';
          _range = btn.dataset.range==='1y'?null:btn.dataset.range;
          render();
        });
      });
    }

    async function load() {
      const loadEl=document.getElementById('ta-loading'), privEl=document.getElementById('ta-private'), errEl=document.getElementById('ta-error'), areaEl=document.getElementById('ta-chart-area');
      bindControls();
      try {
        const res = await fetch(`/api/research/${sessionId}/technical`);
        if (!res.ok) {
          if (res.status===409) { document.getElementById('technical-section').style.display='none'; return; }
          throw new Error(`HTTP ${res.status}`);
        }
        const ta = await res.json();
        _ta = ta;
        loadEl.style.display='none';
        if (!ta.is_public||ta.error==='private_company') { privEl.style.display=''; return; }
        if (ta.error&&ta.error!=='private_company') { errEl.style.display=''; document.getElementById('ta-error-msg').textContent=`Chart error: ${ta.error}`; return; }
        if (!ta.chart_data) { errEl.style.display=''; document.getElementById('ta-error-msg').textContent='Chart data unavailable.'; return; }
        _cd = ta.chart_data;
        setHeaderBadges(ta);
        areaEl.style.display='';
        render();
        renderPanel(ta);
      } catch(err) {
        loadEl.style.display='none';
        errEl.style.display='';
        document.getElementById('ta-error-msg').textContent=`Chart error: ${err.message}`;
      }
    }

    load();
  }

  window.AlphaMemo = { initMemo };
})();
