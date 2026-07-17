import { postJson } from "../shared/api.js";
import { q } from "../shared/dom.js";
import { createSseConnection } from "../shared/sse.js";
import { gotoPage, handleCloudError, handleJobStatusEvent } from "../shared/runtime.js";
import {
  clearPendingPrintRequest,
  saveSessionState,
  setDoneResult,
  state,
} from "../shared/session-state.js";

export function renderPrintingIndicator() {
  const bar = q("77_20");
  const rail = q("77_19");
  if (bar && rail) {
    const railW = rail.clientWidth || 556;
    bar.style.width = `${railW}px`;
  }
}

export function initPrintingPage() {
  setDoneResult("success", "");
  renderPrintingIndicator();

  const sseConnection = createSseConnection({
    onMessage: ({ type, data }) => {
      if (type === "error" || type === "cloud_error") {
        if (data?.session_id && state.session_id && data.session_id !== state.session_id) {
          return;
        }
        handleCloudError({
          page: "printing",
          data,
          errorCode: data?.error_code || data?.code,
          message: data?.message,
          sseConnection,
        });
        return;
      }
      if (type === "job_status") {
        handleJobStatusEvent(data, { page: "printing", sseConnection });
      }
    },
  });
  sseConnection.start();

  const pendingPrintRequest = state.pendingPrintRequest;
  if (!pendingPrintRequest) {
    setDoneResult("error", "打印请求已丢失，请重新扫码上传");
    gotoPage("done", sseConnection);
    return;
  }

  clearPendingPrintRequest();

  void postJson("/api/print", pendingPrintRequest).catch((error) => {
    saveSessionState();
    setDoneResult("error", error?.message || "提交打印失败");
    gotoPage("done", sseConnection);
  });
}
