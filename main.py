
import uvicorn
import json
import asyncio
import os
import socket
import logging
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

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Edge Server 正在停止...")
    if cloud_service:
        cloud_service.stop()

# API 路由
@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/api/status")
async def get_status():
    """获取设备状态"""
    return {
        "status": "online",
        "node_id": node_id,
        "printer_count": len(printer_manager.get_managed_printers()) if printer_manager else 0
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

@app.get("/api/qr_code")
async def get_qr_code():
    """获取上传二维码信息"""
    if not node_id:
        return JSONResponse(status_code=503, content={"success": False, "message": "设备未注册或离线"})
    
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
    upload_url = f"{host_url}/upload?token={upload_token}&node_id={node_id}"
    
    # 使用 qrserver API 生成二维码图片 URL
    qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={upload_url}"
    
    return {
        "success": True,
        "qr_url": qr_img_url, 
        "text_url": upload_url,
        "node_id": node_id,
        "token": upload_token
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
        
        if cloud_service and cloud_service.websocket_client:
            # 获取默认打印机 ID
            printer_id = None
            if printer_manager:
                printers = printer_manager.get_printers()
                if printers:
                    # 默认使用第一台打印机
                    printer_id = printers[0].get("id")
            
            if not printer_id:
                 return JSONResponse(status_code=500, content={"success": False, "message": "未找到可用打印机"})

            # 发送参数到云端
            # 构造消息
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=False)
