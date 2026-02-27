"""
fly-print-cloud WebSocket客户端
接收云端打印任务和实时消息
"""

import asyncio
import websockets
import json
import threading
import time
# import logging
from typing import Dict, Any, Callable, Optional
from cloud_auth import CloudAuthClient

# logger = logging.getLogger("EdgeServer")



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
        
    def add_message_handler(self, message_type: str, handler: Callable[[Dict[str, Any]], None]):
        """添加消息处理器"""
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []
        
        # 避免重复添加相同的handler
        if handler not in self.message_handlers[message_type]:
            self.message_handlers[message_type].append(handler)
            # 标注处理器来源（业务逻辑 or SSE转发）
            handler_name = handler.__name__ if hasattr(handler, '__name__') else str(handler)
            layer = "业务处理" if "handle_" in handler_name else "SSE转发"
            print(f"📝 [DEBUG] 注册WebSocket消息处理器: {message_type} -> {handler_name} ({layer})")
        else:
            print(f"📝 [DEBUG] WebSocket消息处理器已存在，跳过: {message_type}")
    
    def dispatch_local_message(self, message_type: str, data: Dict[str, Any]):
        """分发本地产生的消息到处理器"""
        if message_type in self.message_handlers:
            handlers = self.message_handlers[message_type]
            # print(f"🔧 [DEBUG] 本地分发 {len(handlers)} 个处理器处理 {message_type}")
            # 在主线程或当前线程直接执行，因为通常是UI更新
            for handler in handlers:
                try:
                    handler(data)
                except Exception as e:
                    print(f"❌ [ERROR] 处理本地消息异常: {e}")
    
    def start(self):
        """启动WebSocket客户端"""
        if self.running:
            print("⚠️ [WARNING] WebSocket客户端已经在运行")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        print("🚀 [INFO] WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        # 不直接关闭WebSocket连接，让异步循环自然结束
        # WebSocket连接会在_connect_and_listen循环结束时自动关闭
        print("🛑 [INFO] WebSocket客户端已停止")
    
    def _run_async_loop(self):
        """在单独线程中运行异步循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop  # 保存loop引用
        try:
            loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            print(f"❌ [ERROR] WebSocket异步循环异常: {e}")
        finally:
            loop.close()
            self.loop = None

    async def _connect_and_listen(self):
        """连接WebSocket并监听消息"""
        while self.running:
            try:
                print(f"🔌 [DEBUG] 连接WebSocket: {self.websocket_url}")
                
                # 获取认证头
                token = self.auth_client.get_access_token()
                if not token:
                    print("❌ [ERROR] 无法获取access token，等待重试")
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
                    print("✅ [INFO] WebSocket连接成功")
                    
                    # 监听消息
                    print("👂 [DEBUG] 开始监听WebSocket消息...")
                    async for message in websocket:
                        try:
                            # print(f"📨 [DEBUG] 收到WebSocket消息: {message}")
                            await self._handle_message(message)
                        except Exception as e:
                            print(f"❌ [ERROR] 处理WebSocket消息异常: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                self.connected = False
                print(f"🔌 [WARNING] WebSocket连接关闭: {e}")
            except Exception as e:
                self.connected = False
                print(f"❌ [ERROR] WebSocket连接异常: {e}")
            
            if self.running:
                print(f"🔄 [INFO] {self.reconnect_interval}秒后重连WebSocket")
                await asyncio.sleep(self.reconnect_interval)
    
    async def _handle_message(self, message: str):
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            message_type = data.get("type", "unknown")
            
            print(f"📨 [INFO] 收到WebSocket消息: {message_type}")
            if message_type == "preview_file":
                print(f"📄 [DEBUG] 收到预览文件消息: {json.dumps(data, ensure_ascii=False)}")
            
            # 处理服务端关闭通知（server_close）
            if message_type == "server_close":
                close_data = data.get("data") or {}
                reason = close_data.get("reason") or "unknown"
                msg = close_data.get("message") or ""
                print(f"🔌 [INFO] 收到服务端关闭通知: reason={reason}, message={msg}")
                
                # 节点被删除时，按照协议要求：不要自动重连，等待手动重新注册
                if reason == "node_deleted":
                    print("🛑 [INFO] 节点已被删除，将停止WebSocket重连，等待手动重新注册")
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
                print(f"🔧 [DEBUG] 触发 {len(handlers)} 个处理器处理 {message_type}")
                loop = asyncio.get_event_loop()
                for handler in handlers:
                    # 在线程池中执行处理器，避免阻塞WebSocket
                    await loop.run_in_executor(None, handler, data)
            else:
                print(f"⚠️ [WARNING] 未找到消息类型处理器: {message_type}")
                
        except json.JSONDecodeError as e:
            print(f"❌ [ERROR] WebSocket消息JSON解析失败: {e}")
        except Exception as e:
            print(f"❌ [ERROR] 处理WebSocket消息异常: {e}")
    
    async def _send_message(self, data: Dict[str, Any]) -> bool:
        """发送消息到WebSocket"""
        if not self.websocket:
            return False
        try:
            message = json.dumps(data)
            await self.websocket.send(message)
            print(f"📤 [DEBUG] 发送WebSocket消息: {data.get('type', 'unknown')}")
            return True
        except Exception as e:
            print(f"❌ [ERROR] 发送WebSocket消息失败: {e}")
            return False

    async def send_message(self, data: Dict[str, Any]) -> bool:
        """异步发送消息 (可从任何循环调用)"""
        if not self.loop or not self.loop.is_running():
            print("⚠️ [WARNING] WebSocket事件循环未运行，无法发送消息")
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
            print(f"❌ [ERROR] 异步发送消息异常: {e}")
            return False

    def send_message_sync(self, data: Dict[str, Any]) -> bool:
        """同步发送消息（在其他线程中调用）"""
        if not self.loop or not self.loop.is_running():
            print("⚠️ [WARNING] WebSocket事件循环未运行，无法发送消息")
            return False
            
        try:
            # 使用 run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
            
            # 等待结果，确保消息发送成功
            try:
                return bool(future.result(timeout=5))
            except asyncio.TimeoutError:
                print(f"❌ [ERROR] 同步发送WebSocket消息超时: {data.get('type')}")
                return False
            except Exception as e:
                print(f"❌ [ERROR] 同步发送WebSocket消息执行失败: {e}")
                return False
                
        except Exception as e:
            print(f"❌ [ERROR] 同步发送WebSocket消息失败: {e}")
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
            
            print(f"❌ [ERROR] 收到云端错误: [{error_code}] {error_message}")
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
            print(f"❌ [ERROR] 处理错误消息异常: {e}")
    
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
            
            print(f"🔐 [INFO] 收到上传凭证，过期时间: {expires_at}")
            
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
            print(f"❌ [ERROR] 处理上传凭证异常: {e}")
    
    def handle_preview_file(self, message: Dict[str, Any]):
        """处理文件预览请求"""
        try:
            data = message.get("data", {})
            file_url = data.get("file_url")
            file_name = data.get("file_name")
            task_token = data.get("task_token")
            file_id = data.get("file_id")

            print(f"👀 [DEBUG] 收到文件预览请求: {file_name} (ID: {file_id})")

            if not all([file_url, task_token, file_id]):
                print("❌ [WARNING] 预览请求参数不完整")
                return

            # 暂时仅打印URL，不下载
            print(f"🔗 [INFO] [PREVIEW LINK] {file_url}")
            
            # 移除自动提交，由前端UI负责提交

        except Exception as e:
            print(f"❌ [ERROR] 处理文件预览请求异常: {e}")

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
            duplex_mode = data.get("duplex_mode")
            if duplex_mode and "duplex" not in print_options:
                if str(duplex_mode).lower() == "duplex":
                    print_options["duplex"] = "DuplexNoTumble"
                else:
                    print_options["duplex"] = "None"
            
            print(f"🖨️ [INFO] 处理云端打印任务: {job_name} (ID: {job_id})")
            
            if not all([job_id, printer_name, file_url]):
                print("❌ [WARNING] 打印任务参数不完整")
                return
            
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
                print(f"✅ [INFO] 云端打印任务提交成功: {job_id}")
                # 立即上报打印机状态（任务开始）
                if self.status_reporter:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                # 启动任务完成监控
                self._monitor_job_completion(job_id, printer_name, result.get("job_id"), printer_id)
            else:
                error_msg = result.get("message", "未知错误")
                print(f"❌ [ERROR] 云端打印任务提交失败: {error_msg}")
                self._report_job_failure(job_id, error_msg)
                
        except Exception as e:
            print(f"❌ [ERROR] 处理云端打印任务异常: {e}")
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
            
            # 如果是相对路径，拼接完整URL
            if file_url and not file_url.startswith(('http://', 'https://')):
                if self.api_client and self.api_client.base_url:
                    file_url = f"{self.api_client.base_url.rstrip('/')}/{file_url.lstrip('/')}"
                    print(f"🔗 [DEBUG] 拼接完整文件URL: {file_url}")

            # 确定认证方式
            headers = {}
            download_url = file_url
            
            # S3签名URL不能带认证头
            if 'X-Amz-Algorithm' in file_url and 'X-Amz-Signature' in file_url:
                print(f"🔗 [DEBUG] 检测到S3签名URL，直接下载")
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
                print(f"🔐 [DEBUG] 使用file_access_token下载文件")
            else:
                # 回退到Bearer Token认证
                if self.api_client and self.api_client.auth_client:
                    headers = self.api_client.auth_client.get_auth_headers()
                    print(f"🔐 [DEBUG] 使用Bearer Token下载文件")
                else:
                    print(f"⚠️ [WARNING] 无可用认证方式，尝试直接下载")

            print(f"📥 [INFO] 下载打印文件: {file_url}")
            
            response = requests.get(download_url, headers=headers, timeout=30)
            print(f"📊 [DEBUG] 下载响应状态: {response.status_code}")
            if response.status_code != 200:
                print(f"📊 [ERROR] 响应内容: {response.text[:500]}")  # 打印前500字符的错误信息
            
            if response.status_code == 200:
                # 保存到临时文件
                temp_dir = tempfile.gettempdir()
                
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
                
                print(f"✅ [INFO] 文件下载成功: {temp_file_path}")
                return temp_file_path
            else:
                print(f"❌ [ERROR] 文件下载失败: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ [ERROR] 下载打印文件异常: {e}")
            return None
    
    def _monitor_job_completion(self, cloud_job_id: str, printer_name: str, local_job_id: str, printer_id: str = None):
        """监控打印任务完成状态
        
        Windows 平台优先使用 WMI 事件监听，Linux 使用轮询。
        
        Args:
            cloud_job_id: 云端任务ID
            printer_name: 打印机名称
            local_job_id: 本地任务ID
            printer_id: 打印机ID（用于状态上报）
        """
        import threading
        import time
        import platform
        
        # 尝试使用 WMI 事件监听（仅 Windows）
        if platform.system() == "Windows":
            try:
                from printer_windows import WindowsPrintJobMonitor
                wmi_monitor = WindowsPrintJobMonitor()
                
                if wmi_monitor.available and local_job_id:
                    print(f"🔍 [INFO] 使用 WMI 事件监听监控任务: {cloud_job_id}")
                    
                    def on_wmi_complete(job_info):
                        """WMI 任务完成回调"""
                        print(f"✅ [INFO] WMI 检测到任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        # 任务完成后立即上报打印机状态
                        if self.status_reporter and printer_id:
                            self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                    
                    # 启动 WMI 监听
                    wmi_monitor.start_job_monitor(
                        printer_name=printer_name,
                        job_id=local_job_id,
                        on_complete=on_wmi_complete
                    )
                    return  # 使用 WMI，直接返回
                    
            except Exception as e:
                print(f"⚠️ [WARNING] WMI 监听启动失败，回退到轮询: {e}")
        
        # 回退到轮询方式（Linux 或 WMI 不可用）
        def monitor():
            try:
                if not local_job_id:
                    # 虚拟打印机可能不返回 job_id，直接报告成功
                    print(f"⚠️ [WARNING] 未获取到job_id，假设打印已完成: {cloud_job_id}")
                    self._report_job_success(cloud_job_id)
                    if self.status_reporter and printer_id:
                        self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                    return
                
                max_wait_time = 600  # 最大等待10分钟
                check_interval = 1   # 每1秒检查一次（自助终端场景，轮询开销小）
                waited_time = 0
                
                print(f"🔍 [DEBUG] 开始轮询监控云端任务完成: {cloud_job_id} -> 本地任务: {local_job_id}")
                
                while waited_time < max_wait_time:
                    time.sleep(check_interval)
                    waited_time += check_interval
                    
                    # 检查任务状态
                    job_status = self.printer_manager.get_job_status(printer_name, local_job_id)
                    
                    # 如果任务不存在（完成或失败）或状态为完成，报告成功
                    if not job_status.get("exists", True):
                        print(f"✅ [INFO] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        # 任务完成后立即上报打印机状态
                        if self.status_reporter and printer_id:
                            self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                        return
                    elif job_status.get("status") in ["completed", "completed_or_failed"]:
                        print(f"✅ [INFO] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        # 任务完成后立即上报打印机状态
                        if self.status_reporter and printer_id:
                            self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                        return
                    else:
                        current_status = job_status.get('status', 'unknown')
                        print(f"🔍 [DEBUG] 云端任务 {cloud_job_id} 仍在处理中，状态: {current_status}")
                        # 上报中间状态 (如 printing)
                        if current_status in ["printing", "正在打印", "正在后台处理"]:
                             self._report_job_status(cloud_job_id, "printing", 50, f"正在打印: {current_status}")
                
                # 超时后报告成功（假设长时间运行的任务已完成）
                print(f"⏰ [WARNING] 云端任务监控超时，假设已完成: {cloud_job_id}")
                self._report_job_success(cloud_job_id)
                # 任务完成后立即上报打印机状态
                if self.status_reporter and printer_id:
                    self.status_reporter.force_report_printer(printer_id=printer_id, printer_name=printer_name)
                
            except Exception as e:
                print(f"❌ [ERROR] 监控云端任务完成异常: {e}")
                # 异常时也报告成功，避免任务一直处于分发状态
                self._report_job_success(cloud_job_id)
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
                    print(f"✅ [INFO] 任务状态({status})已通过WebSocket上报: {job_id}")
                
            except Exception as e:
                print(f"❌ [ERROR] 报告任务状态异常: {e}")

    def _report_job_success(self, job_id: str):
        """通过WebSocket报告任务成功"""
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
                print(f"🔍 [DEBUG] WebSocket客户端引用: {self.websocket_client}")
                if self.websocket_client:
                    # print(f"🔍 [DEBUG] WebSocket运行状态: {self.websocket_client.running}")
                    self.websocket_client.send_message_sync(message)
                    print(f"✅ [INFO] 任务成功状态已通过WebSocket上报: {job_id}")
                else:
                    print(f"⚠️ [WARNING] WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    # 构造符合前端期望的 job_status 消息
                    # 前端期望: { type: "job_status", data: { status: "completed", ... } }
                    local_msg = {
                        "type": "job_status",
                        "data": job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    print(f"✅ [INFO] 任务成功状态已分发到本地处理器 (SSE)")

            except Exception as e:
                print(f"❌ [ERROR] 报告任务成功异常: {e}")
    
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
                    print(f"✅ [DEBUG] 任务失败状态已通过WebSocket上报: {job_id}")
                else:
                    print(f"⚠️ [DEBUG] WebSocket连接不可用，无法上报任务状态: {job_id}")
                
                # 2. 分发本地消息给前端 (SSE)
                if self.websocket_client:
                    local_msg = {
                        "type": "job_status",
                        "data": job_data
                    }
                    self.websocket_client.dispatch_local_message("job_status", local_msg)
                    print(f"✅ [DEBUG] 任务失败状态已分发到本地处理器 (SSE)")

            except Exception as e:
                print(f"❌ [DEBUG] 报告任务失败异常: {e}")
