import { getJson } from "../shared/api.js";
import { clearBg, q, on, setBg, setText } from "../shared/dom.js";
import {
  clearPendingPrintRequest,
  createDefaultCapabilityState,
  normalizeRuntimeSettings,
  saveSessionState,
  state,
} from "../shared/session-state.js";
import { createSseConnection } from "../shared/sse.js";
import { hideUserToast, showUserToast } from "../shared/toast.js";
import {
  handleCloudError,
  handlePreviewEvent,
  loginQrRetryCountdownSeconds,
  loginQrRetryIntervalMs,
  loginQrRetrySuffix,
  mapQrErrorMessage,
  setQrCenterVisible,
} from "../shared/runtime.js";

let loginCountdownValue = 0;
let loginCountdownActive = false;
let loginCountdownTimer = null;
let loginQrRefreshing = false;
let loginQrRetryTimer = null;

function setManualRefreshDisabled(disabled) {
  const btn = q("3_28");
  if (!btn) return;

  btn.classList.toggle("manual-refresh-disabled", !!disabled);
  btn.style.cursor = disabled ? "not-allowed" : "pointer";
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
      refreshQrCode();
    }
  }, 1000);
}

function clearLoginQrRetryTimer() {
  if (!loginQrRetryTimer) return;
  window.clearTimeout(loginQrRetryTimer);
  loginQrRetryTimer = null;
}

function setLoginErrorCountdown(message) {
  showUserToast(`${message}${loginQrRetrySuffix}`, "error");
  loginCountdownValue = loginQrRetryCountdownSeconds;
  loginCountdownActive = true;
  setText(["77_56"], String(loginCountdownValue));
}

function setQrRefreshLoading() {
  showUserToast("获取二维码中", "info");
  setQrCenterVisible(false);
}

async function refreshQrCode() {
  if (loginQrRefreshing) return false;
  clearLoginQrRetryTimer();

  const qrWrap = q("3_37");
  clearBg("3_37");
  loginQrRefreshing = true;
  loginCountdownActive = false;
  loginCountdownValue = 0;
  setText(["77_56"], "0");
  setManualRefreshDisabled(true);
  setQrRefreshLoading();

  if (qrWrap) qrWrap.style.opacity = "0.6";

  try {
    const qr = await getJson("/api/qr_code");
    if (qr?.standby) {
      state.session_id = null;
      setLoginErrorCountdown(mapQrErrorMessage(qr?.error_code, qr?.message));
      return false;
    }
    if (qr?.success === false) {
      state.session_id = null;
      setLoginErrorCountdown(mapQrErrorMessage(qr?.error_code, qr?.message));
      return false;
    }
    if (qr?.success && qr.qr_url) {
      clearLoginQrRetryTimer();
      state.session_id = qr.session_id || null;
      state.file = {};
      state.runtimeSettings = normalizeRuntimeSettings(qr.settings);
      state.defaultPrinterCapabilities =
        qr.default_printer_capabilities && typeof qr.default_printer_capabilities === "object"
          ? qr.default_printer_capabilities
          : null;
      state.capabilityState = createDefaultCapabilityState();
      saveSessionState();
      setBg("3_37", qr.qr_url);
      setQrCenterVisible(true);
      hideUserToast();
      loginCountdownValue = 60;
      loginCountdownActive = true;
      setText(["77_56"], String(loginCountdownValue));
      return true;
    }
    setLoginErrorCountdown(`二维码响应异常`);
    return false;
  } catch (err) {
    state.session_id = null;
    setLoginErrorCountdown(mapQrErrorMessage("", err?.message || "二维码获取失败"));
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

export async function initLoginPage() {
  state.file = {};
  state.session_id = null;
  state.doneResult = null;
  clearPendingPrintRequest();
  saveSessionState();
  loginCountdownValue = 0;
  loginCountdownActive = false;
  setText(["77_56"], "0");
  clearBg("3_37");
  setQrCenterVisible(false);
  showUserToast("获取二维码中", "info");

  const sseConnection = createSseConnection({
    onMessage: ({ type, data }) => {
      if (type === "error" || type === "cloud_error") {
        if (data?.session_id && state.session_id && data.session_id !== state.session_id) {
          return;
        }
        const result = handleCloudError({
          page: "login",
          data,
          errorCode: data?.error_code || data?.code,
          message: data?.message,
        });
        if (result?.loginMessage) {
          setLoginErrorCountdown(result.loginMessage);
        }
        return;
      }
      if (type === "preview_file") {
        handlePreviewEvent(data, sseConnection);
      }
    },
  });
  sseConnection.start();

  startLoginCountdownLoop();
  await refreshQrCode();

  on("3_28", () => {
    if (loginQrRefreshing) return;
    refreshQrCode();
  });

  window.setInterval(() => {
    if (loginQrRetryTimer || loginQrRefreshing || loginCountdownActive) return;
    loginQrRetryTimer = window.setTimeout(() => {
      loginQrRetryTimer = null;
      if (loginQrRefreshing || loginCountdownActive) return;
      refreshQrCode();
    }, loginQrRetryIntervalMs);
  }, loginQrRetryIntervalMs);
}
