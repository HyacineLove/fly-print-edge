
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
from PIL import Image
import fitz
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from printer_utils import PrinterManager
from cloud_service import CloudService

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EdgeServer")

# 全局变量
app = FastAPI(title="FlyPrint Edge Kiosk")
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

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    global printer_manager, cloud_service, node_id, sse_clients, main_loop
    
    logger.info("🚀 Edge Server 正在启动...")
    main_loop = asyncio.get_running_loop()
    
    # 初始化打印机管理器
    printer_manager = PrinterManager()
    
    # 初始化云端服务
    cloud_config = printer_manager.config.config.get("cloud", {})
    if not cloud_config.get("enabled", False):
        logger.warning("⚠️ 云端服务未启用，部分功能不可用")
    
    cloud_service = CloudService(cloud_config, printer_manager)
    
    # 启动云端服务
    start_result = cloud_service.start()
    if start_result.get("success"):
        node_id = start_result.get("node_id")
        logger.info(f"✅ 云端服务启动成功，Node ID: {node_id}")
        
        # 注册WebSocket消息处理器
        if cloud_service.websocket_client:
            # 添加消息处理器，将消息推送到SSE队列
            cloud_service.websocket_client.add_message_handler("preview_file", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("job_status", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("printer_status", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("printer_deleted", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("printer_deleted", handle_printer_deleted)
            cloud_service.websocket_client.add_message_handler("node_state", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("node_state", handle_node_state)
            cloud_service.websocket_client.add_message_handler("printer_state", handle_cloud_message)
            cloud_service.websocket_client.add_message_handler("printer_state", handle_printer_state)
    else:
        logger.error(f"❌ 云端服务启动失败: {start_result.get('message')}")

def handle_cloud_message(data: Dict[str, Any]):
    """处理云端消息并推送到所有SSE客户端"""
    try:
        client_count = len(sse_clients)
        logger.info(f"📨 收到云端消息: {data.get('type')}, 推送给 {client_count} 个客户端")
        
        if client_count == 0:
            logger.warning("⚠️ 当前没有连接的前端客户端，消息可能丢失")
            return

        def push_to_queues():
            for q in sse_clients:
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    pass # 忽略已满的队列

        if main_loop:
            # 使用 call_soon_threadsafe 在主循环中执行推送
            main_loop.call_soon_threadsafe(push_to_queues)
        else:
            logger.warning("⚠️ 主事件循环未捕获，尝试直接推送")
            push_to_queues()
            
    except Exception as e:
        logger.error(f"❌ 推送消息到SSE队列失败: {e}")

def handle_printer_deleted(data: Dict[str, Any]):
    try:
        printer_id = data.get("data", {}).get("printer_id")
        if not printer_id:
            logger.warning("⚠️ 未提供 printer_id，跳过处理")
            return
        result = _remove_managed_printer(printer_id, allow_missing=True)
        if result.get("success"):
            logger.info(f"✅ 已同步删除管理打印机: {printer_id}")
        else:
            logger.warning(f"⚠️ 同步删除打印机失败: {result.get('message')}")
    except Exception as e:
        logger.error(f"❌ 同步删除打印机异常: {e}")

def handle_node_state(data: Dict[str, Any]):
    try:
        enabled = data.get("data", {}).get("enabled")
        if enabled is None:
            logger.warning("⚠️ 未提供 enabled 字段，跳过处理")
            return
        if not printer_manager:
            logger.warning("⚠️ 设备未就绪，无法更新节点状态")
            return
        printer_manager.set_node_enabled(bool(enabled))
        logger.info(f"✅ 节点状态已更新: enabled={bool(enabled)}")
    except Exception as e:
        logger.error(f"❌ 同步节点状态异常: {e}")

def handle_printer_state(data: Dict[str, Any]):
    try:
        payload = data.get("data", {})
        printer_id = payload.get("printer_id")
        enabled = payload.get("enabled")
        if not printer_id or enabled is None:
            logger.warning("⚠️ 缺少 printer_id 或 enabled，跳过处理")
            return
        if not printer_manager:
            logger.warning("⚠️ 设备未就绪，无法更新打印机状态")
            return
        result = printer_manager.set_printer_enabled(printer_id, bool(enabled))
        if result:
            logger.info(f"✅ 打印机状态已更新: {printer_id} enabled={bool(enabled)}")
        else:
            logger.warning(f"⚠️ 未找到打印机，无法更新状态: {printer_id}")
    except Exception as e:
        logger.error(f"❌ 同步打印机状态异常: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Edge Server 正在停止...")
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
        "printer_count": len(printer_manager.get_managed_printers()) if printer_manager else 0,
        "node_enabled": printer_manager.is_node_enabled() if printer_manager else False
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

def _download_preview_file(file_url: str, file_name: Optional[str]):
    try:
        headers = cloud_service.auth_client.get_auth_headers() if cloud_service and cloud_service.auth_client else {}
        full_url = _build_file_url(file_url)
        ext = os.path.splitext(file_name or "")[1].lower() or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        path = tmp.name
        tmp.close()
        resp = requests.get(full_url, headers=headers, stream=True, timeout=60)
        if resp.status_code != 200:
            return None, f"下载文件失败: {resp.status_code}"
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return path, None
    except Exception as e:
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
        temp_dir = tempfile.gettempdir()
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
                    capture_output=True, text=True, timeout=60
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
    if not printer_manager.is_node_enabled():
        return {"success": False, "standby": True, "disabled": True, "disabled_target": "node", "message": "设备已被禁用，暂不提供打印服务"}
    if len(_get_managed_printers()) == 0:
        return {"success": False, "standby": True, "message": "暂无可用打印机"}
    default_printer_id = _ensure_default_printer()
    if not default_printer_id:
        return {"success": False, "standby": True, "message": "暂无可用打印机"}
    if not printer_manager.is_printer_enabled(printer_id=default_printer_id):
        return {"success": False, "standby": True, "disabled": True, "disabled_target": "printer", "default_printer_id": default_printer_id, "message": "默认打印机已被禁用，暂不提供打印服务"}
    
    upload_token = None
    
    # 尝试获取 file:upload 权限的 Token
    if cloud_service and cloud_service.auth_client:
        upload_token = cloud_service.auth_client.get_token_with_scope("file:upload")
    
    # 如果获取失败，尝试使用默认 Token (仅用于开发环境)
    if not upload_token:
        logger.warning("⚠️ 无法获取 file:upload Token，尝试使用默认 Token")
        # 这里可以尝试读取本地缓存或请求其他接口
        # 为了演示，如果失败，我们可能需要提示用户或返回错误
        # 但在开发环境中，我们可能需要一个 fallback
        pass

    if not upload_token:
        return JSONResponse(status_code=500, content={"success": False, "message": "无法获取上传凭证"})

    # 构建上传 URL
    # 假设 Cloud API 地址与 Edge 连接的 Base URL 一致
    base_url = cloud_service.api_client.base_url if cloud_service and cloud_service.api_client else "http://localhost:8080"
    # 移除 /api/v1 等后缀，获取主机地址
    # 这里简单处理，假设 base_url 是 http://host:port/api/v1...
    # 或者直接使用 base_url 的 host
    # 更稳健的方法是解析 URL
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # 获取局域网 IP 并替换 localhost/127.0.0.1
    try:
        lan_ip = get_host_ip()
        if "localhost" in host_url:
            host_url = host_url.replace("localhost", lan_ip)
        elif "127.0.0.1" in host_url:
            host_url = host_url.replace("127.0.0.1", lan_ip)
    except Exception as e:
        logger.warning(f"无法获取局域网 IP: {e}")
    
    # 构造最终 URL
    upload_url = f"{host_url}/upload?token={upload_token}&node_id={node_id}&printer_id={default_printer_id}"
    
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
        "token": upload_token,
        "default_printer_id": default_printer_id,
        "default_printer_capabilities": default_printer_capabilities,
        "node_enabled": printer_manager.is_node_enabled(),
        "default_printer_enabled": printer_manager.is_printer_enabled(printer_id=default_printer_id)
    }

@app.get("/api/events")
async def events(request: Request):
    """SSE 事件流"""
    # 为当前连接创建一个专用队列
    client_queue = asyncio.Queue()
    sse_clients.append(client_queue)
    logger.info(f"🔌 新的SSE连接建立，当前客户端数: {len(sse_clients)}")
    
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
            logger.info(f"🔌 SSE连接断开，剩余客户端数: {len(sse_clients)}")
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/preview")
async def preview(request: Request):
    try:
        body = await request.json()
        file_id = body.get("file_id")
        file_url = body.get("file_url")
        file_name = body.get("file_name")
        file_type = body.get("file_type")
        options = body.get("options") or {}
        if not file_id or not file_url:
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: file_id, file_url 必需"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})

        cached = preview_files.get(file_id)
        if cached and cached.get("file_url") != file_url:
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
            cached_payload = preview_cache[key]
            return {"success": True, "preview_url": cached_payload["preview_url"], "page_count": cached_payload["page_count"], "page_index": cached_payload["page_index"]}

        file_path = preview_files.get(file_id, {}).get("path")
        if not file_path or not os.path.exists(file_path):
            file_path, err = _download_preview_file(file_url, file_name)
            if not file_path:
                return JSONResponse(status_code=500, content={"success": False, "message": err or "下载文件失败"})
            cached_pdf = preview_files.get(file_id, {}).get("pdf_path")
            preview_files[file_id] = {"path": file_path, "file_url": file_url}
            if cached_pdf and os.path.exists(cached_pdf):
                preview_files[file_id]["pdf_path"] = cached_pdf

        image, page_count, resolved_page_index, err = _generate_preview_image(file_id, file_path, file_name, file_type, options, page_index)
        if not image:
            return JSONResponse(status_code=500, content={"success": False, "message": err or "预览生成失败"})

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{encoded}"
        cache_key = f"{file_id}:{json.dumps({**options_for_cache, 'page_index': resolved_page_index}, sort_keys=True, ensure_ascii=False)}"
        preview_cache[cache_key] = {"preview_url": data_url, "page_count": page_count, "page_index": resolved_page_index}
        return {"success": True, "preview_url": data_url, "page_count": page_count, "page_index": resolved_page_index}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.post("/api/print")
async def submit_print(request: Request):
    """提交打印参数"""
    try:
        body = await request.json()
        task_token = body.get("task_token")
        options = body.get("options")
        file_id = body.get("file_id")
        
        if not task_token or not options or not file_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "参数不完整: task_token, options, file_id 均必需"})
        if not isinstance(options, dict):
            return JSONResponse(status_code=400, content={"success": False, "message": "参数错误: options 必须为对象"})
        if not printer_manager:
            return JSONResponse(status_code=503, content={"success": False, "message": "设备未就绪"})
        if not printer_manager.is_node_enabled():
            return JSONResponse(status_code=403, content={"success": False, "message": "节点已禁用"})
        
        if cloud_service and cloud_service.websocket_client:
            printer_id = _ensure_default_printer()
            
            if not printer_id:
                 return JSONResponse(status_code=500, content={"success": False, "message": "未找到可用打印机"})
            if not printer_manager.is_printer_enabled(printer_id=printer_id):
                return JSONResponse(status_code=403, content={"success": False, "message": "默认打印机已禁用"})

            # 发送参数到云端
            # 构造消息
            duplex_value = options.get("duplex")
            if duplex_value:
                duplex_value_str = str(duplex_value).lower()
                if duplex_value_str in ["none", "simplex", "单面"]:
                    options["duplex_mode"] = "single"
                elif duplex_value_str in ["longedge", "shortedge", "duplexnotumble", "duplextumble", "双面"]:
                    options["duplex_mode"] = "duplex"
            msg = {
                "type": "submit_print_params",
                "data": {
                    "task_token": task_token,
                    "file_id": file_id,
                    "printer_id": printer_id,
                    "options": options
                }
            }
            # 使用异步发送方法
            await cloud_service.websocket_client.send_message(msg)
            return {"success": True, "message": "打印任务已提交"}
        else:
            return JSONResponse(status_code=503, content={"success": False, "message": "云端服务未连接"})
            
    except Exception as e:
        logger.error(f"提交打印参数失败: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

@app.get("/api/admin/printers/managed")
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
        "default_printer_id": default_id,
        "node_enabled": printer_manager.is_node_enabled()
    }

@app.get("/api/admin/printers/discovered")
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

@app.post("/api/admin/printers/add")
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
    if cloud_service:
        if added_printer:
            cloud_service.register_managed_printer(added_printer)
    return {"success": True, "message": "打印机添加成功", "default_printer_id": default_id}

@app.post("/api/admin/printers/default")
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
    return {"success": True, "default_printer_id": printer_id}

@app.delete("/api/admin/printers/{printer_id}")
async def delete_managed_printer(printer_id: str):
    result = _remove_managed_printer(printer_id)
    if not result.get("success"):
        return {"success": False, "message": result.get("message")}
    if cloud_service:
        cloud_service.delete_printer_from_cloud(printer_id)
    return {"success": True, "default_printer_id": result.get("default_printer_id")}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=False)
