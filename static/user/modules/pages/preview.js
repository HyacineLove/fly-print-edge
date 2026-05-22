import { postJson } from "../shared/api.js";
import { applyPrinterCapabilityState, setOptionDisabledState } from "../shared/capabilities.js";
import { on, q, setPreviewBg, setText } from "../shared/dom.js";
import { createSseConnection } from "../shared/sse.js";
import {
  clearPendingPrintRequest,
  currentSessionId,
  createDefaultCapabilityState,
  createDefaultOptions,
  defaultMaxUpscale,
  defaultPaperSize,
  ensureStateOptions,
  getCopyLimitState,
  normalizeCopies,
  normalizeMaxUpscale,
  normalizeRuntimeSettings,
  normalizeScaleMode,
  saveSessionState,
  setPendingPrintRequest,
  state,
} from "../shared/session-state.js";
import {
  cleanupAndBackToLogin,
  handleCloudError,
  mapPreviewErrorMessage,
  normalizeDuplexForApi,
  previewFailureFallbackSeconds,
  showError,
} from "../shared/runtime.js";

let previewCountdownValue = 60;
let previewCountdownActive = false;
let previewCountdownTimer = null;
let previewFirstLoadDone = false;
let previewLoading = false;
let previewActiveChipBackgroundImage = "";
let previewRefreshTimer = null;
let previewCurrentPage = 0;
let previewPageCount = 0;
let previewFailureMode = false;
let printSubmitting = false;

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

  const enable =
    previewFirstLoadDone && !previewLoading && !previewFailureMode && previewPageCount > 1;
  prevBtn.disabled = !enable || previewCurrentPage <= 0;
  nextBtn.disabled = !enable || previewCurrentPage >= previewPageCount - 1;
}

function setPreviewControlsLocked(locked, allowBackWhenLocked = false) {
  const optionsGroup = q("115_60");
  const backBtn = q("97_454");
  const printBtn = q("97_460");

  optionsGroup?.classList.toggle("is-disabled", locked);
  backBtn?.classList.toggle("is-disabled", locked && !allowBackWhenLocked);
  printBtn?.classList.toggle("is-disabled", locked);

  if (optionsGroup) optionsGroup.style.pointerEvents = locked ? "none" : "auto";
  if (backBtn) backBtn.style.pointerEvents = locked && !allowBackWhenLocked ? "none" : "auto";
  if (printBtn) printBtn.style.pointerEvents = locked ? "none" : "auto";

  updatePreviewPageButtons();
}

function enterPreviewFailureMode(errorMessage) {
  previewFailureMode = true;
  pausePreviewCountdown();
  previewCountdownValue = previewFailureFallbackSeconds;
  previewCountdownActive = true;
  setPreviewCountdownDisplay(previewCountdownValue);

  setText(["97_481"], "预览加载失败，正在返回二维码页...");
  setText(["97_480"], `-${errorMessage || "请稍后重试"}-`);
  setPreviewLoadingPlaceholder(true);
  setPreviewControlsLocked(true, true);
}

function renderOptionsUI() {
  const setOptionVisual = (bgId, labelId, { active = false, disabled = false } = {}) => {
    const bg = q(bgId);
    const label = q(labelId);
    const usesVectorBackground = Boolean(bg?.className?.includes("Pixso-vector"));

    if (bg) {
      if (disabled) {
        bg.classList.remove("fill-primary-gradient");
        bg.style.backgroundImage = "none";
        bg.style.backgroundColor = "rgba(229, 229, 229, 1)";
      } else if (active) {
        bg.classList.add("fill-primary-gradient");
        if (previewActiveChipBackgroundImage) {
          bg.style.backgroundImage = previewActiveChipBackgroundImage;
        }
        bg.style.backgroundColor = "";
      } else {
        bg.classList.remove("fill-primary-gradient");
        bg.style.backgroundImage = usesVectorBackground ? "" : "none";

        if (usesVectorBackground) {
          bg.style.backgroundColor = "";
        } else {
          bg.style.backgroundColor = "rgba(244, 244, 244, 1)";
        }
      }
    }

    if (label) {
      if (disabled) {
        label.style.color = "rgba(80, 80, 80, 0.6)";
      } else {
        label.style.color = active ? "rgba(255,255,255,1)" : "rgba(0,0,0,1)";
      }
    }

    setOptionDisabledState([bgId, labelId], disabled);
  };

  const { min, max } = getCopyLimitState();
  const copies = normalizeCopies(state.options?.copies);
  state.options.copies = copies;
  setText(["55_118"], String(copies));
  setOptionVisual("55_116", "55_117", { disabled: copies <= min });
  setOptionVisual("55_115", "55_118", { active: true });
  setOptionVisual("55_114", "55_119", { disabled: copies >= max });

  const duplex = state.options?.duplex || "simplex";
  const duplexLongEdge = duplex !== "simplex";
  const duplexSupported = Boolean(state.capabilityState?.duplexSupported);
  setOptionVisual("55_123", "55_125", { active: duplexLongEdge, disabled: !duplexSupported });
  setOptionVisual("55_122", "55_126", { active: !duplexLongEdge });

  const color = state.options?.color_mode || "color";
  const colorSupported = Boolean(state.capabilityState?.colorSupported);
  setOptionVisual("133_36", "133_38", { active: color === "mono" });
  setOptionVisual("133_35", "133_39", { active: color === "color", disabled: !colorSupported });

  updatePreviewPageButtons();
}

function queuePreviewRefresh() {
  if (!previewFirstLoadDone || previewFailureMode) return;

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
  if (previewFailureMode) return false;

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

    const r = await postJson("/api/preview", {
      session_id: currentSessionId() || undefined,
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
    saveSessionState();

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
    enterPreviewFailureMode(mapPreviewErrorMessage("", err?.message || "预览加载失败"));
    setPreviewLoadingPlaceholder(true);
    if (blockUi) {
      setPreviewControlsLocked(true, true);
      pausePreviewCountdown();
    }
    return false;
  } finally {
    previewLoading = false;
    updatePreviewPageButtons();
  }
}

export async function initPreviewPage() {
  state.options = createDefaultOptions();
  state.runtimeSettings = normalizeRuntimeSettings(state.runtimeSettings);
  state.capabilityState = createDefaultCapabilityState();
  clearPendingPrintRequest();
  ensureStateOptions();
  applyPrinterCapabilityState(state.defaultPrinterCapabilities);
  saveSessionState();

  previewCountdownValue = 60;
  previewCountdownActive = false;
  previewFirstLoadDone = false;
  previewLoading = false;
  previewCurrentPage = 0;
  previewPageCount = 0;
  previewFailureMode = false;

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

  const sseConnection = createSseConnection({
    onMessage: ({ type, data }) => {
      if (type === "error" || type === "cloud_error") {
        if (data?.session_id && state.session_id && data.session_id !== state.session_id) {
          return;
        }
        handleCloudError({
          page: "preview",
          data,
          errorCode: data?.error_code || data?.code,
          message: data?.message,
          onPreviewError: (message) => enterPreviewFailureMode(message),
        });
      }
    },
  });
  sseConnection.start();

  on("97_454", () => {
    if (!previewFailureMode && !previewFirstLoadDone) return;
    cleanupAndBackToLogin(sseConnection);
  });

  const changeCopies = (delta) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    state.options.copies = normalizeCopies(Number(state.options.copies || 1) + delta);
    saveSessionState();
    renderOptionsUI();
    resumePreviewCountdown(true);
  };

  const pickDuplex = (value) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    if (!state.capabilityState?.duplexSupported && value !== "simplex") return;
    state.options.duplex = value;
    saveSessionState();
    renderOptionsUI();
    resumePreviewCountdown(true);
  };

  const pickColor = (value) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    if (!state.capabilityState?.colorSupported && value === "color") return;
    state.options.color_mode = value;
    saveSessionState();
    renderOptionsUI();
    queuePreviewRefresh();
  };

  ["55_116", "55_117"].forEach((id) => on(id, () => changeCopies(-1)));
  ["55_114", "55_119"].forEach((id) => on(id, () => changeCopies(1)));

  ["55_123", "55_125"].forEach((id) => on(id, () => pickDuplex("longedge")));
  ["55_122", "55_126"].forEach((id) => on(id, () => pickDuplex("simplex")));

  ["133_35", "133_39"].forEach((id) => on(id, () => pickColor("color")));
  ["133_36", "133_38"].forEach((id) => on(id, () => pickColor("mono")));

  on("115_61", async () => {
    if (
      !previewFirstLoadDone ||
      previewLoading ||
      previewFailureMode ||
      previewCurrentPage <= 0
    ) {
      return;
    }
    await renderPreview(previewCurrentPage - 1, false);
  });

  on("115_62", async () => {
    if (
      !previewFirstLoadDone ||
      previewLoading ||
      previewFailureMode ||
      previewCurrentPage >= previewPageCount - 1
    ) {
      return;
    }
    await renderPreview(previewCurrentPage + 1, false);
  });

  on("97_460", async () => {
    if (!previewFirstLoadDone || previewFailureMode || !state.file?.file_id) return;
    if (printSubmitting) return;
    printSubmitting = true;
    setPreviewControlsLocked(true);
    try {
      setPendingPrintRequest({
        session_id: currentSessionId() || undefined,
        file_id: state.file.file_id,
        task_token: state.file.task_token || undefined,
        options: {
          copies: Number(state.options.copies || 1),
          duplex: normalizeDuplexForApi(state.options.duplex),
          color_mode: state.options.color_mode || "color",
          scale_mode: normalizeScaleMode(state.options.scale_mode),
          paper_size: String(state.options.paper_size || defaultPaperSize),
          max_upscale: normalizeMaxUpscale(state.options.max_upscale || defaultMaxUpscale),
        },
      });
      window.location.href = "/static/user/html/printing.html";
    } catch (err) {
      showError(err?.message || "提交打印失败");
    } finally {
      printSubmitting = false;
      setPreviewControlsLocked(false);
    }
  });

  renderOptionsUI();
  setPreviewControlsLocked(true);
  await renderPreview(0, true);
}
