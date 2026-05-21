(() => {
  const apiBase = "/api/admin";

  const el = {
    configSaveBtn: document.getElementById("configSaveBtn"),
    cloudCheckRegisterBtn: document.getElementById("cloudCheckRegisterBtn"),
    configStatusText: document.getElementById("configStatusText"),
    cloudStatusText: document.getElementById("cloudStatusText"),
    restartHintText: document.getElementById("restartHintText"),
    errorBox: document.getElementById("errorBox"),
    resultBox: document.getElementById("resultBox"),
    nav: document.querySelector(".admin-nav"),
    configPanel: document.getElementById("configPanel"),
  };

  const state = {
    config: null,
    initialConfig: null,
    activeSection: "overview",
    saving: false,
    testingCloud: false,
    loading: false,
    managed: [],
    discovered: [],
    defaultPrinterId: "",
    cloudStatus: null,
    lastApplyResult: null,
    pendingActions: new Set(),
  };

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

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

  function showResult(message, warning = false) {
    if (!el.resultBox) return;
    if (!message) {
      el.resultBox.classList.add("is-hidden");
      el.resultBox.classList.remove("warning");
      el.resultBox.textContent = "";
      return;
    }
    el.resultBox.classList.remove("is-hidden");
    el.resultBox.classList.toggle("warning", warning);
    el.resultBox.textContent = message;
  }

  async function request(path, options = {}) {
    const res = await fetch(`${apiBase}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.message || (Array.isArray(data.errors) ? data.errors.join("；") : `请求失败: ${res.status}`));
    }
    return data;
  }

  function configModel() {
    if (!state.config) {
      return {
        cloud: {},
        settings: {},
        network: {},
        printers: { static_list: [] },
        meta: { restart_required_fields: [], masked_fields: [] },
      };
    }
    return state.config;
  }

  function buildConfigPayload() {
    const cfg = configModel();
    const rawMaxUpscale = cfg.settings.default_max_upscale;
    const normalizedMaxUpscale = rawMaxUpscale === "" || rawMaxUpscale == null ? "" : Number(rawMaxUpscale);
    return {
      cloud: {
        base_url: cfg.cloud.base_url || "",
        auth_url: cfg.cloud.auth_url || "",
        client_id: cfg.cloud.client_id || "",
        client_secret: cfg.cloud.client_secret || "",
        node_name: cfg.cloud.node_name || "",
        location: cfg.cloud.location || "",
        heartbeat_interval: Number(cfg.cloud.heartbeat_interval || 30),
      },
      settings: {
        default_paper_size: cfg.settings.default_paper_size || "",
        default_scale_mode: cfg.settings.default_scale_mode || "",
        default_max_upscale: normalizedMaxUpscale,
        libreoffice_path: cfg.settings.libreoffice_path || "",
        pdf_printer_path: cfg.settings.pdf_printer_path || "",
      },
      network: {
        bind_address: cfg.network.bind_address || "",
        port: Number(cfg.network.port || 0),
      },
      printers: {
        discovery_mode: cfg.printers.discovery_mode || "auto",
        static_list: Array.isArray(cfg.printers.static_list)
          ? cfg.printers.static_list.map((item) => ({
              name: item.name || "",
              ip: item.ip || "",
              protocol: item.protocol || "ipp",
              port: item.port === "" || item.port == null ? "" : Number(item.port),
            }))
          : [],
      },
    };
  }

  function isDirty() {
    if (!state.config || !state.initialConfig) return false;
    return JSON.stringify(state.config) !== JSON.stringify(state.initialConfig);
  }

  function actionKey(action, value) {
    return `${action}:${value}`;
  }

  function isActionPending(action, value) {
    return state.pendingActions.has(actionKey(action, value));
  }

  function setActionPending(action, value, pending) {
    const key = actionKey(action, value);
    if (pending) {
      state.pendingActions.add(key);
    } else {
      state.pendingActions.delete(key);
    }
  }

  function printerName(item) {
    return item.name || item.printer_name || item.display_name || "未命名打印机";
  }

  function printerAddr(item) {
    const ip = item.ip || item.host || item.address || "-";
    const port = item.port || item.tcp_port || "-";
    return `${ip}:${port}`;
  }

  function restartRequiredHint() {
    const apply = state.lastApplyResult;
    return apply && Array.isArray(apply.restart_required) && apply.restart_required.length > 0;
  }

  function updateToolbar() {
    if (el.configSaveBtn) {
      el.configSaveBtn.disabled = state.saving || !state.config || !isDirty();
      el.configSaveBtn.textContent = state.saving ? "保存中..." : "保存配置";
    }
    if (el.cloudCheckRegisterBtn) {
      el.cloudCheckRegisterBtn.disabled = state.testingCloud || !state.config;
      el.cloudCheckRegisterBtn.textContent = state.testingCloud ? "检测中..." : "检测连接并注册节点";
    }
    if (el.configStatusText) {
      const text = !state.config
        ? "配置状态: 未加载"
        : isDirty()
          ? "配置状态: 有未保存变更"
          : "配置状态: 已同步";
      el.configStatusText.textContent = text;
      el.configStatusText.classList.remove("status-ok", "status-warn", "status-info");
      el.configStatusText.classList.add(isDirty() ? "status-warn" : "status-ok");
    }
    if (el.restartHintText) {
      el.restartHintText.classList.toggle("is-hidden", !restartRequiredHint());
    }
  }

  function renderCloudStatus(status) {
    state.cloudStatus = status || null;
    if (!el.cloudStatusText) return;

    el.cloudStatusText.classList.remove("status-ok", "status-warn", "status-info");
    if (!status || status.success === false) {
      el.cloudStatusText.textContent = "云端状态: 不可用";
      el.cloudStatusText.classList.add("status-warn");
      return;
    }

    if (!status.configured) {
      el.cloudStatusText.textContent = "云端状态: 配置不完整";
      el.cloudStatusText.classList.add("status-warn");
      return;
    }

    if (status.connected) {
      el.cloudStatusText.textContent = "云端状态: 已连接";
      el.cloudStatusText.classList.add("status-ok");
      return;
    }

    if (status.registered) {
      el.cloudStatusText.textContent = "云端状态: 等待连接";
      el.cloudStatusText.classList.add("status-info");
      return;
    }

    el.cloudStatusText.textContent = "云端状态: 待注册节点";
    el.cloudStatusText.classList.add("status-info");
  }

  function renderOverview() {
    const cfg = configModel();
    const cloudStatus = state.cloudStatus || {};
    const staticCount = (cfg.printers.static_list || []).length;
    const cloudValue = !cloudStatus.configured
      ? "未配置"
      : cloudStatus.connected
        ? "已连接"
        : cloudStatus.registered
          ? "等待连接"
          : "待注册";

    return `
      <div class="section-header">
        <div>
          <h2>概览</h2>
          <p>查看当前配置与运行状态。</p>
        </div>
      </div>
      <div class="overview-grid">
        <article class="overview-card">
          <h3>云端</h3>
          <div class="overview-value">${cloudValue}</div>
          <ul class="overview-list">
            <li>节点 ID: ${cloudStatus.node_id || cfg.cloud.node_id || "-"}</li>
            <li>云端地址: ${cfg.cloud.base_url || "-"}</li>
          </ul>
        </article>
        <article class="overview-card">
          <h3>打印默认设置</h3>
          <div class="overview-value">${cfg.settings.default_paper_size || "A4"}</div>
          <ul class="overview-list">
            <li>缩放模式: ${cfg.settings.default_scale_mode || "fit"}</li>
            <li>最大放大倍数: ${cfg.settings.default_max_upscale || 3.0}</li>
          </ul>
        </article>
        <article class="overview-card">
          <h3>打印机</h3>
          <div class="overview-value">${state.managed.length}</div>
          <ul class="overview-list">
            <li>已管理打印机</li>
            <li>发现模式: ${cfg.printers.discovery_mode || "auto"}</li>
            <li>静态条目: ${staticCount}</li>
          </ul>
        </article>
      </div>
    `;
  }

  function renderCloudSection() {
    const cfg = configModel().cloud;
    const nodeId = (state.cloudStatus && state.cloudStatus.node_id) || cfg.node_id || "-";
    return `
      <div class="section-header">
        <div>
          <h2>云端配置</h2>
          <p>先保存配置，再执行云端检测与节点注册。</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="field">
          <label for="cloud_base_url">云端地址</label>
          <input id="cloud_base_url" data-section="cloud" data-key="base_url" value="${cfg.base_url || ""}">
        </div>
        <div class="field">
          <label for="cloud_auth_url">认证地址</label>
          <input id="cloud_auth_url" data-section="cloud" data-key="auth_url" value="${cfg.auth_url || ""}">
        </div>
        <div class="field">
          <label for="cloud_client_id">客户端 ID</label>
          <input id="cloud_client_id" data-section="cloud" data-key="client_id" value="${cfg.client_id || ""}">
        </div>
        <div class="field">
          <label for="cloud_client_secret">客户端密钥</label>
          <input id="cloud_client_secret" type="password" data-section="cloud" data-key="client_secret" value="" placeholder="${cfg.client_secret_configured ? "已设置" : "未设置"}">
        </div>
        <div class="field">
          <label for="cloud_node_name">节点名称</label>
          <input id="cloud_node_name" data-section="cloud" data-key="node_name" value="${cfg.node_name || ""}">
        </div>
        <div class="field">
          <label for="cloud_location">位置</label>
          <input id="cloud_location" data-section="cloud" data-key="location" value="${cfg.location || ""}">
        </div>
        <div class="field">
          <label for="cloud_heartbeat_interval">心跳间隔(秒)</label>
          <input id="cloud_heartbeat_interval" type="number" min="1" data-section="cloud" data-key="heartbeat_interval" value="${cfg.heartbeat_interval || 30}">
        </div>
        <div class="field">
          <label>当前节点 ID</label>
          <input value="${nodeId}" disabled>
        </div>
      </div>
    `;
  }

  function renderSettingsSection() {
    const cfg = configModel().settings;
    return `
      <div class="section-header">
        <div>
          <h2>打印默认设置</h2>
          <p>这些设置会写入配置，并在后续打印流程中使用。</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="field">
          <label for="settings_default_paper_size">默认纸张</label>
          <input id="settings_default_paper_size" data-section="settings" data-key="default_paper_size" value="${cfg.default_paper_size || "A4"}">
        </div>
        <div class="field">
          <label for="settings_default_scale_mode">默认缩放模式</label>
          <select id="settings_default_scale_mode" data-section="settings" data-key="default_scale_mode">
            ${["fit", "actual", "fill"].map((mode) => `<option value="${mode}" ${String(cfg.default_scale_mode || "fit") === mode ? "selected" : ""}>${mode}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="settings_default_max_upscale">最大放大倍数</label>
          <input id="settings_default_max_upscale" type="number" min="0.1" step="0.1" data-section="settings" data-key="default_max_upscale" value="${cfg.default_max_upscale ?? 3.0}">
        </div>
        <div class="field">
          <label for="settings_libreoffice_path">LibreOffice 路径</label>
          <input id="settings_libreoffice_path" data-section="settings" data-key="libreoffice_path" value="${cfg.libreoffice_path || ""}">
        </div>
        <div class="field">
          <label for="settings_pdf_printer_path">PDF 打印工具路径</label>
          <input id="settings_pdf_printer_path" data-section="settings" data-key="pdf_printer_path" value="${cfg.pdf_printer_path || ""}">
        </div>
      </div>
    `;
  }

  function renderRuntimeSection() {
    const cfg = configModel().network;
    return `
      <div class="section-header">
        <div>
          <h2>运行设置</h2>
          <p>这些设置会写入配置文件，重启 Edge 后生效。</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="field">
          <label for="network_bind_address">监听地址</label>
          <input id="network_bind_address" data-section="network" data-key="bind_address" value="${cfg.bind_address || "127.0.0.1"}">
        </div>
        <div class="field">
          <label for="network_port">监听端口</label>
          <input id="network_port" type="number" min="1" max="65535" data-section="network" data-key="port" value="${cfg.port || 7860}">
        </div>
      </div>
    `;
  }

  function renderStaticPrinterRows() {
    const items = configModel().printers.static_list || [];
    if (!items.length) {
      return '<div class="section-note">当前没有静态打印机条目。仅在“静态发现”模式下会使用这些条目。</div>';
    }

    return `
      <div class="static-list">
        ${items.map((item, index) => `
          <div class="static-item" data-static-index="${index}">
            <div class="field">
              <label>名称</label>
              <input data-static-key="name" value="${item.name || ""}">
            </div>
            <div class="field">
              <label>IP</label>
              <input data-static-key="ip" value="${item.ip || ""}">
            </div>
            <div class="field">
              <label>协议</label>
              <select data-static-key="protocol">
                ${["ipp", "socket", "raw", "hp_jetdirect"].map((protocol) => `<option value="${protocol}" ${String(item.protocol || "ipp") === protocol ? "selected" : ""}>${protocol}</option>`).join("")}
              </select>
            </div>
            <div class="field">
              <label>端口</label>
              <input type="number" min="1" max="65535" data-static-key="port" value="${item.port ?? ""}">
            </div>
            <div class="inline-actions">
              <button type="button" class="btn btn-danger" data-action="remove-static" data-index="${index}">删除</button>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderDiscoverySection() {
    const cfg = configModel().printers;
    return `
      <div class="section-header">
        <div>
          <h2>打印机发现</h2>
          <p>统一维护自动发现与静态发现配置，保存后重启 Edge 生效。</p>
        </div>
      </div>
      <div class="config-grid">
        <div class="field">
          <label for="printers_discovery_mode">发现模式</label>
          <select id="printers_discovery_mode" data-section="printers" data-key="discovery_mode">
            <option value="auto" ${String(cfg.discovery_mode || "auto") === "auto" ? "selected" : ""}>auto</option>
            <option value="static" ${String(cfg.discovery_mode || "auto") === "static" ? "selected" : ""}>static</option>
          </select>
        </div>
      </div>
      <div class="admin-card">
        <div class="card-header">
          <h3>静态打印机列表</h3>
          <button type="button" class="btn" data-action="add-static">新增静态打印机</button>
        </div>
        ${renderStaticPrinterRows()}
      </div>
    `;
  }

  function renderManagedTable() {
    if (!state.managed.length) {
      return '<tr><td class="muted" colspan="5">暂无已管理打印机</td></tr>';
    }

    return state.managed.map((item) => {
      const id = item.id || "";
      const isDefault = id && id === state.defaultPrinterId;
      const pendingDefault = isActionPending("default", id);
      const pendingDelete = isActionPending("delete", id);
      const pendingReregister = isActionPending("reregister", id);
      return `
        <tr>
          <td>${printerName(item)}${isDefault ? '<span class="default-tag">默认</span>' : ""}</td>
          <td class="muted">${id || "-"}</td>
          <td class="muted">${printerAddr(item)}</td>
          <td>${item.enabled === false ? "已禁用" : "可用"}</td>
          <td>
            <div class="ops">
              <button type="button" class="btn" data-action="default" data-id="${id}" ${isDefault || pendingDefault ? "disabled" : ""}>${pendingDefault ? "处理中..." : "设为默认"}</button>
              <button type="button" class="btn" data-action="reregister-printer" data-id="${id}" ${pendingReregister ? "disabled" : ""}>${pendingReregister ? "处理中..." : "重新注册云端"}</button>
              <button type="button" class="btn btn-danger" data-action="delete" data-id="${id}" ${pendingDelete ? "disabled" : ""}>${pendingDelete ? "处理中..." : "删除"}</button>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }

  function renderDiscoveredTable() {
    if (!state.discovered.length) {
      return '<tr><td class="muted" colspan="4">暂无可添加打印机</td></tr>';
    }

    return state.discovered.map((item, index) => {
      const type = item.is_network ? "网络打印机" : "本地打印机";
      const pendingAdd = isActionPending("add", index);
      return `
        <tr>
          <td>${printerName(item)}</td>
          <td class="muted">${item.type || type}</td>
          <td class="muted">${printerAddr(item)}</td>
          <td>
            <button type="button" class="btn btn-primary" data-action="add" data-index="${index}" ${pendingAdd ? "disabled" : ""}>${pendingAdd ? "处理中..." : "添加"}</button>
          </td>
        </tr>
      `;
    }).join("");
  }

  function renderPrintersSection() {
    return `
      <div class="section-header">
        <div>
          <h2>打印机管理</h2>
          <p>这里保留原有的发现、添加、默认设置和删除操作。</p>
        </div>
      </div>
      <div class="table-toolbar">
        <button type="button" class="btn btn-primary" data-action="refresh-all">刷新全部</button>
        <button type="button" class="btn" data-action="refresh-managed">刷新已管理</button>
        <button type="button" class="btn" data-action="refresh-discovered">刷新可添加</button>
      </div>
      <section class="admin-card">
        <div class="card-header">
          <h3>已管理打印机</h3>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>ID</th>
                <th>地址/端口</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>${renderManagedTable()}</tbody>
          </table>
        </div>
      </section>
      <section class="admin-card">
        <div class="card-header">
          <h3>可添加打印机</h3>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>地址/端口</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>${renderDiscoveredTable()}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function renderPanel() {
    if (!el.configPanel) return;

    let html = "";
    switch (state.activeSection) {
      case "cloud":
        html = renderCloudSection();
        break;
      case "settings":
        html = renderSettingsSection();
        break;
      case "runtime":
        html = renderRuntimeSection();
        break;
      case "discovery":
        html = renderDiscoverySection();
        break;
      case "printers":
        html = renderPrintersSection();
        break;
      default:
        html = renderOverview();
        break;
    }
    el.configPanel.innerHTML = html;
  }

  function renderNav() {
    el.nav?.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.section === state.activeSection);
    });
  }

  function render() {
    updateToolbar();
    renderNav();
    renderPanel();
  }

  async function loadConfig() {
    const data = await request("/config");
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

  async function loadManaged() {
    const data = await request("/printers/managed");
    state.managed = Array.isArray(data.items) ? data.items : [];
    state.defaultPrinterId = data.default_printer_id || "";
    render();
  }

  async function loadDiscovered() {
    const data = await request("/printers/discovered");
    state.discovered = Array.isArray(data.items) ? data.items : [];
    render();
  }

  async function loadCloudStatus() {
    const data = await request("/cloud/status");
    renderCloudStatus(data);
  }

  async function loadAll() {
    showError("");
    state.loading = true;
    render();
    try {
      await Promise.all([loadConfig(), loadManaged(), loadDiscovered(), loadCloudStatus()]);
    } catch (err) {
      showError(err.message || "加载失败");
    } finally {
      state.loading = false;
      render();
    }
  }

  async function saveConfig() {
    if (!state.config || state.saving) return;
    showError("");
    showResult("");
    state.saving = true;
    render();
    try {
      const result = await request("/config", {
        method: "POST",
        body: JSON.stringify(buildConfigPayload()),
      });
      state.lastApplyResult = result;
      const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
      const restartRequired = Array.isArray(result.restart_required) ? result.restart_required : [];
      const messages = [];
      if (result.cloud_reconnected) {
        messages.push("云端配置已重新应用。");
      }
      if (restartRequired.length) {
        messages.push(`以下配置需重启生效: ${restartRequired.join("、")}`);
      }
      if (warnings.length) {
        messages.push(`警告: ${warnings.join("；")}`);
      }
      showResult(messages.length ? messages.join(" ") : "配置已保存。", warnings.length > 0 || restartRequired.length > 0);
      await Promise.all([loadConfig(), loadCloudStatus(), loadDiscovered()]);
    } catch (err) {
      showError(err.message || "保存配置失败");
    } finally {
      state.saving = false;
      render();
    }
  }

  async function checkCloudAndRegisterNode() {
    if (!state.config || state.testingCloud) return;
    showError("");
    showResult("");
    state.testingCloud = true;
    render();
    try {
      const result = await request("/cloud/check-register", {
        method: "POST",
        body: JSON.stringify({ cloud: buildConfigPayload().cloud }),
      });
      showResult(result.message || "云端检测完成。");
      await Promise.all([loadConfig(), loadCloudStatus()]);
    } catch (err) {
      showError(err.message || "云端检测失败。");
    } finally {
      state.testingCloud = false;
      render();
    }
  }

  async function setDefaultPrinter(printerId) {
    if (!printerId || isActionPending("default", printerId)) return;
    showError("");
    setActionPending("default", printerId, true);
    render();
    try {
      await request("/printers/default", {
        method: "POST",
        body: JSON.stringify({ printer_id: printerId }),
      });
      await loadManaged();
    } catch (err) {
      showError(err.message || "设置默认打印机失败");
    } finally {
      setActionPending("default", printerId, false);
      render();
    }
  }

  async function deletePrinter(printerId) {
    if (!printerId || isActionPending("delete", printerId)) return;
    if (!window.confirm("确认删除该打印机吗？")) return;
    showError("");
    setActionPending("delete", printerId, true);
    render();
    try {
      const result = await request(`/printers/${encodeURIComponent(printerId)}`, { method: "DELETE" });
      if (result.warning) {
        showResult(result.warning, true);
      }
      await Promise.all([loadManaged(), loadDiscovered()]);
    } catch (err) {
      showError(err.message || "删除打印机失败");
    } finally {
      setActionPending("delete", printerId, false);
      render();
    }
  }

  async function addPrinterByIndex(index) {
    const item = state.discovered[index];
    if (!item || isActionPending("add", index)) return;
    showError("");
    setActionPending("add", index, true);
    render();
    try {
      const result = await request("/printers/add", {
        method: "POST",
        body: JSON.stringify(item),
      });
      if (result.cloud_error) {
        showResult(`打印机已添加，但云端注册失败: ${result.cloud_error}`, true);
      }
      await Promise.all([loadManaged(), loadDiscovered()]);
    } catch (err) {
      showError(err.message || "添加打印机失败");
    } finally {
      setActionPending("add", index, false);
      render();
    }
  }

  async function reregisterPrinter(printerId) {
    if (!printerId || isActionPending("reregister", printerId)) return;
    showError("");
    setActionPending("reregister", printerId, true);
    render();
    try {
      const result = await request(`/printers/${encodeURIComponent(printerId)}/reregister`, { method: "POST" });
      showResult(result.message || "打印机已重新注册到云端。");
    } catch (err) {
      showError(err.message || "重新注册打印机失败");
    } finally {
      setActionPending("reregister", printerId, false);
      render();
    }
  }

  function updateField(section, key, rawValue, type) {
    if (!state.config) return;
    const next = deepClone(state.config);
    let value = rawValue;
    if (type === "checkbox") {
      value = !!rawValue;
    } else if (type === "number") {
      value = rawValue === "" ? "" : Number(rawValue);
    }
    next[section][key] = value;
    state.config = next;
    updateToolbar();
  }

  function addStaticPrinter() {
    const next = deepClone(configModel());
    next.printers.static_list = Array.isArray(next.printers.static_list) ? next.printers.static_list : [];
    next.printers.static_list.push({
      name: "",
      ip: "",
      protocol: "ipp",
      port: 631,
    });
    state.config = next;
    render();
  }

  function removeStaticPrinter(index) {
    const next = deepClone(configModel());
    next.printers.static_list.splice(index, 1);
    state.config = next;
    render();
  }

  function updateStaticPrinter(index, key, rawValue) {
    const next = deepClone(configModel());
    const item = next.printers.static_list[index];
    if (!item) return;
    item[key] = key === "port" ? (rawValue === "" ? "" : Number(rawValue)) : rawValue;
    state.config = next;
    updateToolbar();
  }

  function bindEvents() {
    el.configSaveBtn?.addEventListener("click", saveConfig);
    el.cloudCheckRegisterBtn?.addEventListener("click", checkCloudAndRegisterNode);

    el.nav?.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const section = target.dataset.section;
      if (!section) return;
      state.activeSection = section;
      render();
    });

    el.configPanel?.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.dataset.section && target.dataset.key) {
        const key = target.dataset.key;
        const section = target.dataset.section;
        if (target instanceof HTMLInputElement) {
          updateField(section, key, target.type === "checkbox" ? target.checked : target.value, target.type);
        } else if (target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement) {
          updateField(section, key, target.value, target instanceof HTMLSelectElement ? "select-one" : "text");
        }
        return;
      }

      const staticContainer = target.closest("[data-static-index]");
      if (!staticContainer || !("dataset" in staticContainer)) return;
      const index = Number(staticContainer.dataset.staticIndex);
      const key = target.dataset.staticKey;
      if (!key || !Number.isInteger(index)) return;
      updateStaticPrinter(index, key, target.value);
    });

    el.configPanel?.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.dataset.action;
      if (!action) return;

      if (action === "add-static") {
        addStaticPrinter();
        return;
      }
      if (action === "remove-static") {
        removeStaticPrinter(Number(target.dataset.index));
        return;
      }
      if (action === "refresh-all") {
        loadAll();
        return;
      }
      if (action === "refresh-managed") {
        loadManaged().catch((err) => showError(err.message || "刷新已管理列表失败"));
        return;
      }
      if (action === "refresh-discovered") {
        loadDiscovered().catch((err) => showError(err.message || "刷新可添加列表失败"));
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
  }

  bindEvents();
  loadAll();
})();
