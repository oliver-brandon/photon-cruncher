/* Aurora app controller — live sessions only via photon_cruncher.service */
(function () {
  "use strict";

  const state = {
    view: "data",
    path: null,
    session: null,
    resultsByChannel: {},
    activeChannel: null,
    activeEpoc: null,
    selectedTrialNumbers: null,
    outcomeFilters: {},
    settings: {
      trange_start: -2,
      trange_end: 5,
      baseline_start: -2,
      baseline_end: -0.5,
      baseline_adjust: -2,
      downsample_factor: 10,
      plot_smoothed: true,
      baseline_correction: true,
    },
    ready: false,
    apiBase: "",
  };

  const modeNames = {
    data: "DATA",
    align: "ALIGN",
    trials: "TRIALS",
    batch: "BATCH",
  };

  function $(id) {
    return document.getElementById(id);
  }

  function hasSession() {
    return !!(state.path && state.session);
  }

  function hasResults() {
    return Object.keys(state.resultsByChannel).length > 0;
  }

  function toast(msg) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.textContent = hasSession()
        ? "live session · photon_cruncher.service"
        : "open a MAT file or TDT block";
    }, 4200);
  }

  function setBadge() {
    const b = $("stateBadge");
    if (!b) return;
    if (hasResults()) {
      b.textContent = "ANALYZED";
      b.classList.add("live");
    } else if (hasSession()) {
      b.textContent = "LOADED";
      b.classList.add("live");
    } else {
      b.textContent = "IDLE";
      b.classList.remove("live");
    }
  }

  function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(state.apiBase + path, opts).then(async (resp) => {
      const data = await resp.json();
      if (!resp.ok || data.ok === false) {
        throw new Error(data.error || `HTTP ${resp.status}`);
      }
      return data;
    });
  }

  function bridgeCall(method, arg) {
    return new Promise((resolve, reject) => {
      const bridge = window.auroraBridge;
      if (!bridge || typeof bridge[method] !== "function") {
        reject(new Error("Native bridge unavailable"));
        return;
      }
      try {
        const result = arg === undefined ? bridge[method]() : bridge[method](arg);
        if (result && typeof result.then === "function") result.then(resolve).catch(reject);
        else resolve(result);
      } catch (err) {
        reject(err);
      }
    });
  }

  async function nativeOrFetchAnalyze(body) {
    if (window.auroraBridge && window.auroraBridge.analyze) {
      const raw = await bridgeCall("analyze", JSON.stringify(body));
      const data = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!data.ok) throw new Error(data.error || "analyze failed");
      return data;
    }
    return api("POST", "/api/analyze", body);
  }

  async function nativeOrFetchExport(body) {
    if (window.auroraBridge && window.auroraBridge.export) {
      const raw = await bridgeCall("export", JSON.stringify(body));
      const data = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!data.ok) throw new Error(data.error || "export failed");
      return data;
    }
    return api("POST", "/api/export", body);
  }

  function showView(name) {
    state.view = modeNames[name] ? name : "data";
    document.querySelectorAll(".page").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.page !== state.view);
    });
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.page === state.view);
    });
    if ($("hudMode")) $("hudMode").textContent = modeNames[state.view];
    if (state.view === "align") renderAlign();
    if (state.view === "trials") renderTrials();
    if (state.view === "batch") renderBatchPage();
    if (state.view === "data") renderDataPage();
  }

  function fillSelect(sel, items, labelFn, valueFn) {
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = "";
    items.forEach((item) => {
      const o = document.createElement("option");
      o.value = valueFn(item);
      o.textContent = labelFn(item);
      sel.appendChild(o);
    });
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  }

  function readSettingsFromForm() {
    state.settings.trange_start = Number($("tr0")?.value ?? -2);
    state.settings.trange_end = Number($("tr1")?.value ?? 5);
    state.settings.baseline_start = Number($("b0")?.value ?? -2);
    state.settings.baseline_end = Number($("b1")?.value ?? -0.5);
    state.settings.baseline_adjust = Number($("baseAdjust")?.value ?? -2);
    state.settings.downsample_factor = Number($("downsample")?.value ?? 10);
    state.settings.plot_smoothed = !!$("plotSmooth")?.checked;
    state.settings.baseline_correction = !!$("applyBaseline")?.checked;
  }

  function settingsPayload() {
    readSettingsFromForm();
    return {
      trange_start: state.settings.trange_start,
      trange_end: state.settings.trange_end,
      baseline_start: state.settings.baseline_start,
      baseline_end: state.settings.baseline_end,
      baseline_adjust: state.settings.baseline_adjust,
      downsample_factor: state.settings.downsample_factor,
      plot_smoothed: state.settings.plot_smoothed,
      baseline_correction: state.settings.baseline_correction,
    };
  }

  function clearSessionUi() {
    state.path = null;
    state.session = null;
    state.resultsByChannel = {};
    state.activeChannel = null;
    state.activeEpoc = null;
    state.selectedTrialNumbers = null;
    state.outcomeFilters = {};

    $("hudSession").textContent = "No session";
    $("orbitName").textContent = "No session open";
    $("orbitMeta").textContent = "Open a MAT file or TDT block";
    $("hudTrials").textContent = "—";
    $("statDuration").textContent = "—";
    $("statChannels").textContent = "—";
    $("statEpocs").textContent = "—";
    if ($("sessionPath")) $("sessionPath").textContent = "No file loaded";
    if ($("channelChips")) $("channelChips").innerHTML = '<span class="quiet">—</span>';
    if ($("epocChips")) $("epocChips").innerHTML = '<span class="quiet">—</span>';
    if ($("trialStream")) $("trialStream").innerHTML = "";
    if ($("outcomeChips")) $("outcomeChips").innerHTML = "";
    if ($("selLabel")) $("selLabel").textContent = "0 selected";
    if ($("alignSummary")) $("alignSummary").textContent = "Open a session to analyze";
    if ($("trialSummary")) $("trialSummary").textContent = "—";
    if ($("rPeak")) $("rPeak").textContent = "—";
    if ($("rLat")) $("rLat").textContent = "—";
    if ($("rN")) $("rN").textContent = "—";
    if ($("alignTag")) $("alignTag").textContent = "—";
    clearCanvas($("alignTrace"));
    clearCanvas($("alignHeat"));
    clearCanvas($("trialTrace"));
    clearCanvas($("trialHeat"));
    fillSelect($("alignChannel"), [], () => "", () => "");
    fillSelect($("alignEpoc"), [], () => "", () => "");
    fillSelect($("trialChannel"), [], () => "", () => "");
    setBadge();
    renderDataPage();
    renderBatchPage();
  }

  function clearCanvas(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function applySessionSummary(session, path) {
    state.session = session;
    state.path = path || state.path;
    const name = session.session_name || "session";
    $("hudSession").textContent = name;
    $("orbitName").textContent = name;
    const chans = (session.channels || []).join(" · ") || "no channels";
    const nEpocs = Object.keys(session.epocs || {}).length;
    $("orbitMeta").textContent = chans;
    $("statChannels").textContent = String((session.channels || []).length);
    $("statEpocs").textContent = String(nEpocs);
    const streams = session.streams || {};
    const firstStream = Object.values(streams)[0];
    $("statDuration").textContent =
      firstStream && firstStream.fs
        ? `${(firstStream.samples / firstStream.fs / 60).toFixed(1)}m`
        : "—";
    const firstEpocEvents = Object.values(session.epocs || {})[0]?.events;
    $("hudTrials").textContent =
      firstEpocEvents != null ? String(firstEpocEvents) : String(nEpocs);
    if ($("sessionPath")) $("sessionPath").textContent = state.path || "—";
    if ($("channelChips")) {
      $("channelChips").innerHTML =
        (session.channels || [])
          .map((c) => `<span class="chip on">${c}</span>`)
          .join("") || '<span class="quiet">No channels</span>';
    }
    if ($("epocChips")) {
      const epocNames = Object.keys(session.epocs || {});
      const classified = (session.classified_sources || []).map(
        (s) => s.key || s.label
      );
      $("epocChips").innerHTML =
        [...epocNames, ...classified]
          .map(
            (e, i) =>
              `<span class="chip ${i < epocNames.length ? "on" : "mag"}">${e}</span>`
          )
          .join("") || '<span class="quiet">No epocs</span>';
    }

    const epocNames = Object.keys(session.epocs || {});
    const classified = (session.classified_sources || []).map(
      (s) => s.key || s.label
    );
    const allEpocs = [...epocNames, ...classified];
    fillSelect($("alignEpoc"), allEpocs, (e) => e, (e) => e);
    fillSelect(
      $("alignChannel"),
      session.channels || [],
      (c) => c,
      (c) => c
    );
    if (!state.activeEpoc || !allEpocs.includes(state.activeEpoc)) {
      state.activeEpoc =
        epocNames.find((e) => !["tick", "cam1"].includes(String(e).toLowerCase())) ||
        allEpocs[0] ||
        null;
    }
    if (!state.activeChannel || !(session.channels || []).includes(state.activeChannel)) {
      state.activeChannel = (session.channels || [])[0] || null;
    }
    if (state.activeEpoc) $("alignEpoc").value = state.activeEpoc;
    if (state.activeChannel) $("alignChannel").value = state.activeChannel;
    setBadge();
  }

  function setupAlignControls() {
    $("alignChannel").addEventListener("change", () => {
      state.activeChannel = $("alignChannel").value;
      if ($("trialChannel")) $("trialChannel").value = state.activeChannel;
      renderAlign();
      renderTrials();
    });
    $("alignEpoc").addEventListener("change", async () => {
      state.activeEpoc = $("alignEpoc").value;
      $("alignTag").textContent = state.activeEpoc || "—";
      if (!hasSession()) return;
      try {
        await runLiveAnalyze({ force: true });
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("alignPulse").addEventListener("click", async () => {
      if (!hasSession()) {
        toast("open a session first");
        return;
      }
      try {
        await runLiveAnalyze({ force: true });
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("alignApply")?.addEventListener("click", async () => {
      if (!hasSession()) {
        toast("open a session first");
        return;
      }
      try {
        await runLiveAnalyze({ force: true });
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("alignDefaults")?.addEventListener("click", () => {
      $("tr0").value = -2;
      $("tr1").value = 5;
      $("b0").value = -2;
      $("b1").value = -0.5;
      $("baseAdjust").value = -2;
      $("downsample").value = 10;
      $("plotSmooth").checked = true;
      $("applyBaseline").checked = true;
      toast("defaults restored");
    });
    $("alignExport")?.addEventListener("click", () => exportLive());
  }

  async function runLiveAnalyze(opts = {}) {
    if (!state.path) throw new Error("No session open");
    const epoc =
      state.activeEpoc ||
      $("alignEpoc").value ||
      Object.keys(state.session?.epocs || {})[0];
    if (!epoc) throw new Error("No epoc available");
    toast("analyzing…");
    if (window.auroraBridge?.setStatus) window.auroraBridge.setStatus("Analyzing…");
    const channels = state.session?.channels || null;
    const data = await nativeOrFetchAnalyze({
      path: state.path,
      epoc,
      channels,
      settings: settingsPayload(),
      force: !!opts.force,
      trial_numbers: state.selectedTrialNumbers || undefined,
    });
    applyAnalyzePayload(data);
    toast(`analyzed ${epoc}`);
    return data;
  }

  function applyAnalyzePayload(data) {
    state.path = data.path || state.path;
    if (data.session) applySessionSummary(data.session, state.path);
    state.activeEpoc = data.epoc || state.activeEpoc;
    state.resultsByChannel = {};
    (data.results || []).forEach((r) => {
      state.resultsByChannel[r.channel] = r;
    });
    const keys = Object.keys(state.resultsByChannel);
    if (!keys.length) {
      toast("analyze returned no channels");
      setBadge();
      return;
    }
    if (!state.activeChannel || !state.resultsByChannel[state.activeChannel]) {
      state.activeChannel = keys[0];
    }
    fillSelect($("alignChannel"), keys, (c) => c, (c) => c);
    fillSelect($("trialChannel"), keys, (c) => c, (c) => c);
    if (state.activeChannel) {
      $("alignChannel").value = state.activeChannel;
      if ($("trialChannel")) $("trialChannel").value = state.activeChannel;
    }
    if (state.activeEpoc && $("alignEpoc")) $("alignEpoc").value = state.activeEpoc;
    populateTrialStreamFromLive();
    renderAlign();
    renderDataPage();
    renderBatchPage();
    setBadge();
  }

  function renderAlign() {
    if (!hasResults()) {
      clearCanvas($("alignTrace"));
      clearCanvas($("alignHeat"));
      $("alignSummary").textContent = hasSession()
        ? "Run analyze to plot"
        : "Open a session to analyze";
      return;
    }
    const result =
      state.resultsByChannel[state.activeChannel] ||
      Object.values(state.resultsByChannel)[0];
    if (!result) return;
    const times = Float64Array.from(result.times || []);
    const mean = Float64Array.from(result.mean || []);
    const sem = Float64Array.from(result.sem || []);
    const z = (result.z || []).map((row) => Float64Array.from(row));
    window.AuroraPlots.drawGlowTrace($("alignTrace"), {
      times,
      mean,
      sem,
      color: "#00f5d4",
      baseline: result.settings?.baseline_per || [
        state.settings.baseline_start,
        state.settings.baseline_end,
      ],
    });
    window.AuroraPlots.drawHeat($("alignHeat"), { times, matrix: z });
    if (mean.length) {
      const pk = window.AuroraPlots.peakLatency(times, mean);
      $("rPeak").textContent = pk.peak.toFixed(2) + " z";
      $("rLat").textContent = pk.lat.toFixed(2) + "s";
      $("rN").textContent = String(result.num_trials || z.length);
    }
    $("alignTag").textContent = result.epoc || "epoc";
    $("alignSummary").textContent = `${result.num_trials || 0} trials · ${result.channel}`;
    $("hudTrials").textContent = String(result.num_trials || 0);
  }

  function setupTrials() {
    $("trialSearch").addEventListener("input", filterTrials);
    $("selAll").addEventListener("click", () => setChecks(true, true));
    $("selNone").addEventListener("click", () => setChecks(false, false));
    $("selInvert").addEventListener("click", invertVisible);
    $("trialChannel").addEventListener("change", () => {
      state.activeChannel = $("trialChannel").value;
      if ($("alignChannel")) $("alignChannel").value = state.activeChannel;
      renderTrials();
      renderAlign();
    });
    $("trialMode").addEventListener("change", renderTrials);
    $("trialExportCsv")?.addEventListener("click", () => exportLive());
    $("trialExportFig")?.addEventListener("click", () => exportLive());
  }

  function populateTrialStreamFromLive() {
    const result =
      state.resultsByChannel[state.activeChannel] ||
      Object.values(state.resultsByChannel)[0];
    if (!result) return;
    const list = $("trialStream");
    list.innerHTML = "";
    const numbers = result.trial_numbers || [];
    const labels = result.trial_labels || [];
    const presentOutcomes = new Set();
    numbers.forEach((num, i) => {
      const label = labels[i] || "trial";
      presentOutcomes.add(label);
      const row = document.createElement("label");
      row.className = "trial-row";
      row.dataset.outcome = label || "unclassified";
      row.dataset.number = String(num);
      row.innerHTML = `
        <input type="checkbox" checked data-number="${num}" />
        <span>${label || "trial"}</span>
        <span class="n">T${String(num).padStart(3, "0")}</span>`;
      row.querySelector("input").addEventListener("change", async () => {
        syncSelected();
        try {
          await runLiveAnalyze();
        } catch (err) {
          toast(String(err.message || err));
          renderTrials();
        }
      });
      list.appendChild(row);
    });

    const chips = $("outcomeChips");
    chips.innerHTML = "";
    state.outcomeFilters = {};
    Array.from(presentOutcomes).forEach((label) => {
      state.outcomeFilters[label] = true;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip-btn on";
      b.textContent = label;
      b.dataset.outcome = label;
      b.addEventListener("click", () => {
        state.outcomeFilters[label] = !state.outcomeFilters[label];
        b.classList.toggle("on", state.outcomeFilters[label]);
        filterTrials();
      });
      chips.appendChild(b);
    });

    fillSelect(
      $("trialChannel"),
      Object.keys(state.resultsByChannel),
      (c) => c,
      (c) => c
    );
    if (state.activeChannel) $("trialChannel").value = state.activeChannel;
    $("trialSub").textContent = state.activeEpoc
      ? `${state.activeEpoc} · trial list`
      : "trial list";
    syncSelected();
  }

  function filterTrials() {
    const q = $("trialSearch").value.trim().toLowerCase();
    document.querySelectorAll(".trial-row").forEach((row) => {
      const o = row.dataset.outcome;
      const show =
        state.outcomeFilters[o] !== false &&
        (!q || row.textContent.toLowerCase().includes(q));
      row.classList.toggle("hidden", !show);
      row.style.display = show ? "" : "none";
    });
  }

  function syncSelected() {
    const boxes = document.querySelectorAll(
      '.trial-row input[type="checkbox"]:checked'
    );
    const numbers = Array.from(boxes)
      .map((el) => Number(el.dataset.number))
      .filter((n) => Number.isFinite(n));
    state.selectedTrialNumbers = numbers.length ? numbers : null;
    $("selLabel").textContent = `${numbers.length} selected`;
  }

  function setChecks(checked, visibleOnly) {
    document.querySelectorAll(".trial-row").forEach((row) => {
      if (visibleOnly && (row.style.display === "none" || row.classList.contains("hidden"))) {
        return;
      }
      const n = row.querySelector("input");
      if (n) n.checked = checked;
    });
    syncSelected();
    renderTrials();
  }

  function invertVisible() {
    document.querySelectorAll(".trial-row").forEach((row) => {
      if (row.style.display === "none" || row.classList.contains("hidden")) return;
      const n = row.querySelector("input");
      if (n) n.checked = !n.checked;
    });
    syncSelected();
    renderTrials();
  }

  function meanSemRows(rows) {
    if (!rows.length) return { mean: new Float64Array(), sem: new Float64Array() };
    const n = rows.length;
    const m = rows[0].length;
    const mean = new Float64Array(m);
    const sem = new Float64Array(m);
    for (let j = 0; j < m; j++) {
      let s = 0;
      for (let i = 0; i < n; i++) s += rows[i][j];
      mean[j] = s / n;
    }
    if (n > 1) {
      for (let j = 0; j < m; j++) {
        let ss = 0;
        for (let i = 0; i < n; i++) {
          const d = rows[i][j] - mean[j];
          ss += d * d;
        }
        sem[j] = Math.sqrt(ss / (n - 1)) / Math.sqrt(n);
      }
    }
    return { mean, sem };
  }

  function renderTrials() {
    if (!hasResults()) {
      clearCanvas($("trialTrace"));
      clearCanvas($("trialHeat"));
      $("trialSummary").textContent = hasSession()
        ? "Analyze to populate trials"
        : "Open a session first";
      return;
    }
    const key = $("trialChannel").value || state.activeChannel;
    const result = state.resultsByChannel[key];
    if (!result) return;
    const mode = $("trialMode").value;
    const times = Float64Array.from(result.times || []);
    const mean = Float64Array.from(result.mean || []);
    const sem = Float64Array.from(result.sem || []);
    const z = (result.z || []).map((row) => Float64Array.from(row));
    let rows = z;
    let meanUse = mean;
    let semUse = sem;
    if (state.selectedTrialNumbers && state.selectedTrialNumbers.length) {
      const want = new Set(state.selectedTrialNumbers);
      const nums = result.trial_numbers || [];
      const idx = [];
      nums.forEach((n, i) => {
        if (want.has(n)) idx.push(i);
      });
      if (idx.length) {
        rows = idx.map((i) => z[i]);
        const stats = meanSemRows(rows);
        meanUse = stats.mean;
        semUse = stats.sem;
      }
    }
    window.AuroraPlots.drawGlowTrace($("trialTrace"), {
      times,
      mean: meanUse,
      sem: mode === "mean" ? semUse : null,
      individuals: mode === "individual" ? rows : null,
      color: "#00f5d4",
    });
    window.AuroraPlots.drawHeat($("trialHeat"), { times, matrix: rows });
    $("trialSummary").textContent = `${rows.length} trials · ${key}`;
  }

  function setupBatch() {
    $("launchBatch").addEventListener("click", () => exportLive());
    $("abortBatch").disabled = true;
    renderBatchPage();
  }

  function renderDataPage() {
    const openBtn = $("openSessionBtn");
    const closeBtn = $("closeSessionBtn");
    const page = $("page-data");
    if (page) page.classList.toggle("empty-mode", !hasSession());
    if (hasSession()) {
      openBtn.textContent = "Re-analyze";
      closeBtn.disabled = false;
      $("dataHint").textContent =
        "Session loaded through photon_cruncher.service. Use Align to tune windows.";
      $("dataLede").textContent =
        "Session ready. Adjust processing on Align, filter trials, then export.";
    } else {
      openBtn.textContent = "Open MAT / TDT";
      closeBtn.disabled = true;
      $("dataHint").textContent =
        "Use Open MAT / TDT (or File menu in the native shell) to load real photometry data.";
      $("dataLede").textContent =
        "Open a MATLAB export or TDT block, then analyze with the shared backend.";
    }
  }

  function renderBatchPage() {
    const body = $("batchList");
    if (!body) return;
    if (hasSession()) {
      const nCh = Object.keys(state.resultsByChannel).length;
      const first = Object.values(state.resultsByChannel)[0];
      body.innerHTML = `
        <tr><td>Path</td><td>${state.path}</td></tr>
        <tr><td>Session</td><td>${state.session?.session_name || "—"}</td></tr>
        <tr><td>Epoc</td><td>${state.activeEpoc || "—"}</td></tr>
        <tr><td>Channels analyzed</td><td>${nCh || "not yet"}</td></tr>
        <tr><td>Trials</td><td>${first?.num_trials ?? "—"}</td></tr>`;
      $("batchSessionDetail").textContent = hasResults()
        ? "Ready to export CSV/figures via shared service."
        : "Analyze on Align before exporting.";
      $("mChannels").textContent = String(nCh || "—");
      $("mTrials").textContent = String(first?.num_trials ?? "—");
      $("mEpoc").textContent = String(state.activeEpoc || "—").slice(0, 10);
      $("mMode").textContent = hasResults() ? "ready" : "loaded";
      $("launchBatch").textContent = "Export results";
      $("launchBatch").disabled = !hasResults();
    } else {
      body.innerHTML = `<tr><td colspan="2">No session open</td></tr>`;
      $("batchSessionDetail").textContent =
        "Open and analyze a session, then export CSV/figures here.";
      $("mChannels").textContent = "—";
      $("mTrials").textContent = "—";
      $("mEpoc").textContent = "—";
      $("mMode").textContent = "idle";
      $("launchBatch").textContent = "Export results";
      $("launchBatch").disabled = true;
    }
  }

  function setBatch(pct, detail, status) {
    $("batchPct").textContent = pct + "%";
    $("batchDetail").textContent = detail;
    $("batchStatus").textContent = status;
    if ($("batchBar")) $("batchBar").style.width = pct + "%";
  }

  async function exportLive() {
    if (!state.path || !state.activeEpoc) {
      toast("open and analyze a session first");
      return;
    }
    if (!hasResults()) {
      toast("analyze before exporting");
      return;
    }
    let outputDir = "";
    try {
      if (window.auroraBridge?.chooseExportDir) {
        outputDir = await bridgeCall("chooseExportDir");
      }
    } catch (_) {
      /* fall through */
    }
    if (!outputDir) outputDir = prompt("Export folder path:", "") || "";
    if (!outputDir) return;
    toast("exporting…");
    setBatch(15, "writing exports…", "RUN");
    $("launchBatch").disabled = true;
    try {
      const data = await nativeOrFetchExport({
        path: state.path,
        epoc: state.activeEpoc,
        channels: Object.keys(state.resultsByChannel),
        settings: settingsPayload(),
        output_dir: outputDir,
        export_csv: !!$("expCsv")?.checked,
        export_figure: !!$("expFig")?.checked,
        figure_format: $("figFormat")?.value || "png",
        trial_numbers: state.selectedTrialNumbers || undefined,
      });
      const n = (data.exports || []).length;
      setBatch(100, `wrote ${n} export set(s)`, "DONE");
      toast(`exported ${n} channel(s) → ${data.output_dir}`);
      if (window.auroraBridge?.setStatus)
        window.auroraBridge.setStatus(`Exported to ${data.output_dir}`);
    } catch (err) {
      setBatch(0, "export failed", "FAIL");
      toast(String(err.message || err));
    } finally {
      $("launchBatch").disabled = !hasResults();
    }
  }

  async function openLiveSession(path) {
    toast("opening…");
    const data = await api("POST", "/api/open", { path });
    state.path = data.path;
    applySessionSummary(data.session, data.path);
    const epocs = Object.keys(data.session.epocs || {});
    const preferred =
      epocs.find((e) => !["tick", "cam1"].includes(e.toLowerCase())) ||
      epocs[0] ||
      (data.session.classified_sources || [])[0]?.key;
    state.activeEpoc = preferred || null;
    state.activeChannel = (data.session.channels || [])[0] || null;
    await runLiveAnalyze({ force: true });
    showView("align");
    toast(`loaded ${data.session.session_name}`);
  }

  async function handleOpen() {
    if (hasSession() && hasResults()) {
      try {
        await runLiveAnalyze({ force: true });
        showView("align");
      } catch (e) {
        toast(String(e.message || e));
      }
      return;
    }
    if (window.auroraBridge?.openMatDialog) {
      try {
        const path = await bridgeCall("openMatDialog");
        if (!path) return;
        const raw = await bridgeCall("openSession", path);
        const data = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!data.ok) throw new Error(data.error || "open failed");
        state.path = data.path;
        applySessionSummary(data.session, data.path);
        const epocs = Object.keys(data.session.epocs || {});
        state.activeEpoc =
          epocs.find((e) => !["tick", "cam1"].includes(e.toLowerCase())) ||
          epocs[0] ||
          null;
        state.activeChannel = (data.session.channels || [])[0] || null;
        await runLiveAnalyze({ force: true });
        showView("align");
      } catch (e) {
        toast(String(e.message || e));
      }
      return;
    }
    // Browser mode without native bridge: ask for path
    const path = prompt("Path to MAT file or TDT block folder:", "") || "";
    if (!path) return;
    try {
      await openLiveSession(path);
    } catch (e) {
      toast(String(e.message || e));
    }
  }

  async function handleClose() {
    if (!hasSession()) return;
    try {
      await api("POST", "/api/close", {});
    } catch (_) {
      /* ignore */
    }
    clearSessionUi();
    toast("session closed");
    showView("data");
  }

  function onShellMessage(message) {
    if (!message || !message.type) return;
    if (message.toast) toast(message.toast);
    if (message.type === "goto" && message.page) {
      showView(message.page);
      return;
    }
    if (message.type === "session") {
      state.path = message.path;
      if (message.session) applySessionSummary(message.session, message.path);
      renderDataPage();
      return;
    }
    if (message.type === "analyze") {
      applyAnalyzePayload(message.payload || message);
      showView("align");
      return;
    }
    if (message.type === "reanalyze") {
      runLiveAnalyze({ force: true }).catch((e) => toast(String(e.message || e)));
      return;
    }
    if (message.type === "export") {
      exportLive();
      return;
    }
    if (message.type === "close") {
      clearSessionUi();
      showView("data");
    }
  }

  function onShellReady() {
    toast("native shell connected");
    document.body.classList.add("shell-mode");
  }

  function wireChrome() {
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.addEventListener("click", () => showView(b.dataset.page));
    });
    $("openSessionBtn").addEventListener("click", handleOpen);
    $("closeSessionBtn").addEventListener("click", handleClose);
    $("openTdtBtn")?.addEventListener("click", async () => {
      if (window.auroraBridge?.openTdtDialog) {
        try {
          const path = await bridgeCall("openTdtDialog");
          if (!path) return;
          const raw = await bridgeCall("openSession", path);
          const data = typeof raw === "string" ? JSON.parse(raw) : raw;
          if (!data.ok) throw new Error(data.error || "open failed");
          state.path = data.path;
          applySessionSummary(data.session, data.path);
          const epocs = Object.keys(data.session.epocs || {});
          state.activeEpoc =
            epocs.find((e) => !["tick", "cam1"].includes(e.toLowerCase())) ||
            epocs[0] ||
            null;
          state.activeChannel = (data.session.channels || [])[0] || null;
          await runLiveAnalyze({ force: true });
          showView("align");
        } catch (e) {
          toast(String(e.message || e));
        }
        return;
      }
      handleOpen();
    });
    window.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey) {
        const map = { "1": "data", "2": "align", "3": "trials", "4": "batch" };
        if (map[e.key]) {
          e.preventDefault();
          showView(map[e.key]);
        }
      }
    });
    window.addEventListener("resize", () => {
      if (state.view === "align") renderAlign();
      if (state.view === "trials") renderTrials();
    });
  }

  function init() {
    setupAlignControls();
    setupTrials();
    setupBatch();
    wireChrome();
    clearSessionUi();
    hydrateBrand();

    const params = new URLSearchParams(location.search);
    const page = params.get("page") || "data";
    if (params.get("shell") === "1" || params.get("app") === "1") {
      document.body.classList.add("shell-mode");
    }
    showView(page);

    state.ready = true;
    window.Aurora = {
      ready: true,
      showView,
      toast,
      onShellMessage,
      onShellReady,
      openLiveSession,
      runLiveAnalyze,
      exportLive,
      state,
    };
  }

  function hydrateBrand() {
    // Prefer API brand label so product.py stays the single source of truth.
    api("GET", "/api/health")
      .then((health) => {
        if (health.brand && $("brandSub")) {
          $("brandSub").textContent = health.brand;
        }
        if (health.ui_version && $("railMeta")) {
          $("railMeta").textContent = `developer surface · v${health.ui_version}`;
        }
        document.title = health.title || "Photon Cruncher Aurora";
      })
      .catch(() => {
        /* static HTML already has Aurora v2.0 fallback */
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
