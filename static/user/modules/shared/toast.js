import { q } from "./dom.js";

let hideTimer = null;

function getToastEl() {
  return q("userToast");
}

export function showUserToast(message, tone = "info", autoHideMs = 0) {
  const el = getToastEl();
  if (!el) return;
  if (hideTimer) {
    window.clearTimeout(hideTimer);
    hideTimer = null;
  }

  el.textContent = message || "";
  el.classList.remove("is-hidden", "is-info", "is-success", "is-error");
  el.classList.add(`is-${tone}`);

  if (autoHideMs > 0) {
    hideTimer = window.setTimeout(() => {
      hideUserToast();
    }, autoHideMs);
  }
}

export function hideUserToast() {
  const el = getToastEl();
  if (!el) return;
  if (hideTimer) {
    window.clearTimeout(hideTimer);
    hideTimer = null;
  }
  el.classList.add("is-hidden");
  el.classList.remove("is-info", "is-success", "is-error");
  el.textContent = "";
}
