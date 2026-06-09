const stateKey = "fly_print_state";

export const defaultPaperSize = "A4";
export const defaultScaleMode = "actual";
export const defaultMaxUpscale = 3;

export function createDefaultOptions() {
  return {
    copies: 1,
    duplex: "simplex",
    color_mode: "color",
    scale_mode: defaultScaleMode,
    paper_size: defaultPaperSize,
    max_upscale: defaultMaxUpscale,
  };
}

function loadState() {
  try {
    const raw = sessionStorage.getItem(stateKey);
    return raw
      ? JSON.parse(raw)
      : {
          options: createDefaultOptions(),
          file: {},
          pendingPrintRequest: null,
        };
  } catch {
    return {
      options: createDefaultOptions(),
      file: {},
      pendingPrintRequest: null,
    };
  }
}

export function normalizeScaleMode(value) {
  const mode = String(value || "").toLowerCase();
  if (mode === "actual" || mode === "fill" || mode === "fit") return mode;
  return defaultScaleMode;
}

export function normalizeMaxUpscale(value) {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num : defaultMaxUpscale;
}

export function normalizeRuntimeSettings(rawSettings) {
  const settings = rawSettings && typeof rawSettings === "object" ? rawSettings : {};
  const copiesMin = Math.max(1, Number.parseInt(settings.copies_min, 10) || 1);
  const parsedMax = Number.parseInt(settings.copies_max, 10) || 3;
  const copiesMax = Math.max(copiesMin, parsedMax);
  return {
    copies_min: copiesMin,
    copies_max: copiesMax,
  };
}

export function createDefaultCapabilityState() {
  return {
    duplexSupported: false,
    colorSupported: false,
  };
}

export const state = loadState();
state.runtimeSettings = normalizeRuntimeSettings(state.runtimeSettings);
state.capabilityState =
  state.capabilityState && typeof state.capabilityState === "object"
    ? state.capabilityState
    : createDefaultCapabilityState();

export function getCopyLimitState() {
  const normalized = normalizeRuntimeSettings(state.runtimeSettings);
  state.runtimeSettings = normalized;
  return {
    min: normalized.copies_min,
    max: normalized.copies_max,
  };
}

export function normalizeCopies(value) {
  const { min, max } = getCopyLimitState();
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return min;
  return Math.min(max, Math.max(min, parsed));
}

export function ensureStateOptions() {
  const merged = {
    ...createDefaultOptions(),
    ...(state.options && typeof state.options === "object" ? state.options : {}),
  };
  merged.copies = normalizeCopies(merged.copies);
  merged.scale_mode = normalizeScaleMode(merged.scale_mode);
  merged.paper_size = String(merged.paper_size || defaultPaperSize);
  merged.max_upscale = normalizeMaxUpscale(merged.max_upscale);
  state.options = merged;
}

ensureStateOptions();

export function saveSessionState() {
  sessionStorage.setItem(stateKey, JSON.stringify(state));
}

export function setPendingPrintRequest(request) {
  state.pendingPrintRequest = request || null;
  saveSessionState();
}

export function clearPendingPrintRequest() {
  state.pendingPrintRequest = null;
  saveSessionState();
}

export function currentSessionId() {
  return state.session_id || "";
}

export function setDoneResult(type, message, extra = {}) {
  state.doneResult = {
    type: type || "success",
    message: message || "",
    ts: Date.now(),
    ...(extra && typeof extra === "object" ? extra : {}),
  };
  saveSessionState();
}
