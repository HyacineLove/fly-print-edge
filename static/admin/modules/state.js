export function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function createAdminState() {
  return {
    config: null,
    initialConfig: null,
    activeSection: "cloud",
    saving: false,
    testingCloud: false,
    loading: false,
    printersRefreshing: false,
    managed: [],
    discovered: [],
    defaultPrinterId: "",
    cloudStatus: null,
    lastApplyResult: null,
    pendingActions: new Set(),
  };
}

export function configModel(state) {
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

export function buildConfigPayload(state) {
  const cfg = configModel(state);
  const rawMaxUpscale = cfg.settings.default_max_upscale;
  const normalizedMaxUpscale = rawMaxUpscale === "" || rawMaxUpscale == null ? "" : Number(rawMaxUpscale);
  const rawCopiesMin = cfg.settings.copies_min;
  const rawCopiesMax = cfg.settings.copies_max;
  const normalizedCopiesMin = rawCopiesMin === "" || rawCopiesMin == null ? "" : Number(rawCopiesMin);
  const normalizedCopiesMax = rawCopiesMax === "" || rawCopiesMax == null ? "" : Number(rawCopiesMax);

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
      copies_min: normalizedCopiesMin,
      copies_max: normalizedCopiesMax,
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

export function isDirty(state) {
  if (!state.config || !state.initialConfig) return false;
  return JSON.stringify(state.config) !== JSON.stringify(state.initialConfig);
}

function actionKey(action, value) {
  return `${action}:${value}`;
}

export function isActionPending(state, action, value) {
  return state.pendingActions.has(actionKey(action, value));
}

export function setActionPending(state, action, value, pending) {
  const key = actionKey(action, value);
  if (pending) {
    state.pendingActions.add(key);
  } else {
    state.pendingActions.delete(key);
  }
}

export function printerName(item) {
  return item?.name || item?.printer_name || item?.display_name || "未命名打印机";
}

export function printerAddr(item) {
  const ip = item?.ip || item?.host || item?.address || "-";
  const port = item?.port || item?.tcp_port || "-";
  return `${ip}:${port}`;
}

export function restartRequiredHint(state) {
  const result = state.lastApplyResult;
  return Array.isArray(result?.restart_required) && result.restart_required.length > 0;
}

export function updateField(state, section, key, rawValue, type) {
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
}

export function addStaticPrinter(state) {
  const next = deepClone(configModel(state));
  next.printers.static_list = Array.isArray(next.printers.static_list) ? next.printers.static_list : [];
  next.printers.static_list.push({
    name: "",
    ip: "",
    protocol: "ipp",
    port: 631,
  });
  state.config = next;
}

export function removeStaticPrinter(state, index) {
  const next = deepClone(configModel(state));
  next.printers.static_list.splice(index, 1);
  state.config = next;
}

export function updateStaticPrinter(state, index, key, rawValue) {
  const next = deepClone(configModel(state));
  const item = next.printers.static_list[index];
  if (!item) return;
  item[key] = key === "port" ? (rawValue === "" ? "" : Number(rawValue)) : rawValue;
  state.config = next;
}
