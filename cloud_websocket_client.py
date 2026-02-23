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
            print(f"📝 [DEBUG] 添加WebSocket消息处理器: {message_type}")
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
                print(f"🔌 [WARNING] WebSocket连接关闭: {e}")
            except Exception as e:
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
    
    async def _send_message(self, data: Dict[str, Any]):
        """发送消息到WebSocket"""
        if self.websocket:
            try:
                message = json.dumps(data)
                await self.websocket.send(message)
                print(f"📤 [DEBUG] 发送WebSocket消息: {data.get('type', 'unknown')}")
            except Exception as e:
                print(f"❌ [ERROR] 发送WebSocket消息失败: {e}")

    async def send_message(self, data: Dict[str, Any]):
        """异步发送消息 (可从任何循环调用)"""
        if not self.loop or not self.loop.is_running():
            print("⚠️ [WARNING] WebSocket事件循环未运行，无法发送消息")
            return
            
        try:
            # 检查是否在同一个循环中
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
                
            if current_loop == self.loop:
                # 同一个循环，直接调用
                await self._send_message(data)
            else:
                # 不同循环，使用 run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
                # 等待结果（这里需要包装成 awaitable）
                await asyncio.wrap_future(future)
        except Exception as e:
            print(f"❌ [ERROR] 异步发送消息异常: {e}")

    def send_message_sync(self, data: Dict[str, Any]):
        """同步发送消息（在其他线程中调用）"""
        if not self.loop or not self.loop.is_running():
            print("⚠️ [WARNING] WebSocket事件循环未运行，无法发送消息")
            return
            
        try:
            # 使用 run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self._send_message(data), self.loop)
            
            # 等待结果，确保消息发送成功
            try:
                future.result(timeout=5)  # 等待5秒
            except asyncio.TimeoutError:
                print(f"❌ [ERROR] 同步发送WebSocket消息超时: {data.get('type')}")
            except Exception as e:
                print(f"❌ [ERROR] 同步发送WebSocket消息执行失败: {e}")
                
        except Exception as e:
            print(f"❌ [ERROR] 同步发送WebSocket消息失败: {e}")

    def submit_print_params(self, task_token: str, file_id: str, printer_id: str, options: Dict[str, Any]):
        """提交打印参数"""
        message = {
            "type": "submit_print_params",
            "data": {
                "task_token": task_token,
                "file_id": file_id,
                "printer_id": printer_id,
                "options": options
            }
        }
        self.send_message_sync(message)

    def send_printer_status(self, node_id: str, printer_id: str, status: str, queue_length: int, error_code: Optional[str] = None):
        """发送打印机状态消息"""
        from datetime import datetime, timezone
        message = {
            "type": "printer_status",
            "node_id": node_id,
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "data": {
                "printer_id": printer_id,
                "status": status,
                "queue_length": queue_length,
                "error_code": error_code,
                "supplies": {}
            }
        }
        self.send_message_sync(message)


class PrintJobHandler:
    """打印任务处理器"""
    
    def __init__(self, printer_manager, api_client, websocket_client=None, auth_client=None, node_id=None):
        self.printer_manager = printer_manager
        self.api_client = api_client
        self.websocket_client = websocket_client
        self.auth_client = auth_client
        self.node_id = node_id
    
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
            file_url = data.get("file_url")
            job_name = data.get("name", f"CloudJob_{job_id}")  # 使用name字段作为任务名
            print_options = data.get("print_options", {})
            
            print(f"🖨️ [INFO] 处理云端打印任务: {job_name} (ID: {job_id})")
            
            if not all([job_id, printer_name, file_url]):
                print("❌ [WARNING] 打印任务参数不完整")
                return
            
            # 下载文件
            file_path = self._download_print_file(file_url, job_id, job_name)
            if not file_path:
                self._report_job_failure(job_id, "文件下载失败")
                return
            
            # 使用统一的打印任务提交方法（自动处理清理）
            result = self.printer_manager.submit_print_job_with_cleanup(
                printer_name, file_path, job_name, print_options, "云端WebSocket"
            )
            
            if result.get("success"):
                print(f"✅ [INFO] 云端打印任务提交成功: {job_id}")
                # 启动任务完成监控
                self._monitor_job_completion(job_id, printer_name, result.get("job_id"))
            else:
                error_msg = result.get("message", "未知错误")
                print(f"❌ [ERROR] 云端打印任务提交失败: {error_msg}")
                self._report_job_failure(job_id, error_msg)
                
        except Exception as e:
            print(f"❌ [ERROR] 处理云端打印任务异常: {e}")
            # 统一方法已经处理了异常清理
            self._report_job_failure(data.get("job_id"), str(e))
    
    def _download_print_file(self, file_url: str, job_id: str, expected_filename: str = None) -> Optional[str]:
        """下载打印文件"""
        try:
            import requests
            import tempfile
            import os
            
            # 如果是相对路径，拼接完整URL
            if file_url and not file_url.startswith(('http://', 'https://')):
                if self.api_client and self.api_client.base_url:
                    file_url = f"{self.api_client.base_url.rstrip('/')}/{file_url.lstrip('/')}"
                    print(f"🔗 [DEBUG] 拼接完整文件URL: {file_url}")

            print(f"📥 [INFO] 下载打印文件: {file_url}")
            
            # S3签名URL不能带认证头，检查是否为签名URL
            headers = {}
            if 'X-Amz-Algorithm' in file_url and 'X-Amz-Signature' in file_url:
                # 这是S3签名URL，不需要认证头
                print(f"🔗 [DEBUG] 检测到S3签名URL，直接下载")
            else:
                # 普通URL需要认证头
                headers = self.api_client.auth_client.get_auth_headers()
                print(f"🔐 [DEBUG] 使用认证头下载文件")
            
            response = requests.get(file_url, headers=headers, timeout=30)
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
    
    def _monitor_job_completion(self, cloud_job_id: str, printer_name: str, local_job_id: str):
        """监控打印任务完成状态"""
        import threading
        import time
        
        def monitor():
            try:
                if not local_job_id:
                    # 如果没有本地job_id，延迟后直接报告成功（假设提交成功就是完成）
                    time.sleep(10)
                    self._report_job_success(cloud_job_id)
                    return
                
                max_wait_time = 600  # 最大等待10分钟
                check_interval = 10   # 每10秒检查一次
                waited_time = 0
                
                print(f"🔍 [DEBUG] 开始监控云端任务完成: {cloud_job_id} -> 本地任务: {local_job_id}")
                
                while waited_time < max_wait_time:
                    time.sleep(check_interval)
                    waited_time += check_interval
                    
                    # 检查任务状态
                    job_status = self.printer_manager.get_job_status(printer_name, local_job_id)
                    
                    # 如果任务不存在（完成或失败）或状态为完成，报告成功
                    if not job_status.get("exists", True):
                        print(f"✅ [INFO] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        return
                    elif job_status.get("status") in ["completed", "completed_or_failed"]:
                        print(f"✅ [INFO] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
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
                
            except Exception as e:
                print(f"❌ [ERROR] 监控云端任务完成异常: {e}")
                # 异常时也报告成功，避免任务一直处于分发状态
                self._report_job_success(cloud_job_id)
        
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
