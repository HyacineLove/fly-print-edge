import { requestAdmin } from "./api.js";
import { hideAdminLoading, showAdminLoading } from "./loading-overlay.js";
import { isActionPending, setActionPending } from "./state.js";
import { showAdminToast } from "./toast.js";

export function bindPrinterActions(state, render) {
  function withPrinterOverlay(message, task) {
    showAdminLoading(message);
    return Promise.resolve()
      .then(task)
      .finally(() => {
        hideAdminLoading();
      });
  }

  async function loadManaged() {
    const data = await requestAdmin("/printers/managed");
    state.managed = Array.isArray(data.items) ? data.items : [];
    state.defaultPrinterId = data.default_printer_id || "";
  }

  async function loadDiscovered() {
    const data = await requestAdmin("/printers/discovered");
    state.discovered = Array.isArray(data.items) ? data.items : [];
  }

  async function refreshPrinters(options = {}) {
    const { showToast = true, showOverlay = true } = options;
    state.printersRefreshing = true;
    render();
    try {
      await (showOverlay
        ? withPrinterOverlay("刷新打印机中...", () => Promise.all([loadManaged(), loadDiscovered()]))
        : Promise.all([loadManaged(), loadDiscovered()]));
      state.printersLoadedOnce = true;
      state.printersInvalidated = false;
      if (showToast) {
        showAdminToast("刷新完成", "success");
      }
    } catch (error) {
      if (showToast) {
        showAdminToast(error.message || "刷新失败", "error", 3600);
      }
      throw error;
    } finally {
      state.printersRefreshing = false;
      render();
    }
  }

  async function ensurePrintersLoaded(options = {}) {
    const { force = false, showToast = false, showOverlay = false } = options;
    if (state.printersRefreshing) {
      return;
    }
    if (!force && state.printersLoadedOnce && !state.printersInvalidated) {
      return;
    }
    await refreshPrinters({ showToast, showOverlay });
  }

  async function setDefaultPrinter(printerId) {
    if (!printerId || isActionPending(state, "default", printerId)) return;
    setActionPending(state, "default", printerId, true);
    render();
    try {
      await requestAdmin("/printers/default", {
        method: "POST",
        body: JSON.stringify({ printer_id: printerId }),
      });
      await loadManaged();
      render();
      showAdminToast("默认打印机已更新", "success");
    } catch (error) {
      showAdminToast(error.message || "设置默认打印机失败", "error", 3600);
    } finally {
      setActionPending(state, "default", printerId, false);
      render();
    }
  }

  async function deletePrinter(printerId) {
    if (!printerId || isActionPending(state, "delete", printerId)) return;
    if (!window.confirm("确认删除该打印机吗？")) return;
    setActionPending(state, "delete", printerId, true);
    render();
    try {
      const result = await withPrinterOverlay("删除中...", async () => {
        const response = await requestAdmin(`/printers/${encodeURIComponent(printerId)}`, { method: "DELETE" });
        await refreshPrinters({ showToast: false, showOverlay: false });
        return response;
      });
      showAdminToast(result.warning || "打印机已删除", result.warning ? "error" : "success", 3200);
    } catch (error) {
      showAdminToast(error.message || "删除打印机失败", "error", 3600);
    } finally {
      setActionPending(state, "delete", printerId, false);
      render();
    }
  }

  async function addPrinterByIndex(index) {
    const item = state.discovered[index];
    if (!item || isActionPending(state, "add", index)) return;
    setActionPending(state, "add", index, true);
    render();
    try {
      const result = await withPrinterOverlay("添加中...", async () => {
        const response = await requestAdmin("/printers/add", {
          method: "POST",
          body: JSON.stringify(item),
        });
        await refreshPrinters({ showToast: false, showOverlay: false });
        return response;
      });
      if (result.cloud_error) {
        showAdminToast(`打印机已添加，但云端注册失败: ${result.cloud_error}`, "error", 4200);
      } else {
        showAdminToast("打印机已添加", "success");
      }
    } catch (error) {
      showAdminToast(error.message || "添加打印机失败", "error", 3600);
    } finally {
      setActionPending(state, "add", index, false);
      render();
    }
  }

  async function reregisterPrinter(printerId) {
    if (!printerId || isActionPending(state, "reregister", printerId)) return;
    setActionPending(state, "reregister", printerId, true);
    render();
    try {
      const result = await withPrinterOverlay("重新注册中...", async () => {
        const response = await requestAdmin(`/printers/${encodeURIComponent(printerId)}/reregister`, { method: "POST" });
        await loadManaged();
        return response;
      });
      render();
      showAdminToast(result.message || "打印机已重新注册到云端", "success");
    } catch (error) {
      showAdminToast(error.message || "重新注册打印机失败", "error", 3600);
    } finally {
      setActionPending(state, "reregister", printerId, false);
      render();
    }
  }

  document.getElementById("configPanel")?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    if (!action) return;

    if (action === "refresh-printers") {
      refreshPrinters().catch(() => {});
      return;
    }
    if (action === "default") {
      setDefaultPrinter(target.dataset.id || "");
      return;
    }
    if (action === "delete") {
      deletePrinter(target.dataset.id || "");
      return;
    }
    if (action === "add") {
      addPrinterByIndex(Number(target.dataset.index));
      return;
    }
    if (action === "reregister-printer") {
      reregisterPrinter(target.dataset.id || "");
    }
  });

  return { refreshPrinters, ensurePrintersLoaded };
}
