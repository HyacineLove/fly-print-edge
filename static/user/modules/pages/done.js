import { on, setText } from "../shared/dom.js";
import { cleanupAndBackToLogin } from "../shared/runtime.js";
import { state } from "../shared/session-state.js";

let doneReturnCountdownValue = 10;
let doneReturnCountdownTimer = null;

export function initDonePage() {
  const done = state.doneResult || { type: "success", message: "" };
  if (done.type === "error") {
    setText(["77_18"], "打印失败");
    setText(["77_21"], done.message || "云端服务异常，请稍后重试");
  } else {
    setText(["77_18"], "打印完成");
    setText(["77_21"], "请尽快取走您的简历");
  }

  doneReturnCountdownValue = 10;
  setText(["115_39"], String(doneReturnCountdownValue));

  const leave = () => {
    if (doneReturnCountdownTimer) {
      window.clearInterval(doneReturnCountdownTimer);
      doneReturnCountdownTimer = null;
    }
    cleanupAndBackToLogin();
  };

  if (doneReturnCountdownTimer) {
    window.clearInterval(doneReturnCountdownTimer);
    doneReturnCountdownTimer = null;
  }

  doneReturnCountdownTimer = window.setInterval(() => {
    doneReturnCountdownValue = Math.max(0, doneReturnCountdownValue - 1);
    setText(["115_39"], String(doneReturnCountdownValue));
    if (doneReturnCountdownValue === 0) {
      leave();
    }
  }, 1000);

  on("115_40", () => leave());
}
