(() => {
  const page = document.body?.dataset?.page || "";
  const api = {
    qr: "/api/qr_code",
    events: "/api/events",
    preview: "/api/preview",
    print: "/api/print",
    cleanup: "/api/cleanup",
  };

  const stateKey = "fly_print_state";
  const defaultPaperSize = "A4";
  const defaultScaleMode = "fit";
  const defaultMaxUpscale = 3;
  const state = loadState();
  ensureStateOptions();
  let sseRetryTimer = null;

  let loginCountdownValue = 0;
  let loginCountdownActive = false;
  let loginCountdownTimer = null;
  let loginQrRefreshing = false;

  let previewCountdownValue = 60;
  let previewCountdownActive = false;
  let previewCountdownTimer = null;
  let previewFirstLoadDone = false;
  let previewLoading = false;
  let previewActiveChipBackgroundImage = "";
  let previewRefreshTimer = null;
  let previewCurrentPage = 0;
  let previewPageCount = 0;
  let doneReturnCountdownValue = 10;
  let doneReturnCountdownTimer = null;

  function q(id) {
    return document.getElementById(id);
  }

  function on(id, fn) {
    const el = q(id);
    if (el) el.addEventListener("click", fn);
  }

  function setText(ids, text) {
    ids.forEach((id) => {
      const el = q(id);
      if (el) el.textContent = text;
    });
  }

  function setBg(id, url) {
    const el = q(id);
    if (!el || !url) return;
    el.style.backgroundImage = `url(${url})`;
    el.style.backgroundSize = "cover";
    el.style.backgroundPosition = "center";
  }

  function setPreviewBg(id, url) {
    const el = q(id);
    if (!el || !url) return;
    el.style.backgroundImage = `url(${url})`;
    el.style.backgroundSize = "contain";
    el.style.backgroundPosition = "center";
    el.style.backgroundRepeat = "no-repeat";
    el.style.backgroundColor = "#ffffff";
  }

  function nowText() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(
      d.getHours()
    )}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function tickClock() {
    setText(["97_161", "97_450", "115_21"], nowText());
  }

  function loadState() {
    try {
      const raw = sessionStorage.getItem(stateKey);
      return raw
        ? JSON.parse(raw)
        : {
            options: createDefaultOptions(),
            file: {},
          };
    } catch {
      return {
        options: createDefaultOptions(),
        file: {},
      };
    }
  }

  function createDefaultOptions() {
    return {
      copies: 1,
      duplex: "simplex",
      color_mode: "color",
      scale_mode: defaultScaleMode,
      paper_size: defaultPaperSize,
      max_upscale: defaultMaxUpscale,
    };
  }

  function normalizeScaleMode(value) {
    const mode = String(value || "").toLowerCase();
    if (mode === "actual" || mode === "fill" || mode === "fit") return mode;
    return defaultScaleMode;
  }

  function normalizeMaxUpscale(value) {
    const num = Number(value);
    return Number.isFinite(num) && num > 0 ? num : defaultMaxUpscale;
  }

  function ensureStateOptions() {
    const merged = {
      ...createDefaultOptions(),
      ...(state.options && typeof state.options === "object" ? state.options : {}),
    };
    merged.scale_mode = normalizeScaleMode(merged.scale_mode);
    merged.paper_size = String(merged.paper_size || defaultPaperSize);
    merged.max_upscale = normalizeMaxUpscale(merged.max_upscale);
    state.options = merged;
  }

  function saveState() {
    sessionStorage.setItem(stateKey, JSON.stringify(state));
  }

  function setDoneResult(type, message) {
    state.doneResult = {
      type: type || "success",
      message: message || "",
      ts: Date.now(),
    };
    saveState();
  }

  async function getJson(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function postJson(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || json.success === false) {
      throw new Error(json.message || `HTTP ${res.status}`);
    }
    return json;
  }

  function showError(message) {
    if (!message) return;
    window.alert(message);
  }

  function normalizeDuplexForApi(duplex) {
    const value = String(duplex || "").toLowerCase();
    if (value === "simplex" || value === "single" || value === "none") {
      return "simplex";
    }
    return "longedge";
  }

  function extractEventMessage(rawMessage) {
    if (!rawMessage || typeof rawMessage !== "object") {
      return { type: "", data: {} };
    }

    const type = rawMessage.type || rawMessage?.data?.type || "";
    const data =
      rawMessage.data && typeof rawMessage.data === "object"
        ? rawMessage.data
        : rawMessage;
    return { type, data };
  }

  function gotoPage(name) {
    window.location.href = `/static/user/html/${name}.html`;
  }

  async function cleanupAndBackToLogin() {
    try {
      if (state.file?.file_id) {
        await postJson(api.cleanup, { file_id: state.file.file_id });
      }
    } catch {
      // Ignore cleanup errors to avoid blocking the flow.
    }

    state.file = {};
    saveState();
    gotoPage("login");
  }

  function handleCloudError(type, data) {
    if (type !== "error" && type !== "cloud_error") return false;
    const message = data?.message || "云端服务异常，请稍后重试";
    if (page === "login") {
      setQrStatus(`🔴 ${message}`, "error");
      return true;
    }
    if (page === "printing") {
      setDoneResult("error", mapPrintErrorMessage(data?.error_code, message));
      gotoPage("done");
      return true;
    }
    showError(message);
    return true;
  }

  function handlePreviewEvent(data) {
    if (!data?.file_id || !data?.file_url) return;
    state.file = {
      file_id: data.file_id,
      file_url: data.file_url,
      file_name: data.file_name || "文档",
      file_type: data.file_type || "",
      task_token: data.task_token || state.file?.task_token || null,
      job_id: data.job_id || null,
      page_count: 1,
      page_index: 0,
    };
    saveState();
    if (page === "login") gotoPage("preview");
  }

  function handleJobStatusEvent(data) {
    const status = String(data?.status || "").toLowerCase();
    const progress = Number(data?.progress || 0);
    const total = Number(data?.total_pages || state.file?.page_count || 1);
    const current = Number(data?.current_page || data?.page_index || 1);

    if (status.includes("failed") || status.includes("error")) {
      const message = data?.message || data?.error_message || "打印失败，请重试";
      if (page === "printing") {
        setDoneResult("error", mapPrintErrorMessage(data?.error_code, message));
        gotoPage("done");
      } else {
        showError(message);
      }
      return;
    }

    if (page === "printing") {
      if (progress > 0 && progress < 100) {
        const estimatedCurrent = Math.max(1, Math.round((progress / 100) * total));
        renderPrintingProgress(estimatedCurrent, total);
      } else {
        renderPrintingProgress(current, total);
      }

      if (
        status.includes("complete") ||
        status.includes("success") ||
        status.includes("done") ||
        progress >= 100
      ) {
        setDoneResult("success", "");
        gotoPage("done");
      }
    }
  }

  function renderCommonText() {
    setText(["97_158"], "简历打印服务");
    setText(["3_45"], "扫描二维码登录");
    setText(["3_30"], "刷新二维码");
    setText(["97_456"], "返回");
    setText(["97_462"], "立刻打印");
    setText(["115_42"], page === "done" ? "返回" : "继续打印");
    setText(["97_473"], "打印设置");
    setText(["55_113"], "打印份数");
    setText(["55_124"], "打印模式");
    setText(["133_37"], "色彩选择");
    setText(["55_125"], "双面");
    setText(["55_126"], "单面");
    setText(["133_39"], "彩色");
    setText(["133_38"], "黑白");
    setText(["77_18"], page === "done" ? "打印完成" : "打印中");
    setText(["115_539", "115_26", "97_459", "97_162"], "Power by HQIT");
  }

  function startSSE() {
    const es = new EventSource(api.events);

    es.onmessage = (ev) => {
      let raw;
      try {
        raw = JSON.parse(ev.data);
      } catch {
        return;
      }

      const { type, data } = extractEventMessage(raw);
      if (!type) return;

      if (handleCloudError(type, data)) return;

      if (type === "preview_file") {
        handlePreviewEvent(data);
      }

      if (type === "job_status") {
        handleJobStatusEvent(data);
      }
    };

    es.onerror = () => {
      if (sseRetryTimer) {
        window.clearTimeout(sseRetryTimer);
      }
      sseRetryTimer = window.setTimeout(() => {
        try {
          es.close();
        } catch {
          // no-op
        }
        startSSE();
      }, 2000);
    };
  }

  function updateCapabilityUi(capabilities) {
    if (!capabilities || typeof capabilities !== "object") return;

    const duplexValues = String(capabilities.duplex || "").toLowerCase();
    const duplexSupported = duplexValues.includes("duplex") && !duplexValues.includes("none");

    const colorValues = String(capabilities.color_model || "").toLowerCase();
    const colorSupported = colorValues.includes("rgb") || colorValues.includes("color");

    if (!duplexSupported) {
      state.options.duplex = "simplex";
      const d1 = q("55_125");
      if (d1) d1.style.opacity = "0.35";
    }

    if (!colorSupported) {
      state.options.color_mode = "mono";
      const c1 = q("133_39");
      if (c1) c1.style.opacity = "0.35";
    }

    saveState();
  }

  function setQrStatus(message, type = "info") {
    const el = q("3_46");
    if (!el) return;

    el.textContent = message;
    el.classList.remove("status-ok", "status-error");
    if (type === "ok") el.classList.add("status-ok");
    if (type === "error") el.classList.add("status-error");
  }

  function setManualRefreshDisabled(disabled) {
    const btn = q("3_28");
    if (!btn) return;

    btn.classList.toggle("manual-refresh-disabled", !!disabled);
    btn.style.cursor = disabled ? "not-allowed" : "pointer";
  }

  function mapQrErrorMessage(errorCode, message) {
    const code = String(errorCode || "").toLowerCase();
    const msg = String(message || "").trim();

    if (code === "printer_disabled") return "🔴 打印机已被禁用，请联系管理员";
    if (code === "printer_not_found") return "🔴 打印机已被删除或不存在，请联系管理员";
    if (code === "node_disabled") return "🔴 节点已被禁用，请联系管理员";
    if (code === "node_not_found") return "🔴 节点已被删除或不存在，请联系管理员";
    if (code === "printer_not_belong_to_node") return "🔴 打印机与节点绑定异常，请联系管理员";

    if (msg.includes("打印机已被管理员禁用")) return "🔴 打印机已被禁用，请联系管理员";
    if (msg.includes("打印机不存在")) return "🔴 打印机已被删除或不存在，请联系管理员";
    if (msg.includes("节点已被管理员禁用")) return "🔴 节点已被禁用，请联系管理员";
    if (msg.includes("云端服务未连接")) return "🔴 无法连接到云端服务器";
    if (msg.includes("设备未注册") || msg.includes("设备未就绪")) return "🔴 设备未就绪，请联系管理员";
    if (msg.includes("暂无可用打印机")) return "🔴 暂无可用打印机";

    return `🔴 ${msg || "获取二维码失败，请稍后重试"}`;
  }

  function mapPrintErrorMessage(errorCode, message) {
    const code = String(errorCode || "").toLowerCase();
    const msg = String(message || "").trim();

    if (code === "printer_disabled") return "🔴 打印机已被禁用，请联系管理员";
    if (code === "printer_not_found") return "🔴 打印机已被删除或不存在，请联系管理员";
    if (code === "node_disabled") return "🔴 节点已被禁用，请联系管理员";
    if (code === "node_not_found") return "🔴 节点已被删除或不存在，请联系管理员";
    if (code === "printer_not_belong_to_node") return "🔴 打印机与节点绑定异常，请联系管理员";
    if (code === "token_generation_failed") return "🔴 云端凭证生成失败，请稍后重试";

    if (msg.includes("打印机已被管理员禁用") || msg.includes("打印机禁用")) {
      return "🔴 打印机已被禁用，请联系管理员";
    }
    if (msg.includes("打印机不存在") || msg.includes("打印机删除")) {
      return "🔴 打印机已被删除或不存在，请联系管理员";
    }
    if (msg.includes("节点已被管理员禁用") || msg.includes("节点禁用")) {
      return "🔴 节点已被禁用，请联系管理员";
    }
    if (msg.includes("节点不存在") || msg.includes("节点删除")) {
      return "🔴 节点已被删除或不存在，请联系管理员";
    }
    if (
      msg.includes("云端服务未连接") ||
      msg.includes("无法连接") ||
      msg.includes("连接不上") ||
      msg.includes("websocket")
    ) {
      return "🔴 无法连接到云端服务器";
    }

    return `🔴 ${msg || "打印失败，请稍后重试"}`;
  }

  function startLoginCountdownLoop() {
    if (loginCountdownTimer) return;

    loginCountdownTimer = window.setInterval(() => {
      if (loginQrRefreshing) {
        setText(["77_56"], "0");
        return;
      }

      if (!loginCountdownActive) {
        setText(["77_56"], String(Math.max(0, loginCountdownValue)));
        return;
      }

      loginCountdownValue = Math.max(0, loginCountdownValue - 1);
      setText(["77_56"], String(loginCountdownValue));

      if (loginCountdownValue === 0) {
        loginCountdownActive = false;
        refreshQrCode({ trigger: "auto" });
      }
    }, 1000);
  }

  async function refreshQrCode({ trigger = "auto" } = {}) {
    if (loginQrRefreshing) return false;

    const qrWrap = q("3_37");
    loginQrRefreshing = true;
    loginCountdownActive = false;
    loginCountdownValue = 0;
    setText(["77_56"], "0");
    setManualRefreshDisabled(true);

    if (trigger === "manual") {
      setQrStatus("正在手动刷新二维码...", "info");
    } else {
      setQrStatus("正在获取二维码...", "info");
    }

    if (qrWrap) qrWrap.style.opacity = "0.6";

    try {
      const qr = await getJson(api.qr);
      if (qr?.standby) {
        setQrStatus(mapQrErrorMessage(qr?.error_code, qr?.message), "error");
        return false;
      }
      if (qr?.success === false) {
        setQrStatus(mapQrErrorMessage(qr?.error_code, qr?.message), "error");
        return false;
      }
      if (qr?.success && qr.qr_url) {
        setBg("3_37", qr.qr_url);
        updateCapabilityUi(qr.default_printer_capabilities);
        setQrStatus("🟢 已连接到云端服务器", "ok");
        loginCountdownValue = 60;
        loginCountdownActive = true;
        setText(["77_56"], String(loginCountdownValue));
        return true;
      }
      setQrStatus("🔴 二维码响应异常，请稍后重试", "error");
      return false;
    } catch (err) {
      setQrStatus(mapQrErrorMessage("", err?.message || "二维码获取失败"), "error");
      return false;
    } finally {
      if (qrWrap) qrWrap.style.opacity = "1";
      loginQrRefreshing = false;
      setManualRefreshDisabled(false);
      if (!loginCountdownActive) {
        setText(["77_56"], "0");
      }
    }
  }

  async function initLogin() {
    loginCountdownValue = 0;
    loginCountdownActive = false;
    setText(["77_56"], "0");
    setQrStatus("正在获取二维码...", "info");

    startLoginCountdownLoop();
    await refreshQrCode({ trigger: "init" });

    on("3_28", () => {
      if (loginQrRefreshing) return;
      refreshQrCode({ trigger: "manual" });
    });
  }

  function setPreviewCountdownDisplay(value) {
    setText(["77_44", "97_449"], String(Math.max(0, value)));
  }

  function startPreviewCountdownLoop() {
    if (previewCountdownTimer) return;
    previewCountdownTimer = window.setInterval(() => {
      if (!previewCountdownActive) {
        setPreviewCountdownDisplay(previewCountdownValue);
        return;
      }
      previewCountdownValue = Math.max(0, previewCountdownValue - 1);
      setPreviewCountdownDisplay(previewCountdownValue);
      if (previewCountdownValue === 0) {
        previewCountdownActive = false;
        cleanupAndBackToLogin();
      }
    }, 1000);
  }

  function pausePreviewCountdown() {
    previewCountdownActive = false;
  }

  function resumePreviewCountdown(fullReset = false) {
    if (fullReset) previewCountdownValue = 60;
    previewCountdownActive = true;
    setPreviewCountdownDisplay(previewCountdownValue);
  }

  function setPreviewLoadingPlaceholder(visible) {
    const ph = q("115_59");
    if (!ph) return;
    ph.classList.toggle("is-hidden", !visible);
  }

  function updatePreviewPageButtons() {
    const prevBtn = q("115_61");
    const nextBtn = q("115_62");
    if (!prevBtn || !nextBtn) return;

    const enable = previewFirstLoadDone && !previewLoading && previewPageCount > 1;
    prevBtn.disabled = !enable || previewCurrentPage <= 0;
    nextBtn.disabled = !enable || previewCurrentPage >= previewPageCount - 1;
  }

  function setPreviewControlsLocked(locked) {
    const optionsGroup = q("115_60");
    const backBtn = q("97_454");
    const printBtn = q("97_460");

    optionsGroup?.classList.toggle("is-disabled", locked);
    backBtn?.classList.toggle("is-disabled", locked);
    printBtn?.classList.toggle("is-disabled", locked);

    if (optionsGroup) optionsGroup.style.pointerEvents = locked ? "none" : "auto";
    if (backBtn) backBtn.style.pointerEvents = locked ? "none" : "auto";
    if (printBtn) printBtn.style.pointerEvents = locked ? "none" : "auto";

    updatePreviewPageButtons();
  }

  function renderOptionsUI() {
    const setOptionVisual = (bgId, labelId, active, inactiveStyle) => {
      const bg = q(bgId);
      const label = q(labelId);

      if (bg) {
        if (active) {
          bg.classList.add("fill-primary-gradient");
          if (previewActiveChipBackgroundImage) {
            bg.style.backgroundImage = previewActiveChipBackgroundImage;
          }
          bg.style.backgroundColor = "";
        } else {
          bg.classList.remove("fill-primary-gradient");
          bg.style.backgroundImage = inactiveStyle === "gray" ? "none" : "";

          if (inactiveStyle === "gray") {
            bg.style.backgroundColor = "rgba(244, 244, 244, 1)";
          } else {
            bg.style.backgroundColor = "";
          }
        }
      }

      if (label) {
        label.style.color = active ? "rgba(255,255,255,1)" : "rgba(0,0,0,1)";
      }
    };

    const copies = Number(state.options?.copies || 1);
    setOptionVisual("55_116", "55_117", copies === 1, "vector");
    setOptionVisual("55_115", "55_118", copies === 2, "gray");
    setOptionVisual("55_114", "55_119", copies === 3, "gray");

    const duplex = state.options?.duplex || "simplex";
    const duplexLongEdge = duplex !== "simplex";
    setOptionVisual("55_123", "55_125", duplexLongEdge, "vector");
    setOptionVisual("55_122", "55_126", !duplexLongEdge, "gray");

    const color = state.options?.color_mode || "color";
    setOptionVisual("133_36", "133_38", color === "mono", "vector");
    setOptionVisual("133_35", "133_39", color === "color", "gray");

    updatePreviewPageButtons();
  }

  function queuePreviewRefresh() {
    if (!previewFirstLoadDone) return;

    if (previewRefreshTimer) {
      window.clearTimeout(previewRefreshTimer);
      previewRefreshTimer = null;
    }

    previewRefreshTimer = window.setTimeout(async () => {
      previewRefreshTimer = null;
      if (previewLoading) {
        queuePreviewRefresh();
        return;
      }
      const ok = await renderPreview(previewCurrentPage, false);
      if (ok) {
        resumePreviewCountdown(true);
      }
    }, 120);
  }

  async function renderPreview(pageIndex = 0, blockUi = false) {
    if (!state.file?.file_id || !state.file?.file_url) return false;
    if (previewLoading) return false;

    previewLoading = true;
    setPreviewLoadingPlaceholder(true);
    if (blockUi) {
      setPreviewControlsLocked(true);
      pausePreviewCountdown();
    }
    updatePreviewPageButtons();

    try {
      const previewBox = q("115_58");
      const previewWidth = previewBox?.clientWidth || 620;
      const previewHeight = previewBox?.clientHeight || 870;

      const r = await postJson(api.preview, {
        file_id: state.file.file_id,
        file_url: state.file.file_url,
        file_name: state.file.file_name,
        file_type: state.file.file_type,
        options: {
          ...state.options,
          page_index: pageIndex,
          preview_width_px: previewWidth,
          preview_height_px: previewHeight,
        },
      });

      state.file.page_count = Number(r.page_count || 1);
      state.file.page_index = Number(r.page_index || 0);
      saveState();

      previewCurrentPage = state.file.page_index;
      previewPageCount = state.file.page_count;

      setText(["97_481"], state.file.file_name || "文档");
      setText(["97_480"], `-${previewCurrentPage + 1}/${previewPageCount}页-`);
      setPreviewBg("115_58", r.preview_url);
      setPreviewLoadingPlaceholder(false);

      if (!previewFirstLoadDone && blockUi) {
        previewFirstLoadDone = true;
        setPreviewControlsLocked(false);
        resumePreviewCountdown(true);
      }

      updatePreviewPageButtons();
      return true;
    } catch (err) {
      showError(err?.message || "预览加载失败");
      setText(["97_481"], "预览加载失败，请稍后重试");
      setText(["97_480"], "-0/0页-");
      setPreviewLoadingPlaceholder(true);
      if (blockUi) {
        setPreviewControlsLocked(true);
        pausePreviewCountdown();
      }
      return false;
    } finally {
      previewLoading = false;
      updatePreviewPageButtons();
    }
  }

  async function initPreview() {
    state.options = createDefaultOptions();
    saveState();

    previewCountdownValue = 60;
    previewCountdownActive = false;
    previewFirstLoadDone = false;
    previewLoading = false;
    previewCurrentPage = 0;
    previewPageCount = 0;

    setPreviewCountdownDisplay(60);
    setText(["97_481"], "文档加载中...");
    setText(["97_480"], "-0/0页-");
    setPreviewLoadingPlaceholder(true);

    if (!previewActiveChipBackgroundImage) {
      const sampleChip = q("55_115") || q("55_122") || q("133_35");
      if (sampleChip) {
        previewActiveChipBackgroundImage = getComputedStyle(sampleChip).backgroundImage;
      }
    }

    startPreviewCountdownLoop();

    on("97_454", () => {
      if (!previewFirstLoadDone) return;
      gotoPage("login");
    });

    const pickCopies = (value) => {
      if (!previewFirstLoadDone) return;
      state.options.copies = value;
      saveState();
      renderOptionsUI();
      queuePreviewRefresh();
    };
    const pickDuplex = (value) => {
      if (!previewFirstLoadDone) return;
      state.options.duplex = value;
      saveState();
      renderOptionsUI();
      queuePreviewRefresh();
    };
    const pickColor = (value) => {
      if (!previewFirstLoadDone) return;
      state.options.color_mode = value;
      saveState();
      renderOptionsUI();
      queuePreviewRefresh();
    };

    ["55_116", "55_117"].forEach((id) => on(id, () => pickCopies(1)));
    ["55_115", "55_118"].forEach((id) => on(id, () => pickCopies(2)));
    ["55_114", "55_119"].forEach((id) => on(id, () => pickCopies(3)));

    ["55_123", "55_125"].forEach((id) => on(id, () => pickDuplex("longedge")));
    ["55_122", "55_126"].forEach((id) => on(id, () => pickDuplex("simplex")));

    ["133_35", "133_39"].forEach((id) => on(id, () => pickColor("color")));
    ["133_36", "133_38"].forEach((id) => on(id, () => pickColor("mono")));

    on("115_61", async () => {
      if (!previewFirstLoadDone || previewLoading || previewCurrentPage <= 0) return;
      await renderPreview(previewCurrentPage - 1, false);
    });

    on("115_62", async () => {
      if (
        !previewFirstLoadDone ||
        previewLoading ||
        previewCurrentPage >= previewPageCount - 1
      )
        return;
      await renderPreview(previewCurrentPage + 1, false);
    });

    on("97_460", async () => {
      if (!previewFirstLoadDone || !state.file?.file_id) return;
      try {
        await postJson(api.print, {
          file_id: state.file.file_id,
          task_token: state.file.task_token || undefined,
          options: {
            copies: Number(state.options.copies || 1),
            duplex: normalizeDuplexForApi(state.options.duplex),
            color_mode: state.options.color_mode || "color",
            scale_mode: normalizeScaleMode(state.options.scale_mode),
            paper_size: String(state.options.paper_size || defaultPaperSize),
            max_upscale: normalizeMaxUpscale(state.options.max_upscale),
          },
        });
        gotoPage("printing");
      } catch (err) {
        showError(err?.message || "提交打印失败");
      }
    });

    renderOptionsUI();
    setPreviewControlsLocked(true);
    await renderPreview(0, true);
  }

  function renderPrintingProgress(current, total) {
    const cur = Math.max(1, Number(current || 1));
    const all = Math.max(cur, Number(total || 1));

    const bar = q("77_20");
    const rail = q("77_19");
    if (bar && rail) {
      const railW = rail.clientWidth || 556;
      bar.style.width = `${Math.max(20, Math.round((cur / all) * railW))}px`;
    }
  }

  function initPrinting() {
    setDoneResult("success", "");
    const total = Math.max(1, Number(state.file?.page_count || 1));
    renderPrintingProgress(total, total);
  }

  function initDone() {
    const done = state.doneResult || { type: "success", message: "" };
    if (done.type === "error") {
      setText(["77_18"], "打印失败");
      setText(["77_21"], done.message || "云端服务异常，请稍后重试");
    } else {
      setText(["77_18"], "打印完成");
      setText(["77_21"], "请尽快取走您的简历");
    }

    doneReturnCountdownValue = 10;
    setText(["115_39"], String(doneReturnCountdownValue));

    const leave = () => {
      if (doneReturnCountdownTimer) {
        window.clearInterval(doneReturnCountdownTimer);
        doneReturnCountdownTimer = null;
      }
      cleanupAndBackToLogin();
    };

    if (doneReturnCountdownTimer) {
      window.clearInterval(doneReturnCountdownTimer);
      doneReturnCountdownTimer = null;
    }

    doneReturnCountdownTimer = window.setInterval(() => {
      doneReturnCountdownValue = Math.max(0, doneReturnCountdownValue - 1);
      setText(["115_39"], String(doneReturnCountdownValue));
      if (doneReturnCountdownValue === 0) {
        leave();
      }
    }, 1000);

    on("115_40", () => leave());
  }

  renderCommonText();
  tickClock();
  setInterval(tickClock, 1000);
  startSSE();

  if (page === "login") initLogin();
  if (page === "preview") initPreview();
  if (page === "printing") initPrinting();
  if (page === "done") initDone();
})();
