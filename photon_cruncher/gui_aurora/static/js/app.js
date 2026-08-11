/* Aurora app controller — live sessions only via photon_cruncher.service */
(function () {
  "use strict";

  const state = {
    view: "data",
    path: null,
    session: null,
    resultsByChannel: {},
    filteredResultsByChannel: {},
    trialResultsByChannel: {},
    trialFilteredResultsByChannel: {},
    activeChannel: null,
    activeEpoc: null,
    trialChannel: null,
    trialEpoc: null,
    checkedTrialNumbers: null,
    selectedTrialNumbers: null,
    outcomeFilters: {},
    smoothByChannel: {},
    trialSmoothByChannel: {},
    analysisChannels: [],
    trialAnalysisChannels: [],
    sources: [],
    outputDir: "",
    batchEpocs: null,
    batchChannels: null,
    batchOutcomes: [],
    batchRunning: false,
    batchCancelled: false,
    settings: {
      trange_start: -2,
      trange_end: 5,
      baseline_start: -3,
      baseline_end: -1,
      baseline_adjust: -2,
      downsample_factor: 10,
      plot_smoothed: true,
      baseline_correction: true,
      use_isosbestic: true,
      polynomial_degree: 1,
    },
    trialSettings: {
      trange_start: -2,
      trange_end: 5,
      baseline_start: -3,
      baseline_end: -1,
      baseline_adjust: -2,
      downsample_factor: 10,
      plot_smoothed: true,
      baseline_correction: true,
      use_isosbestic: true,
      polynomial_degree: 1,
    },
    ready: false,
    apiBase: "",
  };

  let alignAnalyzeTimer = null;
  let trialAnalyzeTimer = null;
  let alignRequestSequence = 0;
  let trialRequestSequence = 0;

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

  function hasFilteredResults() {
    return Object.keys(state.filteredResultsByChannel).length > 0;
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
    if (hasResults() || Object.keys(state.trialResultsByChannel).length) {
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

  async function nativeOrFetchBatch(body) {
    return api("POST", "/api/batch-export", body);
  }

  function processingSnapshot() {
    return {
      ...state.settings,
      channel_smoothing: { ...state.smoothByChannel },
      trial_settings: { ...state.trialSettings },
      trial_channel_smoothing: { ...state.trialSmoothByChannel },
    };
  }

  function persistProcessingSettings() {
    const payload = processingSnapshot();
    try {
      localStorage.setItem("aurora.processing", JSON.stringify(payload));
    } catch (_) {
      /* native persistence remains available */
    }
    if (window.auroraBridge?.saveProcessingSettings) {
      bridgeCall("saveProcessingSettings", JSON.stringify(payload)).catch(() => {});
    }
  }

  function applyProcessingSettings(payload) {
    if (!payload || typeof payload !== "object") return;
    const {
      channel_smoothing: channelSmoothing,
      trial_settings: trialSettings,
      trial_channel_smoothing: trialChannelSmoothing,
      ...alignSettings
    } = payload;
    Object.assign(state.settings, alignSettings);
    if (channelSmoothing && typeof channelSmoothing === "object") {
      state.smoothByChannel = { ...channelSmoothing };
    }
    state.trialSettings =
      trialSettings && typeof trialSettings === "object"
        ? { ...state.settings, ...trialSettings }
        : { ...state.settings };
    state.trialSmoothByChannel =
      trialChannelSmoothing && typeof trialChannelSmoothing === "object"
        ? { ...trialChannelSmoothing }
        : { ...state.smoothByChannel };
    const values = {
      tr0: state.settings.trange_start,
      tr1: state.settings.trange_end,
      b0: state.settings.baseline_start,
      b1: state.settings.baseline_end,
      baseAdjust: state.settings.baseline_adjust,
      downsample: state.settings.downsample_factor,
      polynomialDegree: state.settings.polynomial_degree,
      trialTr0: state.trialSettings.trange_start,
      trialTr1: state.trialSettings.trange_end,
      trialB0: state.trialSettings.baseline_start,
      trialB1: state.trialSettings.baseline_end,
      trialBaseAdjust: state.trialSettings.baseline_adjust,
      trialDownsample: state.trialSettings.downsample_factor,
      trialPolynomialDegree: state.trialSettings.polynomial_degree,
    };
    Object.entries(values).forEach(([id, value]) => {
      if ($(id) && value != null) $(id).value = value;
    });
    if ($("plotSmooth")) $("plotSmooth").checked = !!state.settings.plot_smoothed;
    if ($("applyBaseline"))
      $("applyBaseline").checked = !!state.settings.baseline_correction;
    if ($("useIsosbestic"))
      $("useIsosbestic").checked = !!state.settings.use_isosbestic;
    if ($("trialPlotSmooth"))
      $("trialPlotSmooth").checked = !!state.trialSettings.plot_smoothed;
    if ($("trialApplyBaseline"))
      $("trialApplyBaseline").checked = !!state.trialSettings.baseline_correction;
    if ($("trialUseIsosbestic"))
      $("trialUseIsosbestic").checked = !!state.trialSettings.use_isosbestic;
    syncIsosbesticControls(false);
    syncIsosbesticControls(true);
  }

  async function restoreProcessingSettings() {
    let payload = null;
    if (window.auroraBridge?.savedProcessingSettings) {
      try {
        const raw = await bridgeCall("savedProcessingSettings");
        payload = typeof raw === "string" ? JSON.parse(raw) : raw;
      } catch (_) {
        payload = null;
      }
    }
    if (!payload) {
      try {
        payload = JSON.parse(localStorage.getItem("aurora.processing") || "null");
      } catch (_) {
        payload = null;
      }
    }
    applyProcessingSettings(payload);
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
    state.settings.baseline_start = Number($("b0")?.value ?? -3);
    state.settings.baseline_end = Number($("b1")?.value ?? -1);
    state.settings.baseline_adjust = Number($("baseAdjust")?.value ?? -2);
    state.settings.downsample_factor = Number($("downsample")?.value ?? 10);
    state.settings.polynomial_degree = Math.max(
      1,
      Math.round(Number($("polynomialDegree")?.value ?? 1))
    );
    if (state.activeChannel) {
      state.smoothByChannel[state.activeChannel] = Math.max(
        1,
        Number($("smoothFactor")?.value ?? 10)
      );
    }
    state.settings.plot_smoothed = !!$("plotSmooth")?.checked;
    state.settings.baseline_correction = !!$("applyBaseline")?.checked;
    state.settings.use_isosbestic = !!$("useIsosbestic")?.checked;
    syncIsosbesticControls(false);
    persistProcessingSettings();
  }

  function readTrialSettingsFromForm() {
    state.trialSettings.trange_start = Number($("trialTr0")?.value ?? -2);
    state.trialSettings.trange_end = Number($("trialTr1")?.value ?? 5);
    state.trialSettings.baseline_start = Number($("trialB0")?.value ?? -3);
    state.trialSettings.baseline_end = Number($("trialB1")?.value ?? -1);
    state.trialSettings.baseline_adjust = Number(
      $("trialBaseAdjust")?.value ?? -2
    );
    state.trialSettings.downsample_factor = Number(
      $("trialDownsample")?.value ?? 10
    );
    state.trialSettings.polynomial_degree = Math.max(
      1,
      Math.round(Number($("trialPolynomialDegree")?.value ?? 1))
    );
    if (state.trialChannel) {
      state.trialSmoothByChannel[state.trialChannel] = Math.max(
        1,
        Number($("trialSmoothFactor")?.value ?? 10)
      );
    }
    state.trialSettings.plot_smoothed = !!$("trialPlotSmooth")?.checked;
    state.trialSettings.baseline_correction = !!$("trialApplyBaseline")?.checked;
    state.trialSettings.use_isosbestic = !!$("trialUseIsosbestic")?.checked;
    syncIsosbesticControls(true);
    persistProcessingSettings();
  }

  function syncIsosbesticControls(trial) {
    const toggle = $(trial ? "trialUseIsosbestic" : "useIsosbestic");
    const input = $(trial ? "trialPolynomialDegree" : "polynomialDegree");
    const field = $(trial ? "trialPolynomialDegreeField" : "polynomialDegreeField");
    const enabled = !!toggle?.checked;
    if (input) input.disabled = !enabled;
    field?.classList.toggle("is-disabled", !enabled);
  }

  function syncSessionIsosbesticAvailability(session) {
    const details = session?.channel_details || [];
    const fullySignalOnly =
      details.length > 0 && details.every((detail) => !detail.iso_stream);
    [
      ["useIsosbestic", state.settings],
      ["trialUseIsosbestic", state.trialSettings],
    ].forEach(([id, settings]) => {
      const toggle = $(id);
      if (!toggle) return;
      toggle.disabled = fullySignalOnly;
      toggle.title = fullySignalOnly
        ? "No 405 isosbestic control channel is available in this session."
        : "";
      if (fullySignalOnly) {
        toggle.checked = false;
        settings.use_isosbestic = false;
      }
    });
    syncIsosbesticControls(false);
    syncIsosbesticControls(true);
  }

  function trialSettingsPayload() {
    readTrialSettingsFromForm();
    return {
      trange_start: state.trialSettings.trange_start,
      trange_end: state.trialSettings.trange_end,
      baseline_start: state.trialSettings.baseline_start,
      baseline_end: state.trialSettings.baseline_end,
      baseline_adjust: state.trialSettings.baseline_adjust,
      downsample_factor: state.trialSettings.downsample_factor,
      plot_smoothed: state.trialSettings.plot_smoothed,
      baseline_correction: state.trialSettings.baseline_correction,
      use_isosbestic: state.trialSettings.use_isosbestic,
      polynomial_degree: state.trialSettings.polynomial_degree,
    };
  }

  function trialChannelSettingsPayload() {
    const payload = {};
    Object.entries(state.trialSmoothByChannel).forEach(([channel, smoothFactor]) => {
      if (Number.isFinite(Number(smoothFactor))) {
        payload[channel] = { smooth_factor: Math.max(1, Number(smoothFactor)) };
      }
    });
    return payload;
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
      use_isosbestic: state.settings.use_isosbestic,
      polynomial_degree: state.settings.polynomial_degree,
    };
  }

  function processingFormIsValid(trial = false) {
    const ids = trial
      ? [
          "trialTr0",
          "trialTr1",
          "trialB0",
          "trialB1",
          "trialBaseAdjust",
          "trialDownsample",
          "trialSmoothFactor",
          "trialPolynomialDegree",
        ]
      : [
          "tr0",
          "tr1",
          "b0",
          "b1",
          "baseAdjust",
          "downsample",
          "smoothFactor",
          "polynomialDegree",
        ];
    const inputs = ids.map((id) => $(id));
    if (
      inputs.some(
        (input) => {
          if (!input) return true;
          if (input.disabled) return false;
          return (
            input.value.trim() === "" ||
            !Number.isFinite(Number(input.value)) ||
            !input.checkValidity()
          );
        }
      )
    ) {
      return false;
    }
    const values = trial ? state.trialSettings : state.settings;
    return (
      values.trange_start < values.trange_end &&
      values.baseline_start < values.baseline_end &&
      values.downsample_factor >= 1 &&
      values.polynomial_degree >= 1
    );
  }

  function scheduleAlignAnalyze(delay = 280) {
    clearTimeout(alignAnalyzeTimer);
    if (
      !hasSession() ||
      !hasResults() ||
      !state.analysisChannels.length ||
      !processingFormIsValid(false)
    ) {
      return;
    }
    alignAnalyzeTimer = setTimeout(() => {
      alignAnalyzeTimer = null;
      runLiveAnalyze({ force: true }).catch((error) =>
        toast(String(error.message || error))
      );
    }, delay);
  }

  function scheduleTrialAnalyze(delay = 280) {
    clearTimeout(trialAnalyzeTimer);
    if (
      !hasSession() ||
      !Object.keys(state.trialResultsByChannel).length ||
      !state.trialAnalysisChannels.length ||
      state.selectedTrialNumbers?.length === 0 ||
      !processingFormIsValid(true)
    ) {
      return;
    }
    trialAnalyzeTimer = setTimeout(() => {
      trialAnalyzeTimer = null;
      runTrialAnalyze({ force: true }).catch((error) =>
        toast(String(error.message || error))
      );
    }, delay);
  }

  function resetAnalysisState() {
    clearTimeout(alignAnalyzeTimer);
    clearTimeout(trialAnalyzeTimer);
    alignAnalyzeTimer = null;
    trialAnalyzeTimer = null;
    alignRequestSequence += 1;
    trialRequestSequence += 1;
    state.resultsByChannel = {};
    state.filteredResultsByChannel = {};
    state.trialResultsByChannel = {};
    state.trialFilteredResultsByChannel = {};
    state.activeChannel = null;
    state.activeEpoc = null;
    state.trialChannel = null;
    state.trialEpoc = null;
    state.checkedTrialNumbers = null;
    state.selectedTrialNumbers = null;
    state.outcomeFilters = {};
    state.analysisChannels = [];
    state.trialAnalysisChannels = [];
    state.batchRunning = false;
    state.batchCancelled = false;
    if ($("trialStream")) $("trialStream").innerHTML = "";
    if ($("outcomeChips")) $("outcomeChips").innerHTML = "";
    clearCanvas($("alignTrace"));
    clearCanvas($("alignHeat"));
    clearCanvas($("trialTrace"));
    clearCanvas($("trialHeat"));
  }

  function channelSettingsPayload() {
    const payload = {};
    Object.entries(state.smoothByChannel).forEach(([channel, smoothFactor]) => {
      if (Number.isFinite(Number(smoothFactor))) {
        payload[channel] = { smooth_factor: Math.max(1, Number(smoothFactor)) };
      }
    });
    return payload;
  }

  function defaultSmoothForChannel(channel) {
    const detail = (state.session?.channel_details || []).find(
      (item) => item.key === channel
    );
    return detail?.default_smooth ?? 10;
  }

  function syncSmoothingControl() {
    if (!$("smoothFactor")) return;
    const result = state.resultsByChannel[state.activeChannel];
    const value =
      state.smoothByChannel[state.activeChannel] ??
      result?.settings?.smooth_factor ??
      defaultSmoothForChannel(state.activeChannel);
    $("smoothFactor").value = String(value);
  }

  function clearSessionUi() {
    state.path = null;
    state.session = null;
    resetAnalysisState();

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
    if ($("trialCalloutText")) {
      $("trialCalloutText").textContent =
        "Selections re-filter the displayed mean / heatmap using the shared service.";
    }
    $("trialCallout")?.classList.remove("callout-warn");
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
    fillSelect($("alignSession"), [], () => "", () => "");
    fillSelect($("trialChannel"), [], () => "", () => "");
    fillSelect($("trialEpoc"), [], () => "", () => "");
    fillSelect($("trialSession"), [], () => "", () => "");
    if ($("sessionMetadata"))
      $("sessionMetadata").textContent = "Open a session to inspect metadata.";
    setBadge();
    renderImportQueue();
    renderDataPage();
    renderBatchPage();
  }

  function clearCanvas(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function sourceLabel(source) {
    return source.session?.session_name || source.path?.split(/[\\/]/).pop() || "session";
  }

  function classifiedSourceFor(value) {
    return (state.session?.classified_sources || []).find(
      (source) => source.key === value || source.label === value
    );
  }

  function epocDisplayName(value) {
    return classifiedSourceFor(value)?.label || value || "epoc";
  }

  function resultDisplayTitle(result, suffix) {
    const fileName =
      result?.source_path?.split(/[\\/]/).pop() ||
      result?.session_name ||
      state.session?.source_path?.split(/[\\/]/).pop() ||
      state.session?.session_name ||
      "session";
    const parts = [fileName, epocDisplayName(result?.epoc), result?.channel];
    if (suffix) parts.push(suffix);
    return parts.filter(Boolean).join(" · ");
  }

  function rememberSource(path, session) {
    if (!path || !session) return;
    const existing = state.sources.find((source) => source.path === path);
    if (existing) existing.session = session;
    else state.sources.push({ path, session });
    renderSourceSelectors();
    renderImportQueue();
    renderBatchSelectors();
    renderBatchPage();
  }

  function renderImportQueue() {
    const list = $("importQueue");
    const count = $("importQueueCount");
    const meta = $("importQueueMeta");
    if (!list) return;
    list.innerHTML = "";
    if (count) count.textContent = String(state.sources.length);
    if (meta) {
      meta.textContent = state.sources.length
        ? "Click a session to analyze it · multi-select adds more files"
        : "No files loaded yet";
    }
    state.sources.forEach((source) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "import-row" + (source.path === state.path ? " active" : "");
      const marker = document.createElement("span");
      marker.className = "n";
      marker.textContent = source.path === state.path ? "●" : "○";
      const label = document.createElement("span");
      label.textContent = sourceLabel(source);
      const channels = document.createElement("span");
      channels.className = "n";
      channels.textContent = `${(source.session?.channels || []).length} ch`;
      row.append(marker, label, channels);
      row.title = source.path;
      row.addEventListener("click", async () => {
        if (source.path === state.path) {
          showView("align");
          return;
        }
        try {
          await activateSource(source.path, source.session);
        } catch (err) {
          toast(String(err.message || err));
        }
      });
      list.appendChild(row);
    });
    if (!state.sources.length) {
      const empty = document.createElement("div");
      empty.className = "quiet";
      empty.style.padding = "8px";
      empty.textContent = "Open one or more MAT files to populate this list.";
      list.appendChild(empty);
    }
  }

  async function activateSource(path, sessionSummary) {
    toast(`opening ${path.split(/[\\/]/).pop()}…`);
    let session = sessionSummary;
    let resolvedPath = path;
    if (!session) {
      const data = await api("POST", "/api/open", { path });
      resolvedPath = data.path || path;
      session = data.session;
    } else {
      // Ensure backend cache has this session as current.
      await api("POST", "/api/open", { path: resolvedPath });
    }
    resetAnalysisState();
    state.path = resolvedPath;
    rememberSource(resolvedPath, session);
    applySessionSummary(session, resolvedPath);
    const epocs = Object.keys(session.epocs || {});
    state.activeEpoc =
      epocs.find((e) => !["tick", "cam1"].includes(String(e).toLowerCase())) ||
      epocs[0] ||
      null;
    state.activeChannel = (session.channels || [])[0] || null;
    await runLiveAnalyze({ force: true });
    renderImportQueue();
    showView("align");
  }

  async function openManyPaths(paths) {
    const unique = [...new Set((paths || []).filter(Boolean))];
    if (!unique.length) return;
    toast(unique.length === 1 ? "opening…" : `opening ${unique.length} files…`);
    const data = await api("POST", "/api/inspect-paths", { paths: unique });
    const sources = data.sources || [];
    sources.forEach((source) => rememberSource(source.path, source.session));
    if (!sources.length) {
      const detail = (data.errors || []).map((e) => e.error || e).join("; ");
      throw new Error(detail || "no sessions could be opened");
    }
    const primary = sources[0];
    await activateSource(primary.path, primary.session);
    if ((data.errors || []).length) {
      toast(
        `Loaded ${sources.length}; ${data.errors.length} file(s) failed`
      );
    } else if (sources.length > 1) {
      toast(`Loaded ${sources.length} files · analyzing ${sourceLabel(primary)}`);
    }
  }

  async function uploadBrowserFiles(files) {
    const selected = Array.from(files || []).filter(
      (file) => file && (file.webkitRelativePath || file.name)
    );
    if (!selected.length) return [];
    const uploadId =
      globalThis.crypto?.randomUUID?.() ||
      `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const paths = [];
    for (let index = 0; index < selected.length; index += 1) {
      const file = selected[index];
      const relativePath = file.webkitRelativePath || file.name;
      const query = new URLSearchParams({
        upload_id: uploadId,
        relative_path: relativePath,
        final: index === selected.length - 1 ? "1" : "0",
      });
      const response = await fetch(`/api/upload?${query.toString()}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      let data;
      try {
        data = await response.json();
      } catch (_) {
        throw new Error(`Upload failed for ${file.name} (${response.status}).`);
      }
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `Upload failed for ${file.name}.`);
      }
      if (Array.isArray(data.paths)) paths.push(...data.paths);
    }
    return [...new Set(paths)];
  }

  function parsePathList(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw !== "string") return [];
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    } catch (_) {
      /* plain path string */
    }
    return raw ? [raw] : [];
  }

  function renderSourceSelectors() {
    const values = state.sources;
    for (const id of ["alignSession", "trialSession"]) {
      fillSelect($(id), values, sourceLabel, (source) => source.path);
      if ($(id) && state.path) $(id).value = state.path;
    }
  }

  function renderChannelSelector(containerId, values, selectedValues, onChange) {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    const selected = new Set(selectedValues || []);
    values.forEach((value) => {
      const label = document.createElement("label");
      label.className = "selector-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = value;
      input.checked = selected.has(value);
      input.addEventListener("change", () => {
        const next = new Set(selectedValues || []);
        if (input.checked) next.add(value);
        else next.delete(value);
        onChange(values.filter((item) => next.has(item)));
      });
      const text = document.createElement("span");
      text.textContent = value;
      label.append(input, text);
      container.appendChild(label);
    });
    if (!values.length) {
      container.innerHTML = '<span class="quiet">No channels available.</span>';
    }
  }

  function renderAnalysisChannelSelectors() {
    const channels = state.session?.channels || [];
    renderChannelSelector(
      "alignChannelSelectors",
      channels,
      state.analysisChannels,
      (next) => {
        state.analysisChannels = next;
        alignRequestSequence += 1;
        renderAnalysisChannelSelectors();
        scheduleAlignAnalyze();
      }
    );
    renderChannelSelector(
      "trialChannelSelectors",
      channels,
      state.trialAnalysisChannels,
      (next) => {
        state.trialAnalysisChannels = next;
        trialRequestSequence += 1;
        renderAnalysisChannelSelectors();
        scheduleTrialAnalyze();
      }
    );
  }

  function batchEpocChoices() {
    const names = new Set();
    state.sources.forEach((source) => {
      Object.keys(source.session?.epocs || {}).forEach((name) => names.add(name));
    });
    return Array.from(names).sort();
  }

  function batchChannelChoices() {
    const names = new Set();
    state.sources.forEach((source) => {
      (source.session?.channels || []).forEach((name) => names.add(name));
    });
    return Array.from(names).sort();
  }

  function batchEpocSelections(epocs, policy) {
    if (policy === "all") {
      return epocs.map((epoc) => ({ label: epoc, members: [epoc], mode: "all" }));
    }
    const groups = new Map();
    const selections = [];
    epocs.forEach((epoc) => {
      let base = null;
      let family = null;
      if (epoc.endsWith("1_") || epoc.endsWith("2_")) {
        base = epoc.slice(0, -2);
        family = "number_underscore";
      } else if (epoc.endsWith("A") || epoc.endsWith("C")) {
        base = epoc.slice(0, -1);
        family = "letter";
      }
      if (base === null) {
        selections.push({ label: epoc, members: [epoc], mode: "all" });
        return;
      }
      const key = `${base}\u0000${family}`;
      if (!groups.has(key)) groups.set(key, { base, members: [] });
      groups.get(key).members.push(epoc);
    });
    groups.forEach(({ base, members }) => {
      selections.push({
        label:
          policy === "prefer_left"
            ? `${base} (prefer A/1_)`
            : `${base} (prefer C/2_)`,
        members: members.sort(),
        mode: policy,
      });
    });
    return selections;
  }

  async function openKnownSource(path, target = "align") {
    if (!path || path === state.path) return;
    const raw = window.auroraBridge?.openSession
      ? await bridgeCall("openSession", path)
      : await api("POST", "/api/open", { path });
    const data = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (!data.ok) throw new Error(data.error || "open failed");
    resetAnalysisState();
    state.path = data.path;
    applySessionSummary(data.session, data.path);
    if (target === "trials") {
      await runTrialAnalyze({ force: true });
      showView("trials");
    } else {
      await runLiveAnalyze({ force: true });
      showView("align");
    }
  }

  function applySessionSummary(session, path) {
    state.session = session;
    state.path = path || state.path;
    rememberSource(state.path, session);
    syncSessionIsosbesticAvailability(session);
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
    if ($("sessionMetadata"))
      $("sessionMetadata").textContent = JSON.stringify(session.info || {}, null, 2);
    const epocNames = Object.keys(session.epocs || {});
    const classified = session.classified_sources || [];
    const channelChips = $("channelChips");
    if (channelChips) {
      channelChips.replaceChildren();
      const channels = session.channels || [];
      if (!channels.length) {
        const empty = document.createElement("span");
        empty.className = "quiet";
        empty.textContent = "No channels";
        channelChips.appendChild(empty);
      }
      channels.forEach((channel) => {
        const chip = document.createElement("span");
        chip.className = "chip on";
        chip.textContent = channel;
        channelChips.appendChild(chip);
      });
    }
    const epocChips = $("epocChips");
    if (epocChips) {
      epocChips.replaceChildren();
      const allEpocChips = [
        ...epocNames.map((value) => ({ value, label: value, classified: false })),
        ...classified.map((source) => ({
          value: source.key || source.label,
          label: source.label || source.key,
          classified: true,
        })),
      ];
      if (!allEpocChips.length) {
        const empty = document.createElement("span");
        empty.className = "quiet";
        empty.textContent = "No epocs";
        epocChips.appendChild(empty);
      }
      allEpocChips.forEach((epoc) => {
        const chip = document.createElement("span");
        chip.className = `chip ${epoc.classified ? "mag" : "on"}`;
        chip.textContent = epoc.label;
        if (epoc.classified) chip.title = `Derived source: ${epoc.value}`;
        epocChips.appendChild(chip);
      });
    }
    const trialEpocs = [
      ...epocNames.map((value) => ({ value, label: value })),
      ...classified.map((source) => ({
        value: source.key || source.label,
        label: source.label || source.key,
      })),
    ].filter(
      (item, index, items) =>
        items.findIndex((candidate) => candidate.value === item.value) === index
    );
    fillSelect($("alignEpoc"), epocNames, (e) => e, (e) => e);
    fillSelect($("trialEpoc"), trialEpocs, (e) => e.label, (e) => e.value);
    fillSelect(
      $("alignChannel"),
      session.channels || [],
      (c) => c,
      (c) => c
    );
    if (!state.activeEpoc || !epocNames.includes(state.activeEpoc)) {
      state.activeEpoc =
        epocNames.find((e) => !["tick", "cam1"].includes(String(e).toLowerCase())) ||
        epocNames[0] ||
        null;
    }
    if (!state.activeChannel || !(session.channels || []).includes(state.activeChannel)) {
      state.activeChannel = (session.channels || [])[0] || null;
    }
    if (!state.trialEpoc || !trialEpocs.some((item) => item.value === state.trialEpoc)) {
      state.trialEpoc = state.activeEpoc || trialEpocs[0]?.value || null;
    }
    if (!state.trialChannel || !(session.channels || []).includes(state.trialChannel)) {
      state.trialChannel = state.activeChannel;
    }
    if (!state.analysisChannels.length) {
      state.analysisChannels = [...(session.channels || [])];
    } else {
      state.analysisChannels = state.analysisChannels.filter((channel) =>
        (session.channels || []).includes(channel)
      );
    }
    if (!state.trialAnalysisChannels.length) {
      state.trialAnalysisChannels = [...(session.channels || [])];
    } else {
      state.trialAnalysisChannels = state.trialAnalysisChannels.filter((channel) =>
        (session.channels || []).includes(channel)
      );
    }
    const availableBatchEpocs = batchEpocChoices();
    const availableBatchChannels = batchChannelChoices();
    if (state.batchEpocs === null) {
      state.batchEpocs = availableBatchEpocs.includes(state.activeEpoc)
        ? [state.activeEpoc]
        : availableBatchEpocs.slice(0, 1);
    } else {
      state.batchEpocs = state.batchEpocs.filter((epoc) =>
        availableBatchEpocs.includes(epoc)
      );
    }
    if (state.batchChannels === null) {
      state.batchChannels = [...availableBatchChannels];
    } else {
      state.batchChannels = state.batchChannels.filter((channel) =>
        availableBatchChannels.includes(channel)
      );
    }
    (session.channel_details || []).forEach((detail) => {
      if (state.smoothByChannel[detail.key] == null) {
        state.smoothByChannel[detail.key] = detail.default_smooth;
      }
      if (state.trialSmoothByChannel[detail.key] == null) {
        state.trialSmoothByChannel[detail.key] = detail.default_smooth;
      }
    });
    if (state.activeEpoc) $("alignEpoc").value = state.activeEpoc;
    if (state.activeChannel) $("alignChannel").value = state.activeChannel;
    if (state.trialEpoc && $("trialEpoc")) $("trialEpoc").value = state.trialEpoc;
    renderSourceSelectors();
    renderAnalysisChannelSelectors();
    syncSmoothingControl();
    renderBatchSelectors();
    setBadge();
  }

  function setupAlignControls() {
    [
      "tr0",
      "tr1",
      "b0",
      "b1",
      "baseAdjust",
      "downsample",
      "smoothFactor",
      "polynomialDegree",
    ].forEach((id) =>
      $(id)?.addEventListener("input", () => {
        readSettingsFromForm();
        alignRequestSequence += 1;
        scheduleAlignAnalyze();
      })
    );
    ["useIsosbestic", "plotSmooth", "applyBaseline"].forEach((id) =>
      $(id)?.addEventListener("change", () => {
        readSettingsFromForm();
        alignRequestSequence += 1;
        scheduleAlignAnalyze();
      })
    );
    $("alignSession")?.addEventListener("change", async () => {
      try {
        await openKnownSource($("alignSession").value, "align");
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("alignAllChannels")?.addEventListener("click", () => {
      state.analysisChannels = [...(state.session?.channels || [])];
      alignRequestSequence += 1;
      renderAnalysisChannelSelectors();
      scheduleAlignAnalyze(0);
    });
    $("alignNoChannels")?.addEventListener("click", () => {
      state.analysisChannels = [];
      alignRequestSequence += 1;
      renderAnalysisChannelSelectors();
    });
    $("alignChannel").addEventListener("change", () => {
      readSettingsFromForm();
      state.activeChannel = $("alignChannel").value;
      syncSmoothingControl();
      renderAlign();
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
      $("b0").value = -3;
      $("b1").value = -1;
      $("baseAdjust").value = -2;
      $("downsample").value = 10;
      $("polynomialDegree").value = 1;
      $("useIsosbestic").checked = true;
      if (state.activeChannel) {
        const defaultSmooth = defaultSmoothForChannel(state.activeChannel);
        state.smoothByChannel[state.activeChannel] = defaultSmooth;
        $("smoothFactor").value = defaultSmooth;
      }
      $("plotSmooth").checked = true;
      $("applyBaseline").checked = true;
      readSettingsFromForm();
      alignRequestSequence += 1;
      toast("defaults restored");
      scheduleAlignAnalyze(0);
    });
    $("alignExportCsv")?.addEventListener("click", () =>
      exportLive({
        selectedOnly: false,
        exportCsv: true,
        exportFigure: false,
        channels: [...state.analysisChannels],
      })
    );
    $("alignExportFig")?.addEventListener("click", () =>
      exportLive({
        selectedOnly: false,
        exportCsv: false,
        exportFigure: true,
        channels: [...state.analysisChannels],
      })
    );
  }

  async function runLiveAnalyze(opts = {}) {
    if (!state.path) throw new Error("No session open");
    clearTimeout(alignAnalyzeTimer);
    alignAnalyzeTimer = null;
    readSettingsFromForm();
    if (!processingFormIsValid(false)) {
      throw new Error("Check the processing window and numeric settings");
    }
    const epoc =
      state.activeEpoc ||
      $("alignEpoc").value ||
      Object.keys(state.session?.epocs || {})[0];
    if (!epoc) throw new Error("No epoc available");
    toast("analyzing…");
    if (window.auroraBridge?.setStatus) window.auroraBridge.setStatus("Analyzing…");
    const channels = [...state.analysisChannels];
    if (!channels.length) throw new Error("Select at least one channel to analyze");
    const requestId = ++alignRequestSequence;
    let data;
    try {
      data = await nativeOrFetchAnalyze({
        path: state.path,
        epoc,
        channels,
        settings: settingsPayload(),
        channel_settings: channelSettingsPayload(),
        force: !!opts.force,
      });
    } catch (error) {
      if (requestId !== alignRequestSequence) return null;
      throw error;
    }
    if (requestId !== alignRequestSequence) return null;
    applyAnalyzePayload(data);
    toast(`analyzed ${epocDisplayName(epoc)}`);
    return data;
  }

  function applyAnalyzePayload(data) {
    state.path = data.path || state.path;
    if (data.session) applySessionSummary(data.session, state.path);
    state.activeEpoc = data.epoc || state.activeEpoc;
    const fullResults = data.all_results || data.results || [];
    state.resultsByChannel = {};
    fullResults.forEach((r) => {
      state.resultsByChannel[r.channel] = r;
      if (r.settings?.smooth_factor != null) {
        state.smoothByChannel[r.channel] = r.settings.smooth_factor;
      }
    });
    state.filteredResultsByChannel = {};
    (data.results || []).forEach((r) => {
      state.filteredResultsByChannel[r.channel] = r;
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
    if (state.activeChannel) {
      $("alignChannel").value = state.activeChannel;
    }
    syncSmoothingControl();
    if (state.activeEpoc && $("alignEpoc")) $("alignEpoc").value = state.activeEpoc;
    renderAlign();
    renderDataPage();
    renderBatchPage();
    setBadge();
  }

  function correctionSummary(result) {
    if (result.settings?.use_isosbestic === false) return "signal only";
    return `405 fit · degree ${result.settings?.polynomial_degree ?? 1}`;
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
    const plotIdentity = resultDisplayTitle(result);
    window.AuroraPlots.drawGlowTrace($("alignTrace"), {
      times,
      mean,
      sem,
      color: "#00f5d4",
      title: `${plotIdentity} · Mean ± SEM`,
      baseline: result.settings?.baseline_per || [
        state.settings.baseline_start,
        state.settings.baseline_end,
      ],
    });
    window.AuroraPlots.drawHeat($("alignHeat"), {
      times,
      matrix: z,
      trialNumbers: result.trial_numbers || [],
      title: `${plotIdentity} · Z-score heatmap`,
    });
    if (mean.length) {
      const pk = window.AuroraPlots.peakLatency(times, mean);
      $("rPeak").textContent = pk.peak.toFixed(2) + " z";
      $("rLat").textContent = pk.lat.toFixed(2) + "s";
      $("rN").textContent = String(result.num_trials || z.length);
    }
    $("alignTag").textContent = epocDisplayName(result.epoc);
    $("alignSummary").textContent =
      `${resultDisplayTitle(result)} · ` +
      `${result.num_trials || 0} trials · ${correctionSummary(result)}`;
    $("hudTrials").textContent = String(result.num_trials || 0);
    const notices = [];
    const dropped = result.dropped_edge_trials || [];
    if (dropped.length) {
      notices.push(
        `${dropped.length} incomplete edge trial${dropped.length === 1 ? "" : "s"} dropped (${dropped.join(", ")})`
      );
    }
    if (result.num_artifacts) {
      notices.push(
        `${result.num_artifacts} artifact trial${result.num_artifacts === 1 ? "" : "s"} removed`
      );
    }
    $("alignCalloutText").textContent = notices.length
      ? notices.join(" · ")
      : "Incomplete edge trials are dropped, not clipped (MATLAB-faithful).";
    $("alignCallout").classList.toggle("callout-warn", notices.length > 0);
  }

  function trialExportChannels() {
    const channel = $("trialChannel")?.value || state.trialChannel;
    return channel ? [channel] : [];
  }

  function setupTrials() {
    [
      "trialTr0",
      "trialTr1",
      "trialB0",
      "trialB1",
      "trialBaseAdjust",
      "trialDownsample",
      "trialSmoothFactor",
      "trialPolynomialDegree",
    ].forEach((id) =>
      $(id)?.addEventListener("input", () => {
        readTrialSettingsFromForm();
        trialRequestSequence += 1;
        scheduleTrialAnalyze();
      })
    );
    ["trialUseIsosbestic", "trialPlotSmooth", "trialApplyBaseline"].forEach(
      (id) =>
        $(id)?.addEventListener("change", () => {
          readTrialSettingsFromForm();
          trialRequestSequence += 1;
          scheduleTrialAnalyze();
        })
    );
    $("trialSession")?.addEventListener("change", async () => {
      try {
        await openKnownSource($("trialSession").value, "trials");
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("trialEpoc")?.addEventListener("change", async () => {
      state.trialEpoc = $("trialEpoc").value;
      state.selectedTrialNumbers = null;
      state.checkedTrialNumbers = null;
      state.outcomeFilters = {};
      if (!hasSession()) return;
      try {
        await runTrialAnalyze({ force: true, resetSelection: true });
      } catch (error) {
        toast(String(error.message || error));
      }
    });
    $("trialAllChannels")?.addEventListener("click", () => {
      state.trialAnalysisChannels = [...(state.session?.channels || [])];
      trialRequestSequence += 1;
      renderAnalysisChannelSelectors();
      scheduleTrialAnalyze(0);
    });
    $("trialNoChannels")?.addEventListener("click", () => {
      state.trialAnalysisChannels = [];
      trialRequestSequence += 1;
      renderAnalysisChannelSelectors();
    });
    $("trialLoad")?.addEventListener("click", async () => {
      try {
        await runTrialAnalyze({ force: true, resetSelection: true });
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("trialSearch").addEventListener("input", filterTrials);
    $("selAll").addEventListener("click", () => setChecks(true, true));
    $("selNone").addEventListener("click", () => setChecks(false, false));
    $("selInvert").addEventListener("click", invertVisible);
    $("trialChannel").addEventListener("change", () => {
      readTrialSettingsFromForm();
      state.trialChannel = $("trialChannel").value;
      const value =
        state.trialSmoothByChannel[state.trialChannel] ??
        defaultSmoothForChannel(state.trialChannel);
      if ($("trialSmoothFactor")) $("trialSmoothFactor").value = value;
      populateTrialStreamFromLive();
      renderTrials();
    });
    $("trialMode").addEventListener("change", renderTrials);
    $("trialExportCsv")?.addEventListener("click", () =>
      exportLive({
        exportCsv: true,
        exportFigure: false,
        selectedOnly: true,
        channels: trialExportChannels(),
        epoc: state.trialEpoc,
        settings: trialSettingsPayload(),
        channelSettings: trialChannelSettingsPayload(),
      })
    );
    $("trialExportFig")?.addEventListener("click", () =>
      exportLive({
        exportCsv: false,
        exportFigure: true,
        selectedOnly: true,
        channels: trialExportChannels(),
        epoc: state.trialEpoc,
        settings: trialSettingsPayload(),
        channelSettings: trialChannelSettingsPayload(),
      })
    );
  }

  async function runTrialAnalyze(opts = {}) {
    if (!state.path) throw new Error("No session open");
    clearTimeout(trialAnalyzeTimer);
    trialAnalyzeTimer = null;
    readTrialSettingsFromForm();
    if (!processingFormIsValid(true)) {
      throw new Error("Check the Trial Explorer processing settings");
    }
    const epoc = state.trialEpoc || $("trialEpoc")?.value;
    if (!epoc) throw new Error("Select a Trial Explorer epoc");
    if (!state.trialAnalysisChannels.length) {
      throw new Error("Select at least one Trial Explorer channel");
    }
    if (opts.resetSelection) {
      state.selectedTrialNumbers = null;
      state.checkedTrialNumbers = null;
      state.outcomeFilters = {};
    }
    const requestId = ++trialRequestSequence;
    let data;
    try {
      data = await nativeOrFetchAnalyze({
        path: state.path,
        epoc,
        channels: [...state.trialAnalysisChannels],
        settings: trialSettingsPayload(),
        channel_settings: trialChannelSettingsPayload(),
        force: !!opts.force,
        trial_numbers:
          state.selectedTrialNumbers === null
            ? undefined
            : state.selectedTrialNumbers,
      });
    } catch (error) {
      if (requestId !== trialRequestSequence) return null;
      throw error;
    }
    if (requestId !== trialRequestSequence) return null;
    state.trialEpoc = data.epoc || epoc;
    const fullResults = data.all_results || data.results || [];
    state.trialResultsByChannel = {};
    fullResults.forEach((result) => {
      state.trialResultsByChannel[result.channel] = result;
      if (result.settings?.smooth_factor != null) {
        state.trialSmoothByChannel[result.channel] =
          result.settings.smooth_factor;
      }
    });
    state.trialFilteredResultsByChannel = {};
    (data.results || []).forEach((result) => {
      state.trialFilteredResultsByChannel[result.channel] = result;
    });
    const keys = Object.keys(state.trialResultsByChannel);
    if (!keys.length) throw new Error("Trial analysis returned no channels");
    if (!state.trialChannel || !keys.includes(state.trialChannel)) {
      state.trialChannel = keys[0];
    }
    fillSelect($("trialChannel"), keys, (channel) => channel, (channel) => channel);
    $("trialChannel").value = state.trialChannel;
    populateTrialStreamFromLive();
    renderTrials();
    setBadge();
    toast(`loaded trials for ${epocDisplayName(state.trialEpoc)}`);
    return data;
  }

  function populateTrialStreamFromLive() {
    const result =
      state.trialResultsByChannel[state.trialChannel] ||
      Object.values(state.trialResultsByChannel)[0];
    if (!result) return;
    const list = $("trialStream");
    const previousSelection =
      state.checkedTrialNumbers === null
        ? null
        : new Set(state.checkedTrialNumbers);
    const previousFilters = { ...state.outcomeFilters };
    list.replaceChildren();
    const resultValues = Object.values(state.trialResultsByChannel);
    const common = resultValues.reduce((shared, item, index) => {
      const current = new Set(item.trial_numbers || []);
      return index === 0
        ? current
        : new Set(Array.from(shared).filter((number) => current.has(number)));
    }, new Set());
    const labelsByNumber = new Map(
      (result.trial_numbers || []).map((number, index) => [
        number,
        (result.trial_labels || [])[index] || "trial",
      ])
    );
    const timesByNumber = new Map(
      (result.trial_numbers || []).map((number, index) => [
        number,
        Number((result.trial_times || [])[index]),
      ])
    );
    const numbers = Array.from(common).sort((a, b) => a - b);
    const labels = numbers.map((number) => labelsByNumber.get(number) || "trial");
    const presentOutcomes = new Set();
    const outcomeCounts = new Map();
    numbers.forEach((num, i) => {
      const label = labels[i] || "trial";
      presentOutcomes.add(label);
      outcomeCounts.set(label, (outcomeCounts.get(label) || 0) + 1);
      const row = document.createElement("label");
      row.className = "trial-row";
      row.dataset.outcome = label || "unclassified";
      row.dataset.number = String(num);
      const checked = previousSelection === null || previousSelection.has(Number(num));
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = checked;
      checkbox.dataset.number = String(num);
      const labelText = document.createElement("span");
      labelText.className = "trial-label";
      labelText.textContent = label || "trial";
      const trialNumber = document.createElement("span");
      trialNumber.className = "n trial-number";
      trialNumber.textContent = `T${String(num).padStart(3, "0")}`;
      const trialTime = document.createElement("span");
      trialTime.className = "n trial-time";
      const onset = timesByNumber.get(num);
      trialTime.textContent = Number.isFinite(onset) ? `${onset.toFixed(3)} s` : "—";
      row.append(checkbox, trialNumber, labelText, trialTime);
      checkbox.addEventListener("change", async () => {
        await refreshTrialSelection();
      });
      list.appendChild(row);
    });

    const chips = $("outcomeChips");
    chips.replaceChildren();
    state.outcomeFilters = {};
    Array.from(presentOutcomes).forEach((label) => {
      state.outcomeFilters[label] = previousFilters[label] !== false;
      const b = document.createElement("button");
      b.type = "button";
      b.className = `chip-btn ${state.outcomeFilters[label] ? "on" : ""}`;
      b.textContent = `${label} (${outcomeCounts.get(label) || 0})`;
      b.dataset.outcome = label;
      b.addEventListener("click", async () => {
        state.outcomeFilters[label] = !state.outcomeFilters[label];
        b.classList.toggle("on", state.outcomeFilters[label]);
        filterTrials();
        await refreshTrialSelection();
      });
      chips.appendChild(b);
    });

    fillSelect(
      $("trialChannel"),
      Object.keys(state.trialResultsByChannel),
      (c) => c,
      (c) => c
    );
    if (state.trialChannel) $("trialChannel").value = state.trialChannel;
    $("trialSub").textContent = state.trialEpoc
      ? `${epocDisplayName(state.trialEpoc)} · ${numbers.length} analyzed trials`
      : "trial list";
    filterTrials();
    syncSelected();
  }

  function filterTrials() {
    const q = $("trialSearch").value.trim().toLowerCase();
    document.querySelectorAll("#trialStream .trial-row").forEach((row) => {
      const o = row.dataset.outcome;
      const show =
        state.outcomeFilters[o] !== false &&
        (!q || row.textContent.toLowerCase().includes(q));
      row.classList.toggle("hidden", !show);
      row.style.display = show ? "" : "none";
    });
  }

  function syncSelected() {
    const rows = document.querySelectorAll("#trialStream .trial-row");
    const checkedRows = Array.from(rows).filter((row) => {
      const box = row.querySelector('input[type="checkbox"]');
      return !!box?.checked;
    });
    state.checkedTrialNumbers = checkedRows
      .map((row) => Number(row.dataset.number))
      .filter((n) => Number.isFinite(n));
    const numbers = checkedRows
      .filter((row) => {
        return state.outcomeFilters[row.dataset.outcome] !== false;
      })
      .map((row) => Number(row.dataset.number))
      .filter((n) => Number.isFinite(n));
    state.selectedTrialNumbers = numbers;
    $("selLabel").textContent = `${numbers.length} selected`;
    return numbers;
  }

  async function refreshTrialSelection() {
    const numbers = syncSelected();
    if (!numbers.length) {
      clearTimeout(trialAnalyzeTimer);
      trialAnalyzeTimer = null;
      trialRequestSequence += 1;
      state.trialFilteredResultsByChannel = {};
      renderTrials();
      toast("select at least one trial");
      return;
    }
    try {
      await runTrialAnalyze();
    } catch (err) {
      toast(String(err.message || err));
      renderTrials();
    }
  }

  async function setChecks(checked, visibleOnly) {
    document.querySelectorAll("#trialStream .trial-row").forEach((row) => {
      if (visibleOnly && (row.style.display === "none" || row.classList.contains("hidden"))) {
        return;
      }
      const n = row.querySelector("input");
      if (n) n.checked = checked;
    });
    await refreshTrialSelection();
  }

  async function invertVisible() {
    document.querySelectorAll("#trialStream .trial-row").forEach((row) => {
      if (row.style.display === "none" || row.classList.contains("hidden")) return;
      const n = row.querySelector("input");
      if (n) n.checked = !n.checked;
    });
    await refreshTrialSelection();
  }

  function renderTrialStatus(fullResult, filteredResult) {
    const source = classifiedSourceFor(state.trialEpoc);
    const allSources = (state.session?.classified_sources || [])
      .map((item) => item.label || item.key)
      .filter(Boolean);
    const total = fullResult?.num_trials || fullResult?.z?.length || 0;
    const selected = filteredResult?.num_trials || filteredResult?.z?.length || 0;
    const notices = [`${selected} of ${total} analyzed trials selected`];
    const counts = new Map();
    (fullResult?.trial_labels || []).forEach((label) => {
      if (!label) return;
      counts.set(label, (counts.get(label) || 0) + 1);
    });
    if (!counts.size && source?.trial_type_counts) {
      Object.entries(source.trial_type_counts).forEach(([label, count]) =>
        counts.set(label, Number(count))
      );
    }
    if (counts.size) {
      notices.push(
        `types: ${Array.from(counts.entries())
          .map(([label, count]) => `${label} ${count}`)
          .join(", ")}`
      );
    } else if (allSources.length) {
      notices.push(`classified sources available: ${allSources.join(", ")}`);
    }
    const dropped = fullResult?.dropped_edge_trials || [];
    if (dropped.length) {
      notices.push(`${dropped.length} incomplete edge trial(s) dropped`);
    }
    if (fullResult?.num_artifacts) {
      notices.push(`${fullResult.num_artifacts} artifact trial(s) removed`);
    }
    (source?.warnings || []).forEach((warning) => notices.push(`warning: ${warning}`));
    if ($("trialCalloutText")) $("trialCalloutText").textContent = notices.join(" · ");
    const warns = dropped.length > 0 || !!fullResult?.num_artifacts || !!source?.warnings?.length;
    $("trialCallout")?.classList.toggle("callout-warn", warns);
  }

  function renderTrials() {
    const key = $("trialChannel")?.value || state.trialChannel;
    const fullResult =
      state.trialResultsByChannel[key] ||
      Object.values(state.trialResultsByChannel)[0];
    const result = state.trialFilteredResultsByChannel[key];
    if (!fullResult || !result) {
      const emptyMessage = state.selectedTrialNumbers?.length === 0
        ? "Select at least one trial"
        : "Analyze to populate trials";
      const title = fullResult
        ? resultDisplayTitle(fullResult)
        : `${state.session?.source_path?.split(/[\\/]/).pop() || state.session?.session_name || "session"} · ${epocDisplayName(state.trialEpoc)}`;
      window.AuroraPlots.drawGlowTrace($("trialTrace"), {
        times: [],
        mean: [],
        title: `${title} · Mean ± SEM`,
        emptyMessage,
      });
      window.AuroraPlots.drawHeat($("trialHeat"), {
        times: [],
        matrix: [],
        title: `${title} · Z-score heatmap`,
        emptyMessage,
      });
      $("trialSummary").textContent = !hasSession()
        ? "Open a session first"
        : state.selectedTrialNumbers?.length === 0
          ? "Select at least one trial"
          : "Analyze to populate trials";
      renderTrialStatus(fullResult, null);
      return;
    }
    const mode = $("trialMode").value;
    const times = Float64Array.from(result.times || []);
    const mean = Float64Array.from(result.mean || []);
    const sem = Float64Array.from(result.sem || []);
    const z = (result.z || []).map((row) => Float64Array.from(row));
    const plotIdentity = resultDisplayTitle(result);
    window.AuroraPlots.drawGlowTrace($("trialTrace"), {
      times,
      mean,
      sem: mode === "mean" ? sem : null,
      individuals: mode === "individual" ? z : null,
      color: "#00f5d4",
      title: `${plotIdentity} · ${mode === "mean" ? "Mean ± SEM" : "Individual trials"}`,
      baseline: result.settings?.baseline_per || [
        state.trialSettings.baseline_start,
        state.trialSettings.baseline_end,
      ],
    });
    window.AuroraPlots.drawHeat($("trialHeat"), {
      times,
      matrix: z,
      trialNumbers: result.trial_numbers || [],
      title: `${plotIdentity} · Z-score heatmap`,
    });
    $("trialSummary").textContent =
      `${resultDisplayTitle(result)} · ` +
      `${result.num_trials || z.length} trials · ${correctionSummary(result)}`;
    renderTrialStatus(fullResult, result);
  }

  function sessionEpocChoices() {
    return batchEpocChoices();
  }

  function renderBatchSelector(containerId, values, selectedValues, stateKey) {
    const container = $(containerId);
    if (!container) return;
    container.innerHTML = "";
    if (!values.length) {
      const empty = document.createElement("span");
      empty.className = "quiet";
      empty.textContent = "No options available.";
      container.appendChild(empty);
      return;
    }
    const selected = new Set(selectedValues || []);
    values.forEach((value) => {
      const label = document.createElement("label");
      label.className = "selector-option";
      label.title = value;
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = value;
      input.checked = selected.has(value);
      input.disabled = state.batchRunning;
      const text = document.createElement("span");
      text.textContent = value;
      input.addEventListener("change", () => {
        const next = new Set(state[stateKey] || []);
        if (input.checked) next.add(value);
        else next.delete(value);
        state[stateKey] = values.filter((item) => next.has(item));
        renderBatchPage();
      });
      label.append(input, text);
      container.appendChild(label);
    });
  }

  function renderBatchSelectors() {
    renderBatchSelector(
      "batchEpocSelectors",
      batchEpocChoices(),
      state.batchEpocs,
      "batchEpocs"
    );
    renderBatchSelector(
      "batchChannelSelectors",
      batchChannelChoices(),
      state.batchChannels,
      "batchChannels"
    );
    for (const id of [
      "batchAllEpocs",
      "batchNoEpocs",
      "batchLeftEpocs",
      "batchRightEpocs",
      "batchAllChannels",
      "batchNoChannels",
    ]) {
      if ($(id)) $(id).disabled = !state.sources.length || state.batchRunning;
    }
  }

  function setBatchChoices(key, values) {
    state[key] = [...values];
    renderBatchSelectors();
    renderBatchPage();
  }

  function setupBatch() {
    $("launchBatch").addEventListener("click", exportBatchSelection);
    $("abortBatch").addEventListener("click", () => {
      if (!state.batchRunning) return;
      state.batchCancelled = true;
      $("abortBatch").disabled = true;
      setBatch(
        Number.parseInt($("batchPct").textContent, 10) || 0,
        "cancelling after current epoc…",
        "CANCEL"
      );
    });
    $("batchAllEpocs").addEventListener("click", () =>
      setBatchChoices("batchEpocs", sessionEpocChoices())
    );
    $("batchNoEpocs").addEventListener("click", () =>
      setBatchChoices("batchEpocs", [])
    );
    $("batchAllChannels").addEventListener("click", () =>
      setBatchChoices("batchChannels", batchChannelChoices())
    );
    $("batchNoChannels").addEventListener("click", () =>
      setBatchChoices("batchChannels", [])
    );
    $("batchLeftEpocs")?.addEventListener("click", () =>
      setBatchChoices(
        "batchEpocs",
        batchEpocChoices().filter(
          (name) => name.endsWith("A") || name.endsWith("1_")
        )
      )
    );
    $("batchRightEpocs")?.addEventListener("click", () =>
      setBatchChoices(
        "batchEpocs",
        batchEpocChoices().filter(
          (name) => name.endsWith("C") || name.endsWith("2_")
        )
      )
    );
    $("batchAddFiles")?.addEventListener("click", () =>
      addBatchSourcesFromDialog("selectMatFiles")
    );
    $("batchAddFolder")?.addEventListener("click", () =>
      addBatchSourcesFromDialog("selectDataFolder")
    );
    $("batchAddTank")?.addEventListener("click", () =>
      addBatchSourcesFromDialog("selectTdtTank")
    );
    $("batchClearSources")?.addEventListener("click", () => {
      state.sources = [];
      state.batchEpocs = [];
      state.batchChannels = [];
      state.batchOutcomes = [];
      renderSourceSelectors();
      renderBatchSelectors();
      renderBatchPage();
    });
    $("chooseExportDir")?.addEventListener("click", chooseExportDestination);
    $("exportDir")?.addEventListener("input", () => {
      state.outputDir = $("exportDir").value.trim();
    });
    $("expCsv")?.addEventListener("change", renderBatchPage);
    $("expFig")?.addEventListener("change", () => {
      $("figFormat").disabled = !$("expFig").checked;
      renderBatchPage();
    });
    $("figFormat").disabled = !$("expFig")?.checked;
    ["batchMatFileInput", "batchFolderInput", "batchTankInput"].forEach((id) => {
      $(id)?.addEventListener("change", async () => {
        const input = $(id);
        const files = Array.from(input?.files || []);
        if (!files.length || window.auroraBridge) return;
        try {
          toast(`uploading ${files.length} batch file(s)…`);
          const paths = await uploadBrowserFiles(files);
          if (!paths.length) throw new Error("No supported data sources were found.");
          await addBatchPaths(paths);
        } catch (err) {
          toast(String(err.message || err));
        }
      });
    });
    $("abortBatch").disabled = true;
    renderBatchSelectors();
    renderBatchPage();
  }

  async function addBatchSourcesFromDialog(method) {
    if (!window.auroraBridge?.[method]) {
      const inputId = {
        selectMatFiles: "batchMatFileInput",
        selectDataFolder: "batchFolderInput",
        selectTdtTank: "batchTankInput",
      }[method];
      const input = inputId ? $(inputId) : null;
      if (input) {
        input.value = "";
        input.click();
        return;
      }
      toast("This browser does not support the batch picker.");
      return;
    }
    try {
      const raw = await bridgeCall(method);
      const paths = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!paths?.length) return;
      await addBatchPaths(paths);
    } catch (err) {
      toast(String(err.message || err));
    }
  }

  async function addBatchPaths(paths) {
    const data = await api("POST", "/api/inspect-paths", { paths });
      (data.sources || []).forEach((source) =>
        rememberSource(source.path, source.session)
      );
      const epocs = batchEpocChoices();
      const channels = batchChannelChoices();
      state.batchEpocs = epocs;
      state.batchChannels = channels;
      renderSourceSelectors();
      renderBatchSelectors();
      renderBatchPage();
      if (data.errors?.length) {
        toast(
          `Added ${data.sources.length}; ${data.errors.length} source(s) could not load`
        );
      } else {
        toast(`Added ${data.sources.length} data source(s)`);
      }
  }

  function renderDataPage() {
    const openBtn = $("openSessionBtn");
    const closeBtn = $("closeSessionBtn");
    const page = $("page-data");
    if (page) page.classList.toggle("empty-mode", !hasSession());
    if (hasSession()) {
      openBtn.textContent = "Add MAT files";
      closeBtn.disabled = false;
      $("dataHint").textContent =
        "Multi-select MAT files (⌘/Ctrl-click) or TDT tanks/blocks. Click a session in Imported sessions to switch analysis focus.";
      $("dataLede").textContent =
        state.sources.length > 1
          ? `${state.sources.length} sessions imported. Active session ready on Align / Trials / Batch.`
          : "Session ready. Adjust processing on Align, filter trials, then export.";
    } else {
      openBtn.textContent = "Open MAT files";
      closeBtn.disabled = true;
      $("dataHint").textContent =
        "Multi-select MAT files or TDT tank/block folders. A tank expands to every nested block.";
      $("dataLede").textContent =
        "Open one or more MATLAB exports or TDT tanks/blocks, then analyze with the shared backend.";
    }
    renderImportQueue();
  }

  function renderBatchPage() {
    const body = $("batchList");
    if (!body) return;
    if (state.sources.length) {
      const selectedChannels = state.batchChannels || [];
      const selectedEpocs = state.batchEpocs || [];
      body.replaceChildren();
      state.sources.forEach((source) => {
        const row = document.createElement("tr");
        const sourceCell = document.createElement("td");
        sourceCell.title = source.path || "";
        sourceCell.textContent = sourceLabel(source);
        const channelCell = document.createElement("td");
        channelCell.textContent = String((source.session?.channels || []).length);
        const epocCell = document.createElement("td");
        epocCell.textContent = String(Object.keys(source.session?.epocs || {}).length);
        row.append(sourceCell, channelCell, epocCell);
        body.appendChild(row);
      });
      const hasOutputs = !!$("expCsv")?.checked || !!$("expFig")?.checked;
      const ready =
        selectedChannels.length > 0 &&
        selectedEpocs.length > 0 &&
        hasOutputs &&
        !state.batchRunning;
      $("batchSessionDetail").textContent = state.batchRunning
        ? "Exporting the selected epoc × channel combinations."
        : ready
          ? "Ready to analyze and export the selected combinations."
          : "Choose at least one epoc, one channel, and one output type.";
      $("mChannels").textContent = String(selectedChannels.length || "—");
      $("mTrials").textContent = String(state.sources.length);
      $("mEpoc").textContent = String(selectedEpocs.length || "—");
      $("mMode").textContent = state.batchRunning
        ? "running"
        : ready
          ? "ready"
          : "select";
      $("launchBatch").textContent = state.batchRunning
        ? "Exporting…"
        : "Export selection";
      $("launchBatch").disabled = !ready;
      $("abortBatch").disabled = !state.batchRunning || state.batchCancelled;
    } else {
      body.replaceChildren();
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 3;
      cell.textContent = "No data sources added";
      row.appendChild(cell);
      body.appendChild(row);
      $("batchSessionDetail").textContent =
        "Add MAT files, a mixed-data folder, or a TDT tank.";
      $("mChannels").textContent = "—";
      $("mTrials").textContent = "—";
      $("mEpoc").textContent = "—";
      $("mMode").textContent = "idle";
      $("launchBatch").textContent = "Export selection";
      $("launchBatch").disabled = true;
      $("abortBatch").disabled = true;
      renderBatchSelectors();
    }
    renderBatchResults();
  }

  function renderBatchResults() {
    const body = $("batchResults");
    if (!body) return;
    body.replaceChildren();
    if (!state.batchOutcomes.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.className = "quiet";
      cell.textContent = "No batch results yet";
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    state.batchOutcomes.forEach((outcome) => {
      const row = document.createElement("tr");
      const statusCell = document.createElement("td");
      const status = document.createElement("span");
      status.className = `batch-result-status ${outcome.status}`;
      status.textContent = outcome.status;
      statusCell.appendChild(status);
      const sourceCell = document.createElement("td");
      sourceCell.textContent = outcome.source || "—";
      sourceCell.title = outcome.inputPath || outcome.source || "";
      const epocCell = document.createElement("td");
      epocCell.textContent = outcome.epoc || "—";
      const channelsCell = document.createElement("td");
      channelsCell.textContent = (outcome.channels || []).join(", ") || "—";
      const detailCell = document.createElement("td");
      detailCell.textContent = outcome.detail || "—";
      detailCell.title = outcome.paths?.join("\n") || outcome.detail || "";
      row.append(statusCell, sourceCell, epocCell, channelsCell, detailCell);
      body.appendChild(row);
    });
  }

  function appendBatchOutcomes(data) {
    (data.exports || []).forEach((item) => {
      const paths = [item.csv, item.figure].filter(Boolean);
      const kinds = [item.csv ? "CSV" : "", item.figure ? "figure" : ""].filter(Boolean);
      state.batchOutcomes.push({
        status: "exported",
        source: item.session,
        epoc: item.epoc,
        channels: item.channel ? [item.channel] : [],
        detail: `${kinds.join(" + ")} written`,
        paths,
      });
    });
    for (const [key, status] of [["skipped", "skipped"], ["errors", "failed"]]) {
      (data[key] || []).forEach((item) => {
        state.batchOutcomes.push({
          status,
          source: item.session || item.input_path?.split(/[\\/]/).pop(),
          inputPath: item.input_path,
          epoc: item.epoc,
          channels: item.channels || [],
          detail: item.reason || "No reason reported",
        });
      });
    }
    renderBatchResults();
  }

  function setBatch(pct, detail, status) {
    $("batchPct").textContent = pct + "%";
    $("batchDetail").textContent = detail;
    $("batchStatus").textContent = status;
    if ($("batchBar")) $("batchBar").style.width = pct + "%";
  }

  async function chooseExportDestination() {
    let outputDir = state.outputDir || $("exportDir")?.value.trim() || "";
    try {
      if (window.auroraBridge?.chooseExportDir) {
        outputDir = await bridgeCall("chooseExportDir", outputDir);
      } else {
        outputDir = prompt("Export folder path:", outputDir) || "";
      }
    } catch (_) {
      outputDir = prompt("Export folder path:", outputDir) || "";
    }
    if (outputDir) {
      state.outputDir = outputDir;
      if ($("exportDir")) $("exportDir").value = outputDir;
      toast("export destination updated");
    }
    return outputDir;
  }

  async function exportBatchSelection() {
    const epocs = [...(state.batchEpocs || [])];
    const channels = [...(state.batchChannels || [])];
    const exportCsv = !!$("expCsv")?.checked;
    const exportFigure = !!$("expFig")?.checked;
    if (!state.sources.length) {
      toast("add at least one batch data source");
      return;
    }
    if (!epocs.length || !channels.length) {
      toast("choose at least one epoc and one channel");
      return;
    }
    if (!exportCsv && !exportFigure) {
      toast("choose CSV files and/or Figures");
      return;
    }
    let outputDir = state.outputDir || $("exportDir")?.value.trim() || "";
    if (!outputDir) outputDir = await chooseExportDestination();
    if (!outputDir) return;
    state.outputDir = outputDir;
    if ($("exportDir")) $("exportDir").value = outputDir;

    state.batchRunning = true;
    state.batchCancelled = false;
    state.batchOutcomes = [];
    renderBatchSelectors();
    renderBatchPage();
    const settings = settingsPayload();
    const channelSettings = channelSettingsPayload();
    try {
      const policy = $("batchEpocPolicy")?.value || "all";
      const selections = batchEpocSelections(epocs, policy);
      const exports = [];
      const skipped = [];
      const errors = [];
      for (let index = 0; index < selections.length; index += 1) {
        if (state.batchCancelled) break;
        const selection = selections[index];
        setBatch(
          Math.round((index / selections.length) * 100),
          `analyzing + exporting ${selection.label}…`,
          "RUN"
        );
        const data = await nativeOrFetchBatch({
          paths: state.sources.map((source) => source.path),
          epoc_selections: [selection],
          channels,
          settings,
          channel_settings: channelSettings,
          output_dir: outputDir,
          export_csv: exportCsv,
          export_figure: exportFigure,
          figure_format: $("figFormat")?.value || "png",
        });
        exports.push(...(data.exports || []));
        skipped.push(...(data.skipped || []));
        errors.push(...(data.errors || []));
        appendBatchOutcomes(data);
      }
      if (state.batchCancelled) {
        setBatch(
          Number.parseInt($("batchPct").textContent, 10) || 0,
          `cancelled after ${exports.length} export set(s)`,
          "CANCELLED"
        );
        toast("batch export cancelled");
      } else {
        const exportSets = exports.length;
        setBatch(
          100,
          `wrote ${exportSets} export set(s)${skipped.length ? ` · skipped ${skipped.length}` : ""}${errors.length ? ` · failed ${errors.length}` : ""}`,
          "DONE"
        );
        toast(
          `exported ${exportSets} epoc/channel set(s)${skipped.length ? ` · skipped ${skipped.length}` : ""}${errors.length ? ` · failed ${errors.length}` : ""} → ${outputDir}`
        );
      }
      if (window.auroraBridge?.setStatus) {
        window.auroraBridge.setStatus(`Exported to ${outputDir}`);
      }
    } catch (err) {
      state.batchOutcomes.push({
        status: "failed",
        source: "Batch request",
        epoc: "—",
        channels,
        detail: String(err.message || err),
      });
      setBatch(0, "batch export failed", "FAIL");
      toast(String(err.message || err));
    } finally {
      state.batchRunning = false;
      state.batchCancelled = false;
      renderBatchSelectors();
      renderBatchPage();
    }
  }

  async function exportLive(options = {}) {
    const epoc = options.epoc || state.activeEpoc;
    const channels = options.channels || Object.keys(state.resultsByChannel);
    if (!state.path || !epoc) {
      toast("open and analyze a session first");
      return;
    }
    if (
      (!options.selectedOnly && !hasResults()) ||
      (options.selectedOnly && !Object.keys(state.trialResultsByChannel).length)
    ) {
      toast("analyze before exporting");
      return;
    }
    const exportCsv =
      options.exportCsv === undefined ? !!$("expCsv")?.checked : options.exportCsv;
    const exportFigure =
      options.exportFigure === undefined
        ? !!$("expFig")?.checked
        : options.exportFigure;
    if (!exportCsv && !exportFigure) {
      toast("choose CSV files and/or Figures");
      return;
    }
    if (options.selectedOnly && !state.selectedTrialNumbers?.length) {
      toast("select at least one trial before exporting");
      return;
    }
    if (!channels.length) {
      toast("choose at least one channel");
      return;
    }
    const outputDir = await chooseExportDestination();
    if (!outputDir) return;
    state.outputDir = outputDir;
    if ($("exportDir")) $("exportDir").value = outputDir;
    toast("exporting…");
    setBatch(15, "writing exports…", "RUN");
    $("launchBatch").disabled = true;
    try {
      const data = await nativeOrFetchExport({
        path: state.path,
        epoc,
        channels,
        settings: options.settings || settingsPayload(),
        channel_settings:
          options.channelSettings || channelSettingsPayload(),
        output_dir: outputDir,
        export_csv: exportCsv,
        export_figure: exportFigure,
        figure_format: $("figFormat")?.value || "png",
        trial_numbers: options.selectedOnly
          ? state.selectedTrialNumbers
          : undefined,
        selected_trials: !!options.selectedOnly,
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
      renderBatchPage();
    }
  }

  async function openLiveSession(path) {
    await openManyPaths([path]);
  }

  async function handleOpen() {
    if (window.auroraBridge?.openMatDialog) {
      try {
        const raw = await bridgeCall("openMatDialog");
        const paths = parsePathList(raw);
        if (!paths.length) return;
        await openManyPaths(paths);
      } catch (e) {
        toast(String(e.message || e));
      }
      return;
    }
    // Browser mode: native multi file picker when possible
    const input = $("matFileInput");
    if (input) {
      input.value = "";
      input.click();
      return;
    }
    const raw = prompt(
      "Path(s) to MAT file or TDT block (comma or newline separated):",
      ""
    );
    if (!raw) return;
    const paths = raw
      .split(/[\n,]/)
      .map((p) => p.trim())
      .filter(Boolean);
    try {
      await openManyPaths(paths);
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
    if (message.type === "sessions") {
      const primary = message.primary || {};
      const extras = message.sources || [];
      if (primary.path && primary.session) {
        rememberSource(primary.path, primary.session);
        resetAnalysisState();
        state.path = primary.path;
        applySessionSummary(primary.session, primary.path);
      }
      extras.forEach((source) => rememberSource(source.path, source.session));
      renderImportQueue();
      renderDataPage();
      if (primary.path) {
        runLiveAnalyze({ force: true })
          .then(() => showView("align"))
          .catch((e) => toast(String(e.message || e)));
      }
      return;
    }
    if (message.type === "session") {
      if (message.path && message.path !== state.path) resetAnalysisState();
      state.path = message.path;
      if (message.session) {
        rememberSource(message.path, message.session);
        applySessionSummary(message.session, message.path);
      }
      renderImportQueue();
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
      exportLive({
        selectedOnly: false,
        exportCsv: true,
        exportFigure: false,
        channels: [...state.analysisChannels],
      });
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
    if (window.auroraBridge?.savedExportDir) {
      bridgeCall("savedExportDir")
        .then((path) => {
          if (!path) return;
          state.outputDir = path;
          if ($("exportDir")) $("exportDir").value = path;
        })
        .catch(() => {});
    }
    restoreProcessingSettings().catch(() => {});
  }

  function wireChrome() {
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.addEventListener("click", () => showView(b.dataset.page));
    });
    $("openSessionBtn").addEventListener("click", handleOpen);
    $("closeSessionBtn").addEventListener("click", handleClose);
    $("matFileInput")?.addEventListener("change", async () => {
      const input = $("matFileInput");
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      if (window.auroraBridge) return;
      try {
        toast(files.length === 1 ? "uploading…" : `uploading ${files.length} files…`);
        const paths = await uploadBrowserFiles(files);
        if (!paths.length) throw new Error("No MAT files were found in the upload.");
        await openManyPaths(paths);
      } catch (e) {
        toast(String(e.message || e));
      }
    });
    $("openTdtBtn")?.addEventListener("click", async () => {
      if (window.auroraBridge?.openTdtDialog) {
        try {
          const raw = await bridgeCall("openTdtDialog");
          const paths = parsePathList(raw);
          if (!paths.length) return;
          await openManyPaths(paths);
        } catch (e) {
          toast(String(e.message || e));
        }
        return;
      }
      const input = $("tdtFolderInput");
      if (input) {
        input.value = "";
        input.click();
        return;
      }
      toast("This browser does not support folder selection.");
    });
    $("tdtFolderInput")?.addEventListener("change", async () => {
      const input = $("tdtFolderInput");
      const files = Array.from(input?.files || []);
      if (!files.length || window.auroraBridge) return;
      try {
        toast(`uploading ${files.length} TDT files…`);
        const paths = await uploadBrowserFiles(files);
        if (!paths.length) throw new Error("No TDT blocks were found in the folder.");
        await openManyPaths(paths);
      } catch (e) {
        toast(String(e.message || e));
      }
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
    restoreProcessingSettings().catch(() => {});

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
        document.title = health.title || document.title;
      })
      .catch(() => {
        /* Keep the unversioned static fallback when metadata is unavailable. */
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
