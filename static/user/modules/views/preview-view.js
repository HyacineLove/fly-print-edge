import { postJson } from "../shared/api.js";
import { applyPrinterCapabilityState, setOptionDisabledState } from "../shared/capabilities.js";
import { on, q, setPreviewBg, setText } from "../shared/dom.js";
import {
  clearPendingPrintRequest,
  createDefaultCapabilityState,
  createDefaultOptions,
  currentSessionId,
  defaultMaxUpscale,
  defaultPaperSize,
  ensureStateOptions,
  getCopyLimitState,
  normalizeCopies,
  normalizeMaxUpscale,
  normalizeRuntimeSettings,
  normalizeScaleMode,
  saveSessionState,
} from "../shared/session-state.js";
import {
  mapPreviewErrorMessage,
  normalizeDuplexForApi,
  previewFailureFallbackSeconds,
} from "../shared/runtime.js";

export function renderPreviewView() {
  return `
<div class="scroll-container-0_1">
  <div id="0_1" class="Pixso-canvas-0_1">
    <div id="55_77" class="Pixso-frame-55_77 fill-bg-gradient">
      <div id="77_42" class="Pixso-group-77_42">
        <div id="77_43" class="Pixso-vector-77_43"></div>
        <p id="77_44" class="Pixso-paragraph-77_44">15</p>
      </div>
      <div id="97_446" class="Pixso-rectangle-97_446"></div>
      <div id="97_447" class="Pixso-group-97_447">
        <div id="97_448" class="Pixso-vector-97_448"></div>
        <p id="97_449" class="Pixso-paragraph-97_449">60</p>
      </div>
      <p id="97_450" class="Pixso-paragraph-97_450">2025/01/01 10:00:00</p>
      <div id="97_454" class="Pixso-group-97_454" style="cursor: pointer;">
        <div id="97_455" class="Pixso-rectangle-97_455"></div>
        <p id="97_456" class="Pixso-paragraph-97_456"></p>
      </div>
      <div id="97_457" class="Pixso-rectangle-97_457"></div>
      <p id="97_459" class="Pixso-paragraph-97_459"></p>
      <div id="97_460" class="Pixso-group-97_460" style="cursor: pointer;">
        <div id="97_461" class="Pixso-rectangle-97_461 fill-primary-gradient"></div>
        <p id="97_462" class="Pixso-paragraph-97_462"></p>
      </div>
      <div id="115_60" class="Pixso-group-115_60">
        <div id="55_129" class="Pixso-group-55_129">
          <div id="55_112" class="Pixso-rectangle-55_112"></div>
          <div id="55_114" class="Pixso-rectangle-55_114" data-role="copies-increment"></div>
          <div id="55_115" class="Pixso-rectangle-55_115 fill-primary-gradient"></div>
          <div id="55_116" class="Pixso-vector-55_116" data-role="copies-decrement"></div>
          <p id="55_113" class="Pixso-paragraph-55_113"></p>
          <p id="55_117" class="Pixso-paragraph-55_117" data-role="copies-decrement">&#9664;</p>
          <p id="55_118" class="Pixso-paragraph-55_118" data-role="copies-value">1</p>
          <p id="55_119" class="Pixso-paragraph-55_119" data-role="copies-increment">&#9654;</p>
          <div id="55_120" class="Pixso-rectangle-55_120"></div>
          <div id="55_122" class="Pixso-rectangle-55_122 fill-primary-gradient"></div>
          <div id="55_123" class="Pixso-vector-55_123"></div>
          <p id="55_124" class="Pixso-paragraph-55_124"></p>
          <p id="55_125" class="Pixso-paragraph-55_125"></p>
          <p id="55_126" class="Pixso-paragraph-55_126"></p>
          <div id="133_34" class="Pixso-rectangle-133_34"></div>
          <div id="133_35" class="Pixso-rectangle-133_35 fill-primary-gradient"></div>
          <div id="133_36" class="Pixso-vector-133_36"></div>
          <p id="133_37" class="Pixso-paragraph-133_37"></p>
          <p id="133_38" class="Pixso-paragraph-133_38"></p>
          <p id="133_39" class="Pixso-paragraph-133_39"></p>
        </div>
      </div>
      <p id="97_480" class="Pixso-paragraph-97_480">-0/0页-</p>
      <p id="97_481" class="Pixso-paragraph-97_481">文档加载中...</p>
      <p id="97_473" class="Pixso-paragraph-97_473"></p>
      <div id="97_474" class="Pixso-vector-97_474"></div>
      <div id="115_56" class="Pixso-rectangle-115_56"></div>
      <div id="115_57" class="Pixso-group-115_57">
        <div id="115_58" class="Pixso-rectangle-115_58"></div>
        <div id="115_59" class="Pixso-rectangle-115_59"></div>
      </div>
      <button id="115_61" class="Pixso-button-115_61" type="button" aria-label="上一页">&#8249;</button>
      <button id="115_62" class="Pixso-button-115_62" type="button" aria-label="下一页">&#8250;</button>
    </div>
  </div>
</div>
`;
}

export function bindPreviewViewEvents({ appState, queuePrintRequest, restartCycle }) {
  const session = appState.session;
  if (!session.file?.file_id || !session.file?.file_url) {
    void restartCycle();
    return { destroy() {} };
  }

  const initial = session.file?.print_options || {};
  session.options = {
    ...createDefaultOptions(),
    copies: initial.copies ?? 1,
    paper_size: initial.paper_size || defaultPaperSize,
    color_mode: initial.color_mode === "grayscale" ? "mono" : (initial.color_mode || "color"),
    duplex: initial.duplex_mode === "duplex" ? "longedge" : "simplex",
  };
  session.runtimeSettings = normalizeRuntimeSettings(session.runtimeSettings);
  session.capabilityState = createDefaultCapabilityState();
  clearPendingPrintRequest();
  ensureStateOptions();
  applyPrinterCapabilityState(session.defaultPrinterCapabilities);
  saveSessionState();

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
  let previewControlsLocked = true;

  function setPreviewCountdownDisplay(value) {
    setText(["77_44", "97_449"], String(Math.max(0, value)));
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
    const placeholder = q("115_59");
    if (!placeholder) return;
    placeholder.classList.toggle("is-hidden", !visible);
  }

  function updatePreviewPageButtons() {
    const prevBtn = q("115_61");
    const nextBtn = q("115_62");
    if (!prevBtn || !nextBtn) return;
    const enabled = previewFirstLoadDone && !previewLoading && !previewFailureMode && previewPageCount > 1;
    prevBtn.disabled = !enabled || previewCurrentPage <= 0;
    nextBtn.disabled = !enabled || previewCurrentPage >= previewPageCount - 1;
    updatePrintButtonState();
  }

  function setInteractionDisabled(element, disabled) {
    if (!element) return;
    element.classList.toggle("is-disabled", disabled);
    element.style.pointerEvents = disabled ? "none" : "auto";
    element.setAttribute("aria-disabled", disabled ? "true" : "false");
  }

  function updatePrintButtonState() {
    const locked =
      previewControlsLocked ||
      !previewFirstLoadDone ||
      previewLoading ||
      previewFailureMode ||
      printSubmitting ||
      Boolean(previewRefreshTimer);
    setInteractionDisabled(q("97_460"), locked);
  }

  function setPreviewControlsLocked(locked, allowBackWhenLocked = false) {
    previewControlsLocked = locked;
    const optionsGroup = q("115_60");
    const backBtn = q("97_454");

    setInteractionDisabled(optionsGroup, locked);
    setInteractionDisabled(backBtn, locked && !allowBackWhenLocked);
    updatePrintButtonState();
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
          bg.style.backgroundColor = usesVectorBackground ? "" : "rgba(244, 244, 244, 1)";
        }
      }
      if (label) {
        label.style.color = disabled ? "rgba(80, 80, 80, 0.6)" : active ? "rgba(255,255,255,1)" : "rgba(0,0,0,1)";
      }
      setOptionDisabledState([bgId, labelId], disabled);
    };

    const { min, max } = getCopyLimitState();
    const copies = normalizeCopies(session.options?.copies);
    session.options.copies = copies;
    setText(["55_118"], String(copies));
    setOptionVisual("55_116", "55_117", { disabled: copies <= min });
    setOptionVisual("55_115", "55_118", { active: true });
    setOptionVisual("55_114", "55_119", { disabled: copies >= max });

    const duplex = session.options?.duplex || "simplex";
    const duplexLongEdge = duplex !== "simplex";
    const duplexSupported = Boolean(session.capabilityState?.duplexSupported);
    setOptionVisual("55_123", "55_125", { active: duplexLongEdge, disabled: !duplexSupported });
    setOptionVisual("55_122", "55_126", { active: !duplexLongEdge });

    const color = session.options?.color_mode || "color";
    const colorSupported = Boolean(session.capabilityState?.colorSupported);
    setOptionVisual("133_36", "133_38", { active: color === "mono" });
    setOptionVisual("133_35", "133_39", { active: color === "color", disabled: !colorSupported });

    updatePreviewPageButtons();
  }

  async function renderPreview(pageIndex = 0, blockUi = false) {
    if (!session.file?.file_id || !session.file?.file_url || previewLoading || previewFailureMode) return false;
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
      const response = await postJson("/api/preview", {
        session_id: currentSessionId() || undefined,
        file_id: session.file.file_id,
        file_url: session.file.file_url,
        file_name: session.file.file_name,
        file_type: session.file.file_type,
        content_hash: session.file.content_hash,
        options: {
          ...session.options,
          page_index: pageIndex,
          preview_width_px: previewWidth,
          preview_height_px: previewHeight,
        },
      });

      session.file.page_count = Number(response.page_count || 1);
      session.file.page_index = Number(response.page_index || 0);
      saveSessionState();

      previewCurrentPage = session.file.page_index;
      previewPageCount = session.file.page_count;
      setText(["97_481"], session.file.file_name || "文档");
      setText(["97_480"], `-${previewCurrentPage + 1}/${previewPageCount}页-`);
      setPreviewBg("115_58", response.preview_url);
      setPreviewLoadingPlaceholder(false);

      if (!previewFirstLoadDone && blockUi) {
        previewFirstLoadDone = true;
        setPreviewControlsLocked(false);
        resumePreviewCountdown(true);
      }

      updatePreviewPageButtons();
      return true;
    } catch (error) {
      enterPreviewFailureMode(mapPreviewErrorMessage(error?.code, error?.message || "预览加载失败"));
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
    updatePrintButtonState();
  }

  previewCountdownTimer = window.setInterval(() => {
    if (!previewCountdownActive) {
      setPreviewCountdownDisplay(previewCountdownValue);
      return;
    }
    previewCountdownValue = Math.max(0, previewCountdownValue - 1);
    setPreviewCountdownDisplay(previewCountdownValue);
    if (previewCountdownValue === 0) {
      previewCountdownActive = false;
      void restartCycle();
    }
  }, 1000);

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

  on("97_454", () => {
    if (!previewFailureMode && !previewFirstLoadDone) return;
    void restartCycle();
  });

  const changeCopies = (delta) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    session.options.copies = normalizeCopies(Number(session.options.copies || 1) + delta);
    saveSessionState();
    renderOptionsUI();
    resumePreviewCountdown(true);
  };

  const pickDuplex = (value) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    if (!session.capabilityState?.duplexSupported && value !== "simplex") return;
    session.options.duplex = value;
    saveSessionState();
    renderOptionsUI();
    resumePreviewCountdown(true);
  };

  const pickColor = (value) => {
    if (!previewFirstLoadDone || previewFailureMode) return;
    if (!session.capabilityState?.colorSupported && value === "color") return;
    session.options.color_mode = value;
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
    if (!previewFirstLoadDone || previewLoading || previewFailureMode || previewCurrentPage <= 0) return;
    await renderPreview(previewCurrentPage - 1, false);
  });
  on("115_62", async () => {
    if (!previewFirstLoadDone || previewLoading || previewFailureMode || previewCurrentPage >= previewPageCount - 1) return;
    await renderPreview(previewCurrentPage + 1, false);
  });
  on("97_460", () => {
    if (
      !previewFirstLoadDone ||
      previewLoading ||
      previewFailureMode ||
      previewRefreshTimer ||
      !session.file?.file_id ||
      printSubmitting
    ) return;
    printSubmitting = true;
    setPreviewControlsLocked(true);
    queuePrintRequest({
      session_id: currentSessionId() || undefined,
      file_id: session.file.file_id,
      task_token: session.file.task_token || undefined,
      options: {
        copies: Number(session.options.copies || 1),
        duplex: normalizeDuplexForApi(session.options.duplex),
        color_mode: session.options.color_mode || "color",
        scale_mode: normalizeScaleMode(session.options.scale_mode),
        paper_size: String(session.options.paper_size || defaultPaperSize),
        max_upscale: normalizeMaxUpscale(session.options.max_upscale || defaultMaxUpscale),
      },
    });
  });

  renderOptionsUI();
  setPreviewControlsLocked(true);
  void renderPreview(0, true);

  return {
    handlePreviewError: enterPreviewFailureMode,
    destroy() {
      if (previewCountdownTimer) window.clearInterval(previewCountdownTimer);
      if (previewRefreshTimer) window.clearTimeout(previewRefreshTimer);
    },
  };
}
