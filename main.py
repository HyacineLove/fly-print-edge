
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
from file_manager import init_file_manager, get_file_manager
from portable_temp import get_portable_temp_dir, get_temp_file_path, cleanup_temp_dir

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EdgeServer")

# 全局变量
app = FastAPI(title="FlyPrint Edge Kiosk")

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
preview_files: Dict[str, Dict[str, str]] = {}
preview_page_cache: Dict[str, Dict[int, Image.Image]] = {}
preview_page_meta: Dict[str, Dict[str, int]] = {}
file_access_tokens: Dict[str, Dict[str, str]] = {}  # 文件访问 token 缓存

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
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    global printer_manager, cloud_service, node_id, sse_clients, main_loop
    
    logger.info(" Edge Server 正在启动...")
    main_loop = asyncio.get_running_loop()
    
    # 初始化打印机管理器
    printer_manager = PrinterManager()
    
    # 初始化文件管理器（传入 preview_cache 引用用于自动清理）
    file_mgr = init_file_manager(cleanup_interval=300, file_ttl=1800, preview_cache=preview_cache)
    # 清理 portable temp 目录中的遗留文件
    cleanup_temp_dir(max_age_hours=24)
    file_mgr.start()
    logger.info(" 文件管理器已启动（包含预览图缓存清理）")
    
    # 初始化云端服务
    cloud_config = printer_manager.config.config.get("cloud", {})
    
    # 特殊处理：如果配置了 auto_register 但 enabled=False，我们在 CloudService 内部会自动启用
    # 这里不需要提前警告，CloudService 会处理并返回正确状态
    
    cloud_service = CloudService(cloud_config, printer_manager)
    
    # 启动云端服务
    start_result = cloud_service.start()
    if start_result.get("success"):
        node_id = start_result.get("node_id")
        logger.info(f" 云端服务启动成功，Node ID: {node_id}")
        
        # 注册WebSocket消息的SSE转发处理器（将云端消息推送给前端）
        # 云端实际发送的下行消息：print_job, preview_file, upload_token, error
        # - print_job/upload_token/error 由 cloud_service.py 中的 PrintJobHandler 处理业务逻辑，不需要转发给前端
        # - preview_file/error 需要同时转发给前端（用户界面需要显示）
        if cloud_service.websocket_client:
            # preview_file: 将文件预览消息推送到SSE，前端显示预览界面
            cloud_service.websocket_client.add_message_handler("preview_file", handle_cloud_message)
            
            # error: 将云端错误消息推送到SSE，前端显示错误提示
            cloud_service.websocket_client.add_message_handler("error", handle_cloud_message)
            # cloud_error: 由本地封装的云端错误（如节点被删除等），同样转发到前端
            cloud_service.websocket_client.add_message_handler("cloud_error", handle_cloud_message)
            # job_status: 将打印任务状态更新推送到SSE，前端显示打印进度
            cloud_service.websocket_client.add_message_handler("job_status", handle_cloud_message)
    else:
        logger.error(f" 云端服务启动失败: {start_result.get('message')}")

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
        logger.info(f" 广播SSE事件: {event_type} -> {client_count} 客户端")
        
        for q in sse_clients:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass
    except Exception as e:
        logger.error(f" 广播SSE事件失败: {e}")

def handle_cloud_message(data: Dict[str, Any]):
    """处理云端消息并推送到所有SSE客户端"""
    try:
        # 直接使用广播函数，保持原有数据结构（如果是云端消息，直接转发）
        # 云端消息格式通常为 {"type": "...", "data": ...}
        # 如果data本身已经包含type，则直接发送整个对象
        
        client_count = len(sse_clients)
        logger.info(f" 收到云端消息: {data.get('type')}, 推送给 {client_count} 个客户端")
        
        if client_count == 0:
            return

        def push_to_queues():
            for q in sse_clients:
                try:
                    q.put_nowait(data)
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
    return FileResponse("static/index.html")

@app.get("/admin")
async def read_admin():
    return FileResponse("static/admin.html")

@app.get("/api/status")
async def get_status():
    """获取设备状态"""
    return {
        "status": "online",
        "node_id": node_id,
        "printer_count": len(printer_manager.config.get_managed_printers()) if printer_manager else 0
    }

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

def _get_settings():
    if not printer_manager:
        return {}
    return printer_manager.config.config.get("settings", {})

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
        if file_url.startswith("/api/v1") and base_url.endswith("/api/v1"):
            base_url = base_url[:-len("/api/v1")]
        return f"{base_url}{file_url}"
    return f"{base_url}/{file_url}"

def _download_preview_file(file_url: str, file_name: Optional[str], file_id: Optional[str] = None):
    print(f" [DEBUG] ===== 开始下载预览文件 =====")
    print(f" [DEBUG] file_url={file_url}")
    print(f" [DEBUG] file_name={file_name}")
    print(f" [DEBUG] file_id={file_id}")
    try:
        print(f" [DEBUG] 获取认证头...")
        headers = cloud_service.auth_client.get_auth_headers() if cloud_service and cloud_service.auth_client else {}
        
        # 尝试使用文件访问 token（优先级更高）
        global file_access_tokens
        download_url = None
        if file_id and file_id in file_access_tokens:
            token_info = file_access_tokens[file_id]
            file_access_token = token_info.get('token')
            if file_access_token:
                # 使用文件访问 token 作为 URL query 参数（云端要求）
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                full_url = _build_file_url(file_url)
                parsed = urlparse(full_url)
                query_params = parse_qs(parsed.query)
                query_params['token'] = [file_access_token]
                new_query = urlencode(query_params, doseq=True)
                download_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path,
                    parsed.params, new_query, parsed.fragment
                ))
                print(f" [INFO] 使用文件访问 token: {file_access_token[:20]}...")
                print(f" [INFO] 带token的URL: {download_url[:100]}...")
                # 使用后删除 token（一次性）
                del file_access_tokens[file_id]
                print(f" [DEBUG] 已从全局字典删除 token")
                # 不需要 Bearer token
                headers.pop('Authorization', None)
            else:
                print(f" [WARNING] file_access_token 为空，使用默认 Bearer token")
        else:
            print(f" [WARNING] 未找到 file_id={file_id} 的访问 token，全局字典内容: {list(file_access_tokens.keys())}")
        
        # 如果没有文件访问 token，使用默认URL
        if not download_url:
            download_url = _build_file_url(file_url)
        
        print(f" [DEBUG] 最终使用的 headers={headers}")
        print(f" [DEBUG] 最终下载URL: {download_url}")
        
        print(f" [DEBUG] 解析文件扩展名...")
        ext = os.path.splitext(file_name or "")[1].lower() or ".bin"
        print(f" [DEBUG] ext={ext}")
        
        print(f" [DEBUG] 生成临时文件路径...")
        path = get_temp_file_path(prefix="preview", suffix=ext)
        print(f" [DEBUG] 临时路径={path}")
        
        print(f" [DEBUG] 发起HTTP请求...")
        resp = requests.get(download_url, headers=headers, stream=True, timeout=60)
        print(f" [DEBUG] HTTP响应: status_code={resp.status_code}")
        
        if resp.status_code != 200:
            print(f" [DEBUG] 下载失败")
            return None, f"下载文件失败: {resp.status_code}"
        
        print(f" [DEBUG] 写入文件...")
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f" [DEBUG] 文件下载成功: {path}")
        return path, None
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f" [ERROR] 下载文件异常: {e}")
        print(f" [DEBUG] 错误详情:\n{error_detail}")
        return None, str(e)

def _get_paper_size_px(paper_size: Optional[str], dpi: int = 120):
    sizes = {
        "A3": (297, 420),
        "A4": (210, 297),
        "A5": (148, 210),
        "B5": (176, 250),
        "Letter": (216, 279),
        "Legal": (216, 356)
    }
    mm = sizes.get(paper_size or "")
    if not mm:
        return None
    w = int(mm[0] / 25.4 * dpi)
    h = int(mm[1] / 25.4 * dpi)
    return w, h

def _apply_paper_size(image: Image.Image, paper_size: Optional[str]):
    target = _get_paper_size_px(paper_size)
    if not target:
        return image
    w, h = target
    canvas = Image.new("RGB", (w, h), "white")
    img = image.convert("RGB")
    img.thumbnail((w, h))
    x = max((w - img.width) // 2, 0)
    y = max((h - img.height) // 2, 0)
    canvas.paste(img, (x, y))
    return canvas

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
    if ext in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"]:
        try:
            img = Image.open(file_path)
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
    elif ext in [".doc", ".docx"]:
        pdf_path = None
        if file_id:
            cached = preview_files.get(file_id, {})
            pdf_path = cached.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            pdf_path, error = _convert_word_to_pdf(file_path)
            if pdf_path and file_id:
                preview_files.setdefault(file_id, {})["pdf_path"] = pdf_path
                # 同步更新 FileManager 中的 PDF 路径
                file_mgr = get_file_manager()
                if file_mgr:
                    file_info = file_mgr.get_file_info(file_id)
                    if file_info:
                        file_mgr.register_preview_file(file_id, file_info["path"], pdf_path)
        if pdf_path:
            image, page_count, resolved_page_index, error = _get_cached_pdf_page(file_id, pdf_path, page_index)
    else:
        error = "暂不支持该文件类型预览"
    if image is None:
        return None, 0, 0, error or "预览生成失败"
    color_mode = (options.get("color_mode") or options.get("color") or "").lower()
    if "gray" in color_mode or "mono" in color_mode or "黑白" in color_mode:
        image = image.convert("L").convert("RGB")
    paper_size = options.get("paper_size") or options.get("size")
    image = _apply_paper_size(image, paper_size)
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
    from urllib.parse import urlparse
    base_url = cloud_service.api_client.base_url if cloud_service and cloud_service.api_client else "http://localhost:8080"
    parsed = urlparse(base_url)
    cloud_host = f"{parsed.scheme}://{parsed.netloc}"
    
    # 获取局域网 IP 并替换 localhost/127.0.0.1
    try:
        lan_ip = get_host_ip()
        if "localhost" in cloud_host:
            cloud_host = cloud_host.replace("localhost", lan_ip)
        elif "127.0.0.1" in cloud_host:
            cloud_host = cloud_host.replace("127.0.0.1", lan_ip)
    except Exception as e:
        logger.warning(f"无法获取局域网 IP: {e}")
    
    # 使用云端返回的 upload_url（相对路径），拼接完整 URL
    upload_url = f"{cloud_host}{token_data['upload_url']}"
    
    qr_img_url = build_qr_data_url(upload_url)

    default_printer = _get_printer_by_id(default_printer_id)
    default_printer_capabilities = None
    if default_printer and default_printer.get("name"):
        default_printer_capabilities = printer_manager.get_printer_capabilities(default_printer.get("name"))
    
    return {
        "success": True,
        "qr_url": qr_img_url, 
        "text_url": upload_url,
        "node_id": node_id,
        "token": token_data['token'],
        "expires_at": token_data['expires_at'],
        "default_printer_id": default_printer_id,
        "default_printer_capabilities": default_printer_capabilities
    }

@app.get("/api/events")
async def events(request: Request):
    """SSE 事件流"""
    # 为当前连接创建一个专用队列
    client_queue = asyncio.Queue()
    sse_clients.append(client_queue)
    logger.info(f" 新的SSE连接建立，当前客户端数: {len(sse_clients)}")
    
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
            logger.info(f" SSE连接断开，剩余客户端数: {len(sse_clients)}")
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/preview")
async def preview(request: Request):
    print(f"\n [DEBUG] ===== 预览请求开始 =====")
    try:
        # 读取并打印原始请求体
        body_bytes = await request.body()
        print(f" [DEBUG] 原始请求体: {body_bytes[:500]}...")  # 只打印前500字节
        
        # 解析JSON
        body = json.loads(body_bytes)
        print(f" [DEBUG] 解析后的body: {json.dumps(body, ensure_ascii=False, indent=2)}")
        
        file_id = body.get("file_id")
        file_url = body.get("file_url")
        file_name = body.get("file_name")
        file_type = body.get("file_type")
        options = body.get("options") or {}
        
        print(f" [DEBUG] 参数提取: file_id={file_id}, file_url={file_url}, file_name={file_name}")
        
        if not file_id or not file_url:
            print(f" [DEBUG] 参数验证失败")
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: file_id, file_url 必需"})
        if not printer_manager:
            print(f" [DEBUG] 打印机管理器未就绪")
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})

        print(f" [DEBUG] 检查缓存...")
        cached = preview_files.get(file_id)
        print(f" [DEBUG] 缓存查询结果: {cached}")
        
        if cached and cached.get("file_url") != file_url:
            print(f" [DEBUG] URL变化，清理旧文件...")
            # URL变化，清理旧文件
            old_path = cached.get("path")
            if old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
            old_pdf = cached.get("pdf_path")
            if old_pdf and os.path.exists(old_pdf):
                try:
                    os.remove(old_pdf)
                except Exception:
                    pass
            preview_files.pop(file_id, None)
            keys = [k for k in preview_cache.keys() if k.startswith(f"{file_id}:")]
            for k in keys:
                preview_cache.pop(k, None)
            preview_page_cache.pop(file_id, None)
            preview_page_meta.pop(file_id, None)
            
            # 从文件管理器移除
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.cleanup_file(file_id, source="url_changed")

        print(f" [DEBUG] 解析page_index...")
        try:
            page_index = int(options.get("page_index") or 0)
        except Exception:
            page_index = 0
        print(f" [DEBUG] page_index={page_index}")
        
        if page_index < 0:
            page_index = 0
        print(f" [DEBUG] 构建cache key...")
        options_for_cache = dict(options)
        options_for_cache["page_index"] = page_index
        key = f"{file_id}:{json.dumps(options_for_cache, sort_keys=True, ensure_ascii=False)}"
        print(f" [DEBUG] cache key={key[:100]}...")
        
        if key in preview_cache:
            print(f" [DEBUG] 命中缓存，直接返回")
            cached_payload = preview_cache[key]
            # 返回时排除 timestamp 字段
            return {
                "success": True, 
                "preview_url": cached_payload["preview_url"], 
                "page_count": cached_payload["page_count"], 
                "page_index": cached_payload["page_index"]
            }

        print(f" [DEBUG] 检查文件路径...")
        file_path = preview_files.get(file_id, {}).get("path")
        print(f" [DEBUG] file_path={file_path}")
        if not file_path or not os.path.exists(file_path):
            print(f" [DEBUG] 文件不存在，开始下载...")
            file_path, err = _download_preview_file(file_url, file_name, file_id)
            if not file_path:
                print(f" [DEBUG] 下载失败: {err}")
                return JSONResponse(status_code=500, content={"success": False, "message": err or "下载文件失败"})
            cached_pdf = preview_files.get(file_id, {}).get("pdf_path")
            preview_files[file_id] = {"path": file_path, "file_url": file_url}
            if cached_pdf and os.path.exists(cached_pdf):
                preview_files[file_id]["pdf_path"] = cached_pdf
            
            # 注册到文件管理器
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.register_preview_file(file_id, file_path, cached_pdf)
        else:
            # 更新访问时间
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.update_file_access(file_id)

        image, page_count, resolved_page_index, err = _generate_preview_image(file_id, file_path, file_name, file_type, options, page_index)
        if not image:
            return JSONResponse(status_code=500, content={"success": False, "message": err or "预览生成失败"})

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{encoded}"
        cache_key = f"{file_id}:{json.dumps({**options_for_cache, 'page_index': resolved_page_index}, sort_keys=True, ensure_ascii=False)}"
        # 存储预览图时添加时间戳用于自动清理
        preview_cache[cache_key] = {
            "preview_url": data_url, 
            "page_count": page_count, 
            "page_index": resolved_page_index,
            "timestamp": time.time()
        }
        return {"success": True, "preview_url": data_url, "page_count": page_count, "page_index": resolved_page_index}
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f" [ERROR] 预览接口异常: {e}")
        print(f" [DEBUG] 错误详情:\n{error_detail}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/print")
async def submit_print(request: Request):
    """提交打印参数"""
    try:
        body = await request.json()
        task_token = body.get("task_token")
        options = body.get("options")
        file_id = body.get("file_id")
        
        if not options or not file_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: options, file_id 均必需"})
        if not isinstance(options, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "参数错误: options 必须为对象"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})
        
        if cloud_service and cloud_service.websocket_client:
            printer_id = _ensure_default_printer()
            
            if not printer_id:
                 return JSONResponse(status_code=500, content={"success": False, "message": "未找到可用打印机"})

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
            await cloud_service.websocket_client.send_message(msg)
            
            # 清理预览文件（打印时会重新下载，预览文件不再需要）
            file_mgr = get_file_manager()
            if file_mgr:
                file_mgr.cleanup_file(file_id, source="print")
            
            # 清理内存缓存
            preview_files.pop(file_id, None)
            keys = [k for k in preview_cache.keys() if k.startswith(f"{file_id}:")]
            for k in keys:
                preview_cache.pop(k, None)
            preview_page_cache.pop(file_id, None)
            preview_page_meta.pop(file_id, None)
            
            return {"success": True, "message": "打印任务已提交"}
        else:
            return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})
            
    except Exception as e:
        logger.error(f"提交打印参数失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/cleanup")
async def cleanup_preview_file(request: Request):
    """清理预览文件（用户取消时调用）"""
    try:
        body = await request.json()
        file_id = body.get("file_id")
        
        if not file_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "file_id 不能为空"})
        
        # 通过文件管理器清理
        file_mgr = get_file_manager()
        if file_mgr:
            file_mgr.cleanup_file(file_id, source="cancel")
        
        # 清理内存缓存
        preview_files.pop(file_id, None)
        keys = [k for k in preview_cache.keys() if k.startswith(f"{file_id}:")]
        for k in keys:
            preview_cache.pop(k, None)
        preview_page_cache.pop(file_id, None)
        preview_page_meta.pop(file_id, None)
        
        return {"success": True, "message": "文件已清理"}
        
    except Exception as e:
        logger.error(f"清理文件失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@admin_router.post("/node/reregister")
async def reregister_node():
    """重新注册云端节点（在节点被删除或配置异常时使用）"""
    global cloud_service, node_id
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    if not cloud_service:
        return {"success": False, "message": "云端服务未启用"}
    try:
        # 停止当前云端服务
        cloud_service.stop()

        # 清除本地缓存的 node_id
        try:
            if hasattr(printer_manager, "config"):
                cloud_cfg = printer_manager.config.config.get("cloud", {})
                cloud_cfg.pop("node_id", None)
                printer_manager.config.save_config()
        except Exception as e:
            logger.warning(f"清除本地 node_id 缓存失败: {e}")

        # 重置 CloudService 状态
        cloud_service.node_id = None
        cloud_service.registered = False

        # 重新启动云端服务（会触发自动注册）
        start_result = cloud_service.start()
        if not start_result.get("success"):
            return {"success": False, "message": start_result.get("message") or "节点重新注册失败"}

        node_id = start_result.get("node_id")

        # 重新注册 SSE 消息转发处理器
        if cloud_service.websocket_client:
            cloud_service.websocket_client.add_message_handler("preview_file", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("error", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("cloud_error", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("job_status", handle_cloud_message)

        # 广播节点重新注册事件
        await broadcast_sse_event("node_status_changed", {
            "status": "registered",
            "node_id": node_id
        })

        return {"success": True, "message": "节点重新注册成功", "node_id": node_id}
    except Exception as e:
        logger.error(f"重新注册节点失败: {e}")
        return {"success": False, "message": str(e)}

@admin_router.get("/cloud/status")
async def get_cloud_status():
    """获取云端服务连接/注册状态"""
    if not cloud_service:
        return {
            "success": True,
            "enabled": False,
            "registered": False,
            "connected": False,
            "node_id": None,
            "message": "云端服务未启用"
        }
    try:
        status = cloud_service.get_status()
        ws = status.get("websocket") or {}
        connected = bool(ws.get("connected"))  # 使用 connected 而不是 running
        return {
            "success": True,
            "enabled": status.get("enabled", False),
            "registered": status.get("registered", False),
            "connected": connected,
            "node_id": status.get("node_id"),
            "message": "正常" if connected and status.get("registered") else "未连接"
        }
    except Exception as e:
        logger.error(f"获取云端状态失败: {e}")
        return {"success": False, "message": str(e)}

@admin_router.get("/printers/managed")
async def get_managed_printers():
    if not printer_manager:
        return {"success": False, "message": "设备未就绪"}
    default_id = _ensure_default_printer()
    printers = _get_managed_printers()
    for printer in printers:
        printer["is_default"] = printer.get("id") == default_id
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
    available = [p for p in all_printers if p.get("name") not in managed_names]
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

if __name__ == "__main__":
    from printer_config import PrinterConfig
    config = PrinterConfig().config
    network_cfg = config.get("network", {})
    bind_address = network_cfg.get("bind_address", "127.0.0.1")
    port = network_cfg.get("port", 7860)
    
    logger.info(f" 启动服务: {bind_address}:{port}")
    uvicorn.run("main:app", host=bind_address, port=port, reload=False)
