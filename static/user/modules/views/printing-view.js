import { postJson } from "../shared/api.js";
import { q } from "../shared/dom.js";
import { clearPendingPrintRequest, saveSessionState } from "../shared/session-state.js";
import { mapPrintErrorMessage } from "../shared/runtime.js";

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
      <div id="77_20" class="Pixso-rectangle-77_20 fill-primary-gradient" aria-hidden="true"></div>
      <p id="printing_status_message" class="printing-status-message" role="status" aria-live="polite"></p>
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

  function renderJobStatus(data = {}) {
    const status = String(data.status || "").toLowerCase();
    const completedPages = Number(data.current_page);
    const totalPages = Number(data.total_pages);
    const hasPageProgress =
      data.current_page !== null &&
      data.current_page !== undefined &&
      Number.isInteger(completedPages) &&
      completedPages >= 0 &&
      Number.isInteger(totalPages) &&
      totalPages > 0;
    const activePage = hasPageProgress ? Math.min(completedPages + 1, totalPages) : null;
    const messages = {
      preparing: "正在准备打印文件……",
      submitting: "正在发送到打印机……",
      queued: "打印机正在处理任务……",
      printing: hasPageProgress ? `正在打印，第 ${activePage} / ${totalPages} 页……` : "打印机正在打印……",
    };
    const message = messages[status] || data.message || "正在等待打印状态……";
    const label = q("printing_status_message");
    if (label) label.textContent = message;
  }

  renderJobStatus(appState.printing);

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
      finishWithResult("error", mapPrintErrorMessage(error?.code, error?.message));
    });
  }

  return {
    handleJobStatus: renderJobStatus,
    destroy() {},
  };
}
