import { createAppState } from "./app-state.js";
import { createRouter } from "./router.js";
import { UserSseClient } from "./sse-client.js";
import { initTouchRestrictions } from "../shared/touch-guard.js";
import { renderDoneView, bindDoneViewEvents } from "../views/done-view.js";
import { renderLoginView, bindLoginViewEvents } from "../views/login-view.js";
import { renderPreviewView, bindPreviewViewEvents } from "../views/preview-view.js";
import { renderPrintingView, bindPrintingViewEvents } from "../views/printing-view.js";
import {
  clearLocalUserSession,
  cleanupSessionResources,
  mapPreviewErrorMessage,
  mapPrintErrorMessage,
  mapQrErrorMessage,
  renderCommonText,
  startClockLoop,
} from "../shared/runtime.js";
import { api, getJson } from "../shared/api.js";
import { currentSessionId, saveSessionState, setDoneResult, setPendingPrintRequest } from "../shared/session-state.js";

const viewRegistry = {
  login: { render: renderLoginView, bind: bindLoginViewEvents },
  preview: { render: renderPreviewView, bind: bindPreviewViewEvents },
  printing: { render: renderPrintingView, bind: bindPrintingViewEvents },
  done: { render: renderDoneView, bind: bindDoneViewEvents },
};

export function createAppController({ mountNode }) {
  const state = createAppState();
  let currentViewApi = null;
  let restartInFlight = false;
  let started = false;

  const render = () => {
    const definition = viewRegistry[state.currentView] || viewRegistry.login;
    currentViewApi?.destroy?.();
    mountNode.innerHTML = definition.render(state);
    mountNode.dataset.view = state.currentView;
    renderCommonText(state.currentView);
    currentViewApi = definition.bind(createViewContext()) || null;
  };

  const router = createRouter({ state, renderView: async () => render() });

  const sse = new UserSseClient({
    onMessage: ({ type, data }) => {
      state.sseStatus.lastMessageAt = Date.now();
      handleSseMessage(type, data || {});
    },
    onStatusChange: ({ connecting, connected, retryCount = 0 }) => {
      state.sseStatus.connecting = Boolean(connecting);
      state.sseStatus.connected = Boolean(connected);
      state.sseStatus.retryCount = retryCount;
    },
  });

  function createViewContext() {
    return {
      appState: state,
      router,
      queuePrintRequest,
      restartCycle,
      finishWithResult,
    };
  }

  function acceptSessionEvent(data) {
    const incomingSessionId = data?.session_id;
    return !currentSessionId() || !incomingSessionId || incomingSessionId === currentSessionId();
  }

  function handleSseMessage(type, data) {
    if (!acceptSessionEvent(data)) return;

    if (type === "preview_file") {
      state.session.session_id = data.session_id || state.session.session_id || null;
      state.session.file = {
        file_id: data.file_id,
        file_url: data.file_url,
        file_name: data.file_name || "文档",
        file_type: data.file_type || "",
        task_token: data.task_token || null,
        job_id: data.job_id || null,
        page_count: 1,
        page_index: 0,
      };
      state.session.doneResult = null;
      state.sessionPhase = "preview_ready";
      saveSessionState();
      void router.go("preview");
      return;
    }

    if (type === "error" || type === "cloud_error") {
      handleCloudError(data);
      return;
    }

    if (type === "job_status") {
      handleJobStatus(data);
    }
  }

  function handleCloudError(data) {
    const errorCode = data?.error_code || data?.code;
    const message = data?.message || "";

    if (state.currentView === "login") {
      currentViewApi?.setLoginErrorCountdown?.(mapQrErrorMessage(errorCode, message));
      return;
    }
    if (state.currentView === "preview") {
      currentViewApi?.handlePreviewError?.(mapPreviewErrorMessage(errorCode, message));
      return;
    }
    if (state.currentView === "printing") {
      finishWithResult("error", mapPrintErrorMessage(errorCode, message), {
        error_code: errorCode || null,
        printer_fault: data?.printer_fault || null,
      });
    }
  }

  function handleJobStatus(data) {
    if (data?.job_id) {
      state.session.file.job_id = data.job_id;
      saveSessionState();
    }

    currentViewApi?.handleJobStatus?.(data);

    const status = String(data?.status || "").toLowerCase();
    const progress = Number(data?.progress || 0);
    if (status.includes("failed") || status.includes("error")) {
      finishWithResult("error", mapPrintErrorMessage(data?.error_code, data?.message || data?.error_message), {
        error_code: data?.error_code || null,
        printer_fault: data?.printer_fault || null,
      });
      return;
    }

    if (
      state.currentView === "printing" &&
      (status.includes("complete") || status.includes("success") || status.includes("done") || progress >= 100)
    ) {
      finishWithResult("success", "");
    }
  }

  function queuePrintRequest(request) {
    setPendingPrintRequest(request);
    state.sessionPhase = "printing";
    void router.go("printing");
  }

  function applySnapshot(snapshot) {
    const normalized = snapshot && typeof snapshot === "object" ? snapshot : {};
    const sessionState = state.session;
    sessionState.session_id = normalized.session_id || null;
    sessionState.file = normalized.active
      ? {
          file_id: normalized.file_id || null,
          file_url: normalized.file_url || null,
          file_name: normalized.file_name || "鏂囨。",
          file_type: normalized.file_type || "",
          task_token: sessionState.file?.task_token || null,
          job_id: normalized.job_id || null,
          page_count: sessionState.file?.page_count || 1,
          page_index: sessionState.file?.page_index || 0,
        }
      : {};
    sessionState.doneResult = null;
    saveSessionState();
  }

  async function restoreFromSnapshot() {
    let snapshot;
    try {
      snapshot = await getJson(api.sessionCurrent);
    } catch {
      clearLocalUserSession();
      state.sessionPhase = "idle";
      await router.go("login");
      return;
    }

    if (!snapshot?.active) {
      clearLocalUserSession();
      state.sessionPhase = "idle";
      await router.go("login");
      return;
    }

    applySnapshot(snapshot);
    const phase = String(snapshot.state || "idle").toLowerCase();
    state.sessionPhase = phase;

    if (phase === "awaiting_preview") {
      clearLocalUserSession();
      state.sessionPhase = "idle";
      await router.go("login");
      return;
    }

    if (phase === "preview_ready") {
      await router.go("preview");
      return;
    }

    if (phase === "print_submitted" || phase === "printing") {
      await router.go("printing");
      return;
    }

    if (phase === "completed") {
      setDoneResult("success", "");
    }

    if (phase === "failed") {
      setDoneResult(
        "error",
        mapPrintErrorMessage(snapshot.error_code, snapshot.error_message || "打印失败，请联系管理员"),
        {
          error_code: snapshot.error_code || null,
          printer_fault: snapshot.printer_fault || null,
        },
      );
      await router.go("done");
      return;
    }

    clearLocalUserSession();
    state.sessionPhase = "idle";
    await router.go("login");
  }

  async function restartCycle() {
    if (restartInFlight) return;
    restartInFlight = true;
    try {
      await cleanupSessionResources();
      clearLocalUserSession();
      state.sessionPhase = "idle";
      await router.go("login");
    } finally {
      restartInFlight = false;
    }
  }

  function finishWithResult(type, message, extra = {}) {
    setDoneResult(type, message, extra);
    state.sessionPhase = type === "success" ? "completed" : "error";
    void router.go("done");
  }

  return {
    state,
    router,
    async start() {
      if (started) return;
      started = true;
      initTouchRestrictions();
      startClockLoop();
      sse.start();
      await restoreFromSnapshot();
    },
  };
}
