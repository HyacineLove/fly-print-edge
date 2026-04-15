(() => {
  const apiBase = "/api/admin";

  const el = {
    refreshAllBtn: document.getElementById("refreshAllBtn"),
    refreshManagedBtn: document.getElementById("refreshManagedBtn"),
    refreshDiscoveredBtn: document.getElementById("refreshDiscoveredBtn"),
    cloudStatusText: document.getElementById("cloudStatusText"),
    errorBox: document.getElementById("errorBox"),
    managedTbody: document.getElementById("managedTbody"),
    discoveredTbody: document.getElementById("discoveredTbody"),
  };

  const state = {
    managed: [],
    discovered: [],
    defaultPrinterId: "",
    loading: false,
  };

  function showError(message) {
    if (!el.errorBox) return;
    if (!message) {
      el.errorBox.classList.add("is-hidden");
      el.errorBox.textContent = "";
      return;
    }
    el.errorBox.classList.remove("is-hidden");
    el.errorBox.textContent = message;
  }

  async function request(path, options = {}) {
    const res = await fetch(`${apiBase}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.message || `请求失败: ${res.status}`);
    }
    return data;
  }

  function setLoading(loading) {
    state.loading = loading;
    [el.refreshAllBtn, el.refreshManagedBtn, el.refreshDiscoveredBtn].forEach((btn) => {
      if (btn) btn.disabled = loading;
    });
  }

  function printerName(item) {
    return item.name || item.printer_name || item.display_name || "未命名打印机";
  }

  function printerAddr(item) {
    const ip = item.ip || item.host || item.address || "-";
    const port = item.port || item.tcp_port || "-";
    return `${ip}:${port}`;
  }

  function renderManaged() {
    if (!el.managedTbody) return;
    if (!state.managed.length) {
      el.managedTbody.innerHTML = '<tr><td class="muted" colspan="5">暂无已管理打印机</td></tr>';
      return;
    }

    el.managedTbody.innerHTML = state.managed
      .map((item) => {
        const id = item.id || "";
        const isDefault = id && id === state.defaultPrinterId;
        const status = item.enabled === false ? "已禁用" : "可用";
        return `
          <tr>
            <td>
              ${printerName(item)}
              ${isDefault ? '<span class="default-tag">默认</span>' : ""}
            </td>
            <td class="muted">${id || "-"}</td>
            <td class="muted">${printerAddr(item)}</td>
            <td>${status}</td>
            <td>
              <div class="ops">
                <button type="button" class="btn" data-action="default" data-id="${id}" ${isDefault ? "disabled" : ""}>设为默认</button>
                <button type="button" class="btn btn-danger" data-action="delete" data-id="${id}">删除</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function renderDiscovered() {
    if (!el.discoveredTbody) return;
    if (!state.discovered.length) {
      el.discoveredTbody.innerHTML = '<tr><td class="muted" colspan="4">暂无可添加打印机</td></tr>';
      return;
    }

    el.discoveredTbody.innerHTML = state.discovered
      .map((item, index) => {
        const type = item.is_network ? "网络打印机" : "本地打印机";
        return `
          <tr>
            <td>${printerName(item)}</td>
            <td class="muted">${item.type || type}</td>
            <td class="muted">${printerAddr(item)}</td>
            <td>
              <button type="button" class="btn btn-primary" data-action="add" data-index="${index}">添加</button>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function renderCloudStatus(status) {
    if (!el.cloudStatusText) return;

    el.cloudStatusText.classList.remove("status-ok", "status-warn");
    if (!status || status.success === false) {
      el.cloudStatusText.textContent = "云端状态: 获取失败";
      el.cloudStatusText.classList.add("status-warn");
      return;
    }

    const enabled = !!status.enabled;
    const connected = !!status.connected;
    const registered = !!status.registered;

    if (!enabled) {
      el.cloudStatusText.textContent = "云端状态: 未启用";
      el.cloudStatusText.classList.add("status-warn");
      return;
    }

    if (connected && registered) {
      el.cloudStatusText.textContent = `云端状态: 已连接 (节点 ${status.node_id || "-"})`;
      el.cloudStatusText.classList.add("status-ok");
      return;
    }

    el.cloudStatusText.textContent = `云端状态: 未连接 (${status.message || "异常"})`;
    el.cloudStatusText.classList.add("status-warn");
  }

  async function loadManaged() {
    const data = await request("/printers/managed");
    state.managed = Array.isArray(data.items) ? data.items : [];
    state.defaultPrinterId = data.default_printer_id || "";
    renderManaged();
  }

  async function loadDiscovered() {
    const data = await request("/printers/discovered");
    state.discovered = Array.isArray(data.items) ? data.items : [];
    renderDiscovered();
  }

  async function loadCloudStatus() {
    const data = await request("/cloud/status");
    renderCloudStatus(data);
  }

  async function loadAll() {
    showError("");
    setLoading(true);
    try {
      await Promise.all([loadManaged(), loadDiscovered(), loadCloudStatus()]);
    } catch (err) {
      showError(err.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function setDefaultPrinter(printerId) {
    if (!printerId) return;
    showError("");
    try {
      await request("/printers/default", {
        method: "POST",
        body: JSON.stringify({ printer_id: printerId }),
      });
      await loadManaged();
    } catch (err) {
      showError(err.message || "设置默认打印机失败");
    }
  }

  async function deletePrinter(printerId) {
    if (!printerId) return;
    if (!window.confirm("确认删除该打印机吗？")) return;

    showError("");
    try {
      await request(`/printers/${encodeURIComponent(printerId)}`, { method: "DELETE" });
      await Promise.all([loadManaged(), loadDiscovered()]);
    } catch (err) {
      showError(err.message || "删除打印机失败");
    }
  }

  async function addPrinterByIndex(index) {
    const item = state.discovered[index];
    if (!item) return;

    showError("");
    try {
      await request("/printers/add", {
        method: "POST",
        body: JSON.stringify(item),
      });
      await Promise.all([loadManaged(), loadDiscovered()]);
    } catch (err) {
      showError(err.message || "添加打印机失败");
    }
  }

  function bindEvents() {
    el.refreshAllBtn?.addEventListener("click", loadAll);
    el.refreshManagedBtn?.addEventListener("click", () => {
      loadManaged().catch((err) => showError(err.message || "刷新已管理失败"));
    });
    el.refreshDiscoveredBtn?.addEventListener("click", () => {
      loadDiscovered().catch((err) => showError(err.message || "刷新可添加失败"));
    });

    el.managedTbody?.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.dataset.action;
      const id = target.dataset.id || "";
      if (action === "default") {
        setDefaultPrinter(id);
      } else if (action === "delete") {
        deletePrinter(id);
      }
    });

    el.discoveredTbody?.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.dataset.action;
      const index = Number(target.dataset.index);
      if (action === "add" && Number.isInteger(index)) {
        addPrinterByIndex(index);
      }
    });
  }

  bindEvents();
  loadAll();
})();
