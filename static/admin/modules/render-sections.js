import {
  configModel,
  isActionPending,
  isDirty,
  printerAddr,
  printerName,
  restartRequiredHint,
} from "./state.js";
import { printerCapabilitySummary } from "./printer-capabilities.js";

const elements = {
  configSaveBtn: () => document.getElementById("configSaveBtn"),
  cloudCheckRegisterBtn: () => document.getElementById("cloudCheckRegisterBtn"),
  configStatusText: () => document.getElementById("configStatusText"),
  cloudStatusText: () => document.getElementById("cloudStatusText"),
  restartHintText: () => document.getElementById("restartHintText"),
  nav: () => document.querySelector(".admin-nav"),
  configPanel: () => document.getElementById("configPanel"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function updateToolbar(state) {
  const saveBtn = elements.configSaveBtn();
  if (saveBtn) {
    saveBtn.disabled = state.saving || !state.config || !isDirty(state);
  }

  const checkBtn = elements.cloudCheckRegisterBtn();
  if (checkBtn) {
    checkBtn.disabled = state.testingCloud || !state.config;
  }

  const configStatusText = elements.configStatusText();
  if (configStatusText) {
    const text = !state.config
      ? "配置状态: 未加载"
      : isDirty(state)
        ? "配置状态: 有未保存变更"
        : "配置状态: 已同步";
    configStatusText.textContent = text;
    configStatusText.classList.remove("status-ok", "status-warn", "status-info");
    configStatusText.classList.add(isDirty(state) ? "status-warn" : "status-ok");
  }

  const restartHintText = elements.restartHintText();
  if (restartHintText) {
    restartHintText.classList.toggle("is-hidden", !restartRequiredHint(state));
  }

  const cloudStatusText = elements.cloudStatusText();
  if (!cloudStatusText) return;
  const status = state.cloudStatus;
  cloudStatusText.classList.remove("status-ok", "status-warn", "status-info");

  if (!status || status.success === false) {
    cloudStatusText.textContent = "云端状态: 不可用";
    cloudStatusText.classList.add("status-warn");
    return;
  }

  if (!status.configured) {
    cloudStatusText.textContent = "云端状态: 配置不完整";
    cloudStatusText.classList.add("status-warn");
    return;
  }

  if (status.connected) {
    cloudStatusText.textContent = "云端状态: 已连接";
    cloudStatusText.classList.add("status-ok");
    return;
  }

  if (status.registered) {
    cloudStatusText.textContent = "云端状态: 等待连接";
    cloudStatusText.classList.add("status-info");
    return;
  }

  cloudStatusText.textContent = "云端状态: 待注册节点";
  cloudStatusText.classList.add("status-info");
}

export function renderAdminToolbar(state) {
  updateToolbar(state);
}

function renderCloudSection(state) {
  const cfg = configModel(state).cloud;
  const nodeId = state.cloudStatus?.node_id || cfg.node_id || "-";

  return `
    <div class="section-header">
      <div>
        <h2>云端配置</h2>
        <p>先保存配置，再执行连接检查与节点注册。</p>
      </div>
    </div>
    <div class="config-grid">
      <div class="field">
        <label for="cloud_base_url">云端地址</label>
        <input id="cloud_base_url" data-section="cloud" data-key="base_url" value="${escapeHtml(cfg.base_url || "")}">
      </div>
      <div class="field">
        <label for="cloud_auth_url">认证地址</label>
        <input id="cloud_auth_url" data-section="cloud" data-key="auth_url" value="${escapeHtml(cfg.auth_url || "")}">
      </div>
      <div class="field">
        <label for="cloud_client_id">客户端 ID</label>
        <input id="cloud_client_id" data-section="cloud" data-key="client_id" value="${escapeHtml(cfg.client_id || "")}">
      </div>
      <div class="field">
        <label for="cloud_client_secret">客户端密钥</label>
        <input id="cloud_client_secret" type="password" data-section="cloud" data-key="client_secret" value="" placeholder="${cfg.client_secret_configured ? "已设置" : "未设置"}">
      </div>
      <div class="field">
        <label for="cloud_node_name">节点名称</label>
        <input id="cloud_node_name" data-section="cloud" data-key="node_name" value="${escapeHtml(cfg.node_name || "")}">
      </div>
      <div class="field">
        <label for="cloud_location">位置</label>
        <input id="cloud_location" data-section="cloud" data-key="location" value="${escapeHtml(cfg.location || "")}">
      </div>
      <div class="field">
        <label for="cloud_heartbeat_interval">心跳间隔(秒)</label>
        <input id="cloud_heartbeat_interval" type="number" min="1" data-section="cloud" data-key="heartbeat_interval" value="${escapeHtml(cfg.heartbeat_interval || 30)}">
      </div>
      <div class="field">
        <label>当前节点 ID</label>
        <input value="${escapeHtml(nodeId)}" disabled>
      </div>
    </div>
  `;
}

function renderSettingsSection(state) {
  const cfg = configModel(state).settings;
  return `
    <div class="section-header">
      <div>
        <h2>打印默认设置</h2>
        <p>配置默认纸张、缩放和用户端可选的打印份数范围。</p>
      </div>
    </div>
    <div class="config-grid">
      <div class="field">
        <label for="settings_default_paper_size">默认纸张</label>
        <input id="settings_default_paper_size" data-section="settings" data-key="default_paper_size" value="${escapeHtml(cfg.default_paper_size || "A4")}">
      </div>
      <div class="field">
        <label for="settings_default_scale_mode">默认缩放模式</label>
        <select id="settings_default_scale_mode" data-section="settings" data-key="default_scale_mode">
          ${["fit", "actual", "fill"].map((mode) => `<option value="${mode}" ${String(cfg.default_scale_mode || "fit") === mode ? "selected" : ""}>${mode}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="settings_default_max_upscale">最大放大倍数</label>
        <input id="settings_default_max_upscale" type="number" min="0.1" step="0.1" data-section="settings" data-key="default_max_upscale" value="${escapeHtml(cfg.default_max_upscale ?? 3.0)}">
      </div>
      <div class="field">
        <label for="settings_copies_min">最小打印份数</label>
        <input id="settings_copies_min" type="number" min="1" step="1" data-section="settings" data-key="copies_min" value="${escapeHtml(cfg.copies_min ?? 1)}">
      </div>
      <div class="field">
        <label for="settings_copies_max">最大打印份数</label>
        <input id="settings_copies_max" type="number" min="1" step="1" data-section="settings" data-key="copies_max" value="${escapeHtml(cfg.copies_max ?? 3)}">
      </div>
      <div class="field">
        <label for="settings_libreoffice_path">LibreOffice 路径</label>
        <input id="settings_libreoffice_path" data-section="settings" data-key="libreoffice_path" value="${escapeHtml(cfg.libreoffice_path || "")}">
      </div>
      <div class="field">
        <label for="settings_pdf_printer_path">PDF 打印工具路径</label>
        <input id="settings_pdf_printer_path" data-section="settings" data-key="pdf_printer_path" value="${escapeHtml(cfg.pdf_printer_path || "")}">
      </div>
    </div>
  `;
}

function renderRuntimeSection(state) {
  const cfg = configModel(state).network;
  return `
    <div class="section-header">
      <div>
        <h2>运行设置</h2>
        <p>这些设置保存后可能需要重启 Edge 才会生效。</p>
      </div>
    </div>
    <div class="config-grid">
      <div class="field">
        <label for="network_bind_address">监听地址</label>
        <input id="network_bind_address" data-section="network" data-key="bind_address" value="${escapeHtml(cfg.bind_address || "127.0.0.1")}">
      </div>
      <div class="field">
        <label for="network_port">监听端口</label>
        <input id="network_port" type="number" min="1" max="65535" data-section="network" data-key="port" value="${escapeHtml(cfg.port || 7860)}">
      </div>
    </div>
  `;
}

function renderStaticPrinterRows(state) {
  const items = configModel(state).printers.static_list || [];
  if (!items.length) {
    return '<div class="section-note">当前没有静态打印机条目，仅在“静态发现”模式下会使用。</div>';
  }

  return `
    <div class="static-list">
      ${items.map((item, index) => `
        <div class="static-item" data-static-index="${index}">
          <div class="field">
            <label>名称</label>
            <input data-static-key="name" value="${escapeHtml(item.name || "")}">
          </div>
          <div class="field">
            <label>IP</label>
            <input data-static-key="ip" value="${escapeHtml(item.ip || "")}">
          </div>
          <div class="field">
            <label>协议</label>
            <select data-static-key="protocol">
              ${["ipp", "socket", "raw", "hp_jetdirect"].map((protocol) => `<option value="${protocol}" ${String(item.protocol || "ipp") === protocol ? "selected" : ""}>${protocol}</option>`).join("")}
            </select>
          </div>
          <div class="field">
            <label>端口</label>
            <input type="number" min="1" max="65535" data-static-key="port" value="${escapeHtml(item.port ?? "")}">
          </div>
          <div class="inline-actions">
            <button type="button" class="btn btn-danger" data-action="remove-static" data-index="${index}">删除</button>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderManagedTable(state) {
  if (!state.managed.length) {
    return '<tr><td class="muted" colspan="6">暂无已管理打印机</td></tr>';
  }

  return state.managed.map((item) => {
    const id = item.id || "";
    const isDefaultPrinter = id && id === state.defaultPrinterId;
    return `
      <tr>
        <td>${escapeHtml(printerName(item))}${isDefaultPrinter ? '<span class="default-tag">默认</span>' : ""}</td>
        <td class="muted">${escapeHtml(id || "-")}</td>
        <td class="muted">${escapeHtml(printerAddr(item))}</td>
        <td>${item.enabled === false ? "已禁用" : "可用"}</td>
        <td class="capability-cell">${escapeHtml(printerCapabilitySummary(item))}</td>
        <td>
          <div class="ops">
            <button type="button" class="btn" data-action="default" data-id="${escapeHtml(id)}" ${isDefaultPrinter || isActionPending(state, "default", id) ? "disabled" : ""}>设为默认</button>
            <button type="button" class="btn" data-action="reregister-printer" data-id="${escapeHtml(id)}" ${isActionPending(state, "reregister", id) ? "disabled" : ""}>重新注册云端</button>
            <button type="button" class="btn btn-danger" data-action="delete" data-id="${escapeHtml(id)}" ${isActionPending(state, "delete", id) ? "disabled" : ""}>删除</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function renderDiscoveredTable(state) {
  if (!state.discovered.length) {
    return '<tr><td class="muted" colspan="5">暂无可添加打印机</td></tr>';
  }

  return state.discovered.map((item, index) => {
    const type = item.type || (item.is_network ? "网络打印机" : "本地打印机");
    return `
      <tr>
        <td>${escapeHtml(printerName(item))}</td>
        <td class="muted">${escapeHtml(type)}</td>
        <td class="muted">${escapeHtml(printerAddr(item))}</td>
        <td class="capability-cell">${escapeHtml(printerCapabilitySummary(item))}</td>
        <td>
          <button type="button" class="btn btn-primary" data-action="add" data-index="${index}" ${isActionPending(state, "add", index) ? "disabled" : ""}>添加</button>
        </td>
      </tr>
    `;
  }).join("");
}

function renderPrintersSection(state) {
  const cfg = configModel(state).printers;
  return `
    <div class="section-header">
      <div>
        <h2>打印机管理</h2>
        <p>集中查看已管理打印机、可添加打印机以及发现设置。</p>
      </div>
    </div>
    <div class="table-toolbar">
      <button type="button" class="btn btn-primary" data-action="refresh-printers" ${state.printersRefreshing ? "disabled" : ""}>刷新</button>
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
              <th>能力</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>${renderManagedTable(state)}</tbody>
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
              <th>能力</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>${renderDiscoveredTable(state)}</tbody>
        </table>
      </div>
    </section>
    <section class="admin-card">
      <div class="card-header">
        <h3>发现设置</h3>
        <button type="button" class="btn" data-action="add-static">新增静态打印机</button>
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
      ${renderStaticPrinterRows(state)}
    </section>
  `;
}

function renderPanel(state) {
  const panel = elements.configPanel();
  if (!panel) return;

  switch (state.activeSection) {
    case "settings":
      panel.innerHTML = renderSettingsSection(state);
      return;
    case "runtime":
      panel.innerHTML = renderRuntimeSection(state);
      return;
    case "printers":
      panel.innerHTML = renderPrintersSection(state);
      return;
    case "cloud":
    default:
      panel.innerHTML = renderCloudSection(state);
  }
}

function renderNav(state) {
  elements.nav()?.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.section === state.activeSection);
  });
}

export function renderAdminApp(state) {
  renderAdminToolbar(state);
  renderNav(state);
  renderPanel(state);
}
