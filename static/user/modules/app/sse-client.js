import { api } from "../shared/api.js";

export class UserSseClient {
  constructor({ onMessage, onStatusChange } = {}) {
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
    this.eventSource = null;
    this.retryTimer = null;
    this.retryCount = 0;
    this.closed = false;
    this.handleBeforeUnload = () => this.stop();
  }

  start() {
    this.closed = false;
    window.addEventListener("beforeunload", this.handleBeforeUnload);
    this.#connect();
  }

  stop() {
    this.closed = true;
    window.removeEventListener("beforeunload", this.handleBeforeUnload);
    if (this.retryTimer) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.eventSource) {
      try {
        this.eventSource.close();
      } catch {
        // no-op
      }
      this.eventSource = null;
    }
    this.onStatusChange?.({
      connected: false,
      connecting: false,
      retryCount: this.retryCount,
    });
  }

  #connect() {
    if (this.closed) return;

    if (this.eventSource) {
      try {
        this.eventSource.close();
      } catch {
        // no-op
      }
      this.eventSource = null;
    }

    this.onStatusChange?.({
      connected: false,
      connecting: true,
      retryCount: this.retryCount,
    });

    const es = new EventSource(api.events);
    this.eventSource = es;

    es.onopen = () => {
      this.retryCount = 0;
      this.onStatusChange?.({
        connected: true,
        connecting: false,
        retryCount: this.retryCount,
      });
    };

    es.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      this.onMessage?.(payload);
    };

    es.onerror = () => {
      if (this.closed) return;
      this.retryCount += 1;
      this.onStatusChange?.({
        connected: false,
        connecting: false,
        retryCount: this.retryCount,
      });
      if (this.retryTimer) {
        window.clearTimeout(this.retryTimer);
      }
      this.retryTimer = window.setTimeout(() => {
        this.retryTimer = null;
        this.#connect();
      }, 2000);
    };
  }
}
