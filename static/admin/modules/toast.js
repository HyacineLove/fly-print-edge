let hideTimer = null;

function toastEl() {
  return document.getElementById("adminToast");
}

export function showAdminToast(message, tone = "info", autoHideMs = 2400) {
  const el = toastEl();
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
      hideAdminToast();
    }, autoHideMs);
  }
}

export function hideAdminToast() {
  const el = toastEl();
  if (!el) return;
  if (hideTimer) {
    window.clearTimeout(hideTimer);
    hideTimer = null;
  }
  el.classList.add("is-hidden");
  el.classList.remove("is-info", "is-success", "is-error");
  el.textContent = "";
}
