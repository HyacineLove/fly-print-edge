import { api } from "./api.js";

export function createSseConnection({ onMessage } = {}) {
  let currentEventSource = null;
  let retryTimer = null;

  function close() {
    if (currentEventSource) {
      try {
        currentEventSource.close();
      } catch {
        // no-op
      }
      currentEventSource = null;
    }
    if (retryTimer) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
  }

  function start() {
    close();
    const es = new EventSource(api.events);
    currentEventSource = es;

    es.onmessage = (ev) => {
      let raw;
      try {
        raw = JSON.parse(ev.data);
      } catch {
        return;
      }
      const type = raw.type || raw?.data?.type || "";
      const data =
        raw.data && typeof raw.data === "object"
          ? raw.data
          : raw;
      if (!type) return;
      onMessage?.({ type, data });
    };

    es.onerror = () => {
      if (retryTimer) {
        window.clearTimeout(retryTimer);
      }
      retryTimer = window.setTimeout(() => {
        try {
          es.close();
        } catch {
          // no-op
        }
        if (currentEventSource === es) {
          start();
        }
      }, 2000);
    };
  }

  window.addEventListener("beforeunload", close);
  return { start, close };
}
