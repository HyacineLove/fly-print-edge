
import sys
# Windows 控制台默认 GBK 编码，无法输出 emoji 等 Unicode 字符，强制切换为 UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import uvicorn
import json
import asyncio
import os
import socket
import logging
import base64
import hashlib
import io
import tempfile
import shutil
import requests
import qrcode
import time
import uuid
from pathlib import Path
import fitz
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException, Depends, status, APIRouter
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from printer_utils import PrinterManager
from cloud_service import CloudService
from config_service import ConfigService
from file_manager import init_file_manager, get_file_manager, is_valid_content_hash
from interactive_session import InteractiveSessionManager
from logging_utils import configure_logging
from portable_temp import get_portable_temp_dir, get_temp_file_path, cleanup_temp_dir
from windows_startup import get_windows_startup_enabled, set_windows_startup_enabled
from print_layout import resolve_layout_options
from print_options import normalize_print_options, to_cloud_duplex
from print_runtime import build_document_pipeline, stop_document_pipelines
from printing.documents import DocumentIdentity
from printing.domain import ErrorCode, PrintError, PrintOptions

logger = logging.getLogger("EdgeServer")

# 全局变量
app = FastAPI(title="FlyPrint Edge Kiosk")
BASE_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# API Key Authentication - 已移除，仅保留空函数占位以防报错
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Depends(api_key_scheme)):
    return api_key

# 创建 Admin Router
admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    # dependencies=[Depends(get_api_key)]  # 已禁用管理员认证
)

printer_manager: Optional[PrinterManager] = None
cloud_service: Optional[CloudService] = None
# sse_clients 存储所有活跃的 SSE 连接队列
sse_clients: list[asyncio.Queue] = []
SSE_QUEUE_MAXSIZE = 32
node_id: Optional[str] = None
main_loop: Optional[asyncio.AbstractEventLoop] = None
preview_cache: Dict[str, Dict[str, Any]] = {}
interactive_session_manager = InteractiveSessionManager()


def _report_terminal_session_state(session: Optional[Dict[str, Any]] = None) -> None:
    """Best-effort state synchronization; Cloud remains authoritative for dispatch."""
    if not node_id or not cloud_service or not cloud_service.websocket_client:
        return
    cloud_service.websocket_client.report_terminal_session_state(node_id, session)
qr_code_request_lock: Optional[asyncio.Lock] = None
config_service: Optional[ConfigService] = None
printer_test_tasks: Dict[str, Dict[str, Any]] = {}
active_printer_tests: Dict[str, str] = {}

# CORS设置
# 仅允许本地和受信域名访问
origins = [
    "http://localhost",
    "http://localhost:7860",
    "http://127.0.0.1:7860",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _configure_runtime_logging_from_disk():
    from printer_config import PrinterConfig

    config_repo = PrinterConfig()
    return configure_logging(config_repo.get_full_config())


def _enqueue_sse_latest(queue: asyncio.Queue, message: Dict[str, Any]) -> None:
    try:
        queue.put_nowait(message)
        return
    except asyncio.QueueFull:
        pass
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        # The event loop is the sole queue writer in production. This guard
        # keeps the helper safe if a test or future caller introduces a race.
        pass

@app.on_event("startup")
async def startup_event():
    global printer_manager, cloud_service, node_id, sse_clients, main_loop, qr_code_request_lock, config_service

    log_settings = _configure_runtime_logging_from_disk()
    logger.info(
        " Runtime logging initialized: level=%s debug=%s",
        log_settings["level_name"],
        log_settings["debug_logging"],
    )
    logger.info(" Edge Server 正在启动...")
    main_loop = asyncio.get_running_loop()
    qr_code_request_lock = asyncio.Lock()
    
    # 初始化打印机管理器
    printer_manager = PrinterManager()
    config_service = ConfigService(printer_manager.config)
    
    # 初始化文件管理器（传入 preview_cache 引用用于自动清理）
    file_mgr = init_file_manager(
        cleanup_interval=300,
        file_ttl=1800,
        preview_cache=preview_cache,
    )
    # 清理 portable temp 目录中的遗留文件
    cleanup_temp_dir(max_age_hours=24)
    file_mgr.start()
    build_document_pipeline(printer_manager.config, logger)
    logger.info(" 文件管理器已启动（包含预览图缓存清理）")
    
    # 初始化云端服务
    cloud_config = printer_manager.config.config.get("cloud", {})
    cloud_service = CloudService(
        cloud_config,
        printer_manager,
        interactive_job_binder=bind_interactive_cloud_job,
    )

    if cloud_service:
        cloud_service.add_message_listener("preview_file", handle_cloud_message)
        cloud_service.add_message_listener("error", handle_cloud_message)
        cloud_service.add_message_listener("cloud_error", handle_cloud_message)
        cloud_service.add_message_listener("job_status", handle_cloud_message)

    start_result = cloud_service.start()
    if start_result.get("success"):
        node_id = start_result.get("node_id")
        logger.info(f" Cloud service startup result: {start_result.get('message')}, node_id={node_id}")
        # Sessions are intentionally memory-only on Edge. A restart must make
        # Cloud hold any ticket-bound work instead of dispatching it blindly.
        _report_terminal_session_state(None)
    else:
        logger.warning(f" Cloud service startup skipped: {start_result.get('message')}")

async def broadcast_sse_event(event_type: str, data: Dict[str, Any]):
    """广播SSE事件给所有连接的客户端"""
    if not sse_clients:
        return
        
    try:
        from datetime import datetime, timezone
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        client_count = len(sse_clients)
        logger.debug(f" 广播SSE事件: {event_type} -> {client_count} 客户端")
        
        for q in sse_clients:
            _enqueue_sse_latest(q, message)
    except Exception as e:
        logger.error(f" 广播SSE事件失败: {e}")

def _enrich_message_with_session(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    message_type = message.get("type", "")
    payload = message.get("data", {})

    if not isinstance(payload, dict):
        payload = {}

    if message_type == "preview_file":
        accepted = interactive_session_manager.accept_preview_event(payload)
        if not accepted:
            logger.debug(" 丢弃未绑定到当前会话的 preview_file 事件")
            return None
        enriched = dict(message)
        enriched["data"] = accepted
        return enriched

    if message_type == "job_status":
        accepted = interactive_session_manager.accept_job_status_event(payload)
        if not accepted:
            logger.debug(" 丢弃未绑定到当前会话的 job_status 事件")
            return None
        enriched = dict(message)
        enriched["data"] = accepted
        return enriched

    if message_type in {"error", "cloud_error"}:
        active_session = interactive_session_manager.get_active_session()
        if active_session:
            enriched = dict(message)
            enriched_payload = dict(payload)
            enriched_payload.setdefault("session_id", active_session["session_id"])
            enriched["data"] = enriched_payload
            return enriched

    return message

def bind_interactive_cloud_job(file_url: Optional[str], job_id: Optional[str], context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not file_url or not job_id:
        return None
    if context and context.get("terminal_ticket_hash"):
        if not interactive_session_manager.bind_integration_request(context):
            logger.warning("拒绝终端会话不匹配的集成打印任务: job_id=%s", job_id)
            return None
        _report_terminal_session_state(interactive_session_manager.get_active_session())
    bound = interactive_session_manager.attach_cloud_job(file_url, job_id)
    if not bound:
        return None
    return bound

def handle_cloud_message(data: Dict[str, Any]):
    """处理云端消息并推送到所有SSE客户端"""
    try:
        enriched_message = _enrich_message_with_session(data)
        if enriched_message is None:
            return

        # 直接使用广播函数，保持原有数据结构（如果是云端消息，直接转发）
        # 云端消息格式通常为 {"type": "...", "data": ...}
        # 如果data本身已经包含type，则直接发送整个对象
        
        client_count = len(sse_clients)
        logger.info(f" 收到云端消息: {enriched_message.get('type')}, 推送给 {client_count} 个客户端")
        
        if client_count == 0:
            return

        def push_to_queues():
            for q in sse_clients:
                _enqueue_sse_latest(q, enriched_message)

        if main_loop:
            main_loop.call_soon_threadsafe(push_to_queues)
        else:
            push_to_queues()
            
    except Exception as e:
        logger.error(f" 推送消息到SSE队列失败: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(" Edge Server 正在停止...")
    _report_terminal_session_state(None)
    
    # 停止文件管理器
    file_mgr = get_file_manager()
    if file_mgr:
        file_mgr.cleanup_all_preview_files()
        file_mgr.stop()
    stop_document_pipelines()
    
    if cloud_service:
        cloud_service.stop()

# API 路由
@app.get("/")
async def read_root():
    return FileResponse(os.path.join(STATIC_DIR, "user", "Index.html"))

@app.get("/admin")
async def read_admin():
    return FileResponse(os.path.join(STATIC_DIR, "admin", "html", "index.html"))

@app.get("/api/status")
async def get_status():
    """获取设备状态"""
    return {
        "status": "online",
        "node_id": node_id,
        "printer_count": len(printer_manager.config.get_managed_printers()) if printer_manager else 0
    }

@app.get("/api/printer/availability")
async def get_printer_availability():
    return await asyncio.to_thread(_get_default_printer_availability_state)

def get_host_ip():
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

def build_qr_data_url(payload: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"

def _get_managed_printers():
    if not printer_manager:
        return []
    return printer_manager.get_printers()

def _get_printer_by_id(printer_id: str):
    if not printer_manager:
        return None
    for printer in _get_managed_printers():
        if printer.get("id") == printer_id or printer.get("cloud_id") == printer_id:
            return printer
    return None

def _get_cloud_printer_id(printer: Optional[Dict[str, Any]]) -> Optional[str]:
    cloud_id = str((printer or {}).get("cloud_id") or "").strip()
    return cloud_id or None

def _ensure_default_printer():
    if not printer_manager:
        return None
    printers = _get_managed_printers()
    if not printers:
        printer_manager.config.clear_default_printer_id()
        return None
    default_id = printer_manager.config.get_default_printer_id()
    eligible = [p for p in printers if p.get("enabled", True)]
    valid_ids = {p.get("id") for p in eligible}
    if default_id in valid_ids:
        return default_id
    new_default_id = eligible[0].get("id") if eligible else None
    if new_default_id:
        printer_manager.config.set_default_printer_id(new_default_id)
    else:
        printer_manager.config.clear_default_printer_id()
    return new_default_id

def _get_default_printer_record():
    default_printer_id = _ensure_default_printer()
    if not default_printer_id:
        return None
    return _get_printer_by_id(default_printer_id)

def _get_default_printer_availability_state():
    default_printer = _get_default_printer_record()
    if not default_printer:
        return {
            "available": False,
            "faulted": False,
            "error_code": "printer_unavailable",
            "reason_code": "no_default_printer",
            "reason_label": "无可用打印机",
            "message": "暂无可用打印机",
            "raw_reasons": [],
            "printer_id": None,
            "printer_name": None,
        }

    printer_id = default_printer.get("id")
    printer_name = default_printer.get("name")
    printer_uuid = str(default_printer.get("printer_uuid") or "")
    ipp_uri = str(default_printer.get("ipp_uri") or "")
    try:
        from printing.ipp_device import PrinterObservation, normalize_printer_runtime, printer_snapshot, printer_status_message
        from printing.ipp_protocol import IppClient
        from printing.service import DEVICE_JOBS

        if not printer_uuid or not ipp_uri or default_printer.get("type") != "ipp":
            return {
                "available": False,
                "faulted": True,
                "error_code": "printer_unavailable",
                "reason_code": "ipp_configuration_invalid",
                "reason_label": "打印机配置无效",
                "message": "当前打印机暂不可用，请联系工作人员。",
                "raw_reasons": [],
                "printer_id": printer_id,
                "printer_name": printer_name,
            }
        snapshot = printer_snapshot(IppClient(ipp_uri, timeout=5.0))
        runtime = normalize_printer_runtime(PrinterObservation(
            snapshot=snapshot,
            uncertain=DEVICE_JOBS.is_uncertain(printer_uuid),
        ))
        if runtime.printer_status not in {"idle", "printing"}:
            message = printer_status_message(runtime.printer_status)
            return {
                "available": False,
                "faulted": True,
                "error_code": "printer_unconfirmed" if runtime.printer_status == "printer_unconfirmed_lock" else "printer_fault",
                "reason_code": runtime.printer_status,
                "reason_label": message,
                "message": message,
                "raw_reasons": [],
                "printer_id": printer_id,
                "printer_name": printer_name,
            }
        if runtime.printer_status == "printing":
            return {
                "available": False,
                "faulted": False,
                "error_code": "printer_busy",
                "reason_code": "printer_busy",
                "reason_label": "打印机正在处理任务",
                "message": "打印机正在处理其他任务，请稍候。",
                "raw_reasons": [],
                "printer_id": printer_id,
                "printer_name": printer_name,
            }
        return {
            "available": True,
            "faulted": False,
            "error_code": None,
            "reason_code": "ready",
            "reason_label": "可用",
            "message": "打印机可用",
            "raw_reasons": [],
            "printer_id": printer_id,
            "printer_name": printer_name,
        }
    except Exception as exc:
        logger.warning("default IPP printer unavailable printer=%r error=%s", printer_name, exc)
        return {
            "available": False,
            "faulted": True,
            "error_code": "printer_fault",
            "reason_code": "ipp_unreachable",
            "reason_label": "打印机不可用",
            "message": "当前打印机暂不可用，请联系工作人员。",
            "raw_reasons": [],
            "printer_id": printer_id,
            "printer_name": printer_name,
        }

def _get_settings():
    if not printer_manager:
        return {}
    return printer_manager.config.config.get("settings", {})

def _get_config_service() -> ConfigService:
    global config_service
    if config_service:
        return config_service
    if not printer_manager:
        raise RuntimeError("设备未就绪")
    config_service = ConfigService(printer_manager.config)
    return config_service

def _resolve_path(path_value: Optional[str]):
    if not path_value:
        return None
    path_value = os.path.expandvars(path_value)
    if os.path.isabs(path_value):
        return path_value if os.path.exists(path_value) else None
    abs_path = os.path.abspath(path_value)
    return abs_path if os.path.exists(abs_path) else None

def _build_file_url(file_url: str):
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    base_url = cloud_service.api_client.base_url if cloud_service and cloud_service.api_client else ""
    base_url = base_url.rstrip("/")
    if file_url.startswith("/"):
        return f"{base_url}{file_url}"
    return f"{base_url}/{file_url}"

def _download_preview_file(file_url: str, file_name: Optional[str], file_id: Optional[str] = None):
    path = None
    try:
        headers = cloud_service.auth_client.get_auth_headers() if cloud_service and cloud_service.auth_client else {}

        file_mgr = get_file_manager()
        download_url = None
        auth_mode = "bearer"
        file_access_token = file_mgr.consume_file_access_token(file_id) if file_mgr and file_id else None
        if file_access_token:
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            full_url = _build_file_url(file_url)
            parsed = urlparse(full_url)
            query_params = parse_qs(parsed.query)
            query_params["token"] = [file_access_token]
            new_query = urlencode(query_params, doseq=True)
            download_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )
            headers.pop("Authorization", None)
            auth_mode = "file_access_token"
        else:
            logger.warning("Preview file token missing: file_id=%s", file_id)

        if not download_url:
            download_url = _build_file_url(file_url)

        ext = os.path.splitext(file_name or "")[1].lower() or ".bin"
        path = get_temp_file_path(prefix="preview", suffix=ext)
        from urllib.parse import urlsplit
        parsed_download = urlsplit(download_url)
        logger.debug(
            "Downloading preview source: file_id=%s file_name=%s auth=%s host=%s path=%s target=%s",
            file_id,
            file_name,
            auth_mode,
            parsed_download.netloc,
            parsed_download.path,
            path,
        )

        resp = requests.get(download_url, headers=headers, stream=True, timeout=60)
        if resp.status_code != 200:
            logger.warning(
                "Preview file download failed: file_id=%s status=%s",
                file_id,
                resp.status_code,
            )
            return None, f"下载文件失败: {resp.status_code}"

        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info(
            "Preview file downloaded: file_id=%s ext=%s auth=%s status=%s",
            file_id,
            ext,
            auth_mode,
            resp.status_code,
        )
        return path, None
    except Exception as e:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        logger.exception("Preview file download failed: file_id=%s file_name=%s", file_id, file_name)
        return None, str(e)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _normalize_copy_limits(settings: Optional[Dict[str, Any]] = None) -> tuple[int, int]:
    runtime_settings = settings if isinstance(settings, dict) else _get_settings()
    copies_min = max(1, _safe_int(runtime_settings.get("copies_min"), 1))
    copies_max = max(copies_min, _safe_int(runtime_settings.get("copies_max"), 3))
    return copies_min, copies_max

def _clamp_copy_count(copies: Any, settings: Optional[Dict[str, Any]] = None) -> int:
    copies_min, copies_max = _normalize_copy_limits(settings)
    return min(copies_max, max(copies_min, _safe_int(copies, copies_min)))

def _resolve_layout_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return resolve_layout_options(options, _get_settings())

def _normalize_request_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = dict(options or {})
    layout = _resolve_layout_options(normalized)
    normalized.update(layout)
    return normalized












def _remove_managed_printer(printer_id: str, allow_missing: bool = False):
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    managed = _get_managed_printers()
    if not any(p.get("id") == printer_id for p in managed):
        if allow_missing:
            return {"success": True, "default_printer_id": printer_manager.config.get_default_printer_id()}
        return {"success": False, "message": "打印机不存在"}
    default_id = printer_manager.config.get_default_printer_id()
    removed_index = None
    for idx, printer in enumerate(managed):
        if printer.get("id") == printer_id:
            removed_index = idx
            break
    removed_printer = next((dict(item) for item in managed if item.get("id") == printer_id), None)
    printer_manager.config.remove_printer(printer_id)
    managed_after = _get_managed_printers()
    new_default_id = None
    if default_id == printer_id:
        eligible = [item for item in managed_after if item.get("enabled", True)]
        if eligible:
            target_index = min(removed_index or 0, len(eligible) - 1)
            new_default_id = eligible[target_index].get("id")
            if new_default_id:
                printer_manager.config.set_default_printer_id(new_default_id)
        else:
            printer_manager.config.clear_default_printer_id()
    else:
        new_default_id = printer_manager.config.get_default_printer_id()
    return {"success": True, "default_printer_id": new_default_id, "removed_printer": removed_printer}

@app.get("/api/qr_code")
async def get_qr_code():
    """获取上传二维码信息"""
    global qr_code_request_lock

    if qr_code_request_lock is None:
        qr_code_request_lock = asyncio.Lock()

    async with qr_code_request_lock:
        if not node_id:
            return JSONResponse(status_code=503, content={"success": False, "error_code": "service_not_ready", "message": "打印服务暂不可用，请联系工作人员。"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "error_code": "service_not_ready", "message": "打印服务暂不可用，请联系工作人员。"})
        if len(_get_managed_printers()) == 0:
            return {"success": False, "standby": True, "error_code": "service_not_ready", "message": "打印服务暂不可用，请联系工作人员。"}
        default_printer_id = _ensure_default_printer()
        if not default_printer_id:
            return {"success": False, "standby": True, "error_code": "service_not_ready", "message": "打印服务暂不可用，请联系工作人员。"}

        # 通过 WebSocket 请求上传凭证
        default_printer = _get_printer_by_id(default_printer_id)
        cloud_printer_id = _get_cloud_printer_id(default_printer)
        if not cloud_printer_id:
            return {
                "success": False,
                "standby": True,
                "error_code": "printer_cloud_registration_incomplete",
                "message": "打印机尚未注册到云端，请联系管理员。",
            }

        availability = await asyncio.to_thread(_get_default_printer_availability_state)
        if availability.get("faulted"):
            return {
                "success": False,
                "standby": True,
                "error_code": "printer_fault",
                "message": availability.get("message") or "打印机暂不可用，请联系工作人员处理。",
                "printer_fault": availability,
            }

        status_reporter = getattr(cloud_service, "status_reporter", None) if cloud_service else None
        if not status_reporter:
            return {
                "success": False,
                "standby": True,
                "error_code": "status_sync_pending",
                "message": "打印服务正在恢复，请稍候。",
            }
        status_synced = await asyncio.to_thread(
            status_reporter.force_report_printer,
            printer_id=cloud_printer_id,
            printer_name=default_printer.get("name"),
            wait=True,
            timeout=8.0,
        )
        if not status_synced:
            logger.warning("QR status synchronization did not complete printer_id=%s", cloud_printer_id)
            return {
                "success": False,
                "standby": True,
                "error_code": "status_sync_pending",
                "message": "打印服务正在恢复，请稍候。",
            }

        if not cloud_service or not cloud_service.websocket_client:
            return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})

        # 创建一个 Future 用于等待上传凭证响应
        upload_token_future = asyncio.Future()
        upload_token_request_id = str(uuid.uuid4())
        upload_token_loop = asyncio.get_running_loop()

        def resolve_upload_token(value):
            if not upload_token_future.done():
                upload_token_future.set_result(value)

        def upload_token_callback(token, expires_at, upload_url):
            """上传凭证成功回调"""
            upload_token_loop.call_soon_threadsafe(resolve_upload_token, {
                    "success": True,
                    "token": token,
                    "expires_at": expires_at,
                    "upload_url": upload_url
                })

        def upload_token_error_callback(error_code, error_message):
            """上传凭证错误回调"""
            upload_token_loop.call_soon_threadsafe(resolve_upload_token, {
                    "success": False,
                    "error_code": error_code,
                    "error_message": error_message
                })

        # 设置回调
        if cloud_service.print_job_handler:
            cloud_service.print_job_handler.upload_token_callback = upload_token_callback
            cloud_service.print_job_handler.upload_token_error_callback = upload_token_error_callback
            cloud_service.print_job_handler.upload_token_request_id = upload_token_request_id

        # 请求上传凭证
        success = cloud_service.websocket_client.request_upload_token(
            node_id,
            cloud_printer_id,
            upload_token_request_id,
        )
        if not success:
            if (
                cloud_service.print_job_handler
                and cloud_service.print_job_handler.upload_token_request_id == upload_token_request_id
            ):
                cloud_service.print_job_handler.upload_token_callback = None
                cloud_service.print_job_handler.upload_token_error_callback = None
                cloud_service.print_job_handler.upload_token_request_id = None
            return JSONResponse(status_code=500, content={"success": False, "message": "请求上传凭证失败"})

        # 等待上传凭证响应（最多等待 10 秒）
        # 增加超时时间以应对 WebSocket 重连场景（打印完成后可能断开重连需要约5秒）
        try:
            token_data = await asyncio.wait_for(upload_token_future, timeout=10.0)
        except asyncio.TimeoutError:
            return JSONResponse(status_code=504, content={"success": False, "message": "获取上传凭证超时"})
        finally:
            # 清除回调
            if (
                cloud_service.print_job_handler
                and cloud_service.print_job_handler.upload_token_request_id == upload_token_request_id
            ):
                cloud_service.print_job_handler.upload_token_callback = None
                cloud_service.print_job_handler.upload_token_error_callback = None
                cloud_service.print_job_handler.upload_token_request_id = None
    
    # 检查是否是错误响应
    if not token_data.get("success"):
        error_code = token_data.get("error_code", "unknown_error")
        error_message = token_data.get("error_message", "未知错误")
        
        # 根据错误码返回友好提示
        if error_code == "node_disabled":
            return JSONResponse(status_code=403, content={
                "success": False, 
                "error_code": error_code,
                "message": "此节点已被管理员禁用，请联系管理员解除禁用后手动点击刷新按钮"
            })
        elif error_code == "printer_disabled":
            return JSONResponse(status_code=403, content={
                "success": False, 
                "error_code": error_code,
                "message": "所选打印机已被管理员禁用，请联系管理员解除禁用后手动点击刷新按钮"
            })
        elif error_code == "printer_not_found":
            return JSONResponse(status_code=404, content={
                "success": False, 
                "error_code": error_code,
                "message": "打印机不存在，请联系管理员检查配置"
            })
        elif error_code == "printer_not_belong_to_node":
            return JSONResponse(status_code=403, content={
                "success": False, 
                "error_code": error_code,
                "message": "打印机不属于此节点，请联系管理员检查配置"
            })
        elif error_code == "token_generation_failed":
            return JSONResponse(status_code=500, content={
                "success": False, 
                "error_code": error_code,
                "message": "凭证生成失败，请稍后重试"
            })
        else:
            # 其他未知错误
            return JSONResponse(status_code=500, content={
                "success": False, 
                "error_code": error_code,
                "message": error_message or "获取上传凭证失败，请稍后重试"
            })
    
    # 构建完整的上传 URL（指向云端）
    # 使用完整 base_url（含子路径），以便子路径部署时二维码指向正确地址
    base_url = cloud_service.api_client.base_url if cloud_service and cloud_service.api_client else "http://localhost:8080"
    upload_base = (base_url or "").rstrip("/")

    # 获取局域网 IP 并替换 localhost/127.0.0.1（在完整 base 上替换，保留 path）
    try:
        lan_ip = get_host_ip()
        if lan_ip and "localhost" in upload_base:
            upload_base = upload_base.replace("localhost", lan_ip)
        elif lan_ip and "127.0.0.1" in upload_base:
            upload_base = upload_base.replace("127.0.0.1", lan_ip)
    except Exception as e:
        logger.warning(f"无法获取局域网 IP: {e}")

    # 使用云端返回的 upload_url（相对路径），拼接成对浏览器可访问的完整 URL
    raw_upload_url = str(token_data.get("upload_url") or "")
    if raw_upload_url.startswith("http://") or raw_upload_url.startswith("https://"):
        upload_url = raw_upload_url
    else:
        # 严格模式：Cloud 必须下发 web_url/upload_url，相对路径必须以 / 开头
        if not raw_upload_url.strip():
            return JSONResponse(status_code=500, content={"success": False, "message": "云端未返回可用的上传页面 URL"})
        path = raw_upload_url.strip()
        if not path.startswith("/"):
            path = "/" + path
        upload_url = f"{upload_base}{path}"

    session = interactive_session_manager.start_session(upload_token=token_data["token"])
    _report_terminal_session_state(session)
    qr_img_url = build_qr_data_url(upload_url)

    default_printer_capabilities = None
    if default_printer and default_printer.get("name"):
        default_printer_capabilities = printer_manager.get_printer_capabilities(default_printer.get("name"))
    copies_min, copies_max = _normalize_copy_limits()
    
    return {
        "success": True,
        "qr_url": qr_img_url, 
        "text_url": upload_url,
        "node_id": node_id,
        "token": token_data['token'],
        "expires_at": token_data['expires_at'],
        "default_printer_id": default_printer_id,
        "default_printer_capabilities": default_printer_capabilities,
        "settings": {
            "copies_min": copies_min,
            "copies_max": copies_max,
        },
        "session_id": session["session_id"],
    }

@app.get("/api/integration/terminal-ticket")
async def get_terminal_ticket_qr():
    """Return the single Cloud entry QR for the kiosk's default printer."""
    if not node_id or not printer_manager or not cloud_service or not cloud_service.api_client:
        return JSONResponse(status_code=503, content={"success": False, "error_code": "service_not_ready"})
    default_printer_id = _ensure_default_printer()
    default_printer = _get_printer_by_id(default_printer_id) if default_printer_id else None
    cloud_printer_id = _get_cloud_printer_id(default_printer)
    if not cloud_printer_id:
        return {"success": False, "standby": True, "error_code": "printer_cloud_registration_incomplete"}
    availability = await asyncio.to_thread(_get_default_printer_availability_state)
    if availability.get("faulted"):
        return {"success": False, "standby": True, "error_code": "printer_fault", "printer_fault": availability}

    session = interactive_session_manager.start_session(entry_type="entry")
    _report_terminal_session_state(session)
    result = await asyncio.to_thread(
        cloud_service.api_client.issue_terminal_ticket,
        cloud_printer_id,
        session["session_id"],
    )
    entry_url = str(result.get("entry_url") or "")
    raw_ticket = str(result.get("terminal_ticket") or "")
    if not result.get("success") or not entry_url or not raw_ticket:
        interactive_session_manager.clear_session(session["session_id"])
        return JSONResponse(status_code=503, content={"success": False, "error_code": "terminal_ticket_unavailable"})
    # Raw ticket is held only long enough to hash it; never expose it through
    # local APIs, SSE, or logs.
    if not interactive_session_manager.bind_terminal_ticket(session["session_id"], raw_ticket):
        return JSONResponse(status_code=409, content={"success": False, "error_code": "terminal_session_replaced"})
    _report_terminal_session_state(interactive_session_manager.get_active_session())
    return {
        "success": True,
        "qr_url": build_qr_data_url(entry_url),
        "text_url": entry_url,
        "expires_at": result.get("expires_at"),
        "session_id": session["session_id"],
    }


@app.get("/api/events")
async def events(request: Request):
    """SSE 事件流"""
    # 为当前连接创建一个专用队列
    client_queue = asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE)
    sse_clients.append(client_queue)
    logger.debug(f" 新的SSE连接建立，当前客户端数: {len(sse_clients)}")
    
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # 等待消息，设置超时以便处理断开连接
                    data = await asyncio.wait_for(client_queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # 发送心跳注释，保持连接活跃
                    yield ": keep-alive\n\n"
                except Exception as e:
                    logger.error(f"SSE 生成器错误: {e}")
                    break
        finally:
            # 清理连接
            if client_queue in sse_clients:
                sse_clients.remove(client_queue)
            logger.debug(f" SSE连接断开，剩余客户端数: {len(sse_clients)}")
                
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/session/current")
async def get_current_interactive_session():
    return interactive_session_manager.build_snapshot()

@app.post("/api/preview")
async def preview(request: Request):
    request_started_at = time.perf_counter()
    try:
        body_bytes = await request.body()
        body = json.loads(body_bytes)

        session_id = body.get("session_id")
        file_id = body.get("file_id")
        file_url = body.get("file_url")
        file_name = body.get("file_name")
        file_type = body.get("file_type")
        content_hash = body.get("content_hash")
        options = _normalize_request_options(body.get("options") or {})

        if not file_id or not file_url:
            logger.warning("Preview request rejected: missing file_id or file_url")
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: file_id, file_url 必需"})
        if not is_valid_content_hash(content_hash):
            logger.warning("Preview request rejected: missing or invalid content_hash file_id=%s", file_id)
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: content_hash 必需"})
        if session_id and not interactive_session_manager.matches(session_id, file_id):
            return JSONResponse(status_code=409, content={"success": False, "message": "当前会话已失效，请重新扫码"})
        if not printer_manager:
            logger.warning("Preview request rejected: printer manager not ready")
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})

        logger.debug(
            "Preview request started: file_id=%s file_type=%s file_name=%s option_keys=%s body_bytes=%s",
            file_id,
            file_type,
            file_name,
            sorted(options.keys()),
            len(body_bytes),
        )

        try:
            page_index = int(options.get("page_index") or 0)
        except Exception:
            page_index = 0

        if page_index < 0:
            page_index = 0
        options_for_cache = dict(options)
        options_for_cache["page_index"] = page_index
        key = f"{file_id}:{json.dumps(options_for_cache, sort_keys=True, ensure_ascii=False)}"

        file_mgr = get_file_manager()
        if not file_mgr:
            return JSONResponse(status_code=503, content={"success": False, "message": "文件服务未就绪"})
        cached_payload = file_mgr.get_preview(key)
        if cached_payload:
            logger.info("Preview cache hit: file_id=%s page_index=%s", file_id, page_index)
            return {
                "success": True,
                "preview_url": cached_payload["preview_url"],
                "page_count": cached_payload["page_count"],
                "page_index": cached_payload["page_index"],
            }

        download_ms = 0.0
        pipeline = build_document_pipeline(printer_manager.config, logger)
        identity = DocumentIdentity(content_hash, file_name or "", file_type or "")

        def source_supplier():
            nonlocal download_ms
            download_started_at = time.perf_counter()
            downloaded_path, download_error = _download_preview_file(file_url, file_name, file_id)
            download_ms = (time.perf_counter() - download_started_at) * 1000
            if not downloaded_path:
                raise PrintError(ErrorCode.SOURCE_NOT_FOUND, download_error or "preview download failed")
            return Path(downloaded_path)

        canonical = pipeline.resolve_canonical(identity, source_supplier, delete_source=True)
        render_started_at = time.perf_counter()
        preview_page = pipeline.render_preview(canonical, PrintOptions.from_mapping(options), page_index)
        image = preview_page.image
        page_count = preview_page.page_count
        resolved_page_index = preview_page.page_index
        render_ms = (time.perf_counter() - render_started_at) * 1000

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{encoded}"
        cache_key = f"{file_id}:{json.dumps({**options_for_cache, 'page_index': resolved_page_index}, sort_keys=True, ensure_ascii=False)}"
        file_mgr.put_preview(cache_key, {
            "preview_url": data_url,
            "page_count": page_count,
            "page_index": resolved_page_index,
        })
        logger.info(
            "Preview generated: file_id=%s page_index=%s page_count=%s download_ms=%.1f prepare_render_ms=%.1f total_ms=%.1f",
            file_id,
            resolved_page_index,
            page_count,
            download_ms,
            render_ms,
            (time.perf_counter() - request_started_at) * 1000,
        )
        return {"success": True, "preview_url": data_url, "page_count": page_count, "page_index": resolved_page_index}
    except PrintError as e:
        logger.warning(
            "Preview document processing failed: code=%s detail=%s",
            e.code.value,
            e.technical_message,
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "error_code": e.code.value, "message": e.user_message},
        )
    except Exception as e:
        logger.exception("Preview request failed")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.post("/api/print")
async def submit_print(request: Request):
    """提交打印参数"""
    try:
        body = await request.json()
        session_id = body.get("session_id")
        task_token = body.get("task_token")
        raw_options = body.get("options")
        file_id = body.get("file_id")
        
        if not raw_options or not file_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: options, file_id 均必需"})
        if not isinstance(raw_options, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "参数错误: options 必须为对象"})
        options = normalize_print_options(_normalize_request_options(raw_options))
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})
        if not session_id or not interactive_session_manager.matches(session_id, file_id):
            return JSONResponse(status_code=409, content={"success": False, "message": "当前会话已失效，请重新扫码"})
        options["copies"] = _clamp_copy_count(options.get("copies"))

        if cloud_service and cloud_service.websocket_client:
            printer_id = _ensure_default_printer()
            
            if not printer_id:
                 return JSONResponse(status_code=500, content={"success": False, "message": "未找到可用打印机"})
            printer = _get_printer_by_id(printer_id)
            cloud_printer_id = _get_cloud_printer_id(printer)
            if not cloud_printer_id:
                return JSONResponse(status_code=503, content={
                    "success": False,
                    "error_code": "printer_cloud_registration_incomplete",
                    "message": "打印机尚未注册到云端，请联系管理员。",
                })
            if not interactive_session_manager.mark_print_submitted(session_id, file_id, options):
                return JSONResponse(status_code=409, content={"success": False, "message": "打印请求已提交，请勿重复点击"})

            # 发送参数到云端
            # 构造消息
            cloud_duplex = to_cloud_duplex(options.get("duplex"))
            if cloud_duplex:
                options["duplex_mode"] = cloud_duplex
            logger.info(
                "Interactive print options normalized: file_id=%s printer_id=%s options=%r",
                file_id,
                cloud_printer_id,
                options,
            )
            
            from datetime import datetime, timezone
            msg = {
                "type": "submit_print_params",
                "node_id": cloud_service.node_id,
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "data": {
                    "file_id": file_id,
                    "printer_id": cloud_printer_id,
                    "options": options
                }
            }
            # 使用异步发送方法
            send_ok = await cloud_service.websocket_client.send_message(msg)
            if not send_ok:
                interactive_session_manager.revert_print_submission(session_id, file_id)
                return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})
            
            # 清理预览文件（打印时会重新下载，预览文件不再需要）
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.release_preview_resource(file_id, reason="print")
            
            return {"success": True, "message": "打印任务已提交"}
        else:
            return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})
            
    except Exception as e:
        if 'session_id' in locals() and 'file_id' in locals() and session_id and file_id:
            interactive_session_manager.revert_print_submission(session_id, file_id)
        logger.error(f"提交打印参数失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/cleanup")
async def cleanup_preview_file(request: Request):
    """清理预览文件（用户取消时调用）"""
    try:
        body = await request.json()
        file_id = body.get("file_id")
        session_id = body.get("session_id")
        
        if not file_id and not session_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "file_id 或 session_id 不能为空"})
        if session_id and not interactive_session_manager.clear_session(session_id):
            return JSONResponse(status_code=409, content={"success": False, "message": "当前会话已失效，请重新扫码"})
        if session_id:
            _report_terminal_session_state(None)
        
        # 通过文件管理器清理
        if file_id:
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.release_preview_resource(file_id, reason="cancel")
        
        return {"success": True, "message": "文件已清理"}
        
    except Exception as e:
        logger.error(f"清理文件失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@admin_router.get("/config")
async def get_admin_config():
    service = _get_config_service()
    payload = service.get_public_config()
    return {"success": True, **payload}


@admin_router.get("/system/startup")
async def get_admin_startup_state():
    return {"success": True, "enabled": get_windows_startup_enabled()}


@admin_router.post("/system/startup")
async def update_admin_startup_state(request: Request):
    body = await request.json()
    enabled = bool(body.get("enabled"))
    set_windows_startup_enabled(enabled)
    return {"success": True, "enabled": enabled}


@admin_router.post("/config")
async def save_admin_config(request: Request):
    global node_id
    body = await request.json()
    try:
        service = _get_config_service()
        result = service.save_and_apply(body, cloud_service=cloud_service)
        if cloud_service:
            node_id = cloud_service.node_id
        status_code = 200 if result.get("success") else 400
        return JSONResponse(status_code=status_code, content=result)
    except Exception as e:
        logger.error(f"save admin config failed: {e}")
        return JSONResponse(status_code=500, content={"success": False, "saved": False, "errors": [str(e)]})


@admin_router.post("/cloud/activate")
async def activate_cloud_node(request: Request):
    """The only initial Cloud onboarding endpoint for an unactivated Edge."""
    global node_id
    if not cloud_service:
        return JSONResponse(status_code=503, content={"success": False, "message": "云端服务不可用"})
    body = await request.json()
    result = await asyncio.to_thread(
        cloud_service.activate,
        str(body.get("base_url") or ""),
        str(body.get("activation_code") or ""),
    )
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    node_id = result.get("node_id")
    await broadcast_sse_event("node_status_changed", {"status": "registered", "node_id": node_id})
    return {"success": True, "message": "终端已激活并连接 Cloud", "node_id": node_id}


@admin_router.post("/cloud/unbind")
async def unbind_cloud_node():
    """Make the local device return to the activation screen."""
    global node_id
    if not cloud_service:
        return JSONResponse(status_code=503, content={"success": False, "message": "云端服务不可用"})
    result = await asyncio.to_thread(cloud_service.unbind)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    node_id = None
    await broadcast_sse_event("node_status_changed", {"status": "unbound", "node_id": None})
    return result


@admin_router.get("/cloud/status")
async def get_cloud_status():
    if not cloud_service:
        return {
            "success": True,
            "configured": False,
            "registered": False,
            "connected": False,
            "node_id": None,
            "message": "\u4e91\u7aef\u670d\u52a1\u4e0d\u53ef\u7528",
            "missing_fields": ["base_url", "credential_blob"],
            "activated": False,
        }
    try:
        status = cloud_service.get_status()
        ws = status.get("websocket") or {}
        connected = bool(ws.get("connected"))
        configured = bool(status.get("configured"))
        registered = bool(status.get("registered"))
        if not configured:
            message = "\u914d\u7f6e\u4e0d\u5b8c\u6574"
        elif connected:
            message = "\u5df2\u8fde\u63a5"
        elif registered:
            message = "\u7b49\u5f85\u8fde\u63a5"
        else:
            message = "\u5f85\u6ce8\u518c\u8282\u70b9"
        return {
            "success": True,
            "configured": configured,
            "registered": registered,
            "connected": connected,
            "node_id": status.get("node_id"),
            "message": message,
            "missing_fields": status.get("missing_fields", []),
            "activated": bool(status.get("node_id") and (printer_manager.config.config.get("cloud", {}).get("credential_blob") if printer_manager else "")),
        }
    except Exception as e:
        logger.error(f"get cloud status failed: {e}")
        return {"success": False, "message": str(e)}

@admin_router.get("/printers/managed")
async def get_managed_printers():
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    default_id = _ensure_default_printer()
    printers = []
    for printer in _get_managed_printers():
        item = dict(printer)
        item["is_default"] = item.get("id") == default_id
        item.update(printer_manager.get_admin_printer_summary(item.get("name")))
        status_detail = await asyncio.to_thread(printer_manager.get_printer_status_detail, item.get("name"))
        item["status"] = status_detail.get("status_text", "unknown")
        item["uncertain"] = bool(status_detail.get("uncertain"))
        printers.append(item)
    return {
        "success": True,
        "items": printers,
        "default_printer_id": default_id
    }

@admin_router.get("/printers/discovered")
async def get_discovered_printers():
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    managed_uuids = {str(p.get("printer_uuid") or "").casefold() for p in _get_managed_printers()}
    all_printers = await asyncio.to_thread(printer_manager.discovery.discover_network_printers)
    available = []
    for printer in all_printers:
        if str(printer.get("printer_uuid") or "").casefold() in managed_uuids:
            continue
        available.append(dict(printer))
    return {"success": True, "items": available}


@admin_router.post("/printers/probe")
async def probe_ipp_printer(request: Request):
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    body = await request.json()
    ipp_uri = str(body.get("ipp_uri") or "").strip()
    if not ipp_uri:
        return {"success": False, "message": "请输入完整的 IPP URI"}
    try:
        item = await asyncio.to_thread(printer_manager.probe_printer, ipp_uri)
    except Exception as exc:
        return {"success": False, "message": f"IPP 检测失败: {exc}"}
    return {"success": True, "item": item}

@admin_router.post("/printers/add")
async def add_managed_printer(request: Request):
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    body = await request.json()
    body = {"ipp_uri": str(body.get("ipp_uri") or "").strip()}
    success, message = await asyncio.to_thread(printer_manager.add_printer_intelligently, body)
    if not success:
        return {"success": False, "message": message}
    default_id = _ensure_default_printer()
    added_printer = None
    for printer in _get_managed_printers():
        if printer.get("ipp_uri") == body.get("ipp_uri"):
            added_printer = printer
            break
    if not default_id and added_printer:
        printer_manager.config.set_default_printer_id(added_printer.get("id"))
        default_id = added_printer.get("id")
    
    # 广播打印机添加事件
    await broadcast_sse_event("printer_added", {
        "printer": added_printer,
        "default_printer_id": default_id
    })
    
    # 尝试注册到云端，并记录注册状态
    cloud_registered = False
    cloud_error = None
    if cloud_service and added_printer:
        result = cloud_service.register_managed_printer(added_printer)
        if result.get("success"):
            cloud_registered = True
        else:
            cloud_error = result.get("message") or result.get("error") or "云端注册失败"
            logger.warning(f"打印机 {added_printer.get('name')} 云端注册失败: {cloud_error}")
    
    return {
        "success": True, 
        "message": "打印机添加成功", 
        "default_printer_id": default_id,
        "printer_id": added_printer.get("id") if added_printer else None,
        "cloud_registered": cloud_registered,
        "cloud_error": cloud_error
    }


@admin_router.post("/printers/{printer_id}/clear-unconfirmed")
async def clear_unconfirmed_printer(printer_id: str):
    if not printer_manager or not _get_printer_by_id(printer_id):
        return {"success": False, "message": "未找到该打印机"}
    printer_manager.clear_uncertain(printer_id)
    return {"success": True, "message": "已解除结果未知锁定，请确认打印机中没有遗留任务后再继续。"}

@admin_router.post("/printers/default")
async def set_default_printer(request: Request):
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    body = await request.json()
    printer_id = body.get("printer_id")
    if not printer_id:
        return {"success": False, "message": "printer_id 不能为空"}
    managed = _get_managed_printers()
    if not any(p.get("id") == printer_id for p in managed):
        return {"success": False, "message": "打印机不存在"}
    target = next(p for p in managed if p.get("id") == printer_id)
    if not target.get("enabled", True):
        return {"success": False, "message": "已禁用的打印机不能设为默认打印机。"}
    printer_manager.config.set_default_printer_id(printer_id)
    
    # 广播默认打印机变更事件
    await broadcast_sse_event("default_printer_changed", {
        "printer_id": printer_id
    })
    
    return {"success": True, "default_printer_id": printer_id}

@admin_router.delete("/printers/{printer_id}")
async def delete_managed_printer(printer_id: str):
    result = _remove_managed_printer(printer_id)
    if not result.get("success"):
        return {"success": False, "message": result.get("message")}
    
    # 尝试从云端删除，但不影响本地删除结果
    cloud_delete_warning = None
    removed_printer = result.get("removed_printer") or {}
    cloud_printer_id = removed_printer.get("cloud_id")
    if cloud_service and cloud_printer_id:
        cloud_result = cloud_service.delete_printer_from_cloud(cloud_printer_id)
        if not cloud_result.get("success"):
            cloud_delete_warning = cloud_result.get("message") or cloud_result.get("error") or "云端删除失败"
            logger.warning(f"打印机 {printer_id} 云端删除失败: {cloud_delete_warning}")
    
    # 广播打印机删除事件
    await broadcast_sse_event("printer_deleted", {
        "printer_id": printer_id,
        "default_printer_id": result.get("default_printer_id")
    })
    
    response = {
        "success": True, 
        "default_printer_id": result.get("default_printer_id")
    }
    
    # 如果云端删除失败，附带警告信息
    if cloud_delete_warning:
        response["warning"] = f"打印机已从本地删除，但云端删除失败: {cloud_delete_warning}"
    
    return response

@admin_router.post("/printers/{printer_id}/reregister")
async def reregister_printer(printer_id: str):
    """重新注册单个打印机到云端（仅在节点已注册时可用）"""
    if not printer_manager or not cloud_service:
        return {"success": False, "message": "服务未就绪"}
    try:
        # 检查节点是否已注册
        status = cloud_service.get_status()
        if not status.get("registered"):
            return {"success": False, "message": "节点未注册，无法重新注册打印机"}
        
        # 查找本地打印机
        managed = _get_managed_printers()
        target = None
        for p in managed:
            if p.get("id") == printer_id:
                target = p
                break
        if not target:
            return {"success": False, "message": "打印机不存在"}
        
        # 调用云端注册
        result = cloud_service.register_managed_printer(target)
        if result.get("success"):
            return {"success": True, "message": "打印机重新注册成功"}
        else:
            # 兼容不同返回格式
            msg = result.get("message") or result.get("error") or "打印机重新注册失败"
            return {"success": False, "message": msg}
    except Exception as e:
        logger.error(f"重新注册打印机失败: {e}")
        return {"success": False, "message": str(e)}

# 注册 Admin Router
@admin_router.post("/printers/{printer_id}/test")
async def start_printer_test(printer_id: str):
    printer = _get_printer_by_id(printer_id)
    if not printer:
        return {"success": False, "message": "未找到该打印机。"}
    active_task_id = active_printer_tests.get(printer_id)
    if active_task_id and printer_test_tasks.get(active_task_id, {}).get("status") == "running":
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "message": "该打印机正在执行测试，请勿重复提交。",
                "task_id": active_task_id,
            },
        )
    task_id = f"printer-test-{printer_id}-{time.time_ns()}"
    while len(printer_test_tasks) >= 50:
        oldest = next(iter(printer_test_tasks))
        if printer_test_tasks[oldest].get("status") == "running":
            break
        printer_test_tasks.pop(oldest)
    printer_test_tasks[task_id] = {
        "task_id": task_id,
        "printer_id": printer_id,
        "status": "running",
        "events": [],
    }
    active_printer_tests[printer_id] = task_id

    def record(event):
        public = event.public_dict()
        printer_test_tasks[task_id]["events"].append(public)
        printer_test_tasks[task_id]["current"] = public

    def run():
        test_source = None
        try:
            from pathlib import Path
            from print_runtime import build_print_request, build_print_service
            from printing.domain import PrintOptions, PrintState

            test_source = Path(get_portable_temp_dir()) / f"{task_id}.pdf"
            document = fitz.open()
            try:
                page = document.new_page(width=595.276, height=841.89)
                page.insert_text((72, 90), "FlyPrint Direct IPP Test", fontsize=18)
                page.insert_text((72, 125), f"Printer: {printer.get('name')}", fontsize=11)
                document.save(test_source)
            finally:
                document.close()
            service = build_print_service(printer_manager.config, logger)
            request = build_print_request(
                printer_manager.config,
                job_id=task_id,
                printer_id=printer_id,
                printer_name=printer.get("name"),
                file_path=str(test_source),
                source_name=test_source.name,
                content_hash=hashlib.sha256(test_source.read_bytes()).hexdigest(),
                source_kind="application/pdf",
                print_options=PrintOptions(
                    copies=1,
                    duplex="simplex",
                    color_mode="mono",
                    paper_size="A4",
                ).__dict__,
            )
            event = service.execute(request, record)
            success = event.state == PrintState.COMPLETED
            printer_test_tasks[task_id].update({
                "status": "completed" if success else "failed",
                "result": {
                    "success": success,
                    "message": "设备已确认打印完成。" if success else event.message,
                    "error_code": event.error_code.value if event.error_code else None,
                },
            })
        except Exception as exc:
            logger.exception("printer test failed: task_id=%s", task_id)
            printer_test_tasks[task_id].update({
                "status": "failed",
                "result": {"success": False, "message": str(exc)},
            })
        finally:
            if test_source:
                test_source.unlink(missing_ok=True)
            active_printer_tests.pop(printer_id, None)

    import threading
    threading.Thread(target=run, name=task_id, daemon=True).start()
    return {"success": True, "task_id": task_id}


@admin_router.get("/printer-tests/{task_id}")
async def get_printer_test(task_id: str):
    task = printer_test_tasks.get(task_id)
    if not task:
        return {"success": False, "message": "未找到测试任务。"}
    return {"success": True, **task}


app.include_router(admin_router)

def run_server():
    from printer_config import PrinterConfig
    config_repo = PrinterConfig()
    log_settings = configure_logging(config_repo.get_full_config())
    config = config_repo.config
    network_cfg = config.get("network", {})
    bind_address = network_cfg.get("bind_address", "127.0.0.1")
    port = network_cfg.get("port", 7860)
    
    logger.info(f" 启动服务: {bind_address}:{port}")
    uvicorn.run(
        app,
        host=bind_address,
        port=port,
        reload=False,
        access_log=log_settings["access_log"],
        log_config=None,
        use_colors=False,
    )


if __name__ == "__main__":
    run_server()
