
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
import io
import tempfile
import shutil
import requests
import qrcode
import time
from PIL import Image
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
from printer_fault_probe import IPPPrinterFaultProbe, resolve_printer_host
from printer_fault_state import PrinterFaultStateStore
from windows_startup import get_windows_startup_enabled, set_windows_startup_enabled
from print_layout import (
    compute_physical_fit_rect,
    compute_scaled_size,
    image_size_inches,
    normalize_paper_size,
    normalize_scale_mode,
    paper_size_px,
    paper_size_inches,
    resolve_layout_options,
    safe_float,
)

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
node_id: Optional[str] = None
main_loop: Optional[asyncio.AbstractEventLoop] = None
preview_cache: Dict[str, Dict[str, Any]] = {}
preview_page_cache: Dict[str, Dict[int, Image.Image]] = {}
preview_page_meta: Dict[str, Dict[str, int]] = {}
interactive_session_manager = InteractiveSessionManager()
printer_fault_state_store = PrinterFaultStateStore()
printer_fault_probe = IPPPrinterFaultProbe()
qr_code_request_lock: Optional[asyncio.Lock] = None
config_service: Optional[ConfigService] = None

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
        preview_page_cache=preview_page_cache,
        preview_page_meta=preview_page_meta,
    )
    # 清理 portable temp 目录中的遗留文件
    cleanup_temp_dir(max_age_hours=24)
    file_mgr.start()
    logger.info(" 文件管理器已启动（包含预览图缓存清理）")
    
    # 初始化云端服务
    cloud_config = printer_manager.config.config.get("cloud", {})
    cloud_service = CloudService(
        cloud_config,
        printer_manager,
        interactive_job_binder=bind_interactive_cloud_job,
        fault_state_store=printer_fault_state_store,
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
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass
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

def bind_interactive_cloud_job(file_url: Optional[str], job_id: Optional[str]) -> Optional[str]:
    if not file_url or not job_id:
        return None
    bound = interactive_session_manager.attach_cloud_job(file_url, job_id)
    if not bound:
        return None
    return bound.get("session_id")

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
                try:
                    q.put_nowait(enriched_message)
                except asyncio.QueueFull:
                    pass

        if main_loop:
            main_loop.call_soon_threadsafe(push_to_queues)
        else:
            push_to_queues()
            
    except Exception as e:
        logger.error(f" 推送消息到SSE队列失败: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(" Edge Server 正在停止...")
    
    # 停止文件管理器
    file_mgr = get_file_manager()
    if file_mgr:
        file_mgr.cleanup_all_preview_files()
        file_mgr.stop()
    
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
    return _get_default_printer_availability_state()

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
        if printer.get("id") == printer_id:
            return printer
    return None

def _ensure_default_printer():
    if not printer_manager:
        return None
    printers = _get_managed_printers()
    if not printers:
        printer_manager.config.clear_default_printer_id()
        return None
    default_id = printer_manager.config.get_default_printer_id()
    valid_ids = {p.get("id") for p in printers}
    if default_id in valid_ids:
        return default_id
    new_default_id = printers[0].get("id")
    if new_default_id:
        printer_manager.config.set_default_printer_id(new_default_id)
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
    host = resolve_printer_host(default_printer)
    if printer_fault_probe and host:
        result = printer_fault_probe.probe(host)
        if getattr(result, "available", False):
            return printer_fault_state_store.update_from_probe(
                printer_id=printer_id,
                printer_name=printer_name,
                result=result,
            )

    state = printer_fault_state_store.get_state()
    state["printer_id"] = printer_id
    state["printer_name"] = printer_name
    return state

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

async def _wait_for_cloud_connected(timeout_seconds: float = 5.0, interval_seconds: float = 0.2) -> bool:
    if not cloud_service:
        return False

    elapsed = 0.0
    while elapsed < timeout_seconds:
        status = cloud_service.get_status()
        websocket = status.get("websocket") or {}
        if status.get("registered") and websocket.get("connected"):
            return True
        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds

    status = cloud_service.get_status()
    websocket = status.get("websocket") or {}
    return bool(status.get("registered") and websocket.get("connected"))

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
        logger.debug(
            "Downloading preview source: file_id=%s file_name=%s auth=%s url=%s path=%s headers=%s",
            file_id,
            file_name,
            auth_mode,
            download_url,
            path,
            headers,
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
        logger.exception("Preview file download failed: file_id=%s file_name=%s", file_id, file_name)
        return None, str(e)


def _normalize_paper_size(paper_size: Optional[str]) -> str:
    """规范化纸张名称，支持 'Letter (横向)' 等"""
    return normalize_paper_size(paper_size)


def _get_paper_size_px(paper_size: Optional[str], dpi: int = 120):
    return paper_size_px(paper_size, dpi=dpi)

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

def _safe_float(value: Any, default: float) -> float:
    return safe_float(value, default)

def _normalize_scale_mode(value: Any, default: str = "fit") -> str:
    return normalize_scale_mode(value, default)

def _resolve_layout_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return resolve_layout_options(options, _get_settings())

def _compute_scaled_size(src_w: int, src_h: int, dst_w: int, dst_h: int, scale_mode: str, max_upscale: float):
    target_w, target_h, _ = compute_scaled_size(src_w, src_h, dst_w, dst_h, scale_mode, max_upscale)
    return target_w, target_h

def _normalize_request_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = dict(options or {})
    layout = _resolve_layout_options(normalized)
    normalized.update(layout)
    return normalized

def _apply_paper_size(image: Image.Image, paper_size: Optional[str], options: Optional[Dict[str, Any]] = None):
    opts = options or {}
    preview_w = _safe_int(opts.get("preview_width_px"), 0)
    preview_h = _safe_int(opts.get("preview_height_px"), 0)
    layout = _resolve_layout_options(opts)
    paper_target = _get_paper_size_px(paper_size or layout.get("paper_size"))
    if preview_w > 0 and preview_h > 0:
        # 预览始终以页面容器为边界，但按真实纸张比例缩放，避免预览与实打方向/比例偏移
        if paper_target:
            pw, ph = paper_target
            scale = min(preview_w / max(1, pw), preview_h / max(1, ph))
            target = (max(1, int(round(pw * scale))), max(1, int(round(ph * scale))))
        else:
            target = (preview_w, preview_h)
    else:
        target = paper_target
        if not target:
            return image

    w, h = target
    canvas = Image.new("RGB", (w, h), "white")
    img = image.convert("RGB")
    source_inches = opts.get("source_inches")
    if source_inches and layout.get("scale_mode") == "actual":
        target_inches = paper_size_inches(paper_size or layout.get("paper_size"))
        if target_inches:
            target_dpi = (w / target_inches[0], h / target_inches[1])
            x, y, new_w, new_h, _ = compute_physical_fit_rect(
                source_inches,
                (w, h),
                target_dpi,
            )
        else:
            x = y = 0
            new_w, new_h = _compute_scaled_size(
                img.width,
                img.height,
                w,
                h,
                layout.get("scale_mode", "actual"),
                _safe_float(layout.get("max_upscale"), 3.0)
            )
    else:
        new_w, new_h = _compute_scaled_size(
            img.width,
            img.height,
            w,
            h,
            layout.get("scale_mode", "actual"),
            _safe_float(layout.get("max_upscale"), 3.0)
        )
        x = (w - new_w) // 2
        y = (h - new_h) // 2
    resample_lanczos = getattr(Image, "Resampling", Image).LANCZOS
    resized = img.resize((new_w, new_h), resample=resample_lanczos)
    canvas.paste(resized, (x, y))
    return canvas

def _detect_pdf_paper_size_from_file(file_path: str) -> Optional[str]:
    """从 PDF 第一页检测纸张尺寸，用于预览与打印一致"""
    try:
        doc = fitz.open(file_path)
        if doc.page_count == 0:
            doc.close()
            return None
        page = doc.load_page(0)
        media_box = page.mediabox
        width_pt = media_box.width
        height_pt = media_box.height
        doc.close()
        width_inch = width_pt / 72.0
        height_inch = height_pt / 72.0
        paper_sizes = {
            "A4": (8.27, 11.69),
            "Letter": (8.5, 11.0),
            "Legal": (8.5, 14.0),
            "A3": (11.69, 16.54),
            "A5": (5.83, 8.27),
            "Tabloid": (11.0, 17.0),
        }
        tolerance = 0.2
        for size_name, (std_w, std_h) in paper_sizes.items():
            if abs(width_inch - std_w) <= tolerance and abs(height_inch - std_h) <= tolerance:
                return size_name
            if abs(width_inch - std_h) <= tolerance and abs(height_inch - std_w) <= tolerance:
                return f"{size_name} (横向)"
        return None
    except Exception:
        return None


def _get_pdf_page_size_inches(file_path: str, page_index: int = 0) -> Optional[tuple[float, float]]:
    try:
        doc = fitz.open(file_path)
        if doc.page_count == 0:
            doc.close()
            return None
        page_index = max(0, min(page_index, doc.page_count - 1))
        page = doc.load_page(page_index)
        media_box = page.mediabox
        size = (media_box.width / 72.0, media_box.height / 72.0)
        doc.close()
        return size
    except Exception:
        return None


def _detect_paper_size_from_file(file_path: str, file_name: Optional[str], file_type: Optional[str], pdf_path: Optional[str] = None) -> Optional[str]:
    """根据文件类型检测纸张尺寸"""
    ext = os.path.splitext(file_name or "")[1].lower()
    if not ext and file_type:
        ext = ".pdf" if "pdf" in (file_type or "").lower() else ".docx" if "word" in (file_type or "").lower() else ""
    path_to_check = pdf_path if pdf_path and os.path.exists(pdf_path) else file_path
    if ext == ".pdf" and path_to_check:
        return _detect_pdf_paper_size_from_file(path_to_check)
    return None


def _render_pdf_to_image(file_path: str, page_index: int):
    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count
        if page_count == 0:
            doc.close()
            return None, 0, 0, "PDF 无可预览页面"
        if page_index < 0:
            page_index = 0
        if page_index >= page_count:
            page_index = page_count - 1
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=120, alpha=False)
        doc.close()
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return image, page_count, page_index, None
    except Exception as e:
        return None, 0, 0, str(e)

def _find_libreoffice_path():
    settings = _get_settings()
    configured = _resolve_path(settings.get("libreoffice_path"))
    if configured:
        return configured
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return shutil.which("soffice")

def _convert_word_to_pdf(file_path: str):
    import pythoncom
    from win32com import client
    import subprocess
    pdf_path = None
    try:
        pythoncom.CoInitialize()
        # 使用 portable temp 目录
        temp_dir = get_portable_temp_dir()
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        pdf_path = os.path.join(temp_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass
        abs_file_path = os.path.abspath(file_path)

        def convert_with_com(prog_id: str):
            word = None
            doc = None
            try:
                word = client.Dispatch(prog_id)
                word.Visible = False
                try:
                    word.DisplayAlerts = False
                except Exception:
                    pass
                doc = word.Documents.Open(abs_file_path)
                doc.SaveAs(pdf_path, FileFormat=17)
                doc.Close()
                return True, None
            except Exception as e:
                try:
                    if doc:
                        doc.Close()
                except Exception:
                    pass
                return False, str(e)
            finally:
                try:
                    if word:
                        word.Quit()
                except Exception:
                    pass

        wps_prog_ids = ["Kwps.Application", "WPS.Application", "wps.application"]
        for prog_id in wps_prog_ids:
            ok, _ = convert_with_com(prog_id)
            if ok and os.path.exists(pdf_path):
                return pdf_path, None

        soffice = _find_libreoffice_path()
        if soffice:
            try:
                result = subprocess.run(
                    [soffice, "--headless", "--convert-to", "pdf", "--outdir", temp_dir, abs_file_path],
                    capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=60
                )
                if result.returncode == 0 and os.path.exists(pdf_path):
                    return pdf_path, None
            except Exception as e:
                return None, str(e)

        ok, err = convert_with_com("Word.Application")
        if ok and os.path.exists(pdf_path):
            return pdf_path, None
        return None, err or "文档转PDF失败"
    finally:
        pythoncom.CoUninitialize()

def _resolve_preview_ext(file_name: Optional[str], file_type: Optional[str]):
    ext = os.path.splitext(file_name or "")[1].lower()
    if not ext and file_type:
        lowered = file_type.lower()
        if "pdf" in lowered:
            ext = ".pdf"
        elif "image" in lowered:
            ext = ".png"
        elif "word" in lowered:
            ext = ".docx"
    return ext

def _get_cached_pdf_page(file_id: str, pdf_path: str, page_index: int):
    if file_id:
        file_cache = preview_page_cache.get(file_id)
        if file_cache and page_index in file_cache:
            meta = preview_page_meta.get(file_id, {})
            page_count = meta.get("page_count", 1)
            return file_cache[page_index], page_count, page_index, None
    image, page_count, resolved_page_index, error = _render_pdf_to_image(pdf_path, page_index)
    if image is None:
        return None, page_count, resolved_page_index, error
    if file_id:
        preview_page_cache.setdefault(file_id, {})[resolved_page_index] = image
        preview_page_meta[file_id] = {"page_count": page_count}
    return image, page_count, resolved_page_index, None

def _generate_preview_image(file_id: str, file_path: str, file_name: Optional[str], file_type: Optional[str], options: Dict[str, Any], page_index: int):
    ext = _resolve_preview_ext(file_name, file_type)
    image = None
    page_count = 1
    resolved_page_index = page_index
    error = None
    source_inches = None
    if ext in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"]:
        try:
            img = Image.open(file_path)
            source_inches = image_size_inches(img)
            image = img.convert("RGB")
            img.close()
            resolved_page_index = 0
            page_count = 1
            if file_id:
                preview_page_cache.setdefault(file_id, {})[resolved_page_index] = image
                preview_page_meta[file_id] = {"page_count": page_count}
        except Exception as e:
            error = str(e)
    elif ext == ".pdf":
        image, page_count, resolved_page_index, error = _get_cached_pdf_page(file_id, file_path, page_index)
        if image is not None:
            source_inches = _get_pdf_page_size_inches(file_path, resolved_page_index)
    elif ext in [".doc", ".docx"]:
        pdf_path = None
        file_mgr = get_file_manager()
        file_info = file_mgr.get_preview_resource(file_id) if file_mgr and file_id else None
        if file_info:
            pdf_path = file_info.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path, error = _convert_word_to_pdf(file_path)
            if pdf_path and file_id:
                if file_mgr and file_info and file_info.get("source_path"):
                    file_mgr.register_preview_resource(file_id, file_info.get("file_url") or "", file_info["source_path"], pdf_path)
        if pdf_path:
            image, page_count, resolved_page_index, error = _get_cached_pdf_page(file_id, pdf_path, page_index)
            if image is not None:
                source_inches = _get_pdf_page_size_inches(pdf_path, resolved_page_index)
    else:
        error = "暂不支持该文件类型预览"
    if image is None:
        return None, 0, 0, error or "预览生成失败"
    color_mode = (options.get("color_mode") or options.get("color") or "").lower()
    if "gray" in color_mode or "mono" in color_mode or "黑白" in color_mode:
        image = image.convert("L").convert("RGB")
    resolved_options = _normalize_request_options(options)
    if source_inches:
        resolved_options["source_inches"] = source_inches
    # 预览固定落在目标纸张画布上；源文件尺寸只参与内容绘制比例，不改变目标纸张。
    explicit_paper = options.get("paper_size") or options.get("page_size") or options.get("size")
    if explicit_paper:
        resolved_options["paper_size"] = str(explicit_paper).strip()
    image = _apply_paper_size(image, resolved_options.get("paper_size"), resolved_options)
    return image, page_count, resolved_page_index, None

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
    printer_manager.config.remove_printer(printer_id)
    managed_after = _get_managed_printers()
    new_default_id = None
    if default_id == printer_id:
        if managed_after:
            target_index = min(removed_index or 0, len(managed_after) - 1)
            new_default_id = managed_after[target_index].get("id")
            if new_default_id:
                printer_manager.config.set_default_printer_id(new_default_id)
        else:
            printer_manager.config.clear_default_printer_id()
    else:
        new_default_id = printer_manager.config.get_default_printer_id()
    return {"success": True, "default_printer_id": new_default_id}

@app.get("/api/qr_code")
async def get_qr_code():
    """获取上传二维码信息"""
    global qr_code_request_lock

    if qr_code_request_lock is None:
        qr_code_request_lock = asyncio.Lock()

    async with qr_code_request_lock:
        if not node_id:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未注册或离线"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})
        if len(_get_managed_printers()) == 0:
            return {"success": False, "standby": True, "message": "暂无可用打印机"}
        default_printer_id = _ensure_default_printer()
        if not default_printer_id:
            return {"success": False, "standby": True, "message": "暂无可用打印机"}

        # 通过 WebSocket 请求上传凭证
        availability = _get_default_printer_availability_state()
        if availability.get("faulted"):
            return {
                "success": False,
                "standby": True,
                "error_code": "printer_fault",
                "message": availability.get("message") or "打印机故障，请联系管理员处理",
                "printer_fault": availability,
            }

        if not cloud_service or not cloud_service.websocket_client:
            return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})

        # 创建一个 Future 用于等待上传凭证响应
        upload_token_future = asyncio.Future()

        def upload_token_callback(token, expires_at, upload_url):
            """上传凭证成功回调"""
            if not upload_token_future.done():
                upload_token_future.set_result({
                    "success": True,
                    "token": token,
                    "expires_at": expires_at,
                    "upload_url": upload_url
                })

        def upload_token_error_callback(error_code, error_message):
            """上传凭证错误回调"""
            if not upload_token_future.done():
                upload_token_future.set_result({
                    "success": False,
                    "error_code": error_code,
                    "error_message": error_message
                })

        # 设置回调
        if cloud_service.print_job_handler:
            cloud_service.print_job_handler.upload_token_callback = upload_token_callback
            cloud_service.print_job_handler.upload_token_error_callback = upload_token_error_callback

        # 请求上传凭证
        success = cloud_service.websocket_client.request_upload_token(node_id, default_printer_id)
        if not success:
            return JSONResponse(status_code=500, content={"success": False, "message": "请求上传凭证失败"})

        # 等待上传凭证响应（最多等待 10 秒）
        # 增加超时时间以应对 WebSocket 重连场景（打印完成后可能断开重连需要约5秒）
        try:
            token_data = await asyncio.wait_for(upload_token_future, timeout=10.0)
        except asyncio.TimeoutError:
            return JSONResponse(status_code=504, content={"success": False, "message": "获取上传凭证超时"})
        finally:
            # 清除回调
            if cloud_service.print_job_handler:
                cloud_service.print_job_handler.upload_token_callback = None
                cloud_service.print_job_handler.upload_token_error_callback = None
    
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
    qr_img_url = build_qr_data_url(upload_url)

    default_printer = _get_printer_by_id(default_printer_id)
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

@app.get("/api/events")
async def events(request: Request):
    """SSE 事件流"""
    # 为当前连接创建一个专用队列
    client_queue = asyncio.Queue()
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

        file_mgr = get_file_manager()
        cached = file_mgr.get_preview_resource(file_id) if file_mgr else None
        if not cached and file_mgr:
            cached = file_mgr.reuse_cached_resource(file_id, file_url, content_hash)
        logger.debug(
            "Preview request started: file_id=%s file_type=%s file_name=%s option_keys=%s cached=%s body_bytes=%s",
            file_id,
            file_type,
            file_name,
            sorted(options.keys()),
            bool(cached),
            len(body_bytes),
        )

        if cached and cached.get("file_url") != file_url:
            logger.debug("Preview source URL changed: file_id=%s", file_id)
            file_mgr.release_preview_resource(file_id, reason="url_changed")
            cached = None

        try:
            page_index = int(options.get("page_index") or 0)
        except Exception:
            page_index = 0

        if page_index < 0:
            page_index = 0
        options_for_cache = dict(options)
        options_for_cache["page_index"] = page_index
        key = f"{file_id}:{json.dumps(options_for_cache, sort_keys=True, ensure_ascii=False)}"

        if key in preview_cache:
            logger.info("Preview cache hit: file_id=%s page_index=%s", file_id, page_index)
            cached_payload = preview_cache[key]
            return {
                "success": True,
                "preview_url": cached_payload["preview_url"],
                "page_count": cached_payload["page_count"],
                "page_index": cached_payload["page_index"],
            }

        file_path = cached.get("source_path") if cached else None
        if not file_path or not os.path.exists(file_path):
            logger.debug("Preview source missing locally, downloading: file_id=%s", file_id)
            file_path, err = _download_preview_file(file_url, file_name, file_id)
            if not file_path:
                logger.warning("Preview source download failed: file_id=%s error=%s", file_id, err)
                return JSONResponse(status_code=500, content={"success": False, "message": err or "下载文件失败"})
            if file_mgr:
                cached_pdf = cached.get("pdf_path") if cached else None
                if cached_pdf and not os.path.exists(cached_pdf):
                    cached_pdf = None
                file_mgr.register_preview_resource(file_id, file_url, file_path, cached_pdf, content_hash=content_hash)
        else:
            if file_mgr:
                file_mgr.touch_preview_resource(file_id)

        image, page_count, resolved_page_index, err = _generate_preview_image(
            file_id, file_path, file_name, file_type, options, page_index
        )
        if not image:
            return JSONResponse(status_code=500, content={"success": False, "message": err or "预览生成失败"})

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{encoded}"
        cache_key = f"{file_id}:{json.dumps({**options_for_cache, 'page_index': resolved_page_index}, sort_keys=True, ensure_ascii=False)}"
        preview_cache[cache_key] = {
            "preview_url": data_url,
            "page_count": page_count,
            "page_index": resolved_page_index,
            "timestamp": time.time(),
        }
        logger.info(
            "Preview generated: file_id=%s page_index=%s page_count=%s",
            file_id,
            resolved_page_index,
            page_count,
        )
        return {"success": True, "preview_url": data_url, "page_count": page_count, "page_index": resolved_page_index}
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
        options = _normalize_request_options(raw_options)
        file_id = body.get("file_id")
        
        if not raw_options or not file_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: options, file_id 均必需"})
        if not isinstance(raw_options, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "参数错误: options 必须为对象"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})
        if not session_id or not interactive_session_manager.matches(session_id, file_id):
            return JSONResponse(status_code=409, content={"success": False, "message": "当前会话已失效，请重新扫码"})
        options["copies"] = _clamp_copy_count(options.get("copies"))

        if cloud_service and cloud_service.websocket_client:
            printer_id = _ensure_default_printer()
            
            if not printer_id:
                 return JSONResponse(status_code=500, content={"success": False, "message": "未找到可用打印机"})
            if not interactive_session_manager.mark_print_submitted(session_id, file_id):
                return JSONResponse(status_code=409, content={"success": False, "message": "打印请求已提交，请勿重复点击"})

            # 发送参数到云端
            # 构造消息
            duplex_value = options.get("duplex")
            if duplex_value:
                duplex_value_str = str(duplex_value).lower()
                if duplex_value_str in ["none", "simplex", "单面"]:
                    options["duplex_mode"] = "single"
                elif duplex_value_str in ["longedge", "shortedge", "duplexnotumble", "duplextumble", "双面"]:
                    options["duplex_mode"] = "duplex"
            
            from datetime import datetime, timezone
            msg = {
                "type": "submit_print_params",
                "node_id": cloud_service.node_id,
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "data": {
                    "file_id": file_id,
                    "printer_id": printer_id,
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
        
        # 通过文件管理器清理
        if file_id:
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.release_preview_resource(file_id, reason="cancel")
        
        return {"success": True, "message": "文件已清理"}
        
    except Exception as e:
        logger.error(f"清理文件失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@admin_router.post("/node/reregister")
async def reregister_node():
    global cloud_service, node_id
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    if not cloud_service:
        return {"success": False, "message": "云端服务不可用"}
    try:
        cloud_cfg = printer_manager.config.config.get("cloud", {})
        cloud_cfg.pop("node_id", None)
        printer_manager.config.save_config()

        result = cloud_service.reconfigure(cloud_cfg, preserve_node_id=False)
        if result.get("success"):
            result = cloud_service.ensure_registered(force_reregister=True)
        if not result.get("success"):
            return {"success": False, "message": result.get("message") or "节点重新注册失败"}

        node_id = result.get("node_id")
        await broadcast_sse_event("node_status_changed", {
            "status": "registered",
            "node_id": node_id,
        })
        return {"success": True, "message": "节点已重新注册", "node_id": node_id}
    except Exception as e:
        logger.error(f"node reregister failed: {e}")
        return {"success": False, "message": str(e)}


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


@admin_router.post("/cloud/check-register")
@admin_router.post("/config/test-cloud")
async def check_cloud_and_register_node(request: Request):
    global node_id
    body = await request.json()
    try:
        service = _get_config_service()
        if not printer_manager or not cloud_service:
            return JSONResponse(status_code=503, content={"success": False, "message": "\u670d\u52a1\u4e0d\u53ef\u7528"})

        current = printer_manager.config.get_full_config()
        merged = service.merge_update(current, body)
        errors = service.validate(merged)
        if errors:
            return JSONResponse(status_code=400, content={"success": False, "message": "; ".join(errors), "errors": errors})

        preflight = service.test_cloud_connection({"cloud": merged.get("cloud", {})})
        if not preflight.get("success"):
            return JSONResponse(status_code=400, content=preflight)

        had_local_node_id = bool((current.get("cloud") or {}).get("node_id") or cloud_service.node_id)
        stale_node = bool(getattr(cloud_service, "has_stale_node_registration", lambda: False)())
        should_register = not had_local_node_id or stale_node

        if should_register:
            merged.setdefault("cloud", {}).pop("node_id", None)

        printer_manager.config.replace_full_config(merged)
        reconfigure_result = cloud_service.reconfigure(
            merged.get("cloud", {}),
            preserve_node_id=not should_register,
        )
        if not reconfigure_result.get("success"):
            return JSONResponse(status_code=400, content=reconfigure_result)

        if should_register:
            ensure_result = cloud_service.ensure_registered(force_reregister=False)
            if not ensure_result.get("success"):
                return JSONResponse(status_code=400, content=ensure_result)
            result_payload = ensure_result
        else:
            result_payload = {
                "success": True,
                "node_id": cloud_service.node_id,
                "registered": bool(cloud_service.node_id),
                "connected": bool(reconfigure_result.get("connected")),
            }

        connected = await _wait_for_cloud_connected()
        if not connected and getattr(cloud_service, "has_stale_node_registration", lambda: False)():
            repaired = printer_manager.config.get_full_config()
            repaired.setdefault("cloud", {}).pop("node_id", None)
            printer_manager.config.replace_full_config(repaired)

            reconfigure_result = cloud_service.reconfigure(repaired.get("cloud", {}), preserve_node_id=False)
            if not reconfigure_result.get("success"):
                return JSONResponse(status_code=400, content=reconfigure_result)

            ensure_result = cloud_service.ensure_registered(force_reregister=False)
            if not ensure_result.get("success"):
                return JSONResponse(status_code=400, content=ensure_result)
            result_payload = ensure_result
            should_register = True
            connected = await _wait_for_cloud_connected()

        if not connected:
            return JSONResponse(
                status_code=409,
                content={
                    "success": False,
                    "message": "\u8282\u70b9\u5df2\u6ce8\u518c\uff0c\u4f46\u4e91\u7aef\u8fde\u63a5\u5c1a\u672a\u5efa\u7acb",
                    "node_id": cloud_service.node_id,
                    "registered": True,
                    "connected": False,
                },
            )

        node_id = cloud_service.node_id
        if should_register and node_id:
            await broadcast_sse_event("node_status_changed", {
                "status": "registered",
                "node_id": node_id,
            })

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "\u4e91\u7aef\u8fde\u63a5\u6b63\u5e38\uff0c\u8282\u70b9\u5df2\u8fde\u63a5",
                "node_id": node_id,
                "registered": result_payload.get("registered", False),
                "connected": True,
                "saved": True,
            },
        )
    except Exception as e:
        logger.error(f"check/register cloud failed: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


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
            "missing_fields": ["base_url", "auth_url", "client_id", "client_secret"],
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
    managed = _get_managed_printers()
    managed_names = {p.get("name") for p in managed}
    local_printers = printer_manager.discovery.discover_local_printers()
    network_printers = printer_manager.discovery.discover_network_printers()
    all_printers = local_printers + network_printers
    available = []
    for printer in all_printers:
        if printer.get("name") in managed_names:
            continue
        item = dict(printer)
        item.update(printer_manager.get_admin_printer_summary(item.get("name")))
        available.append(item)
    return {"success": True, "items": available}

@admin_router.post("/printers/add")
async def add_managed_printer(request: Request):
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    body = await request.json()
    success, message = printer_manager.add_printer_intelligently(body)
    if not success:
        return {"success": False, "message": message}
    default_id = _ensure_default_printer()
    added_printer = None
    for printer in _get_managed_printers():
        if printer.get("name") == body.get("name"):
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
    if cloud_service:
        cloud_result = cloud_service.delete_printer_from_cloud(printer_id)
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
