"""
fly-print-cloud WebSocket客户端
接收云端打印任务和实时消息
"""

import asyncio
import websockets
import json
import threading
import time
import logging
import requests
import os
import base64
from typing import Dict, Any, Callable, Optional, List
from cloud_auth import CloudAuthClient
from file_manager import get_file_manager
from printer_fault_probe import IPPPrinterFaultProbe, resolve_printer_host
from printer_fault_state import PrinterFaultStateStore

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
        self.completed_jobs_ttl = 3600  # 缓存保留1小时
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
        def cleanup_loop():
            while True:
                try:
                    time.sleep(300)  # 每5分钟清理一次
                    self._cleanup_completed_jobs()
                except Exception as e:
                    logger.error(f"清理已完成任务缓存异常: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
    
    def _cleanup_completed_jobs(self):
        """清理过期的已完成任务记录"""
        now = time.time()
        expired_jobs = [job_id for job_id, timestamp in self.completed_jobs.items() 
                       if now - timestamp > self.completed_jobs_ttl]
        
        for job_id in expired_jobs:
            del self.completed_jobs[job_id]
        
        if expired_jobs:
            logger.info(f"清理 {len(expired_jobs)} 个过期任务记录")
    
    def _mark_job_completed(self, job_id: str):
        """标记任务为已完成"""
        self.completed_jobs[job_id] = time.time()
        logger.debug(f"任务已标记为完成: {job_id} (缓存中共 {len(self.completed_jobs)} 个)")
    
    def _is_job_completed(self, job_id: str) -> bool:
        """检查任务是否已完成"""
        return job_id in self.completed_jobs
    
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

    _TERMINAL_SPOOLER_STATUS_FLAGS = (
        0x00000002,  # JOB_STATUS_ERROR
        0x00000020,  # JOB_STATUS_OFFLINE
        0x00000040,  # JOB_STATUS_PAPEROUT
        0x00000100,  # JOB_STATUS_DELETED
        0x00000200,  # JOB_STATUS_BLOCKED_DEVQ
        0x00000400,  # JOB_STATUS_USER_INTERVENTION
    )
    _TERMINAL_SPOOLER_STATUS_KEYWORDS = (
        "error",
        "failed",
        "offline",
        "paper",
        "blocked",
        "intervention",
        "deleted",
        "\u9519\u8bef",
        "\u79bb\u7ebf",
        "\u7f3a\u7eb8",
        "\u88ab\u963b\u6b62",
        "\u7528\u6237\u5e72\u9884",
        "\u5df2\u5220\u9664",
    )
    
    def __init__(
        self,
        printer_manager,
        api_client,
        websocket_client=None,
        auth_client=None,
        node_id=None,
        status_reporter=None,
        interactive_job_binder=None,
        fault_probe=None,
        fault_state_store=None,
    ):
        self.printer_manager = printer_manager
        self.api_client = api_client
        self.websocket_client = websocket_client
        self.auth_client = auth_client
        self.node_id = node_id
        self.status_reporter = status_reporter  # 打印机状态上报器
        self.interactive_job_binder = interactive_job_binder
        self.fault_probe = fault_probe or IPPPrinterFaultProbe()
        self.fault_state_store = fault_state_store or PrinterFaultStateStore()
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
            file_access_token = data.get("file_access_token")  # 获取文件下载凭证
            job_name = data.get("name", f"CloudJob_{job_id}")  # 使用name字段作为任务名
            print_options = data.get("print_options", {})
            if not isinstance(print_options, dict):
                print_options = {}
            
            logger.info(f"处理云端打印任务: {job_name} (ID: {job_id})")
            
            if not all([job_id, printer_name, file_url]):
                logger.warning("打印任务参数不完整")
                return

            try:
                if callable(self.interactive_job_binder):
                    bound_session_id = self.interactive_job_binder(file_url, job_id)
                    if bound_session_id:
                        logger.debug(f"已将云端任务绑定到当前交互会话: {bound_session_id}")
            except Exception as bind_error:
                logger.warning(f"绑定交互会话失败: {bind_error}")
            
            # 【去重检查】如果任务已经完成过，直接上报成功，不重复打印
            if self.websocket_client and self.websocket_client._is_job_completed(job_id):
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

            if "paper_size" not in print_options and "page_size" in print_options:
                print_options["paper_size"] = print_options.get("page_size")

            # 处理旧有的 duplex_mode 逻辑 (保留兼容性，但已被上面的映射覆盖了一部分)
            # 如果映射后的 print_options['duplex'] 还是原始值（如 "duplex"），需要转换为 CUPS 标准值
            duplex_val = print_options.get("duplex")
            if duplex_val:
                if str(duplex_val).lower() == "duplex":
                    print_options["duplex"] = "DuplexNoTumble"
                elif str(duplex_val).lower() == "none":
                    print_options["duplex"] = "None"
            
            # 下载文件（优先使用file_access_token）
            file_path = self._download_print_file(file_url, job_id, job_name, file_access_token)
            if not file_path:
                self._report_job_failure(job_id, "文件下载失败")
                return
            
            if isinstance(print_options, dict):
                duplex_value = print_options.get("duplex")
                if duplex_value in ["LongEdge", "long", "long_edge", "short", "ShortEdge", "short_edge"]:
                    if duplex_value in ["ShortEdge", "short", "short_edge"]:
                        print_options["duplex"] = "DuplexTumble"
                    else:
                        print_options["duplex"] = "DuplexNoTumble"
            # 使用统一的打印任务提交方法（自动处理清理）
            result = self.printer_manager.submit_print_job_with_cleanup(
                printer_name, file_path, job_name, print_options, "云端WebSocket", printer_id, artifact_key=job_id
            )
            
            if result.get("success"):
                logger.info(f"云端打印任务提交成功: {job_id}")
                local_job_id = result.get("job_id")
                if local_job_id is None:
                    logger.error(
                        "job_id_debug missing_local_job_id cloud_job_id=%s printer_name=%s printer_id=%s printer_result_success=%s printer_result_message=%r",
                        job_id,
                        printer_name,
                        printer_id,
                        result.get("success"),
                        result.get("message"),
                    )
                    self._report_job_failure(job_id, "无法获取本地打印任务ID")
                    return

                # 立即上报打印机状态（任务开始）
                if self.status_reporter:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                # 启动任务完成监控
                self._monitor_job_completion(job_id, printer_name, local_job_id, printer_id)
            else:
                error_msg = result.get("message", "未知错误")
                logger.error(f"云端打印任务提交失败: {error_msg}")
                self._report_job_failure(job_id, error_msg)
                
        except Exception as e:
            logger.error(f"处理云端打印任务异常: {e}")
            # 统一方法已经处理了异常清理
            self._report_job_failure(data.get("job_id"), str(e))
    
    def _download_print_file(self, file_url: str, job_id: str, expected_filename: str = None, file_access_token: str = None) -> Optional[str]:
        """下载打印文件
        
        Args:
            file_url: 文件URL
            job_id: 任务ID
            expected_filename: 期望的文件名
            file_access_token: 文件下载凭证（来自print_job指令）
        
        Returns:
            下载的临时文件路径，失败返回None
        """
        try:
            import requests
            import tempfile
            import os
            from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
            from portable_temp import get_portable_temp_dir
            
            # 如果是相对路径，拼接完整URL
            if file_url and not file_url.startswith(('http://', 'https://')):
                if self.api_client and self.api_client.base_url:
                    file_url = f"{self.api_client.base_url.rstrip('/')}/{file_url.lstrip('/')}"

            # 确定认证方式
            headers = {}
            download_url = file_url
            
            # S3签名URL不能带认证头
            if 'X-Amz-Algorithm' in file_url and 'X-Amz-Signature' in file_url:
                logger.debug("检测到S3签名URL，使用直连下载")
            # 优先使用file_access_token（API文档推荐方式）
            elif file_access_token:
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
                    headers = self.api_client.auth_client.get_auth_headers()
                    logger.debug("使用Bearer Token下载文件")
                else:
                    logger.warning(f"无可用认证方式，尝试直接下载")

            logger.info(f"下载打印文件: {file_url}")
            
            response = requests.get(download_url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error(f"响应内容: {response.text[:500]}")  # 打印前500字符的错误信息
            
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
                
                temp_file_path = os.path.join(temp_dir, final_filename)
                
                with open(temp_file_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"文件下载成功: {temp_file_path}")
                file_mgr = get_file_manager()
                if file_mgr:
                    file_mgr.register_print_artifact(job_id, temp_file_path)
                return temp_file_path
            else:
                logger.error(f"文件下载失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"下载打印文件异常: {e}")
            return None
    
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

    def _resolve_fault_probe_host(self, printer_id: str = None, printer_name: str = None):
        return resolve_printer_host(
            self._get_managed_printer_record(
                printer_id=printer_id,
                printer_name=printer_name,
            )
        )

    def _probe_printer_fault(self, printer_id: str, printer_name: str):
        host = self._resolve_fault_probe_host(
            printer_id=printer_id,
            printer_name=printer_name,
        )
        if not host:
            logger.info(
                "fault_probe_unavailable printer=%r printer_id=%s reason=device_host_unresolved",
                printer_name,
                printer_id,
            )
            return None

        result = self.fault_probe.probe(host)
        if not getattr(result, "available", False):
            logger.info(
                "fault_probe_unavailable printer=%r printer_id=%s host=%r error=%r",
                printer_name,
                printer_id,
                host,
                getattr(result, "error", ""),
            )
            return result

        logger.info(
            "fault_probe_result printer=%r printer_id=%s host=%r state=%r state_name=%r reasons=%s faulted=%s",
            printer_name,
            printer_id,
            host,
            getattr(result, "printer_state", None),
            getattr(result, "printer_state_name", "unknown"),
            getattr(result, "printer_state_reasons", []),
            getattr(result, "faulted", False),
        )
        return result

    def _format_fault_failure_message(self, fault_result) -> str:
        fault_state = self.fault_state_store.update_from_probe(result=fault_result)
        return fault_state.get("message") or "打印机故障，请联系管理员处理"

    def _cancel_local_print_job(self, printer_name: str, local_job_id) -> tuple[bool, str]:
        if not hasattr(self.printer_manager, "remove_print_job"):
            logger.warning(
                "job_cancel_failed reason=remove_print_job_unavailable printer=%r job_id=%s",
                printer_name,
                local_job_id,
            )
            return False, "remove_print_job unavailable"

        success, message = self.printer_manager.remove_print_job(
            printer_name,
            local_job_id,
        )
        if success:
            logger.info(
                "job_cancel_confirmed printer=%r job_id=%s message=%r",
                printer_name,
                local_job_id,
                message,
            )
        else:
            logger.warning(
                "job_cancel_failed printer=%r job_id=%s message=%r",
                printer_name,
                local_job_id,
                message,
            )
        return success, message

    @classmethod
    def _is_terminal_spooler_error(cls, job_status: Dict[str, Any]) -> bool:
        if not isinstance(job_status, dict):
            return False

        raw_status = job_status.get("status_code")
        if raw_status is not None:
            try:
                status_code = int(raw_status)
            except (TypeError, ValueError):
                status_code = 0
            if any(status_code & flag for flag in cls._TERMINAL_SPOOLER_STATUS_FLAGS):
                return True

        status_text = str(job_status.get("status") or "").casefold()
        return any(
            keyword.casefold() in status_text
            for keyword in cls._TERMINAL_SPOOLER_STATUS_KEYWORDS
        )

    def _report_terminal_spooler_error(
        self,
        cloud_job_id: str,
        printer_name: str,
        local_job_id,
        job_status: Dict[str, Any],
    ) -> None:
        status_text = str(job_status.get("status") or "unknown")
        cancel_success, cancel_message = self._cancel_local_print_job(
            printer_name,
            local_job_id,
        )
        cancel_suffix = (
            f"; local job cancelled: {cancel_message}"
            if cancel_success
            else f"; local job cancel failed: {cancel_message}"
        )
        failure_message = (
            f"spooler job entered terminal error status: {status_text}{cancel_suffix}"
        )
        logger.error(
            "job_failed_spooler_error cloud_job_id=%s printer=%r local_job_id=%s status=%r cancel_success=%s message=%r",
            cloud_job_id,
            printer_name,
            local_job_id,
            status_text,
            cancel_success,
            failure_message,
        )
        self._report_job_failure(cloud_job_id, failure_message)

    def _monitor_job_completion(
        self,
        cloud_job_id: str,
        printer_name: str,
        local_job_id: str,
        printer_id: str = None,
    ):
        """Monitor a cloud job by spooler lifecycle and IPP device faults."""
        import threading
        import time

        def monitor():
            try:
                if not local_job_id:
                    logger.error(
                        "missing local print job id; cloud_job_id=%s printer=%r",
                        cloud_job_id,
                        printer_name,
                    )
                    self._report_job_failure(cloud_job_id, "无法获取本地打印任务ID")
                    return

                max_wait_time = 600
                check_interval = 1
                waited_time = 0

                logger.info(
                    "start job monitor cloud_job_id=%s printer=%r local_job_id=%s",
                    cloud_job_id,
                    printer_name,
                    local_job_id,
                )

                while waited_time < max_wait_time:
                    time.sleep(check_interval)
                    waited_time += check_interval

                    job_status = self.printer_manager.get_job_status(
                        printer_name,
                        local_job_id,
                    )
                    if not job_status.get("exists", True):
                        logger.info(
                            "spooler job removed; reporting completed cloud_job_id=%s local_job_id=%s",
                            cloud_job_id,
                            local_job_id,
                        )
                        self._report_job_success(cloud_job_id, printer_id)
                        self._refresh_printer_status(printer_id, printer_name)
                        return

                    fault_result = self._probe_printer_fault(printer_id, printer_name)
                    if fault_result and getattr(fault_result, "available", False) and getattr(fault_result, "faulted", False):
                        cancel_success, cancel_message = self._cancel_local_print_job(
                            printer_name,
                            local_job_id,
                        )
                        fault_state = self.fault_state_store.update_from_probe(
                            printer_id=printer_id,
                            printer_name=printer_name,
                            result=fault_result,
                        )
                        failure_message = fault_state.get("message") or self._format_fault_failure_message(fault_result)
                        if not cancel_success:
                            failure_message = (
                                f"{failure_message}; 本地任务取消失败: {cancel_message}"
                            )
                        logger.error(
                            "job_failed_after_cancel cloud_job_id=%s printer=%r local_job_id=%s cancel_success=%s message=%r",
                            cloud_job_id,
                            printer_name,
                            local_job_id,
                            cancel_success,
                            failure_message,
                        )
                        self._report_job_failure(
                            cloud_job_id,
                            failure_message,
                            error_code="printer_fault",
                            local_extra={"printer_fault": fault_state},
                        )
                        self._refresh_printer_status(printer_id, printer_name)
                        return

                    if self._is_terminal_spooler_error(job_status):
                        self._report_terminal_spooler_error(
                            cloud_job_id,
                            printer_name,
                            local_job_id,
                            job_status,
                        )
                        self._refresh_printer_status(printer_id, printer_name)
                        return

                    if waited_time % 10 == 0:
                        logger.debug(
                            "job monitor active cloud_job_id=%s local_job_id=%s status=%r pages=%s/%s",
                            cloud_job_id,
                            local_job_id,
                            job_status.get("status", "unknown"),
                            job_status.get("pages_printed", 0),
                            job_status.get("total_pages", 0),
                        )

                job_status = self.printer_manager.get_job_status(printer_name, local_job_id)
                cancel_suffix = ""
                if job_status.get("exists", True):
                    cancel_success, cancel_message = self._cancel_local_print_job(
                        printer_name,
                        local_job_id,
                    )
                    cancel_suffix = (
                        f"; 本地任务已取消: {cancel_message}"
                        if cancel_success
                        else f"; 本地任务取消失败: {cancel_message}"
                    )

                error_message = (
                    f"打印任务监控超时({max_wait_time}s){cancel_suffix}"
                )
                logger.warning(
                    "job monitor timeout cloud_job_id=%s printer=%r local_job_id=%s message=%r",
                    cloud_job_id,
                    printer_name,
                    local_job_id,
                    error_message,
                )
                self._report_job_failure(cloud_job_id, error_message)
                self._refresh_printer_status(printer_id, printer_name)
            except Exception as exc:
                logger.error("job monitor exception cloud_job_id=%s error=%s", cloud_job_id, exc)
                self._report_job_failure(cloud_job_id, f"打印任务监控异常: {exc}")
                self._refresh_printer_status(printer_id, printer_name)

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

    def _report_job_status(self, job_id: str, status: str, progress: int, message_text: str):
        """通过WebSocket报告任务状态"""
        if job_id:
            try:
                from datetime import datetime, timezone
                
                job_data = {
                    "job_id": job_id,
                    "status": status,
                    "progress": progress,
                    "error_message": None,
                    "message": message_text
                }
                
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id if self.api_client else "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": job_data
                }
                
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
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
                    logger.debug(f"任务失败状态已分发到本地处理器 (SSE)")

            except Exception as e:
                logger.error(f"报告任务失败异常: {e}")
