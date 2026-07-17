import {
  createDefaultCapabilityState,
  ensureStateOptions,
  normalizeRuntimeSettings,
  saveSessionState,
  state as sessionState,
} from "../shared/session-state.js";

export function createAppState() {
  ensureStateOptions();
  sessionState.runtimeSettings = normalizeRuntimeSettings(sessionState.runtimeSettings);
  sessionState.capabilityState =
    sessionState.capabilityState && typeof sessionState.capabilityState === "object"
      ? sessionState.capabilityState
      : createDefaultCapabilityState();
  saveSessionState();

  return {
    currentView: "login",
    viewCleanup: null,
    session: sessionState,
    sessionPhase: "idle",
    sseStatus: {
      connected: false,
      connecting: false,
      retryCount: 0,
      lastMessageAt: 0,
    },
    printing: {},
  };
}
