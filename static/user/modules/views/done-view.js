import { on, setText } from "../shared/dom.js";

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
  if (result.type === "error") {
    setText(["77_18"], "打印失败");
    setText(["77_21"], result.message || "云端服务异常，请稍后重试");
  } else {
    setText(["77_18"], "打印完成");
    setText(["77_21"], "请尽快取走您的简历");
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
