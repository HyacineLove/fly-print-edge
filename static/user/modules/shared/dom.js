export function q(id) {
  return document.getElementById(id);
}

export function on(id, fn) {
  const el = q(id);
  if (el) el.addEventListener("click", fn);
}

export function setText(ids, text) {
  ids.forEach((id) => {
    const el = q(id);
    if (el) el.textContent = text;
  });
}

export function setBg(id, url) {
  const el = q(id);
  if (!el || !url) return;
  el.style.backgroundImage = `url(${url})`;
  el.style.backgroundSize = "cover";
  el.style.backgroundPosition = "center";
}

export function clearBg(id) {
  const el = q(id);
  if (!el) return;
  el.style.backgroundImage = "none";
}

export function setPreviewBg(id, url) {
  const el = q(id);
  if (!el || !url) return;
  el.style.backgroundImage = `url(${url})`;
  el.style.backgroundSize = "contain";
  el.style.backgroundPosition = "center";
  el.style.backgroundRepeat = "no-repeat";
  el.style.backgroundColor = "#ffffff";
}
