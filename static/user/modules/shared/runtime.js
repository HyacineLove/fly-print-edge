import { api, postJson } from "./api.js";
import { q, setText } from "./dom.js";
import {
  createDefaultCapabilityState,
  clearPendingPrintRequest,
  currentSessionId,
  saveSessionState,
  setDoneResult,
  state,
} from "./session-state.js";

export const loginQrRetryIntervalMs = 10000;
export const loginQrRetryCountdownSeconds = 10;
export const loginQrRetrySuffix = "，10 秒后将自动重试";
export const previewFailureFallbackSeconds = 10;

export function showError(message) {
  if (!message) return;
  window.alert(message);
}

export function normalizeDuplexForApi(duplex) {
  const value = String(duplex || "").toLowerCase();
  if (value === "simplex" || value === "single" || value === "none") {
    return "simplex";
  }
  return "longedge";
}

export function gotoPage(name, sseConnection = null) {
  sseConnection?.close?.();
  window.location.href = `/static/user/html/${name}.html`;
}

export async function cleanupSessionResources() {
  try {
    if (state.file?.file_id || currentSessionId()) {
      await postJson(api.cleanup, {
        file_id: state.file?.file_id,
        session_id: currentSessionId() || undefined,
      });
    }
  } catch {
    // Ignore cleanup errors to avoid blocking UI recovery.
  }
}

export function clearLocalUserSession() {
  state.file = {};
  state.session_id = null;
  state.doneResult = null;
  state.pendingPrintRequest = null;
  state.defaultPrinterCapabilities = null;
  state.capabilityState = createDefaultCapabilityState();
  clearPendingPrintRequest();
  saveSessionState();
}

export async function cleanupAndBackToLogin(sseConnection = null) {
  sseConnection?.close?.();
  await cleanupSessionResources();
  clearLocalUserSession();
  gotoPage("login");
}

export function nowText() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(
    d.getHours()
  )}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function tickClock() {
  setText(["97_161", "97_450", "115_21"], nowText());
}

export function startClockLoop() {
  tickClock();
  window.setInterval(tickClock, 1000);
}

export function renderCommonText(page) {
  setText(["97_158"], "简历打印服务");
  setText(["3_45"], "扫描二维码上传");
  setText(["3_30"], "刷新二维码");
  setText(["97_456"], "返回");
  setText(["97_462"], "立刻打印");
  setText(["115_42"], page === "done" ? "返回首页" : "继续打印");
  setText(["97_473"], "打印设置");
  setText(["55_113"], "打印份数");
  setText(["55_124"], "打印模式");
  setText(["133_37"], "色彩选择");
  setText(["55_125"], "双面");
  setText(["55_126"], "单面");
  setText(["133_39"], "彩色");
  setText(["133_38"], "黑白");
  setText(["77_18"], page === "done" ? "打印完成" : "打印中");
  setText(["115_539", "115_26", "97_459", "97_162"], "");
}

export function mapQrErrorMessage(errorCode, message) {
  const code = String(errorCode || "").toLowerCase();
  const msg = String(message || "").trim();

  if (code === "printer_fault") return msg || "打印机故障，请联系管理员处理";

  if (code === "printer_disabled") return "打印机已被禁用，请联系管理员";
  if (code === "printer_not_found") return "打印机已被删除或不存在，请联系管理员";
  if (code === "node_disabled") return "节点已被禁用，请联系管理员";
  if (code === "node_not_found") return "节点已被删除或不存在，请联系管理员";
  if (code === "printer_not_belong_to_node") return "打印机与节点绑定异常，请联系管理员";

  if (msg.includes("打印机已被管理员禁用")) return "打印机已被禁用，请联系管理员";
  if (msg.includes("打印机不存在")) return "打印机已被删除或不存在，请联系管理员";
  if (msg.includes("节点已被管理员禁用")) return "节点已被禁用，请联系管理员";
  if (msg.includes("云端服务未连接")) return "无法连接到云端服务器";
  if (msg.includes("设备未注册") || msg.includes("设备未就绪")) return "设备未就绪，请联系管理员";
  if (msg.includes("暂无可用打印机")) return "暂无可用打印机";
  if (msg.includes("HTTP 500") || msg.includes("HTTP500") || /^\s*500\s*$/.test(msg) || /\b500\b/.test(msg)) {
    return "服务暂时不可用";
  }
  if (msg.includes("HTTP 502") || msg.includes("HTTP502") || msg.includes("HTTP 503") || msg.includes("HTTP503")) {
    return "服务暂时不可用";
  }

  return msg || "获取二维码失败，请稍后重试";
}

export function mapPrintErrorMessage(errorCode, message) {
  const code = String(errorCode || "").toLowerCase();
  const msg = String(message || "").trim();
  const lowerMsg = msg.toLowerCase();

  if (code === "printer_fault") return msg || "打印机故障，请联系管理员处理";

  if (code === "printer_disabled") return "打印机已被禁用，请联系管理员";
  if (code === "printer_not_found") return "打印机已被删除或不存在，请联系管理员";
  if (code === "node_disabled") return "节点已被禁用，请联系管理员";
  if (code === "node_not_found") return "节点已被删除或不存在，请联系管理员";
  if (code === "printer_not_belong_to_node") return "打印机与节点绑定异常，请联系管理员";
  if (code === "token_generation_failed") return "云端凭证生成失败，请稍后重试";
  if (code === "print_spooler_error") {
    return "打印机处理该文件失败，请联系管理员检查打印机驱动或内存状态";
  }

  if (
    msg.includes("PCL XL") ||
    msg.includes("MemAllocError") ||
    msg.includes("ReadImage") ||
    lowerMsg.includes("memallocerror") ||
    lowerMsg.includes("readimage") ||
    lowerMsg.includes("spooler job entered terminal error status")
  ) {
    return "打印机处理该文件失败，请联系管理员检查打印机驱动或内存状态";
  }
  if (msg.includes("无法获取本地打印任务ID")) {
    return "打印任务提交失败，请联系管理员检查打印机队列";
  }

  if (msg.includes("打印机已被管理员禁用") || msg.includes("打印机禁用")) {
    return "打印机已被禁用，请联系管理员";
  }
  if (msg.includes("打印机不存在") || msg.includes("打印机删除")) {
    return "打印机已被删除或不存在，请联系管理员";
  }
  if (msg.includes("节点已被管理员禁用") || msg.includes("节点禁用")) {
    return "节点已被禁用，请联系管理员";
  }
  if (msg.includes("节点不存在") || msg.includes("节点删除")) {
    return "节点已被删除或不存在，请联系管理员";
  }
  if (
    msg.includes("云端服务未连接") ||
    msg.includes("无法连接") ||
    msg.includes("连接不上") ||
    msg.includes("websocket")
  ) {
    return "无法连接到云端服务器";
  }

  return msg || "打印失败，请稍后重试";
}

export function mapPreviewErrorMessage(errorCode, message) {
  const code = String(errorCode || "").toLowerCase();
  const msg = String(message || "").trim();
  const lowerMsg = msg.toLowerCase();

  if (code === "file_not_found") return "文件不存在或已过期，请重新扫码上传";
  if (code === "token_generation_failed") return "文件访问凭证生成失败，请重新扫码上传";
  if (code === "node_disabled") return "节点已被禁用，请联系管理员";
  if (code === "node_not_found") return "节点不存在，请联系管理员";
  if (code === "printer_disabled") return "打印机已被禁用，请联系管理员";
  if (code === "printer_not_found") return "打印机不存在，请联系管理员";

  if (msg.includes("下载文件失败") || msg.includes("拉取文件失败")) {
    return "文件拉取失败，请重新扫码上传";
  }
  if (msg.includes("文件不存在") || msg.includes("文件已删除") || lowerMsg.includes("file not found")) {
    return "文件不存在或已过期，请重新扫码上传";
  }
  if (msg.includes("超时") || lowerMsg.includes("timeout") || lowerMsg.includes("timed out")) {
    return "预览超时，请检查网络后重试";
  }
  if (
    msg.includes("云端服务未连接") ||
    msg.includes("无法连接") ||
    msg.includes("连接不上") ||
    lowerMsg.includes("failed to fetch") ||
    lowerMsg.includes("networkerror") ||
    lowerMsg.includes("connection")
  ) {
    return "无法连接云端服务，请稍后重试";
  }
  if (msg.includes("HTTP 404") || lowerMsg.includes("http 404") || lowerMsg.includes("status 404")) {
    return "文件地址已失效，请重新扫码上传";
  }

  return msg || "预览加载失败，请重新扫码上传";
}

export function handleCloudError({ page, data, errorCode, message, sseConnection, onPreviewError }) {
  const safeMessage = message || "云端服务异常，请稍后重试";
  if (page === "login") {
    return { handled: true, loginMessage: mapQrErrorMessage(errorCode, safeMessage) };
  }
  if (page === "preview") {
    onPreviewError?.(mapPreviewErrorMessage(errorCode, safeMessage));
    return { handled: true };
  }
  if (page === "printing") {
    setDoneResult("error", mapPrintErrorMessage(errorCode, safeMessage));
    gotoPage("done", sseConnection);
    return { handled: true };
  }
  showError(safeMessage);
  return { handled: true };
}

export function handlePreviewEvent(data, sseConnection = null) {
  if (!data?.file_id || !data?.file_url) return;
  if (currentSessionId() && data?.session_id !== currentSessionId()) return;
  state.session_id = data.session_id || state.session_id || null;
  state.file = {
    file_id: data.file_id,
    file_url: data.file_url,
    file_name: data.file_name || "文档",
    file_type: data.file_type || "",
    task_token: data.task_token || state.file?.task_token || null,
    job_id: data.job_id || null,
    page_count: 1,
    page_index: 0,
  };
  saveSessionState();
  gotoPage("preview", sseConnection);
}

export function handleJobStatusEvent(data, { page, sseConnection, renderPrintingProgress: renderProgress } = {}) {
  if (currentSessionId() && data?.session_id !== currentSessionId()) return;
  const status = String(data?.status || "").toLowerCase();
  const progress = Number(data?.progress || 0);
  const total = Number(data?.total_pages || state.file?.page_count || 1);
  const current = Number(data?.current_page || data?.page_index || 1);
  if (data?.job_id) {
    state.file.job_id = data.job_id;
    saveSessionState();
  }

  if (status.includes("failed") || status.includes("error")) {
    const message = data?.message || data?.error_message || "打印失败，请重试";
    if (page === "printing") {
      setDoneResult("error", mapPrintErrorMessage(data?.error_code, message), {
        error_code: data?.error_code || null,
        printer_fault: data?.printer_fault || null,
      });
      gotoPage("done", sseConnection);
    } else {
      showError(message);
    }
    return;
  }

  if (page === "printing") {
    if (progress > 0 && progress < 100) {
      const estimatedCurrent = Math.max(1, Math.round((progress / 100) * total));
      renderProgress?.(estimatedCurrent, total);
    } else {
      renderProgress?.(current, total);
    }

    if (
      status.includes("complete") ||
      status.includes("success") ||
      status.includes("done") ||
      progress >= 100
    ) {
      setDoneResult("success", "");
      gotoPage("done", sseConnection);
    }
  }
}

export function setQrCenterVisible(visible) {
  ["3_39", "3_26"].forEach((id) => {
    const el = q(id);
    if (!el) return;
    el.classList.toggle("is-hidden", !visible);
  });
}
