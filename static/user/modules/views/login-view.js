import { api, getJson } from "../shared/api.js";
import { clearBg, on, q, setBg, setText } from "../shared/dom.js";
import {
  createDefaultCapabilityState,
  normalizeRuntimeSettings,
  saveSessionState,
  setOpsContacts,
} from "../shared/session-state.js";
import { hideUserToast, showUserToast } from "../shared/toast.js";
import {
  loginQrRetryCountdownSeconds,
  loginQrRetryIntervalMs,
  mapQrErrorMessage,
  renderCommonText,
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
          <div id="qrCenterStatus" class="qr-center-status is-hidden" aria-live="polite"></div>
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
  let printerFaultLocked = false;
  let cloudAccessLocked = false;
  let terminalActivationRequired = false;
  let availabilityPollTimer = null;

  let terminalOccupied = false;
  let occupiedExpireTimer = null;

  function clearOccupiedExpireTimer() {
    if (!occupiedExpireTimer) return;
    window.clearTimeout(occupiedExpireTimer);
    occupiedExpireTimer = null;
  }

  function setQrCenterStatus(message) {
    const el = q("qrCenterStatus");
    if (!el) return;
    const text = String(message || "").trim();
    if (!text) {
      el.textContent = "";
      el.classList.add("is-hidden");
      return;
    }
    el.textContent = text;
    el.classList.remove("is-hidden");
  }

  function setTerminalOccupied(occupied, { expiresAt = null, message = "终端使用中\n请稍候或点击刷新" } = {}) {
    terminalOccupied = Boolean(occupied);
    clearOccupiedExpireTimer();
    if (terminalOccupied) {
      clearRetryTimer();
      clearBg("3_37");
      setQrCenterVisible(false);
      loginCountdownActive = false;
      loginCountdownValue = 0;
      setText(["77_56"], "0");
      hideUserToast();
      setQrCenterStatus(message);
      updateManualRefreshState();
      if (expiresAt) {
        const expiryMs = Date.parse(expiresAt);
        if (!Number.isNaN(expiryMs)) {
          const delay = Math.max(1000, expiryMs - Date.now());
          occupiedExpireTimer = window.setTimeout(() => {
            occupiedExpireTimer = null;
            if (!terminalOccupied) return;
            terminalOccupied = false;
            setQrCenterStatus("");
            void refreshQrCode({ automatic: true });
          }, delay);
        }
      }
      return;
    }
    setQrCenterStatus("");
    hideUserToast();
    updateManualRefreshState();
  }

  function setManualRefreshDisabled(disabled) {
    const btn = q("3_28");
    if (!btn) return;
    btn.classList.toggle("manual-refresh-disabled", !!disabled);
    btn.style.cursor = disabled ? "not-allowed" : "pointer";
  }

  function updateManualRefreshState() {
    setManualRefreshDisabled(
      printerFaultLocked || cloudAccessLocked || terminalActivationRequired || loginQrRefreshing,
    );
  }

  function clearRetryTimer() {
    if (!loginQrRetryTimer) return;
    window.clearTimeout(loginQrRetryTimer);
    loginQrRetryTimer = null;
  }

  function clearAvailabilityPollTimer() {
    if (!availabilityPollTimer) return;
    window.clearInterval(availabilityPollTimer);
    availabilityPollTimer = null;
  }

  function setPrinterFaultLocked(fault) {
    printerFaultLocked = Boolean(fault?.faulted);
    if (printerFaultLocked) {
      clearRetryTimer();
      clearBg("3_37");
      setQrCenterVisible(false);
      updateManualRefreshState();
      loginCountdownActive = false;
      loginCountdownValue = 0;
      setText(["77_56"], "0");
      showUserToast(fault?.message || "打印机故障，请联系管理员处理", "error");
      if (!availabilityPollTimer) {
        availabilityPollTimer = window.setInterval(checkPrinterAvailability, 4000);
      }
    } else {
      clearAvailabilityPollTimer();
      updateManualRefreshState();
    }
  }

  async function checkPrinterAvailability() {
    try {
      const availability = await getJson(api.printerAvailability);
      if (availability?.faulted) {
        setPrinterFaultLocked(availability);
        return false;
      }
      if (printerFaultLocked) {
        setPrinterFaultLocked(null);
        hideUserToast();
        void refreshQrCode();
      }
      return true;
    } catch {
      return !printerFaultLocked;
    }
  }

  function setLoginErrorCountdown(message, errorCode = "") {
    const code = String(errorCode || "").toLowerCase();
    terminalActivationRequired = code === "node_not_found";
    cloudAccessLocked = code === "node_disabled" || code === "printer_disabled";
    updateManualRefreshState();
    showUserToast(message, "error");
    if (terminalActivationRequired) {
      clearRetryTimer();
      loginCountdownActive = false;
      loginCountdownValue = 0;
      setText(["77_56"], "0");
      return;
    }
    loginCountdownValue = loginQrRetryCountdownSeconds;
    loginCountdownActive = true;
    setText(["77_56"], String(loginCountdownValue));
  }

  function setQrRefreshLoading() {
    setQrCenterVisible(false);
  }

  async function refreshQrCode({ automatic = false } = {}) {
    if (loginQrRefreshing || printerFaultLocked || terminalActivationRequired || (cloudAccessLocked && !automatic)) return false;
    clearRetryTimer();
    clearOccupiedExpireTimer();
    terminalOccupied = false;
    const qrWrap = q("3_37");
    clearBg("3_37");
    loginQrRefreshing = true;
    loginCountdownActive = false;
    loginCountdownValue = 0;
    setText(["77_56"], "0");
    updateManualRefreshState();
    setQrRefreshLoading();
    hideUserToast();
    setQrCenterStatus("正在拉取二维码…");

    if (qrWrap) qrWrap.style.opacity = "0.6";

    try {
      const available = await checkPrinterAvailability();
      if (!available) {
        setQrCenterStatus("");
        return false;
      }
      const qr = await getJson(api.qr);
      if (qr?.error_code === "printer_fault") {
        setQrCenterStatus("");
        setPrinterFaultLocked(qr.printer_fault || qr);
        return false;
      }
      if (qr?.standby || qr?.success === false) {
        session.session_id = null;
        setQrCenterStatus("");
        setLoginErrorCountdown(mapQrErrorMessage(qr?.error_code, qr?.message), qr?.error_code);
        return false;
      }
      if (qr?.success && qr.qr_url) {
        session.session_id = qr.session_id || null;
        session.file = {};
        session.runtimeSettings = normalizeRuntimeSettings(qr.settings);
        setOpsContacts(session.runtimeSettings.ops_contacts);
        session.opsContacts = session.runtimeSettings.ops_contacts || [];
        session.defaultPrinterCapabilities =
          qr.default_printer_capabilities && typeof qr.default_printer_capabilities === "object"
            ? qr.default_printer_capabilities
            : null;
        session.capabilityState = createDefaultCapabilityState();
        saveSessionState();
        renderCommonText("login");
        setBg("3_37", qr.qr_url);
        setQrCenterVisible(true);
        setQrCenterStatus("");
        hideUserToast();
        cloudAccessLocked = false;
        terminalActivationRequired = false;
        terminalOccupied = false;
        loginCountdownValue = 60;
        loginCountdownActive = true;
        setText(["77_56"], String(loginCountdownValue));
        return true;
      }
      setQrCenterStatus("");
      setLoginErrorCountdown("二维码响应异常");
      return false;
    } catch (error) {
      session.session_id = null;
      setQrCenterStatus("");
      setLoginErrorCountdown(mapQrErrorMessage(error?.code, error?.message || "二维码获取失败"), error?.code);
      return false;
    } finally {
      if (qrWrap) qrWrap.style.opacity = "1";
      loginQrRefreshing = false;
      updateManualRefreshState();
      if (!loginCountdownActive) {
        setText(["77_56"], "0");
      }
    }
  }

  loginCountdownTimer = window.setInterval(() => {
    if (loginQrRefreshing || terminalOccupied) {
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
      void refreshQrCode({ automatic: true });
    }
  }, 1000);

  loginQrAutoRefreshTimer = window.setInterval(() => {
    if (
      printerFaultLocked ||
      cloudAccessLocked ||
      terminalActivationRequired ||
      terminalOccupied ||
      loginQrRetryTimer ||
      loginQrRefreshing ||
      loginCountdownActive
    ) {
      return;
    }
    loginQrRetryTimer = window.setTimeout(() => {
      loginQrRetryTimer = null;
      if (loginQrRefreshing || loginCountdownActive || terminalOccupied) return;
      void refreshQrCode({ automatic: true });
    }, loginQrRetryIntervalMs);
  }, loginQrRetryIntervalMs);

  setText(["77_56"], "0");
  clearBg("3_37");
  setQrCenterVisible(false);

  on("3_28", () => {
    if (loginQrRefreshing || printerFaultLocked || cloudAccessLocked || terminalActivationRequired) return;
    void refreshQrCode();
  });

  void refreshQrCode();

  return {
    setLoginErrorCountdown,
    setTerminalOccupied,
    destroy() {
      if (loginCountdownTimer) window.clearInterval(loginCountdownTimer);
      if (loginQrAutoRefreshTimer) window.clearInterval(loginQrAutoRefreshTimer);
      clearAvailabilityPollTimer();
      clearRetryTimer();
      clearOccupiedExpireTimer();
    },
  };
}
