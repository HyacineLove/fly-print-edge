function overlayEl() {
  return document.getElementById("adminLoadingOverlay");
}

export function showAdminLoading(message = "加载中...") {
  const el = overlayEl();
  if (!el) return;
  const textEl = el.querySelector('[data-role="loading-text"]');
  if (textEl) {
    textEl.textContent = message;
  }
  el.classList.remove("is-hidden");
}

export function hideAdminLoading() {
  overlayEl()?.classList.add("is-hidden");
}
