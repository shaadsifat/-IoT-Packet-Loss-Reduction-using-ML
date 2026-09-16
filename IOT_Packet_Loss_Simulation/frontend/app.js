(function () {
  "use strict";

  const API = "";

  const STRATEGIES = [
    { key: "baseline", tag: "Strategy A", title: "No protection / no analysis", cls: "", short: "No protection" },
    { key: "math", tag: "Strategy B", title: "Mathematical analysis (Stage 1 rule)", cls: "math", short: "Analysis" },
    { key: "math_ai", tag: "Strategy C", title: "Mathematical analysis + ML (Random Forest)", cls: "ai", short: "Analysis + AI" },
  ];
  const STRAT_BY_KEY = Object.fromEntries(STRATEGIES.map(s => [s.key, s]));

  const DEVICE_META = [
    { id: "lb1", name: "Light Bulb 1", type: "Light Bulb", icon: "bulb" },
    { id: "lb2", name: "Light Bulb 2", type: "Light Bulb", icon: "bulb" },
    { id: "lb3", name: "Light Bulb 3", type: "Light Bulb", icon: "bulb" },
    { id: "cf1", name: "Ceiling Fan 1", type: "Ceiling Fan", icon: "fan" },
    { id: "cf2", name: "Ceiling Fan 2", type: "Ceiling Fan", icon: "fan" },
    { id: "ac1", name: "AC Unit", type: "Air Conditioner", icon: "ac" },
    { id: "ht1", name: "Heater", type: "Heater", icon: "heater" },
  ];

  const ICONS = {
    bulb: '<svg class="icon" viewBox="0 0 24 24"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.45 1.1 1.2 1.1 2.2h5c0-1 .5-1.75 1.1-2.2A6 6 0 0 0 12 3Z"/></svg>',
    fan: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="1.6"/><path d="M12 11c0-3 1.5-6.5 4.5-6.5S19 7.5 17 10c-1 1.2-3 1.6-5 1Z"/><path d="M12 13c0 3-1.5 6.5-4.5 6.5S4.5 16.5 6.5 14c1-1.2 3-1.6 5-1Z"/><path d="M11 12c-3 0-6.5-1.5-6.5-4.5S7.5 3 10 5c1.2 1 1.6 3 1 5Z"/></svg>',
    ac: '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="7" rx="1.5"/><path d="M6 17v2M10 17v3M14 17v2M18 17v3"/></svg>',
    heater: '<svg class="icon" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9c0 1.2 1 1.2 1 2.4S8 13.8 8 15M12 9c0 1.2 1 1.2 1 2.4s-1 2.4-1 3.6M16 9c0 1.2 1 1.2 1 2.4s-1 2.4-1 3.6"/></svg>',
  };

  let currentBatch = null;               // {id, name, packets_per_device, total_per_strategy, strategies_run}
  let results = { baseline: null, math: null, math_ai: null }; // full fetched result payloads
  let logs = [];                         // merged rows for the table
  let filtered = [];
  let page = 0;
  const PAGE_SIZE = 40;
  let sortKey = "idx", sortDir = 1;
  let activeSource = null;               // current EventSource

  function el(id) { return document.getElementById(id); }
  function clip(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

  // ---------------- model info panel ----------------

  async function loadModelInfo() {
    try {
      const res = await fetch(`${API}/api/model-info`);
      const data = await res.json();
      const panel = el("modelInfoPanel");
      const body = el("modelInfoBody");
      panel.style.display = "";
      if (data.available) {
        const info = data.info || {};
        body.innerHTML = `
          <span class="model-badge ok">&#10003; loaded</span>
          <div class="model-meta">
            <span>type <b>${info.model_type || "?"}</b></span>
            <span>test accuracy <b>${info.test_accuracy_pct}%</b></span>
            <span>macro F1 <b>${info.test_macro_f1}</b></span>
            <span>trained on <b>${(info.training_rows || 0).toLocaleString()}</b> rows</span>
          </div>
          <div class="model-features">${(info.feature_columns || []).map(f => `<span>${f}</span>`).join("")}</div>`;
      } else {
        body.innerHTML = `<span class="model-badge bad">&times; not loaded</span>
          <div class="model-meta"><span>${escapeHtml(data.load_error || "Model file not found.")} Strategy C will fall back to math-only.</span></div>`;
      }
    } catch (e) {
      // model-info endpoint itself unreachable - not fatal, just skip the panel
    }
  }

  // ---------------- batch creation & listing ----------------

  async function loadBatchList() {
    const res = await fetch(`${API}/api/batches`);
    const batches = await res.json();
    const list = el("batchList");
    list.innerHTML = batches.map(b => {
      const active = currentBatch && currentBatch.id === b.id ? "active" : "";
      const doneCount = (b.strategies_run || []).length;
      return `<div class="batch-chip ${active}" data-id="${b.id}">
        <button type="button" class="batch-chip-select" data-id="${b.id}">
          <span class="dot ${doneCount === STRATEGIES.length ? 'done' : ''}"></span>
          ${escapeHtml(b.name)} · ${b.packets_per_device}/device
        </button>
        <button type="button" class="batch-chip-del" data-id="${b.id}" data-name="${escapeHtml(b.name)}" title="Delete this batch" aria-label="Delete batch ${escapeHtml(b.name)}">&times;</button>
      </div>`;
    }).join("") || `<span class="section-sub" style="margin:0;">No batches yet — create one above.</span>`;

    list.querySelectorAll(".batch-chip-select").forEach(btn => {
      btn.addEventListener("click", () => selectBatch(btn.dataset.id));
    });
    list.querySelectorAll(".batch-chip-del").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteBatch(btn.dataset.id, btn.dataset.name);
      });
    });
  }

  async function deleteBatch(id, name) {
    const ok = window.confirm(`Delete batch "${name}"? This permanently removes it and all strategies' results. This cannot be undone.`);
    if (!ok) return;
    const res = await fetch(`${API}/api/batches/${id}`, { method: "DELETE" });
    if (!res.ok) {
      alert("Could not delete this batch.");
      return;
    }
    if (currentBatch && currentBatch.id === id) {
      currentBatch = null;
      results = { baseline: null, math: null, math_ai: null };
      logs = [];
      el("runnerSection").style.display = "none";
      hideResultSections();
    }
    loadBatchList();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------- runner cards (built once per batch selection) ----------------

  function renderRunnerCards() {
    el("runnersGrid").innerHTML = STRATEGIES.map(s => `
      <div class="runner ${s.cls}" id="runner-${s.key}">
        <span class="tag">${s.tag}</span>
        <h3>${s.title}</h3>
        <div class="status" id="status-${s.key}">Not run on this batch yet.</div>
        <div class="runbtns"><button class="primary" id="run-${s.key}">Run ${s.tag}</button></div>
        <div class="live-box" id="live-${s.key}">
          <div class="progress-track"><div class="progress-fill ${s.cls}" id="progress-${s.key}"></div></div>
          <div class="live-stats">
            <span>sent <b id="sent-${s.key}">0</b></span>
            <span>lost <b id="lost-${s.key}">0</b></span>
            <span>loss <b id="pct-${s.key}">0.0%</b></span>
          </div>
          <div class="congestion-row">live network congestion
            <div class="congestion-track"><div class="congestion-fill" id="cong-${s.key}"></div></div>
            <b id="congval-${s.key}">–</b>
          </div>
          <div class="ticker" id="ticker-${s.key}"></div>
        </div>
      </div>`).join("");

    STRATEGIES.forEach(s => {
      el(`run-${s.key}`).addEventListener("click", () => runStrategy(s.key));
    });
  }

  function renderExportButtons() {
    el("exportRow").innerHTML = STRATEGIES.map(s =>
      `<button class="ghost" id="export-${s.key}" ${results[s.key] ? "" : "disabled"}>Save ${s.tag} results (CSV)</button>`
    ).join("");
    STRATEGIES.forEach(s => {
      el(`export-${s.key}`).addEventListener("click", () => {
        if (currentBatch) window.location.href = `${API}/api/batches/${currentBatch.id}/export?strategy=${s.key}`;
      });
    });
  }

  async function selectBatch(id) {
    const res = await fetch(`${API}/api/batches/${id}`);
    if (!res.ok) return;
    currentBatch = await res.json();
    results = { baseline: null, math: null, math_ai: null };
    logs = [];

    el("runnerSection").style.display = "";
    el("runnerSub").textContent =
      `"${currentBatch.name}" — ${currentBatch.packets_per_device} packets/device × ${DEVICE_META.length} devices = ${currentBatch.total_per_strategy.toLocaleString()} sends per strategy.`;

    renderRunnerCards();
    STRATEGIES.forEach(s => setRunnerStatus(s.key, currentBatch.strategies_run.includes(s.key)));

    hideResultSections();
    renderDeviceGrid();
    el("deviceSection").style.display = "";

    for (const s of STRATEGIES) {
      if (currentBatch.strategies_run.includes(s.key)) {
        const r = await fetchResults(s.key);
        if (r) results[s.key] = r;
      }
    }
    if (STRATEGIES.some(s => results[s.key])) renderAll();

    loadBatchList();
  }

  function setRunnerStatus(key, done) {
    const s = STRAT_BY_KEY[key];
    const statusEl = el(`status-${key}`);
    if (!statusEl) return;
    statusEl.textContent = done ? `${s.tag} has been run on this batch.` : `${s.tag} not run on this batch yet.`;
    statusEl.className = "status" + (done ? " done" : "");
  }

  function hideResultSections() {
    el("resultsSection").style.display = "none";
    el("chartSection").style.display = "none";
    el("deviceSection").style.display = "none";
    el("logSection").style.display = "none";
    renderExportButtons();
  }

  el("createBatchBtn").addEventListener("click", async () => {
    const name = el("batchName").value.trim() || "Untitled batch";
    const packets = clip(parseInt(el("packetCount").value || "500", 10), 1, 20000);
    el("packetCount").value = packets;
    el("createBatchBtn").disabled = true;
    try {
      const res = await fetch(`${API}/api/batches`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, packets_per_device: packets }),
      });
      const batch = await res.json();
      if (!res.ok) { alert(batch.error || "Could not create batch"); return; }
      await loadBatchList();
      await selectBatch(batch.id);
      el("batchName").value = "";
    } finally {
      el("createBatchBtn").disabled = false;
    }
  });

  // ---------------- speed slider ----------------

  el("speed").addEventListener("input", () => {
    el("speedVal").textContent = `${el("speed").value} ms / packet`;
  });

  // ---------------- running a strategy (SSE) ----------------

  function setAllRunButtonsDisabled(disabled) {
    STRATEGIES.forEach(s => { const b = el(`run-${s.key}`); if (b) b.disabled = disabled; });
  }

  function runStrategy(strategy) {
    if (!currentBatch || activeSource) return;
    const speed = el("speed").value;
    const liveBox = el(`live-${strategy}`);
    const progress = el(`progress-${strategy}`);
    const sentEl = el(`sent-${strategy}`);
    const lostEl = el(`lost-${strategy}`);
    const pctEl = el(`pct-${strategy}`);
    const ticker = el(`ticker-${strategy}`);
    const congFill = el(`cong-${strategy}`);
    const congVal = el(`congval-${strategy}`);

    setAllRunButtonsDisabled(true);
    liveBox.classList.add("active");
    ticker.innerHTML = "";
    progress.style.width = "0%";
    sentEl.textContent = "0"; lostEl.textContent = "0"; pctEl.textContent = "0.0%";
    resetDeviceVisuals();

    let total = 0, sentCount = 0, landedCount = 0, lostCount = 0;
    const tickerLines = new Map(); // idx -> DOM node

    const url = `${API}/api/batches/${currentBatch.id}/stream?strategy=${strategy}&speed_ms=${speed}`;
    const source = new EventSource(url);
    activeSource = source;

    source.addEventListener("meta", (e) => { total = JSON.parse(e.data).total; });

    // Phase 1: packet has left the router, outcome not decided yet.
    source.addEventListener("sent", (e) => {
      const ctx = JSON.parse(e.data);
      sentCount++;
      sentEl.textContent = sentCount.toLocaleString();
      markDeviceTick(ctx.device_id, "pending");

      const line = document.createElement("div");
      line.className = "trow pending";
      line.textContent = `#${ctx.idx} ${ctx.device} · Spkts=${ctx.spkts} sttl=${ctx.sttl} · sending…`;
      ticker.prepend(line);
      tickerLines.set(ctx.idx, line);
      while (ticker.childElementCount > 40) {
        const last = ticker.lastChild;
        for (const [k, v] of tickerLines) if (v === last) tickerLines.delete(k);
        ticker.removeChild(last);
      }
    });

    // Phase 2: packet has resolved - loss decided live, right now (model call included, for math_ai).
    source.addEventListener("landed", (e) => {
      const row = JSON.parse(e.data);
      landedCount++; if (row.packet_lost) lostCount++;
      progress.style.width = total ? `${(landedCount / total * 100).toFixed(2)}%` : "0%";
      lostEl.textContent = lostCount.toLocaleString();
      pctEl.textContent = `${(lostCount / landedCount * 100).toFixed(1)}%`;
      congFill.style.width = `${clip((row.congestion - 0.5) / 1.0 * 100, 0, 100)}%`;
      congVal.textContent = row.congestion.toFixed(2) + "×";

      markDeviceTick(row.device_id, row.packet_lost ? "lost" : "ok");

      const line = tickerLines.get(row.idx);
      if (line) {
        line.className = "trow " + (row.packet_lost ? "lost" : "ok");
        const modelTag = row.used_model ? ` · RF ${row.model_risk_pct.toFixed(1)}%` : "";
        line.textContent = `#${row.idx} ${row.device} · risk ${row.risk_pct.toFixed(1)}%${modelTag} · ${row.action} · ${row.packet_lost ? "LOST" : "delivered"}`;
      }
    });

    source.addEventListener("done", async () => {
      source.close();
      activeSource = null;
      setAllRunButtonsDisabled(false);
      liveBox.classList.remove("active");
      setRunnerStatus(strategy, true);
      const r = await fetchResults(strategy);
      if (r) results[strategy] = r;
      renderAll();
      loadBatchList();
    });

    source.onerror = () => {
      source.close();
      activeSource = null;
      setAllRunButtonsDisabled(false);
      liveBox.classList.remove("active");
    };
  }

  // Fixed-size tick history per device: index cycles through a ring buffer so the
  // bar never grows, shrinks, or reflows - only a tick's own color ever changes.
  // Devices round-robin sequentially in the backend loop, so a device's own
  // "sent" and "landed" for the same packet are never interleaved with another
  // "sent" for that same device - reusing the last tick index on "landed" is safe.
  const TICK_COUNT = 32;
  let deviceTickPos = {};

  function markDeviceTick(deviceId, state) {
    const card = document.querySelector(`.device-card[data-id="${deviceId}"]`);
    if (!card) return;
    const dot = card.querySelector(".statusdot");
    if (dot) dot.className = "statusdot " + state;

    if (state === "pending") {
      deviceTickPos[deviceId] = deviceTickPos[deviceId] === undefined ? 0 : (deviceTickPos[deviceId] + 1) % TICK_COUNT;
    }
    const pos = deviceTickPos[deviceId] || 0;
    const tick = card.querySelectorAll(".tick")[pos];
    if (tick) tick.className = "tick " + state;
  }

  function resetDeviceVisuals() {
    deviceTickPos = {};
    document.querySelectorAll(".device-card").forEach(card => {
      card.querySelectorAll(".tick").forEach(t => t.className = "tick");
      const dot = card.querySelector(".statusdot");
      if (dot) dot.className = "statusdot";
    });
  }

  async function fetchResults(strategy) {
    const res = await fetch(`${API}/api/batches/${currentBatch.id}/results?strategy=${strategy}`);
    if (!res.ok) return null;
    return res.json();
  }

  // ---------------- rendering results ----------------

  function renderAll() {
    logs = [];
    STRATEGIES.forEach(s => { if (results[s.key]) logs = logs.concat(results[s.key].rows); });

    renderSummary();
    renderDeviceChart();
    renderDeviceRates(); // NOT renderDeviceGrid() - that would wipe the tick bars a run just live-populated
    populateDeviceFilter();
    renderHead();
    applyFilters();
    renderExportButtons();

    const any = logs.length > 0;
    el("resultsSection").style.display = any ? "" : "none";
    el("chartSection").style.display = any ? "" : "none";
    el("deviceSection").style.display = "";
    el("logSection").style.display = any ? "" : "none";
  }

  function strategyCard(s) {
    const data = results[s.key];
    if (!data) {
      return `<div class="strategy-card empty ${s.cls}">
        <span class="tag">${s.tag}</span><div>${s.title}<br>Not run yet on this batch.</div>
      </div>`;
    }
    let pills = "";
    if (s.key !== "baseline" && results.baseline && results.baseline.loss_pct > 0) {
      const improvement = (results.baseline.loss_pct - data.loss_pct) / results.baseline.loss_pct * 100;
      pills += `<span class="improve-pill">&darr; ${improvement.toFixed(1)}% fewer losses than no protection</span>`;
    }
    if (s.key === "math_ai" && results.math && results.math.loss_pct > 0) {
      const vsMath = (results.math.loss_pct - data.loss_pct) / results.math.loss_pct * 100;
      const arrow = vsMath >= 0 ? "&darr;" : "&uarr;";
      pills += `<span class="improve-pill vs-math">${arrow} ${Math.abs(vsMath).toFixed(1)}% ${vsMath >= 0 ? "fewer" : "more"} losses than math-only</span>`;
    }
    return `<div class="strategy-card ${s.cls}">
      <span class="tag">${s.tag}</span>
      <h3>${s.title}</h3>
      <div class="big">${data.loss_pct.toFixed(1)}<small>% lost</small></div>
      <div class="rowline"><span>Packets sent</span><b>${data.total.toLocaleString()}</b></div>
      <div class="rowline"><span>Packets lost</span><b>${data.lost.toLocaleString()}</b></div>
      ${pills}
    </div>`;
  }

  function renderSummary() {
    el("summaryGrid").innerHTML = STRATEGIES.map(strategyCard).join("");
  }

  function renderDeviceChart() {
    const chartEl = el("deviceChart");
    if (!STRATEGIES.some(s => results[s.key])) { chartEl.innerHTML = ""; return; }
    const barCls = { baseline: "bar-base", math: "bar-math", math_ai: "bar-ai" };
    const rows = DEVICE_META.map(d => ({
      name: d.name,
      vals: STRATEGIES.map(s => (results[s.key] && results[s.key].by_device[d.name]) ? results[s.key].by_device[d.name].loss_pct : 0),
    }));
    const barH = 8, barGap = 3, subH = STRATEGIES.length * (barH + barGap);
    const W = 1100, rowH = subH + 16, padTop = 10, padLeft = 130, chartW = W - padLeft - 70;
    const H = rowH * rows.length + padTop + 20;
    const maxV = 100;
    let bars = "";
    rows.forEach((r, i) => {
      const yTop = padTop + i * rowH;
      bars += `<text class="devname" x="0" y="${yTop + subH / 2 + 4}">${r.name}</text>`;
      STRATEGIES.forEach((s, j) => {
        const y = yTop + j * (barH + barGap);
        const w = r.vals[j] / maxV * chartW;
        bars += `<rect class="${barCls[s.key]}" x="${padLeft}" y="${y}" width="${w}" height="${barH}" rx="2"></rect>`;
        bars += `<text class="barlabel" x="${padLeft + w + 6}" y="${y + barH - 1}">${r.vals[j].toFixed(1)}%</text>`;
      });
    });
    const gridlines = [0, 25, 50, 75, 100].map(g => {
      const x = padLeft + g / maxV * chartW;
      return `<line class="axis-line" x1="${x}" y1="${padTop - 4}" x2="${x}" y2="${H - 14}"></line><text x="${x}" y="${H - 2}" text-anchor="middle">${g}%</text>`;
    }).join("");
    const legend = STRATEGIES.map(s => {
      const color = s.key === "baseline" ? "var(--text-muted)" : s.key === "math" ? "var(--accent)" : "var(--ai)";
      const opacity = s.key === "baseline" ? "opacity:.55;" : "";
      return `<span><span style="display:inline-block;width:10px;height:10px;background:${color};${opacity}border-radius:2px;margin-right:5px;"></span>${s.short}</span>`;
    }).join("");
    chartEl.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Loss rate by device">${gridlines}${bars}</svg>
      <div style="display:flex; gap:18px; margin-top:6px; font-size:12px; color:var(--text-muted); flex-wrap:wrap;">${legend}</div>`;
  }

  // Builds the device card skeleton - called only when a batch is created/selected,
  // NEVER after a run, so the tick bars a live run just populated are never wiped.
  function renderDeviceGrid() {
    const ticks = '<span class="tick"></span>'.repeat(TICK_COUNT);
    el("deviceGrid").innerHTML = DEVICE_META.map(d => {
      const rateLines = STRATEGIES.map(s => `<div class="drates"><span class="${s.key === 'baseline' ? 'b' : s.key === 'math' ? 'm' : 'ai'}" data-rate="${s.key}">${s.short} –%</span></div>`).join("");
      return `<div class="device-card" data-id="${d.id}">
        <div class="dtop">${ICONS[d.icon]}<div><div class="dname">${d.name}</div><div class="dtype">${d.type}</div></div><span class="statusdot"></span></div>
        <div class="tickbar">${ticks}</div>
        <div class="tickbar-caption"><span>grey = in flight</span><span style="color:var(--good)">ok</span> / <span style="color:var(--bad)">lost</span></div>
        ${rateLines}
      </div>`;
    }).join("");
    deviceTickPos = {};
  }

  // Updates only the final-rate lines in each existing card - safe to call
  // after every run without touching that run's live tick history.
  function renderDeviceRates() {
    DEVICE_META.forEach(d => {
      const card = document.querySelector(`.device-card[data-id="${d.id}"]`);
      if (!card) return;
      STRATEGIES.forEach(s => {
        const rateEl = card.querySelector(`[data-rate="${s.key}"]`);
        if (!rateEl) return;
        const pct = (results[s.key] && results[s.key].by_device[d.name]) ? results[s.key].by_device[d.name].loss_pct.toFixed(1) : "–";
        rateEl.textContent = `${s.short} ${pct}%`;
      });
    });
  }

  function populateDeviceFilter() {
    const sel = el("fDevice");
    const currentVal = sel.value;
    sel.innerHTML = '<option value="all">All devices</option>' +
      DEVICE_META.map(d => `<option value="${d.id}">${d.name}</option>`).join("");
    sel.value = currentVal || "all";
  }

  const COLS = [
    ["idx", "#", "id"], ["strategy", "Strategy", "id"], ["device", "Device", "id"],
    ["proto", "proto", "pre"], ["service", "service", "pre"], ["sbytes", "sbytes", "pre"], ["spkts", "Spkts", "pre"],
    ["smeansz", "smeansz", "pre"], ["sttl", "sttl", "pre"], ["swin", "swin", "pre"], ["dst_port_bucket", "dst_port_bucket", "pre"],
    ["ct_state_ttl", "ct_state_ttl", "pre"], ["ct_srv_src", "ct_srv_src", "pre"], ["ct_srv_dst", "ct_srv_dst", "pre"],
    ["ct_dst_ltm", "ct_dst_ltm", "pre"], ["ct_src_ltm", "ct_src_ltm", "pre"], ["ct_src_dport_ltm", "ct_src_dport_ltm", "pre"],
    ["ct_dst_sport_ltm", "ct_dst_sport_ltm", "pre"], ["ct_dst_src_ltm", "ct_dst_src_ltm", "pre"],
    ["action", "Action", "decision"], ["attempts", "attempts", "decision"], ["extra_delay_ms", "extra delay (ms)", "decision"],
    ["used_model", "RF used", "decision"], ["model_risk_pct", "RF risk %", "decision"],
    ["congestion", "congestion", "decision"], ["risk_pct", "risk %", "decision"],
    ["state", "state", "post"], ["dbytes", "dbytes", "post"], ["sloss", "sloss", "post"], ["dloss", "dloss", "post"],
    ["copies_lost", "copies lost", "post"], ["packet_lost", "Outcome", "post"],
  ];

  function renderHead() {
    const head = el("headRow");
    head.innerHTML = COLS.map(([key, label, group]) => {
      const arrow = sortKey === key ? (sortDir === 1 ? " &uarr;" : " &darr;") : "";
      const cls = group === "id" ? "" : ` class="col-${group}"`;
      return `<th${cls}><button data-key="${key}">${label}${arrow}</button></th>`;
    }).join("");
    head.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.key;
        if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = 1; }
        applyFilters();
      });
    });
  }

  function applyFilters() {
    const fS = el("fStrategy").value, fD = el("fDevice").value, fO = el("fOutcome").value;
    filtered = logs.filter(r => {
      if (fS !== "all" && r.strategy !== fS) return false;
      if (fD !== "all" && r.device_id !== fD) return false;
      if (fO === "lost" && r.packet_lost !== 1) return false;
      if (fO === "ok" && r.packet_lost !== 0) return false;
      return true;
    });
    filtered.sort((a, b) => {
      let av = a[sortKey], bv = b[sortKey];
      if (av === null || av === undefined) av = "";
      if (bv === null || bv === undefined) bv = "";
      if (typeof av === "string") { av = av.toLowerCase(); bv = String(bv).toLowerCase(); }
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      return 0;
    });
    page = 0;
    renderTable();
  }

  // Deterministic color from a packet's idx - same idx always gets the same
  // hue, so the same underlying packet is recognizable by color across all
  // three strategies' rows, even when they aren't adjacent.
  function pairColor(idx) {
    const hue = (idx * 47) % 360; // 47 is coprime with 360 -> hues spread out, not clustered
    return `hsl(${hue}, 65%, 55%)`;
  }

  function renderTable() {
    const body = el("logBody");
    const total = filtered.length;
    const maxPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
    if (page > maxPage) page = maxPage;
    const rows = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

    const CELL_FORMAT = {
      idx: r => `<span class="pairdot" style="background:${pairColor(r.idx)}" title="Same #${r.idx} shares this color across strategies"></span>${r.idx}`,
      strategy: r => (STRAT_BY_KEY[r.strategy] || {}).short || r.strategy,
      action: r => `<span class="pill act-${r.action}">${r.action.replace("_", " ")}</span>`,
      used_model: r => r.used_model ? '<span class="pill act-MAX" style="background:var(--ai-soft); color:var(--ai-strong);">yes</span>' : "–",
      model_risk_pct: r => r.model_risk_pct === null || r.model_risk_pct === undefined ? "–" : r.model_risk_pct.toFixed(2) + "%",
      congestion: r => r.congestion.toFixed(2) + "×",
      risk_pct: r => r.risk_pct.toFixed(2) + "%",
      packet_lost: r => r.packet_lost ? '<span class="pill lost">LOST</span>' : '<span class="pill ok">OK</span>',
    };

    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="${COLS.length}"><div class="empty-state">No packets match these filters.</div></td></tr>`;
    } else {
      body.innerHTML = rows.map(r => {
        const cells = COLS.map(([key, , group]) => {
          const cls = group === "id" ? "" : ` class="col-${group}"`;
          const val = CELL_FORMAT[key] ? CELL_FORMAT[key](r) : r[key];
          return `<td${cls}>${val}</td>`;
        }).join("");
        return `<tr>${cells}</tr>`;
      }).join("");
    }
    el("rowCount").textContent = `${total.toLocaleString()} packet${total === 1 ? "" : "s"}`;
    el("pageInfo").textContent = total ? `Page ${page + 1} of ${maxPage + 1}` : "—";
    el("prevPage").disabled = page <= 0;
    el("nextPage").disabled = page >= maxPage;
  }

  ["fStrategy", "fDevice", "fOutcome"].forEach(id => el(id).addEventListener("change", applyFilters));
  el("prevPage").addEventListener("click", () => { if (page > 0) { page--; renderTable(); } });
  el("nextPage").addEventListener("click", () => {
    const maxPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1);
    if (page < maxPage) { page++; renderTable(); }
  });

  // ---------------- boot ----------------
  loadModelInfo();
  loadBatchList();
})();
