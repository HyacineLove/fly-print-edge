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
          body: JSON.stringify({ ipp_uri: item.ipp_uri }),
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

  async function probeIppPrinter() {
    if (state.ippProbing || state.printersRefreshing) return;
    const input = document.getElementById("manualIppUri");
    const ippUri = input instanceof HTMLInputElement ? input.value.trim() : "";
    state.ippProbeUri = ippUri;
    if (!ippUri) {
      showAdminToast("请输入完整的 IPP URI", "error", 3200);
      return;
    }
    state.ippProbing = true;
    state.ippProbeResult = { message: "正在连接并检测打印能力…" };
    render();
    try {
      const result = await requestAdmin("/printers/probe", {
        method: "POST",
        body: JSON.stringify({ ipp_uri: ippUri }),
      });
      const item = result.item;
      if (!item?.compatible) {
        state.ippProbeResult = { message: (item?.issues || []).join("；") || "该设备不兼容" };
        showAdminToast(state.ippProbeResult.message, "error", 4200);
        return;
      }
      state.ippProbeResult = { message: `检测通过：${item.name}` };
      const added = await requestAdmin("/printers/add", {
        method: "POST",
        body: JSON.stringify({ ipp_uri: ippUri }),
      });
      await refreshPrinters({ showToast: false, showOverlay: false });
      showAdminToast(
        added.cloud_error ? `打印机已添加，但云端注册失败: ${added.cloud_error}` : "IPP 打印机已添加",
        added.cloud_error ? "error" : "success",
        4200,
      );
    } catch (error) {
      state.ippProbeResult = { message: error.message || "IPP 检测失败" };
      showAdminToast(state.ippProbeResult.message, "error", 4200);
    } finally {
      state.ippProbing = false;
      render();
    }
  }

  async function clearUnconfirmed(printerId) {
    if (!printerId || isActionPending(state, "clear-unconfirmed", printerId)) return;
    if (!window.confirm("请先确认打印机中没有遗留任务。确定解除结果未知锁定吗？")) return;
    setActionPending(state, "clear-unconfirmed", printerId, true);
    render();
    try {
      const result = await requestAdmin(`/printers/${encodeURIComponent(printerId)}/clear-unconfirmed`, { method: "POST" });
      await loadManaged();
      showAdminToast(result.message || "锁定已解除", "success", 3600);
    } catch (error) {
      showAdminToast(error.message || "解除锁定失败", "error", 3600);
    } finally {
      setActionPending(state, "clear-unconfirmed", printerId, false);
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

  async function testPrinter(printerId) {
    if (!printerId || isActionPending(state, "test", printerId)) return;
    setActionPending(state, "test", printerId, true);
    state.printerTests[printerId] = {
      status: "running",
      current: { message: "正在准备测试打印……" },
    };
    render();
    try {
      const started = await requestAdmin(`/printers/${encodeURIComponent(printerId)}/test`, {
        method: "POST",
      });
      let task;
      do {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        task = await requestAdmin(`/printer-tests/${encodeURIComponent(started.task_id)}`);
        state.printerTests[printerId] = task;
        render();
      } while (task.status === "running");
      showAdminToast(
        task.result?.message || "测试结束",
        task.result?.success ? "success" : "error",
        4200,
      );
    } catch (error) {
      state.printerTests[printerId] = {
        status: "failed",
        result: { success: false, message: error.message || "测试打印失败" },
      };
      showAdminToast(error.message || "测试打印失败", "error", 4200);
    } finally {
      setActionPending(state, "test", printerId, false);
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
      return;
    }
    if (action === "probe-ipp") {
      probeIppPrinter();
      return;
    }
    if (action === "test-printer") {
      testPrinter(target.dataset.id || "");
      return;
    }
    if (action === "clear-unconfirmed") {
      clearUnconfirmed(target.dataset.id || "");
    }
  });

  return { refreshPrinters, ensurePrintersLoaded };
}
