import { requestAdmin } from "./api.js";
import { hideAdminLoading, showAdminLoading } from "./loading-overlay.js";
import {
  addStaticPrinter,
  buildConfigPayload,
  deepClone,
  removeStaticPrinter,
  updateField,
  updateStaticPrinter,
} from "./state.js";
import { showAdminToast } from "./toast.js";

export async function loadConfig(state, render) {
  const data = await requestAdmin("/config");
  state.config = {
    cloud: data.cloud,
    settings: data.settings,
    network: data.network,
    printers: data.printers,
    meta: data.meta,
  };
  state.initialConfig = deepClone(state.config);
  render();
}

export async function loadCloudStatus(state, render) {
  state.cloudStatus = await requestAdmin("/cloud/status");
  render();
}

function saveSuccessMessage(result) {
  const warnings = Array.isArray(result?.warnings) ? result.warnings.filter(Boolean) : [];
  const restartRequired = Array.isArray(result?.restart_required) ? result.restart_required : [];
  if (restartRequired.length) {
    return `保存完毕，以下配置需重启后生效: ${restartRequired.join("、")}`;
  }
  if (warnings.length) {
    return `保存完毕，注意: ${warnings.join("，")}`;
  }
  return "保存完毕";
}

export function bindConfigActions(state, render, refreshPrinters) {
  const saveBtn = document.getElementById("configSaveBtn");
  const checkBtn = document.getElementById("cloudCheckRegisterBtn");
  const nav = document.querySelector(".admin-nav");
  const panel = document.getElementById("configPanel");

  saveBtn?.addEventListener("click", async () => {
    if (!state.config || state.saving) return;
    state.saving = true;
    render();
    showAdminLoading("保存中...");
    try {
      const result = await requestAdmin("/config", {
        method: "POST",
        body: JSON.stringify(buildConfigPayload(state)),
      });
      state.lastApplyResult = result;
      await Promise.all([
        loadConfig(state, render),
        loadCloudStatus(state, render),
        refreshPrinters({ showToast: false, showOverlay: false }),
      ]);
      showAdminToast(saveSuccessMessage(result), "success");
    } catch (error) {
      showAdminToast(error.message || "保存失败", "error", 3600);
    } finally {
      state.saving = false;
      hideAdminLoading();
      render();
    }
  });

  checkBtn?.addEventListener("click", async () => {
    if (!state.config || state.testingCloud) return;
    state.testingCloud = true;
    render();
    showAdminLoading("检查连接并注册节点中...");
    try {
      const result = await requestAdmin("/cloud/check-register", {
        method: "POST",
        body: JSON.stringify({ cloud: buildConfigPayload(state).cloud }),
      });
      await Promise.all([loadConfig(state, render), loadCloudStatus(state, render)]);
      showAdminToast(result.message || "检查完成", "success");
    } catch (error) {
      showAdminToast(error.message || "检查失败", "error", 3600);
    } finally {
      state.testingCloud = false;
      hideAdminLoading();
      render();
    }
  });

  nav?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const section = target.dataset.section;
    if (!section) return;
    state.activeSection = section;
    render();
  });

  panel?.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (target.dataset.section && target.dataset.key) {
      if (target instanceof HTMLInputElement) {
        updateField(
          state,
          target.dataset.section,
          target.dataset.key,
          target.type === "checkbox" ? target.checked : target.value,
          target.type,
        );
      } else if (target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement) {
        updateField(state, target.dataset.section, target.dataset.key, target.value, "text");
      }
      render();
      return;
    }

    const staticContainer = target.closest("[data-static-index]");
    if (!(staticContainer instanceof HTMLElement)) return;
    const index = Number(staticContainer.dataset.staticIndex);
    const key = target.dataset.staticKey;
    if (!Number.isInteger(index) || !key) return;
    updateStaticPrinter(state, index, key, target.value);
    render();
  });

  panel?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    if (!action) return;
    if (action === "add-static") {
      addStaticPrinter(state);
      render();
      return;
    }
    if (action === "remove-static") {
      removeStaticPrinter(state, Number(target.dataset.index));
      render();
    }
  });
}

export async function loadInitialAdminData(state, render, refreshPrinters) {
  state.loading = true;
  render();
  showAdminLoading("加载中...");
  try {
    await Promise.all([
      loadConfig(state, render),
      loadCloudStatus(state, render),
      refreshPrinters({ showToast: false, showOverlay: false }),
    ]);
  } catch (error) {
    showAdminToast(error.message || "加载失败", "error", 3600);
  } finally {
    state.loading = false;
    hideAdminLoading();
    render();
  }
}
