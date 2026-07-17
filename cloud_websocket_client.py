"""
fly-print-cloud WebSocket客户端
接收云端打印任务和实时消息
"""

import asyncio
import hashlib
import websockets
import json
import threading
import time
import logging
import requests
import os
import base64
import shutil
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
from cloud_auth import CloudAuthClient
from file_manager import get_file_manager, is_valid_content_hash
from print_options import normalize_print_options

logger = logging.getLogger(__name__)


class CloudWebSocketClient:
    """云端WebSocket客户端"""
    
    def __init__(self, websocket_url: str, auth_client: CloudAuthClient, node_missing_handler: Optional[Callable[[str], None]] = None):
        self.websocket_url = websocket_url
        self.auth_client = auth_client
        self.node_missing_handler = node_missing_handler
        self.websocket = None
        self.running = False
        self.connected = False  # 实际连接状态（握手成功才为True）
        self.thread = None
        self.loop = None  # 存储WebSocket线程的事件循环
        self.message_handlers = {}  # type: Dict[str, List[Callable]]
        self.last_http_status = None
        self.last_error_message = None
        self.node_missing = False
        self.reconnect_interval = 5  # 重连间隔秒数
        
        # 任务去重缓存：记录已完成的任务ID及完成时间戳
        self.completed_jobs = {}  # {job_id: completion_timestamp}
        self.processing_jobs = {}  # {job_id: start_timestamp}
        self.completed_jobs_ttl = 3600  # 缓存保留1小时
        self.processing_jobs_ttl = 3600
        self._job_tracking_lock = threading.Lock()
        self._job_cleanup_stop = threading.Event()
        self._job_cleanup_thread = None
        self._start_cleanup_task()  # 启动定期清理任务
        
    def add_message_handler(self, message_type: str, handler: Callable[[Dict[str, Any]], None]):
        """添加消息处理器"""
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []
        
        # 避免重复添加相同的handler
        if handler not in self.message_handlers[message_type]:
            self.message_handlers[message_type].append(handler)
    
    def dispatch_local_message(self, message_type: str, data: Dict[str, Any]):
        """分发本地产生的消息到处理器"""
        if message_type in self.message_handlers:
            handlers = self.message_handlers[message_type]
            # logger.debug(f"本地分发 {len(handlers)} 个处理器处理 {message_type}")
            # 在主线程或当前线程直接执行，因为通常是UI更新
            for handler in handlers:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"处理本地消息异常: {e}")
    
    def start(self):
        """启动WebSocket客户端"""
        if self.running:
            logger.warning("WebSocket客户端已经在运行")
            return

        self._start_cleanup_task()
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        logger.info("WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        self.connected = False

        if self.loop and self.loop.is_running() and self.websocket:
            try:
                future = asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
                future.result(timeout=3)
            except Exception as e:
                logger.debug(f"停止WebSocket时关闭连接失败: {e}")

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

        self._job_cleanup_stop.set()
        if self._job_cleanup_thread and self._job_cleanup_thread.is_alive():
            self._job_cleanup_thread.join(timeout=3)

        self.websocket = None
        logger.info("WebSocket客户端已停止")
    
    def _extract_http_status(self, exc: Exception) -> Optional[int]:
        status = getattr(exc, "status_code", None)
        if status is not None:
            return int(status)
        response = getattr(exc, "response", None)
        if response is not None:
            response_status = getattr(response, "status_code", None)
            if response_status is not None:
                return int(response_status)
        return None

    def _notify_node_missing(self, detail: str):
        if self.node_missing:
            return
        self.node_missing = True
        if self.node_missing_handler:
            try:
                self.node_missing_handler(detail)
            except Exception as e:
                logger.error(f"鑺傜偣澶辫仈鍥炶皟寮傚父: {e}")

    def _start_cleanup_task(self):
        """启动定期清理过期任务记录的后台线程"""
        if self._job_cleanup_thread and self._job_cleanup_thread.is_alive():
            return
        self._job_cleanup_stop.clear()

        def cleanup_loop():
            while not self._job_cleanup_stop.wait(300):
                try:
                    self._cleanup_completed_jobs()
                except Exception as e:
                    logger.error(f"清理已完成任务缓存异常: {e}")

        self._job_cleanup_thread = threading.Thread(
            target=cleanup_loop,
            name="cloud-job-cleanup",
            daemon=True,
        )
        self._job_cleanup_thread.start()
    
    def _cleanup_completed_jobs(self):
        """在现有任务锁内清理过期的完成与处理中记录。"""
        now = time.time()
        with self._job_tracking_lock:
            expired_completed = [
                job_id for job_id, timestamp in self.completed_jobs.items()
                if now - timestamp > self.completed_jobs_ttl
            ]
            expired_processing = [
                job_id for job_id, timestamp in self.processing_jobs.items()
                if now - timestamp > self.processing_jobs_ttl
            ]
            for job_id in expired_completed:
                self.completed_jobs.pop(job_id, None)
            for job_id in expired_processing:
                self.processing_jobs.pop(job_id, None)

        if expired_completed or expired_processing:
            logger.info(
                "清理过期任务记录: completed=%s processing=%s",
                len(expired_completed),
                len(expired_processing),
            )
    
    def _mark_job_completed(self, job_id: str):
        """标记任务为已完成"""
        with self._job_tracking_lock:
            self.processing_jobs.pop(job_id, None)
            self.completed_jobs[job_id] = time.time()
        logger.debug(f"任务已标记为完成: {job_id} (缓存中共 {len(self.completed_jobs)} 个)")
    
    def _is_job_completed(self, job_id: str) -> bool:
        """检查任务是否已完成"""
        with self._job_tracking_lock:
            return job_id in self.completed_jobs
    
    def _begin_job_processing(self, job_id: str) -> str:
        """Return started, processing, or completed for cloud job idempotency."""
        if not job_id:
            return "started"
        with self._job_tracking_lock:
            if job_id in self.completed_jobs:
                return "completed"
            if job_id in self.processing_jobs:
                return "processing"
            self.processing_jobs[job_id] = time.time()
            return "started"

    def _finish_job_processing(self, job_id: str):
        """Release an in-flight job marker without marking it completed."""
        if not job_id:
            return
        with self._job_tracking_lock:
            self.processing_jobs.pop(job_id, None)

    def _run_async_loop(self):
        """在单独线程中运行异步循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop  # 保存loop引用
        try:
            loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            logger.error(f"WebSocket异步循环异常: {e}")
        finally:
            loop.close()
            self.loop = None

    async def _connect_and_listen(self):
        """连接WebSocket并监听消息"""
        while self.running:
            try:
                logger.info(f"连接WebSocket: {self.websocket_url}")
                
                # 获取认证头
                token = self.auth_client.get_access_token()
                if not token:
                    logger.error("无法获取access token，等待重试")
                    self.connected = False
                    await asyncio.sleep(self.reconnect_interval)
                    continue
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Connection": "Upgrade",
                    "Upgrade": "websocket"
                }
                
                async with websockets.connect(
                    self.websocket_url, 
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10
                ) as websocket:
                    self.websocket = websocket
                    self.connected = True  # 握手成功
                    self.last_http_status = None
                    self.last_error_message = None
                    self.node_missing = False
                    logger.info("WebSocket连接成功")
                    
                    # 监听消息
                    async for message in websocket:
                        try:
                            await self._handle_message(message)
                        except Exception as e:
                            logger.error(f"处理WebSocket消息异常: {e}")
                    self.websocket = None
                    self.connected = False
                            
            except websockets.exceptions.ConnectionClosed as e:
                self.connected = False
                self.websocket = None
                self.last_error_message = str(e)
                logger.warning(f"WebSocket连接关闭: {e}")
            except Exception as e:
                self.connected = False
                self.websocket = None
                self.last_http_status = self._extract_http_status(e)
                self.last_error_message = str(e)
                if self.last_http_status == 404:
                    self._notify_node_missing("websocket handshake returned 404")
                logger.error(f"WebSocket连接异常: {e}")
            
            if self.running:
                logger.info(f"{self.reconnect_interval}秒后重连WebSocket")
                await asyncio.sleep(self.reconnect_interval)
    
    async def _handle_message(self, message: str):
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            message_type = data.get("type", "unknown")
            
            # 自动回复 ACK (如果消息包含 msg_id)
            if "msg_id" in data:
                from datetime import datetime, timezone
                ack_payload = {
                    "type": "ack",
                    "msg_id": data["msg_id"],
                    "command_id": data.get("command_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "accepted",
                    "message": "Received"
                }
                # 不阻塞后续处理，直接发送
                await self._send_message(ack_payload)
                # logger.debug(f"已自动回复 ACK: {data['msg_id']}")

            if message_type == "preview_file":
                logger.debug("收到预览文件消息")
            
            # 处理服务端关闭通知（server_close）
            if message_type == "server_close":
                close_data = data.get("data") or {}
                reason = close_data.get("reason") or "unknown"
                msg = close_data.get("message") or ""
                logger.info(f"收到服务端关闭通知: reason={reason}, message={msg}")
                
                # 节点被删除时，按照协议要求：不要自动重连，等待手动重新注册
                if reason == "node_deleted":
                    logger.info("节点已被删除，将停止WebSocket重连，等待手动重新注册")
                    # 通过本地消息分发，将事件通知到前端（SSE）
                    local_msg = {
                        "type": "cloud_error",
                        "data": {
                            "code": "node_deleted",
                            "message": msg or "节点已被管理员删除，请在管理端重新注册节点"
                        }
                    }
                    # 使用本地分发机制触发相关处理器（例如 SSE 转发）
                    self.dispatch_local_message("cloud_error", local_msg)
                    self.running = False
                return
            
            # 调用对应的消息处理器
            if message_type in self.message_handlers:
                handlers = self.message_handlers[message_type]
                loop = asyncio.get_event_loop()
                for handler in handlers:
                    # 在线程池中执行处理器，避免阻塞WebSocket
                    await loop.run_in_executor(None, handler, data)
            else:
                logger.warning(f"未找到消息类型处理器: {message_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"WebSocket消息JSON解析失败: {e}")
        except Exception as e:
            logger.error(f"处理WebSocket消息异常: {e}")
    
    async def _send_message(self, data: Dict[str, Any]) -> bool:
        """发送消息到WebSocket"""
        if not self.websocket:
            return False
        try:
            message = json.dumps(data)
            await self.websocket.send(message)
            return True
        except Exception as e:
            logger.error(f"发送WebSocket消息失败: {e}")
            return False

    async def send_message(self, data: Dict[str, Any]) -> bool:
        """异步发送消息 (可从任何循环调用)"""
        if not self.loop or not self.loop.is_running():
            logger.warning("WebSocket事件循环未运行，无法发送消息")
            return False
            
        try:
            # 检查是否在同一个循环中
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
                
            if current_loop == self.loop:
                # 同一个循环，直接调用
                return await self._send_message(data)
            else:
                # 不同循环，使用 run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
                # 等待结果（这里需要包装成 awaitable）
                return await asyncio.wrap_future(future)
        except Exception as e:
            logger.error(f"异步发送消息异常: {e}")
            return False

    def send_message_sync(self, data: Dict[str, Any]) -> bool:
        """同步发送消息（在其他线程中调用）"""
        if not self.loop or not self.loop.is_running():
            logger.warning("WebSocket事件循环未运行，无法发送消息")
            return False
            
        try:
            # 使用 run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
            
            # 等待结果，确保消息发送成功
            try:
                return bool(future.result(timeout=5))
            except asyncio.TimeoutError:
                logger.error(f"同步发送WebSocket消息超时: {data.get('type')}")
                return False
            except Exception as e:
                logger.error(f"同步发送WebSocket消息执行失败: {e}")
                return False
                
        except Exception as e:
            logger.error(f"同步发送WebSocket消息失败: {e}")
            return False

    def submit_print_params(self, node_id: str, file_id: str, printer_id: str, options: Dict[str, Any]):
        """提交打印参数
        
        Args:
            node_id: 节点ID
            file_id: 已上传的文件ID
            printer_id: 目标打印机ID
            options: 打印参数，包含 copies, paper_size, color_mode, duplex_mode, page_count
        """
        from datetime import datetime, timezone
        message = {
            "type": "submit_print_params",
            "node_id": node_id,
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "data": {
                "file_id": file_id,
                "printer_id": printer_id,
                "options": options
            }
        }
        self.send_message_sync(message)

    def send_heartbeat(self, node_id: str, system_info: Dict[str, Any]) -> bool:
        """发送心跳消息到云端
        
        Args:
            node_id: 节点ID
            system_info: 系统信息，包含 cpu_usage, memory_usage, disk_usage, network_quality, latency
        
        Returns:
            bool: 发送是否成功
        """
        from datetime import datetime, timezone
        message = {
            "type": "edge_heartbeat",
            "node_id": node_id,
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "data": {
                "system_info": system_info
            }
        }
        return self.send_message_sync(message)

    def request_upload_token(self, node_id: str, printer_id: str) -> bool:
        """请求上传凭证
        
        Args:
            node_id: 节点ID
            printer_id: 目标打印机ID
        
        Returns:
            bool: 请求是否发送成功
        """
        from datetime import datetime, timezone
        message = {
            "type": "request_upload_token",
            "node_id": node_id,
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "data": {
                "printer_id": printer_id
            }
        }
        return self.send_message_sync(message)


class PrintJobHandler:
    """打印任务处理器"""

    def __init__(
        self,
        printer_manager,
        api_client,
        websocket_client=None,
        auth_client=None,
        node_id=None,
        status_reporter=None,
        interactive_job_binder=None,
    ):
        self.printer_manager = printer_manager
        self.api_client = api_client
        self.websocket_client = websocket_client
        self.auth_client = auth_client
        self.node_id = node_id
        self.status_reporter = status_reporter  # 打印机状态上报器
        self.interactive_job_binder = interactive_job_binder
        self.upload_token_callback = None  # 上传凭证成功回调
        self.upload_token_error_callback = None  # 上传凭证错误回调
        self.last_upload_token = None  # 缓存最近的上传凭证
    
    def handle_error_message(self, message: Dict[str, Any]):
        """处理云端错误响应
        
        错误码说明:
        - node_not_found: 节点不存在
        - node_disabled: 节点被禁用
        - printer_not_found: 打印机不存在
        - printer_not_belong_to_node: 打印机不属于该节点
        - printer_disabled: 打印机被禁用
        - token_generation_failed: 凭证生成失败
        - invalid_request: 请求格式错误
        - file_not_found: 文件不存在
        """
        try:
            data = message.get("data", {})
            error_code = data.get("code", "unknown_error")
            error_message = data.get("message", "未知错误")
            printer_id = data.get("printer_id")
            
            logger.error(f"收到云端错误: [{error_code}] {error_message}")
            if printer_id:
                logger.debug(f"  └─ 相关打印机: {printer_id}")
            
            # 检查是否是上传凭证请求的错误响应
            # 上传凭证相关的错误码：node_disabled, node_not_found, printer_disabled, printer_not_found, printer_not_belong_to_node
            upload_token_error_codes = [
                "node_disabled", "node_not_found", 
                "printer_disabled", "printer_not_found", "printer_not_belong_to_node",
                "token_generation_failed"
            ]
            
            if error_code in upload_token_error_codes:
                # 调用上传凭证错误回调
                if self.upload_token_error_callback and callable(self.upload_token_error_callback):
                    self.upload_token_error_callback(error_code, error_message)
                    logger.debug(f"  └─ 已触发上传凭证错误回调")
            
            # 分发错误消息到本地（SSE通知前端）
            if self.websocket_client:
                local_msg = {
                    "type": "cloud_error",
                    "data": {
                        "code": error_code,
                        "message": error_message,
                        "printer_id": printer_id
                    }
                }
                self.websocket_client.dispatch_local_message("cloud_error", local_msg)
            
            # 根据错误码进行特定处理
            # 打印机禁用状态已由云端统一管理，不再同步到本地
                    
        except Exception as e:
            logger.error(f"处理错误消息异常: {e}")
    
    def handle_upload_token(self, message: Dict[str, Any]):
        """处理上传凭证响应
        
        响应格式:
        {
            "type": "upload_token",
            "timestamp": "ISO8601",
            "data": {
                "token": "Base64编码凭证",
                "expires_at": "过期时间",
                "upload_url": "/api/v1/files?token=xxx",  # API上传端点（POST请求）
                "web_url": "/upload?token=xxx&node_id=xxx&printer_id=xxx"  # Web上传页面（GET请求，用于生成二维码）
            }
        }
        """
        try:
            data = message.get("data", {})
            token = data.get("token")
            expires_at = data.get("expires_at")
            upload_url = data.get("upload_url")  # API端点
            web_url = data.get("web_url")  # Web页面（优先使用）
            
            logger.info(f"收到上传凭证，过期时间: {expires_at}")
            
            # 缓存凭证（优先使用 web_url，如果不存在则使用 upload_url）
            self.last_upload_token = {
                "token": token,
                "expires_at": expires_at,
                "upload_url": web_url if web_url else upload_url  # 优先使用 web_url 生成二维码
            }
            
            # 如果有回调，执行回调
            if self.upload_token_callback and callable(self.upload_token_callback):
                self.upload_token_callback(token, expires_at, web_url if web_url else upload_url)
                
        except Exception as e:
            logger.error(f"处理上传凭证异常: {e}")
    
    def handle_preview_file(self, message: Dict[str, Any]):
        """处理文件预览请求
        
        注意：此方法只负责打印日志和保存文件访问 token，不做额外处理。
        消息转发由 main.py 中的 handle_cloud_message 统一处理。
        """
        try:
            data = message.get("data", {})
            file_url = data.get("file_url")
            file_name = data.get("file_name")
            file_id = data.get("file_id")
            file_type = data.get("file_type")
            file_size = data.get("file_size")
            file_access_token = data.get("file_access_token")
            file_access_token_expires_at = data.get("file_access_token_expires_at")

            logger.info(f"收到文件预览请求: {file_name} (ID: {file_id})")

            # 检查必需参数（根据云端API文档）
            if not all([file_url, file_id]):
                logger.warning(f"预览请求参数不完整: file_url={file_url}, file_id={file_id}")
                return

            logger.debug(f"文件预览链接: {file_url}")
            logger.debug(f"文件信息: 类型={file_type}, 大小={file_size} bytes")
            
            # 保存文件访问 token 到全局字典（使用 main.py 中的全局变量）
            if file_access_token:
                file_mgr = get_file_manager()
                if file_mgr:
                    file_mgr.store_file_access_token(file_id, file_access_token, file_access_token_expires_at)
                    logger.debug(f"保存文件访问 token 到统一管理器，过期时间: {file_access_token_expires_at}")
                else:
                    logger.warning("FileManager 未初始化，无法缓存文件访问 token")
            else:
                logger.warning(f"未收到文件访问 token")
            
            # 消息转发由 main.py 中的 handle_cloud_message 统一处理
            # 不需要在这里再次调用 dispatch_local_message
            logger.debug(f"预览消息将由 SSE 转发器自动推送到前端")

        except Exception as e:
            logger.error(f"处理文件预览请求异常: {e}")

    def handle_print_job(self, message: Dict[str, Any]):
        """处理打印任务消息"""
        try:
            # 从WebSocket消息中提取实际的打印任务数据
            data = message.get("data", {})
            
            job_id = data.get("job_id")
            printer_name = data.get("printer_name")
            printer_id = data.get("printer_id")
            file_url = data.get("file_url")
            content_hash = data.get("content_hash")
            file_access_token = data.get("file_access_token")  # 获取文件下载凭证
            job_name = data.get("name", f"CloudJob_{job_id}")  # 使用name字段作为任务名
            print_options = data.get("print_options", {})
            if not isinstance(print_options, dict):
                print_options = {}
            
            logger.info(f"处理云端打印任务: {job_name} (ID: {job_id})")
            
            if not all([job_id, printer_name, file_url]):
                logger.warning("打印任务参数不完整")
                return
            if not is_valid_content_hash(content_hash):
                logger.warning("打印任务缺少有效 content_hash: job_id=%s", job_id)
                self._report_job_failure(job_id, "content_hash missing or invalid")
                return

            interactive_options = None
            try:
                if callable(self.interactive_job_binder):
                    bound_context = self.interactive_job_binder(file_url, job_id)
                    if isinstance(bound_context, dict):
                        bound_session_id = bound_context.get("session_id")
                        interactive_options = bound_context.get("print_options")
                    else:
                        bound_session_id = bound_context
                    if bound_session_id:
                        logger.debug(f"已将云端任务绑定到当前交互会话: {bound_session_id}")
            except Exception as bind_error:
                logger.warning(f"绑定交互会话失败: {bind_error}")
            
            # 【去重检查】如果任务已经完成过，直接上报成功，不重复打印
            if self.websocket_client and hasattr(self.websocket_client, "_begin_job_processing"):
                job_state = self.websocket_client._begin_job_processing(job_id)
                if job_state == "completed":
                    logger.info("duplicate completed cloud print job acknowledged: %s", job_id)
                    self._report_job_success(job_id, printer_id)
                    return
                if job_state == "processing":
                    logger.warning("duplicate cloud print job ignored while in flight: %s", job_id)
                    return
            if self.websocket_client and hasattr(self.websocket_client, "_is_job_completed") and self.websocket_client._is_job_completed(job_id):
                logger.info(f"任务 {job_id} 已完成过，跳过重复打印，直接上报成功状态")
                self._report_job_success(job_id, printer_id)
                return
            
            # 兼容 Cloud 的扁平化字段，如果 print_options 中不存在，则从根 data 读取
            fields_mapping = {
                "copies": "copies",
                "paper_size": "paper_size", 
                "color_mode": "color_mode",
                "duplex": "duplex_mode",  # 注意字段名映射
                "page_count": "page_count",
                "scale_mode": "scale_mode",
                "max_upscale": "max_upscale"
            }

            for option_key, data_key in fields_mapping.items():
                if option_key not in print_options and data_key in data:
                    print_options[option_key] = data[data_key]

            if isinstance(interactive_options, dict):
                print_options.update(interactive_options)

            if "paper_size" not in print_options and "page_size" in print_options:
                print_options["paper_size"] = print_options.get("page_size")

            print_options = normalize_print_options(print_options)
            logger.info(
                "Cloud print options normalized: job_id=%s printer=%r options=%r",
                job_id,
                printer_name,
                print_options,
            )

            file_mgr = get_file_manager()

            def source_supplier():
                downloaded = self._download_print_file(
                    file_url,
                    job_id,
                    job_name,
                    file_access_token,
                    content_hash,
                )
                if not downloaded:
                    raise FileNotFoundError("cloud print source download failed")
                return Path(downloaded)
            
            # 使用统一的打印任务提交方法（自动处理清理）
            self._start_ipp_print_service(
                job_id=job_id,
                printer_id=printer_id,
                printer_name=printer_name,
                file_path=None,
                job_name=job_name,
                print_options=print_options,
                content_hash=content_hash,
                file_mgr=file_mgr,
                source_kind=str(data.get("file_type") or data.get("content_type") or ""),
                source_supplier=source_supplier,
            )
            return
                
        except Exception as e:
            logger.error(f"处理云端打印任务异常: {e}")
            # 统一方法已经处理了异常清理
            self._report_job_failure(data.get("job_id"), str(e))
    
    def _start_ipp_print_service(
        self,
        *,
        job_id,
        printer_id,
        printer_name,
        file_path,
        job_name,
        print_options,
        content_hash,
        file_mgr,
        source_kind="",
        source_supplier=None,
    ):
        from print_runtime import build_print_request, build_print_service
        from printing.domain import PrintState

        printer = self.printer_manager.config.get_printer_by_id(printer_id) if printer_id else None
        if not printer:
            printer = self.printer_manager.config.get_printer_by_name(printer_name)
        if not printer or not printer.get("enabled", True):
            self._report_job_failure(job_id, "打印服务尚未配置完成，请联系工作人员。", "service_not_ready")
            return
        service = build_print_service(self.printer_manager.config, logger)
        request = build_print_request(
            self.printer_manager.config,
            job_id=job_id,
            printer_id=printer_id,
            printer_name=printer_name,
            file_path=file_path,
            source_name=job_name,
            print_options=print_options,
            content_hash=content_hash,
            source_kind=source_kind,
            source_supplier=source_supplier,
            delete_source_after_standardize=True,
        )

        def report(event):
            if event.state == PrintState.COMPLETED:
                self._report_job_success(job_id, printer_id)
            elif event.state in {PrintState.FAILED, PrintState.CANCELED, PrintState.UNCONFIRMED}:
                self._report_job_failure(
                    job_id,
                    event.message,
                    event.error_code.value if event.error_code else event.state.value,
                )
            else:
                self._report_job_status(
                    job_id,
                    event.state.value,
                    0,
                    event.message,
                    current_page=event.current_page,
                    total_pages=event.total_pages,
                )

        def run():
            try:
                service.execute(request, report)
            finally:
                if file_mgr:
                    file_mgr.release_print_artifact(job_id, reason="ipp_print_service_terminal")
                if self.status_reporter:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)

        import threading
        threading.Thread(target=run, name=f"print-{job_id}", daemon=True).start()

    def _download_print_file(self, file_url: str, job_id: str, expected_filename: str = None, file_access_token: str = None, content_hash: str = None) -> Optional[str]:
        """下载打印文件
        
        Args:
            file_url: 文件URL
            job_id: 任务ID
            expected_filename: 期望的文件名
            file_access_token: 文件下载凭证（来自print_job指令）
        
        Returns:
            下载的临时文件路径，失败返回None
        """
        job_dir = None
        partial_path = None
        registered = False
        try:
            import requests
            import os
            from urllib.parse import urlparse, urlencode, urlunparse, parse_qs, urlsplit
            from portable_temp import get_portable_temp_dir
            
            # 如果是相对路径，拼接完整URL
            if file_url and not file_url.startswith(('http://', 'https://')):
                if self.api_client and self.api_client.base_url:
                    file_url = f"{self.api_client.base_url.rstrip('/')}/{file_url.lstrip('/')}"

            # 确定认证方式
            headers = {}
            download_url = file_url
            auth_mode = "direct"
            
            # S3签名URL不能带认证头
            if 'X-Amz-Algorithm' in file_url and 'X-Amz-Signature' in file_url:
                auth_mode = "signed_url"
                logger.debug("检测到S3签名URL，使用直连下载")
            # 优先使用file_access_token（API文档推荐方式）
            elif file_access_token:
                auth_mode = "file_access_token"
                # 将token作为查询参数添加到URL
                parsed = urlparse(file_url)
                query_params = parse_qs(parsed.query)
                query_params['token'] = [file_access_token]
                new_query = urlencode(query_params, doseq=True)
                download_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path,
                    parsed.params, new_query, parsed.fragment
                ))
                logger.debug("使用file_access_token下载文件")
            else:
                # 回退到Bearer Token认证
                if self.api_client and self.api_client.auth_client:
                    auth_mode = "bearer"
                    headers = self.api_client.auth_client.get_auth_headers()
                    logger.debug("使用Bearer Token下载文件")
                else:
                    logger.warning(f"无可用认证方式，尝试直接下载")

            parsed_download = urlsplit(download_url)
            logger.info(
                "Downloading print file: job_id=%s auth=%s host=%s path=%s",
                job_id,
                auth_mode,
                parsed_download.netloc,
                parsed_download.path,
            )
            
            response = requests.get(download_url, headers=headers, stream=True, timeout=30)
            if response.status_code != 200:
                logger.error("Print file download failed: job_id=%s status=%s", job_id, response.status_code)
                response.close()
            
            if response.status_code == 200:
                # 使用 portable temp 目录
                temp_dir = get_portable_temp_dir()
                
                # 确定文件名
                final_filename = None
                
                # 1. 优先使用传入的期望文件名
                if expected_filename and '.' in expected_filename:
                    final_filename = expected_filename
                    # 确保文件名安全
                    final_filename = "".join([c for c in final_filename if c.isalpha() or c.isdigit() or c in '._- ']).strip()
                
                # 2. 尝试从URL提取
                if not final_filename:
                    # 从URL路径中提取原始文件名，忽略查询参数
                    from urllib.parse import urlparse
                    parsed_url = urlparse(file_url)
                    url_filename = os.path.basename(parsed_url.path)
                    if url_filename and '.' in url_filename:
                        final_filename = url_filename
                
                # 3. 兜底策略：使用job_id作为文件名，默认为pdf (这可能是之前的bug来源)
                # 只有在真的无法确定类型时才这样做
                if not final_filename:
                    final_filename = f"cloud_job_{job_id}.pdf"
                
                final_filename = "".join(
                    c for c in final_filename if c.isalpha() or c.isdigit() or c in "._- "
                ).strip() or f"cloud_job_{job_id}.pdf"
                safe_prefix = "".join(c for c in str(job_id) if c.isalnum() or c in "-_")[:48] or "job"
                job_digest = hashlib.sha256(str(job_id).encode("utf-8")).hexdigest()[:16]
                job_dir = os.path.join(temp_dir, "downloads", f"{safe_prefix}-{job_digest}")
                os.makedirs(job_dir, exist_ok=True)
                temp_file_path = os.path.join(job_dir, final_filename)
                partial_path = f"{temp_file_path}.part"
                try:
                    os.remove(partial_path)
                except FileNotFoundError:
                    pass

                try:
                    with open(partial_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    os.replace(partial_path, temp_file_path)
                finally:
                    response.close()

                file_mgr = get_file_manager()
                if not file_mgr:
                    raise RuntimeError("file manager is unavailable")
                file_mgr.register_print_artifact(job_id, temp_file_path)
                registered = True
                logger.info("Print file downloaded: job_id=%s file=%s", job_id, final_filename)
                return temp_file_path
            else:
                logger.error(f"文件下载失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error("Print file download failed: job_id=%s error=%s", job_id, e)
            return None
        finally:
            if partial_path:
                try:
                    os.remove(partial_path)
                except OSError:
                    pass
            if job_dir and not registered:
                shutil.rmtree(job_dir, ignore_errors=True)
    
    def _refresh_printer_status(self, printer_id: str = None, printer_name: str = None):
        if self.status_reporter and printer_id:
            self.status_reporter.force_report_printer(
                printer_id=printer_id,
                printer_name=printer_name,
            )

    def _get_managed_printer_record(self, printer_id: str = None, printer_name: str = None):
        config = getattr(self.printer_manager, "config", None)
        if not config:
            return None
        if printer_id and hasattr(config, "get_printer_by_id"):
            printer = config.get_printer_by_id(printer_id)
            if printer:
                return printer
        if printer_name and hasattr(config, "get_printer_by_name"):
            return config.get_printer_by_name(printer_name)
        return None

    def _report_job_status(
        self,
        job_id: str,
        status: str,
        progress: int,
        message_text: str,
        current_page: int = None,
        total_pages: int = None,
    ):
        """通过WebSocket报告任务状态"""
        if job_id:
            try:
                from datetime import datetime, timezone
                
                cloud_job_data = {
                    "job_id": job_id,
                    "status": status,
                    "progress": progress,
                    "error_message": None,
                    "message": message_text
                }
                local_job_data = dict(cloud_job_data)
                if current_page is not None:
                    local_job_data["current_page"] = current_page
                if total_pages is not None:
                    local_job_data["total_pages"] = total_pages
                
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id if self.api_client else "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": cloud_job_data
                }
                
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
                    self.websocket_client.dispatch_local_message(
                        "job_status",
                        {"type": "job_status", "data": local_job_data},
                    )
                    logger.debug(f"任务状态({status})已通过WebSocket上报: {job_id}")
                
            except Exception as e:
                logger.error(f"报告任务状态异常: {e}")

    def _report_job_success(self, job_id: str, printer_id: str = None):
        """通过WebSocket报告任务成功
        
        Args:
            job_id: 任务ID
            printer_id: 打印机ID（可选，用于日志）
        """
        if job_id:
            try:
                from datetime import datetime, timezone
                
                # 构造消息数据
                job_data = {
                    "job_id": job_id,
                    "status": "completed",
                    "progress": 100,
                    "error_message": None,
                    "message": "打印任务已完成" # 前端可能需要这个字段
                }
                
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id if self.api_client else "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": job_data
                }
                
                # 1. 通过WebSocket发送给Cloud
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
                    logger.info(f"任务成功状态已通过WebSocket上报: {job_id}")
                    
                    # 【关键】标记任务为已完成，防止重复执行
                    self.websocket_client._mark_job_completed(job_id)
                else:
                    logger.warning(f"WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    # 构造符合前端期望的 job_status 消息
                    # 前端期望: { type: "job_status", data: { status: "completed", ... } }
                    local_msg = {
                        "type": "job_status",
                        "data": job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    if hasattr(self.websocket_client, "_finish_job_processing"):
                        self.websocket_client._finish_job_processing(job_id)
                    logger.debug(f"任务成功状态已分发到本地处理器 (SSE)")

            except Exception as e:
                logger.error(f"报告任务成功异常: {e}")
    
    def _report_job_failure(
        self,
        job_id: str,
        error_message: str,
        error_code: str = None,
        local_extra: Optional[Dict[str, Any]] = None,
    ):
        """通过WebSocket报告任务失败"""
        if job_id:
            try:
                from datetime import datetime, timezone
                
                job_data = {
                    "job_id": job_id,
                    "status": "failed",
                    "progress": 0,
                    "error_message": error_message,
                    "message": error_message
                }
                local_job_data = dict(job_data)
                if error_code:
                    local_job_data["error_code"] = error_code
                if local_extra:
                    local_job_data.update(local_extra)
                
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id if self.api_client else "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": job_data
                }
                
                # 1. 通过WebSocket发送给Cloud
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
                    logger.info(f"任务失败状态已通过WebSocket上报: {job_id}")
                else:
                    logger.warning(f"WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    local_msg = {
                        "type": "job_status",
                        "data": local_job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    if hasattr(self.websocket_client, "_finish_job_processing"):
                        self.websocket_client._finish_job_processing(job_id)
                    logger.debug(f"任务失败状态已分发到本地处理器 (SSE)")

            except Exception as e:
                logger.error(f"报告任务失败异常: {e}")
