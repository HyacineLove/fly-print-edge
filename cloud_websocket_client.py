"""
fly-print-cloud WebSocket客户端
接收云端打印任务和实时消息
"""

import asyncio
import websockets
import json
import threading
import time
import requests
import os
import base64
from typing import Dict, Any, Callable, Optional, List
from cloud_auth import CloudAuthClient

class CloudWebSocketClient:
    """云端WebSocket客户端"""
    
    def __init__(self, websocket_url: str, auth_client: CloudAuthClient):
        self.websocket_url = websocket_url
        self.auth_client = auth_client
        self.websocket = None
        self.running = False
        self.connected = False  # 实际连接状态（握手成功才为True）
        self.thread = None
        self.loop = None  # 存储WebSocket线程的事件循环
        self.message_handlers = {}  # type: Dict[str, List[Callable]]
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
            # print(f" [DEBUG] 本地分发 {len(handlers)} 个处理器处理 {message_type}")
            # 在主线程或当前线程直接执行，因为通常是UI更新
            for handler in handlers:
                try:
                    handler(data)
                except Exception as e:
                    print(f" [ERROR] 处理本地消息异常: {e}")
    
    def start(self):
        """启动WebSocket客户端"""
        if self.running:
            print(" [WARNING] WebSocket客户端已经在运行")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        print(" [INFO] WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        # 不直接关闭WebSocket连接，让异步循环自然结束
        # WebSocket连接会在_connect_and_listen循环结束时自动关闭
        print(" [INFO] WebSocket客户端已停止")
    
    def _start_cleanup_task(self):
        """启动定期清理过期任务记录的后台线程"""
        def cleanup_loop():
            while True:
                try:
                    time.sleep(300)  # 每5分钟清理一次
                    self._cleanup_completed_jobs()
                except Exception as e:
                    print(f" [ERROR] 清理已完成任务缓存异常: {e}")
        
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
            print(f" [INFO] 清理 {len(expired_jobs)} 个过期任务记录")
    
    def _mark_job_completed(self, job_id: str):
        """标记任务为已完成"""
        self.completed_jobs[job_id] = time.time()
        print(f" [INFO] 任务已标记为完成: {job_id} (缓存中共 {len(self.completed_jobs)} 个)")
    
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
            print(f" [ERROR] WebSocket异步循环异常: {e}")
        finally:
            loop.close()
            self.loop = None

    async def _connect_and_listen(self):
        """连接WebSocket并监听消息"""
        while self.running:
            try:
                print(f" [INFO] 连接WebSocket: {self.websocket_url}")
                
                # 获取认证头
                token = self.auth_client.get_access_token()
                if not token:
                    print(" [ERROR] 无法获取access token，等待重试")
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
                    print(" [INFO] WebSocket连接成功")
                    
                    # 监听消息
                    async for message in websocket:
                        try:
                            await self._handle_message(message)
                        except Exception as e:
                            print(f" [ERROR] 处理WebSocket消息异常: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                self.connected = False
                print(f" [WARNING] WebSocket连接关闭: {e}")
            except Exception as e:
                self.connected = False
                print(f" [ERROR] WebSocket连接异常: {e}")
            
            if self.running:
                print(f" [INFO] {self.reconnect_interval}秒后重连WebSocket")
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
                # print(f" [DEBUG] 已自动回复 ACK: {data['msg_id']}")

            if message_type == "preview_file":
                print(" [INFO] 收到预览文件消息")
            
            # 处理服务端关闭通知（server_close）
            if message_type == "server_close":
                close_data = data.get("data") or {}
                reason = close_data.get("reason") or "unknown"
                msg = close_data.get("message") or ""
                print(f" [INFO] 收到服务端关闭通知: reason={reason}, message={msg}")
                
                # 节点被删除时，按照协议要求：不要自动重连，等待手动重新注册
                if reason == "node_deleted":
                    print(" [INFO] 节点已被删除，将停止WebSocket重连，等待手动重新注册")
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
                print(f" [WARNING] 未找到消息类型处理器: {message_type}")
                
        except json.JSONDecodeError as e:
            print(f" [ERROR] WebSocket消息JSON解析失败: {e}")
        except Exception as e:
            print(f" [ERROR] 处理WebSocket消息异常: {e}")
    
    async def _send_message(self, data: Dict[str, Any]) -> bool:
        """发送消息到WebSocket"""
        if not self.websocket:
            return False
        try:
            message = json.dumps(data)
            await self.websocket.send(message)
            return True
        except Exception as e:
            print(f" [ERROR] 发送WebSocket消息失败: {e}")
            return False

    async def send_message(self, data: Dict[str, Any]) -> bool:
        """异步发送消息 (可从任何循环调用)"""
        if not self.loop or not self.loop.is_running():
            print(" [WARNING] WebSocket事件循环未运行，无法发送消息")
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
            print(f" [ERROR] 异步发送消息异常: {e}")
            return False

    def send_message_sync(self, data: Dict[str, Any]) -> bool:
        """同步发送消息（在其他线程中调用）"""
        if not self.loop or not self.loop.is_running():
            print(" [WARNING] WebSocket事件循环未运行，无法发送消息")
            return False
            
        try:
            # 使用 run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
            
            # 等待结果，确保消息发送成功
            try:
                return bool(future.result(timeout=5))
            except asyncio.TimeoutError:
                print(f" [ERROR] 同步发送WebSocket消息超时: {data.get('type')}")
                return False
            except Exception as e:
                print(f" [ERROR] 同步发送WebSocket消息执行失败: {e}")
                return False
                
        except Exception as e:
            print(f" [ERROR] 同步发送WebSocket消息失败: {e}")
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
    
    def __init__(self, printer_manager, api_client, websocket_client=None, auth_client=None, node_id=None, status_reporter=None):
        self.printer_manager = printer_manager
        self.api_client = api_client
        self.websocket_client = websocket_client
        self.auth_client = auth_client
        self.node_id = node_id
        self.status_reporter = status_reporter  # 打印机状态上报器
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
            
            print(f" [ERROR] 收到云端错误: [{error_code}] {error_message}")
            if printer_id:
                print(f"  └─ 相关打印机: {printer_id}")
            
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
                    print(f"  └─ 已触发上传凭证错误回调")
            
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
            print(f" [ERROR] 处理错误消息异常: {e}")
    
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
            
            print(f" [INFO] 收到上传凭证，过期时间: {expires_at}")
            
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
            print(f" [ERROR] 处理上传凭证异常: {e}")
    
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

            print(f" [INFO] 收到文件预览请求: {file_name} (ID: {file_id})")

            # 检查必需参数（根据云端API文档）
            if not all([file_url, file_id]):
                print(f" [WARNING] 预览请求参数不完整: file_url={file_url}, file_id={file_id}")
                return

            print(f" [INFO] 文件预览链接: {file_url}")
            print(f" [INFO] 文件信息: 类型={file_type}, 大小={file_size} bytes")
            
            # 保存文件访问 token 到全局字典（使用 main.py 中的全局变量）
            if file_access_token:
                # 导入 main.py 的全局变量
                import main
                main.file_access_tokens[file_id] = {
                    'token': file_access_token,
                    'expires_at': file_access_token_expires_at
                }
                print(f" [INFO] 保存文件访问 token 到全局字典，过期时间: {file_access_token_expires_at}")
            else:
                print(f" [WARNING] 未收到文件访问 token")
            
            # 消息转发由 main.py 中的 handle_cloud_message 统一处理
            # 不需要在这里再次调用 dispatch_local_message
            print(f" [INFO] 预览消息将由 SSE 转发器自动推送到前端")

        except Exception as e:
            print(f" [ERROR] 处理文件预览请求异常: {e}")

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
            
            print(f" [INFO] 处理云端打印任务: {job_name} (ID: {job_id})")
            
            if not all([job_id, printer_name, file_url]):
                print(" [WARNING] 打印任务参数不完整")
                return
            
            # 【去重检查】如果任务已经完成过，直接上报成功，不重复打印
            if self.websocket_client and self.websocket_client._is_job_completed(job_id):
                print(f" [INFO] 任务 {job_id} 已完成过，跳过重复打印，直接上报成功状态")
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
                printer_name, file_path, job_name, print_options, "云端WebSocket", printer_id
            )
            
            if result.get("success"):
                print(f" [INFO] 云端打印任务提交成功: {job_id}")
                # 立即上报打印机状态（任务开始）
                if self.status_reporter:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                # 启动任务完成监控
                self._monitor_job_completion(job_id, printer_name, result.get("job_id"), printer_id)
            else:
                error_msg = result.get("message", "未知错误")
                print(f" [ERROR] 云端打印任务提交失败: {error_msg}")
                self._report_job_failure(job_id, error_msg)
                
        except Exception as e:
            print(f" [ERROR] 处理云端打印任务异常: {e}")
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
                print(" [INFO] 检测到S3签名URL，使用直连下载")
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
                print(" [INFO] 使用file_access_token下载文件")
            else:
                # 回退到Bearer Token认证
                if self.api_client and self.api_client.auth_client:
                    headers = self.api_client.auth_client.get_auth_headers()
                    print(" [INFO] 使用Bearer Token下载文件")
                else:
                    print(f" [WARNING] 无可用认证方式，尝试直接下载")

            print(f" [INFO] 下载打印文件: {file_url}")
            
            response = requests.get(download_url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f" [ERROR] 响应内容: {response.text[:500]}")  # 打印前500字符的错误信息
            
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
                
                print(f" [INFO] 文件下载成功: {temp_file_path}")
                return temp_file_path
            else:
                print(f" [ERROR] 文件下载失败: {response.status_code}")
                return None
                
        except Exception as e:
            print(f" [ERROR] 下载打印文件异常: {e}")
            return None
    
    def _monitor_job_completion(self, cloud_job_id: str, printer_name: str, local_job_id: str, printer_id: str = None):
        """监控打印任务完成状态（使用轮询方式）
        
        Args:
            cloud_job_id: 云端任务ID
            printer_name: 打印机名称
            local_job_id: 本地任务ID
            printer_id: 打印机ID（用于状态上报）
        """
        import threading
        import time

        def detect_error_from_status(status_text: str):
            """根据状态文本判断是否处于错误状态。"""
            if not status_text:
                return False, ""
            s = str(status_text).strip().lower()

            error_keywords = [
                "错误", "离线", "缺纸", "卡纸", "被阻止", "用户干预", "删除", "暂停", "故障",
                "error", "offline", "paper", "jam", "blocked", "intervention", "paused", "failed"
            ]
            for kw in error_keywords:
                if kw in s:
                    return True, kw
            return False, ""

        def get_printer_status_snapshot():
            """获取打印机状态快照（包含原始码，若可用）。"""
            detail = {}
            if hasattr(self.printer_manager, 'get_printer_status_detail'):
                detail = self.printer_manager.get_printer_status_detail(printer_name) or {}
            if not detail:
                detail = {"status_text": self.printer_manager.get_printer_status(printer_name)}
            status_text = detail.get("status_text", "未知")
            return status_text, detail

        def format_printer_status_codes(detail: dict) -> str:
            """格式化原始状态码日志。"""
            win32_status = detail.get("win32_status")
            win32_attr = detail.get("win32_attributes")
            wmi = detail.get("wmi") or {}
            return (
                f"win32_status={win32_status}, "
                f"win32_attributes={win32_attr}, "
                f"wmi_printer_status={wmi.get('printer_status')}, "
                f"wmi_extended_status={wmi.get('extended_status')}, "
                f"wmi_detected_error_state={wmi.get('detected_error_state')}, "
                f"wmi_work_offline={wmi.get('work_offline')}, "
                f"wmi_availability={wmi.get('availability')}"
            )
        
        # 使用轮询方式（更可靠）
        def monitor():
            try:
                if not local_job_id:
                    # 没有job_id，通过轮询打印机队列状态判断是否完成
                    print(f"[WARN] 未获取到job_id，改为队列轮询监控: {cloud_job_id}")
                    
                    max_wait_time = 120  # 最大等待2分钟
                    check_interval = 1   # 每1秒检查一次
                    waited_time = 0
                    
                    # 先等待3秒让任务进入队列
                    time.sleep(3)
                    
                    while waited_time < max_wait_time:
                        # 先检查打印机本体状态（离线、缺纸等）
                        printer_status, printer_detail = get_printer_status_snapshot()
                        has_error, reason = detect_error_from_status(printer_status)
                        if has_error:
                            raw_codes = format_printer_status_codes(printer_detail)
                            err_msg = f"打印机异常({reason}): {printer_status} | 原始状态码: {raw_codes}"
                            print(f"[ERROR] {err_msg} | 任务: {cloud_job_id}")
                            self._report_job_failure(cloud_job_id, err_msg)
                            if self.status_reporter and printer_id:
                                self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                            return

                        # 检查打印机队列是否为空
                        queue_jobs = self.printer_manager.get_print_queue(printer_name)
                        if queue_jobs:
                            # 队列里存在任务时，检查任务状态是否错误
                            for qj in queue_jobs:
                                q_status = qj.get("status", "")
                                has_error, reason = detect_error_from_status(q_status)
                                if has_error:
                                    err_msg = f"打印任务异常({reason}): {q_status}"
                                    print(f"[ERROR] {err_msg} | 任务: {cloud_job_id}")
                                    self._report_job_failure(cloud_job_id, err_msg)
                                    if self.status_reporter and printer_id:
                                        self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                                    return

                            jobs_count = len(queue_jobs)
                            if waited_time % 10 == 0:
                                print(f"[INFO] 打印机队列中仍有 {jobs_count} 个任务: {cloud_job_id}")
                            time.sleep(check_interval)
                            waited_time += check_interval
                        else:
                            # 队列为空，任务完成
                            print(f"[INFO] 打印机队列为空，任务完成: {cloud_job_id}")
                            self._report_job_success(cloud_job_id, printer_id)
                            if self.status_reporter and printer_id:
                                self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                            return
                    
                    # 超时按失败处理，避免打印异常被误判为成功
                    err_msg = f"打印任务监控超时({max_wait_time}s)，未确认完成"
                    print(f"[WARN] {err_msg}: {cloud_job_id}")
                    self._report_job_failure(cloud_job_id, err_msg)
                    if self.status_reporter and printer_id:
                        self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                    return
                
                max_wait_time = 600  # 最大等待10分钟
                check_interval = 1   # 每1秒检查一次
                waited_time = 0
                
                print(f"[INFO] 开始监控任务完成: {cloud_job_id} (本地任务ID: {local_job_id})")
                
                while waited_time < max_wait_time:
                    time.sleep(check_interval)
                    waited_time += check_interval

                    # 先检查打印机本体状态（覆盖不体现在队列中的异常）
                    printer_status, printer_detail = get_printer_status_snapshot()
                    has_error, reason = detect_error_from_status(printer_status)
                    if has_error:
                        raw_codes = format_printer_status_codes(printer_detail)
                        err_msg = f"打印机异常({reason}): {printer_status} | 原始状态码: {raw_codes}"
                        print(f"[ERROR] {err_msg} | 任务: {cloud_job_id}")
                        self._report_job_failure(cloud_job_id, err_msg)
                        if self.status_reporter and printer_id:
                            self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                        return
                    
                    # 检查任务状态
                    job_status = self.printer_manager.get_job_status(printer_name, local_job_id)

                    # 任务仍在队列时，识别错误状态
                    if job_status.get("exists", True):
                        current_status = job_status.get("status", "")
                        has_error, reason = detect_error_from_status(current_status)
                        if has_error:
                            err_msg = f"打印任务异常({reason}): {current_status}"
                            print(f"[ERROR] {err_msg} | 任务: {cloud_job_id}")
                            self._report_job_failure(cloud_job_id, err_msg)
                            if self.status_reporter and printer_id:
                                self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                            return
                    
                    # 如果任务不存在（完成或失败）
                    if not job_status.get("exists", True):
                        print(f"[INFO] 任务已从队列中移除（已完成）: {cloud_job_id}")
                        self._report_job_success(cloud_job_id, printer_id)
                        # 任务完成后立即上报打印机状态
                        if self.status_reporter and printer_id:
                            self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                        return
                    
                    # 显示当前状态（每10秒显示一次）
                    if waited_time % 10 == 0:
                        current_status = job_status.get('status', 'unknown')
                        pages_printed = job_status.get('pages_printed', 0)
                        total_pages = job_status.get('total_pages', 0)
                        print(f"[INFO] 任务处理中: {cloud_job_id} | 状态: {current_status} | 页数: {pages_printed}/{total_pages}")
                
                # 超时按失败处理，避免误判成功
                err_msg = f"打印任务监控超时({max_wait_time}s)，未确认完成"
                print(f"[WARN] {err_msg}: {cloud_job_id}")
                self._report_job_failure(cloud_job_id, err_msg)
                # 任务完成后立即上报打印机状态
                if self.status_reporter and printer_id:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                
            except Exception as e:
                print(f"[ERROR] 监控任务完成异常: {e}")
                # 异常按失败处理，避免掩盖真实问题
                self._report_job_failure(cloud_job_id, f"监控任务异常: {e}")
                # 异常后也要上报打印机状态
                if self.status_reporter and printer_id:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
        
        # 在后台线程中监控
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
                    print(f" [INFO] 任务状态({status})已通过WebSocket上报: {job_id}")
                
            except Exception as e:
                print(f" [ERROR] 报告任务状态异常: {e}")

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
                    print(f" [INFO] 任务成功状态已通过WebSocket上报: {job_id}")
                    
                    # 【关键】标记任务为已完成，防止重复执行
                    self.websocket_client._mark_job_completed(job_id)
                else:
                    print(f" [WARNING] WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    # 构造符合前端期望的 job_status 消息
                    # 前端期望: { type: "job_status", data: { status: "completed", ... } }
                    local_msg = {
                        "type": "job_status",
                        "data": job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    print(f" [INFO] 任务成功状态已分发到本地处理器 (SSE)")

            except Exception as e:
                print(f" [ERROR] 报告任务成功异常: {e}")
    
    def _report_job_failure(self, job_id: str, error_message: str):
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
                
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id if self.api_client else "unknown",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": job_data
                }
                
                # 1. 通过WebSocket发送给Cloud
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
                    print(f" [INFO] 任务失败状态已通过WebSocket上报: {job_id}")
                else:
                    print(f" [WARNING] WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    local_msg = {
                        "type": "job_status",
                        "data": job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    print(f" [INFO] 任务失败状态已分发到本地处理器 (SSE)")

            except Exception as e:
                print(f" [ERROR] 报告任务失败异常: {e}")
