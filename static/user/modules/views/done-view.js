import { on, setText } from "../shared/dom.js";
import { api, getJson } from "../shared/api.js";

export function renderDoneView() {
  return `
<div class="scroll-container-0_1">
  <div id="0_1" class="Pixso-canvas-0_1">
    <div id="55_158" class="Pixso-frame-55_158 fill-bg-gradient">
      <div id="115_17" class="Pixso-rectangle-115_17"></div>
      <p id="115_21" class="Pixso-paragraph-115_21">2025/01/01 10:00:00</p>
      <div id="77_17" class="Pixso-rectangle-77_17"></div>
      <p id="77_18" class="Pixso-paragraph-77_18"></p>
      <p id="77_21" class="Pixso-paragraph-77_21"></p>
      <div id="115_40" class="Pixso-group-115_40" style="cursor: pointer;">
        <div id="115_41" class="Pixso-rectangle-115_41 fill-primary-gradient"></div>
        <p id="115_42" class="Pixso-paragraph-115_42"></p>
        <div id="115_37" class="Pixso-group-115_37">
          <div id="115_38" class="Pixso-vector-115_38"></div>
          <p id="115_39" class="Pixso-paragraph-115_39">10</p>
        </div>
      </div>
      <p id="115_26" class="Pixso-paragraph-115_26"></p>
    </div>
  </div>
</div>
`;
}

export function bindDoneViewEvents({ appState, restartCycle }) {
  const result = appState.session.doneResult || { type: "success", message: "" };
  let availabilityPollTimer = null;
  const printerFaultCodes = new Set([
    "printer_fault",
    "printer_out_of_paper",
    "printer_out_of_toner",
    "printer_jammed",
    "printer_cover_open",
    "printer_offline",
    "printer_user_intervention",
  ]);
  const unconfirmedCodes = new Set([
    "result_unconfirmed",
    "ipp_submission_unconfirmed",
    "ipp_job_query_failed",
    "ipp_cancel_failed",
  ]);

  function isPrinterFaultResult() {
    return result.type === "error" && printerFaultCodes.has(result.error_code);
  }

  function isUnconfirmedResult() {
    return result.type === "error" && unconfirmedCodes.has(result.error_code);
  }

  function setReturnEnabled(enabled) {
    const button = document.getElementById("115_40");
    if (!button) return;
    button.style.pointerEvents = enabled ? "auto" : "none";
    button.style.opacity = enabled ? "1" : "0.45";
    button.style.cursor = enabled ? "pointer" : "not-allowed";
  }

  function setCountdownAccessoryVisible(visible) {
    const accessory = document.getElementById("115_37");
    if (accessory) accessory.style.display = visible ? "" : "none";
    if (!visible) setText(["115_39"], "");
  }

  if (isPrinterFaultResult() || isUnconfirmedResult()) {
    const unconfirmed = isUnconfirmedResult();
    setText(["77_18"], unconfirmed ? "结果待确认" : "设备维护中");
    setText(["77_21"], result.message || (unconfirmed ? "请勿重复提交，请联系工作人员。" : "打印机故障，请联系管理员处理"));
    setText(["115_42"], unconfirmed ? "等待管理员处理" : "等待恢复");
    setCountdownAccessoryVisible(false);
    setReturnEnabled(false);

    const pollAvailability = async () => {
      try {
        const availability = await getJson(api.printerAvailability);
        if (!availability?.faulted) {
          if (availabilityPollTimer) {
            window.clearInterval(availabilityPollTimer);
            availabilityPollTimer = null;
          }
          setText(["77_21"], unconfirmed ? "管理员已解除锁定，可返回首页继续使用" : "打印机已恢复，可返回首页继续使用");
          setText(["115_42"], "返回首页");
          setCountdownAccessoryVisible(false);
          setReturnEnabled(true);
        }
      } catch {
        // Keep the locked state until a positive recovery signal is observed.
      }
    };

    availabilityPollTimer = window.setInterval(pollAvailability, 4000);
    void pollAvailability();
    on("115_40", () => {
      if (availabilityPollTimer) return;
      void restartCycle();
    });

    return {
      destroy() {
        if (availabilityPollTimer) window.clearInterval(availabilityPollTimer);
      },
    };
  }
  if (result.type === "error") {
    setCountdownAccessoryVisible(true);
    setText(["77_18"], "打印失败");
    setText(["77_21"], result.message || "云端服务异常，请稍后重试");
  } else {
    setCountdownAccessoryVisible(true);
    setText(["77_18"], "打印完成");
    setText(["77_21"], "请尽快取走您的文件");
  }

  let countdownValue = 10;
  setText(["115_39"], String(countdownValue));

  const leave = () => {
    if (countdownTimer) {
      window.clearInterval(countdownTimer);
      countdownTimer = null;
    }
    void restartCycle();
  };

  let countdownTimer = window.setInterval(() => {
    countdownValue = Math.max(0, countdownValue - 1);
    setText(["115_39"], String(countdownValue));
    if (countdownValue === 0) {
      leave();
    }
  }, 1000);

  on("115_40", () => leave());

  return {
    destroy() {
      if (countdownTimer) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
      }
    },
  };
}
