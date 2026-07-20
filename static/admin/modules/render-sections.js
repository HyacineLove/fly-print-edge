import {
  configModel,
  isActionPending,
  isPrinterActionPending,
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
  if (!cloudStatusText) {
    return;
  }

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
        <input
          id="cloud_client_secret"
          type="password"
          data-section="cloud"
          data-key="client_secret"
          value=""
          placeholder="${cfg.client_secret_configured ? "已设置" : "未设置"}"
        >
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
        <input
          id="cloud_heartbeat_interval"
          type="number"
          min="1"
          data-section="cloud"
          data-key="heartbeat_interval"
          value="${escapeHtml(cfg.heartbeat_interval || 30)}"
        >
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
        <p>配置默认纸张、缩放和用户侧可选份数范围。</p>
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
          ${[
            ["actual", "原始尺寸/过大缩小"],
            ["fit", "适合纸张"],
            ["fill", "填满纸张"],
          ].map(([mode, label]) => `<option value="${mode}" ${String(cfg.default_scale_mode || "actual") === mode ? "selected" : ""}>${label}</option>`).join("")}
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
    </div>
  `;
}

function renderRuntimeSection(state) {
  const cfg = configModel(state).network;
  const startupChecked = state.startupEnabled ? "checked" : "";
  const startupDisabled = state.startupLoading || state.startupSaving ? "disabled" : "";
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
      <div class="field field-checkbox">
        <label for="runtime_autostart_enabled">开机自启并自动打开用户页</label>
        <input id="runtime_autostart_enabled" type="checkbox" ${startupChecked} ${startupDisabled}>
      </div>
    </div>
  `;
}

function printerStatusLabel(item) {
  const labels = {
    idle: "可用",
    processing: "打印中",
    stopped: "已停止",
    offline: "离线",
    unknown: "状态未知",
    printer_out_of_paper: "缺纸",
    printer_out_of_toner: "碳粉已用尽",
    printer_jammed: "卡纸",
    printer_cover_open: "机盖打开",
    printer_user_intervention: "需要处理",
  };
  const status = item.status || (item.enabled === false ? "已禁用" : "unknown");
  return labels[status] || status;
}

function renderManagedTable(state) {
  if (!state.managed.length) {
    return '<tr><td class="muted" colspan="7">暂无已管理打印机</td></tr>';
  }

  return state.managed.map((item) => {
    const id = item.id || "";
    const isDefaultPrinter = id && id === state.defaultPrinterId;
    const test = state.printerTests?.[id];
    const testRunning = test?.status === "running" || isActionPending(state, "test", id);
    const currentPage = Number(test?.current?.current_page);
    const totalPages = Number(test?.current?.total_pages);
    const hasPages = Number.isInteger(currentPage) && currentPage > 0 && Number.isInteger(totalPages) && totalPages > 0;
    const testMessage = testRunning && hasPages
      ? `正在打印，第 ${Math.min(currentPage, totalPages)} / ${totalPages} 页……`
      : test?.current?.message || test?.result?.message || "";
    const rowLocked = state.printersRefreshing || state.ippProbing || testRunning || isPrinterActionPending(state, id);
    return `
      <tr>
        <td>${escapeHtml(printerName(item))}${isDefaultPrinter ? '<span class="default-tag">默认</span>' : ""}</td>
        <td>${escapeHtml(item.make_model || "-")}</td>
        <td class="muted">${escapeHtml(id || "-")}</td>
        <td class="muted">${escapeHtml(printerAddr(item))}</td>
        <td>${escapeHtml(printerStatusLabel(item))}</td>
        <td class="capability-cell">${escapeHtml(printerCapabilitySummary(item))}</td>
        <td>
          <div class="ops">
            <button type="button" class="btn" data-action="default" data-id="${escapeHtml(id)}" ${rowLocked || isDefaultPrinter ? "disabled" : ""}>设为默认</button>
            <button type="button" class="btn" data-action="test-printer" data-id="${escapeHtml(id)}" ${rowLocked ? "disabled" : ""}>${testRunning ? "测试中…" : "测试打印"}</button>
            <button type="button" class="btn" data-action="reregister-printer" data-id="${escapeHtml(id)}" ${rowLocked ? "disabled" : ""}>重新注册云端</button>
            <button type="button" class="btn btn-danger" data-action="delete" data-id="${escapeHtml(id)}" ${rowLocked ? "disabled" : ""}>删除</button>
            ${item.uncertain ? `<button type="button" class="btn" data-action="clear-unconfirmed" data-id="${escapeHtml(id)}" ${rowLocked ? "disabled" : ""}>解除结果未知锁定</button>` : ""}
          </div>
          ${testMessage ? `<p class="muted">${escapeHtml(testMessage)}</p>` : ""}
        </td>
      </tr>
    `;
  }).join("");
}

function renderDiscoveredTable(state) {
  if (!state.discovered.length) {
    return '<tr><td class="muted" colspan="6">暂无可添加打印机</td></tr>';
  }

  return state.discovered.map((item, index) => {
    const type = "IPP";
    const issues = Array.isArray(item.issues) ? item.issues.join("；") : "";
    return `
      <tr>
        <td>${escapeHtml(printerName(item))}</td>
        <td>${escapeHtml(item.make_model || "-")}</td>
        <td class="muted">${escapeHtml(type)}</td>
        <td class="muted">${escapeHtml(printerAddr(item))}</td>
        <td class="capability-cell">${escapeHtml(item.compatible === false ? issues || "不兼容" : printerCapabilitySummary(item))}</td>
        <td>
          <button type="button" class="btn btn-primary" data-action="add" data-index="${index}" ${state.printersRefreshing || state.ippProbing || item.compatible === false || isActionPending(state, "add", index) ? "disabled" : ""}>添加</button>
        </td>
      </tr>
    `;
  }).join("");
}

function renderPrintersSection(state) {
  return `
    <div class="section-header">
      <div>
        <h2>打印机管理</h2>
        <p>发现并管理支持直接 PDF 打印和设备作业状态的 IPP 打印机。</p>
      </div>
    </div>
    <div class="table-toolbar">
      <button type="button" class="btn btn-primary" data-action="refresh-printers" ${state.printersRefreshing || state.ippProbing ? "disabled" : ""}>${state.printersRefreshing ? "正在发现并检测…" : "刷新 IPP 打印机"}</button>
    </div>
    <section class="admin-card">
      <div class="card-header"><h3>手动添加 IPP 打印机</h3></div>
      <div class="config-grid">
        <div class="field">
          <label for="manualIppUri">完整 IPP URI</label>
          <input id="manualIppUri" value="${escapeHtml(state.ippProbeUri || "")}" placeholder="ipp://192.168.50.2:631/ipp/print" ${state.ippProbing || state.printersRefreshing ? "disabled" : ""}>
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button type="button" class="btn btn-primary" data-action="probe-ipp" ${state.ippProbing || state.printersRefreshing ? "disabled" : ""}>${state.ippProbing ? "正在检测…" : "检测 IPP 打印机"}</button>
        </div>
      </div>
      ${state.ippProbeResult ? `
        <p class="muted">${escapeHtml(state.ippProbeResult.message || "检测完成")}</p>
        ${state.ippProbeResult.item?.compatible ? `<button type="button" class="btn btn-primary" data-action="add-probed" ${state.printersRefreshing || state.ippProbing || isActionPending(state, "add-probed", state.ippProbeResult.item.ipp_uri) ? "disabled" : ""}>添加此打印机</button>` : ""}
      ` : ""}
    </section>
    <section class="admin-card">
      <div class="card-header">
        <h3>已管理打印机</h3>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>型号</th>
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
              <th>型号</th>
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
  `;
}

function renderPanel(state) {
  const panel = elements.configPanel();
  if (!panel) {
    return;
  }

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
