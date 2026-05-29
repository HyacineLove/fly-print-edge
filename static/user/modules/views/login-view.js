import { getJson } from "../shared/api.js";
import { clearBg, on, q, setBg, setText } from "../shared/dom.js";
import {
  createDefaultCapabilityState,
  normalizeRuntimeSettings,
  saveSessionState,
} from "../shared/session-state.js";
import { hideUserToast, showUserToast } from "../shared/toast.js";
import {
  loginQrRetryCountdownSeconds,
  loginQrRetryIntervalMs,
  loginQrRetrySuffix,
  mapQrErrorMessage,
  setQrCenterVisible,
} from "../shared/runtime.js";

export function renderLoginView() {
  return `
<div class="scroll-container-0_1">
  <div id="0_1" class="Pixso-canvas-0_1">
    <div id="3_24" class="Pixso-frame-3_24">
      <div id="97_164" class="Pixso-rectangle-97_164"></div>
      <p id="97_158" class="Pixso-paragraph-97_158"></p>
      <div id="3_33" class="Pixso-rectangle-3_33"></div>
      <div id="97_166" class="Pixso-group-97_166">
        <div id="3_35" class="Pixso-rectangle-3_35"></div>
        <p id="3_45" class="Pixso-paragraph-3_45"></p>
        <div id="3_28" class="Pixso-group-3_28" style="cursor: pointer;">
          <div id="3_29" class="Pixso-rectangle-3_29 fill-primary-gradient"></div>
          <p id="3_30" class="Pixso-paragraph-3_30"></p>
        </div>
        <div id="97_159" class="Pixso-group-97_159">
          <div id="3_37" class="Pixso-rectangle-3_37"></div>
          <div id="3_39" class="Pixso-rectangle-3_39"></div>
          <div id="3_26" class="Pixso-rectangle-3_26"></div>
        </div>
        <p id="3_46" class="Pixso-paragraph-3_46"></p>
      </div>
      <div id="77_54" class="Pixso-group-77_54">
        <div id="77_55" class="Pixso-vector-77_55"></div>
        <p id="77_56" class="Pixso-paragraph-77_56">15</p>
      </div>
      <div id="97_155" class="Pixso-rectangle-97_155"></div>
      <p id="97_161" class="Pixso-paragraph-97_161">2025/01/01 10:00:00</p>
      <p id="97_162" class="Pixso-paragraph-97_162"></p>
    </div>
  </div>
</div>
`;
}

export function bindLoginViewEvents({ appState }) {
  const { session } = appState;
  let loginCountdownValue = 0;
  let loginCountdownActive = false;
  let loginCountdownTimer = null;
  let loginQrRefreshing = false;
  let loginQrRetryTimer = null;
  let loginQrAutoRefreshTimer = null;

  function setManualRefreshDisabled(disabled) {
    const btn = q("3_28");
    if (!btn) return;
    btn.classList.toggle("manual-refresh-disabled", !!disabled);
    btn.style.cursor = disabled ? "not-allowed" : "pointer";
  }

  function clearRetryTimer() {
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
    clearRetryTimer();
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
      if (qr?.standby || qr?.success === false) {
        session.session_id = null;
        setLoginErrorCountdown(mapQrErrorMessage(qr?.error_code, qr?.message));
        return false;
      }
      if (qr?.success && qr.qr_url) {
        session.session_id = qr.session_id || null;
        session.file = {};
        session.runtimeSettings = normalizeRuntimeSettings(qr.settings);
        session.defaultPrinterCapabilities =
          qr.default_printer_capabilities && typeof qr.default_printer_capabilities === "object"
            ? qr.default_printer_capabilities
            : null;
        session.capabilityState = createDefaultCapabilityState();
        saveSessionState();
        setBg("3_37", qr.qr_url);
        setQrCenterVisible(true);
        hideUserToast();
        loginCountdownValue = 60;
        loginCountdownActive = true;
        setText(["77_56"], String(loginCountdownValue));
        return true;
      }
      setLoginErrorCountdown("二维码响应异常");
      return false;
    } catch (error) {
      session.session_id = null;
      setLoginErrorCountdown(mapQrErrorMessage("", error?.message || "二维码获取失败"));
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
      void refreshQrCode();
    }
  }, 1000);

  loginQrAutoRefreshTimer = window.setInterval(() => {
    if (loginQrRetryTimer || loginQrRefreshing || loginCountdownActive) return;
    loginQrRetryTimer = window.setTimeout(() => {
      loginQrRetryTimer = null;
      if (loginQrRefreshing || loginCountdownActive) return;
      void refreshQrCode();
    }, loginQrRetryIntervalMs);
  }, loginQrRetryIntervalMs);

  setText(["77_56"], "0");
  clearBg("3_37");
  setQrCenterVisible(false);
  showUserToast("获取二维码中", "info");

  on("3_28", () => {
    if (loginQrRefreshing) return;
    void refreshQrCode();
  });

  void refreshQrCode();

  return {
    setLoginErrorCountdown,
    destroy() {
      if (loginCountdownTimer) window.clearInterval(loginCountdownTimer);
      if (loginQrAutoRefreshTimer) window.clearInterval(loginQrAutoRefreshTimer);
      clearRetryTimer();
    },
  };
}
