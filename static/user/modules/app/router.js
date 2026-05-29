export function createRouter({ state, renderView }) {
  return {
    async go(viewName) {
      if (typeof state.viewCleanup === "function") {
        state.viewCleanup();
        state.viewCleanup = null;
      }
      state.currentView = viewName;
      state.viewCleanup = (await renderView(viewName)) || null;
    },
  };
}
