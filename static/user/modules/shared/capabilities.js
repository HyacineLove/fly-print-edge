import { q } from "./dom.js";
import { state, saveSessionState } from "./session-state.js";

export function capabilityValues(rawValue) {
  if (Array.isArray(rawValue)) {
    return rawValue.map((item) => String(item || "").toLowerCase()).filter(Boolean);
  }
  if (rawValue == null) return [];
  return [String(rawValue).toLowerCase()];
}

export function supportsDuplex(capabilities) {
  return capabilityValues(capabilities?.duplex).some((value) => {
    return (
      value !== "none" &&
      value !== "simplex" &&
      (value.includes("duplex") || value.includes("long") || value.includes("short"))
    );
  });
}

export function supportsColor(capabilities) {
  return capabilityValues(capabilities?.color_model).some((value) => {
    return value.includes("rgb") || value.includes("color") || value.includes("colour");
  });
}

export function applyPrinterCapabilityState(capabilities) {
  const capabilityState = {
    duplexSupported: supportsDuplex(capabilities),
    colorSupported: supportsColor(capabilities),
  };
  state.defaultPrinterCapabilities =
    capabilities && typeof capabilities === "object" ? capabilities : null;
  state.capabilityState = capabilityState;

  if (!capabilityState.duplexSupported) {
    state.options.duplex = "simplex";
  }
  if (!capabilityState.colorSupported) {
    state.options.color_mode = "mono";
  }

  saveSessionState();
  return capabilityState;
}

export function setOptionDisabledState(ids, disabled) {
  ids.forEach((id) => {
    const el = q(id);
    if (!el) return;
    el.classList.toggle("is-option-disabled", disabled);
    el.style.pointerEvents = disabled ? "none" : "auto";
    el.style.cursor = disabled ? "not-allowed" : "pointer";
    el.setAttribute("aria-disabled", disabled ? "true" : "false");
  });
}
