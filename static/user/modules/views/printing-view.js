import { postJson } from "../shared/api.js";
import { q } from "../shared/dom.js";
import { clearPendingPrintRequest, saveSessionState } from "../shared/session-state.js";

export function renderPrintingView() {
  return `
<div class="scroll-container-0_1">
  <div id="0_1" class="Pixso-canvas-0_1">
    <div id="55_158" class="Pixso-frame-55_158 fill-bg-gradient">
      <div id="115_17" class="Pixso-rectangle-115_17"></div>
      <p id="115_21" class="Pixso-paragraph-115_21">2025/01/01 10:00:00</p>
      <div id="77_17" class="Pixso-rectangle-77_17"></div>
      <p id="77_18" class="Pixso-paragraph-77_18"></p>
      <div id="77_19" class="Pixso-rectangle-77_19">
        <div class="shadow-blend-77_19-0"></div>
      </div>
      <div id="77_20" class="Pixso-rectangle-77_20 fill-primary-gradient"></div>
      <p id="115_26" class="Pixso-paragraph-115_26"></p>
    </div>
  </div>
</div>
`;
}

export function bindPrintingViewEvents({ appState, finishWithResult }) {
  const session = appState.session;
  const pendingPrintRequest = session.pendingPrintRequest;
  const phase = String(appState.sessionPhase || "").toLowerCase();
  const waitingExistingJob =
    !pendingPrintRequest && (phase === "print_submitted" || phase === "printing");

  function renderPrintingIndicator() {
    const bar = q("77_20");
    const rail = q("77_19");
    if (bar && rail) {
      const railWidth = rail.clientWidth || 556;
      bar.style.width = `${railWidth}px`;
    }
  }

  renderPrintingIndicator();

  if (!pendingPrintRequest && !waitingExistingJob) {
    finishWithResult("error", "打印请求已丢失，请重新扫码上传");
    return {
      destroy() {},
      handleJobStatus() {},
    };
  }

  if (pendingPrintRequest) {
    clearPendingPrintRequest();
    void postJson("/api/print", pendingPrintRequest).catch((error) => {
      saveSessionState();
      finishWithResult("error", error?.message || "提交打印失败");
    });
  }

  return {
    handleJobStatus() {},
    destroy() {},
  };
}
