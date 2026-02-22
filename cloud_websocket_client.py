"""
fly-print-cloud WebSocket客户端
接收云端打印任务和实时消息
"""

import asyncio
import websockets
import json
import threading
import time
from typing import Dict, Any, Callable, Optional
from cloud_auth import CloudAuthClient


class CloudWebSocketClient:
    """云端WebSocket客户端"""
    
    def __init__(self, websocket_url: str, auth_client: CloudAuthClient):
        self.websocket_url = websocket_url
        self.auth_client = auth_client
        self.websocket = None
        self.running = False
        self.thread = None
        self.message_handlers = {}
        self.reconnect_interval = 5  # 重连间隔秒数
        
    def add_message_handler(self, message_type: str, handler: Callable[[Dict[str, Any]], None]):
        """添加消息处理器"""
        self.message_handlers[message_type] = handler
        print(f"📝 [DEBUG] 添加WebSocket消息处理器: {message_type}")
    
    def start(self):
        """启动WebSocket客户端"""
        if self.running:
            print("⚠️ [DEBUG] WebSocket客户端已经在运行")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        print("🚀 [DEBUG] WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        # 不直接关闭WebSocket连接，让异步循环自然结束
        # WebSocket连接会在_connect_and_listen循环结束时自动关闭
        print("🛑 [DEBUG] WebSocket客户端已停止")
    
    def _run_async_loop(self):
        """在单独线程中运行异步循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            print(f"❌ [DEBUG] WebSocket异步循环异常: {e}")
        finally:
            loop.close()
    
    async def _connect_and_listen(self):
        """连接WebSocket并监听消息"""
        while self.running:
            try:
                print(f"🔌 [DEBUG] 连接WebSocket: {self.websocket_url}")
                
                # 获取认证头
                token = self.auth_client.get_access_token()
                if not token:
                    print("❌ [DEBUG] 无法获取access token，等待重试")
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
                    print("✅ [DEBUG] WebSocket连接成功")
                    
                    # 监听消息
                    print("👂 [DEBUG] 开始监听WebSocket消息...")
                    async for message in websocket:
                        try:
                            print(f"📨 [DEBUG] 收到WebSocket消息: {message}")
                            await self._handle_message(message)
                        except Exception as e:
                            print(f"❌ [DEBUG] 处理WebSocket消息异常: {e}")
                            
            except websockets.exceptions.ConnectionClosed as e:
                print(f"🔌 [DEBUG] WebSocket连接关闭: {e}")
            except Exception as e:
                print(f"❌ [DEBUG] WebSocket连接异常: {e}")
            
            if self.running:
                print(f"🔄 [DEBUG] {self.reconnect_interval}秒后重连WebSocket")
                await asyncio.sleep(self.reconnect_interval)
    
    async def _handle_message(self, message: str):
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            message_type = data.get("type", "unknown")
            
            print(f"📨 [DEBUG] 收到WebSocket消息: {message_type}")
            
            # 调用对应的消息处理器
            if message_type in self.message_handlers:
                handler = self.message_handlers[message_type]
                # 在线程池中执行处理器，避免阻塞WebSocket
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, handler, data)
            else:
                print(f"⚠️ [DEBUG] 未找到消息类型处理器: {message_type}")
                
        except json.JSONDecodeError as e:
            print(f"❌ [DEBUG] WebSocket消息JSON解析失败: {e}")
        except Exception as e:
            print(f"❌ [DEBUG] 处理WebSocket消息异常: {e}")
    
    async def _send_message(self, data: Dict[str, Any]):
        """发送消息到WebSocket"""
        if self.websocket:
            try:
                message = json.dumps(data)
                await self.websocket.send(message)
                print(f"📤 [DEBUG] 发送WebSocket消息: {data.get('type', 'unknown')}")
            except Exception as e:
                print(f"❌ [DEBUG] 发送WebSocket消息失败: {e}")
    
    def send_message_sync(self, data: Dict[str, Any]):
        """同步发送消息（在其他线程中调用）"""
        if self.websocket:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._send_message(data))
                loop.close()
            except Exception as e:
                print(f"❌ [DEBUG] 同步发送WebSocket消息失败: {e}")
    
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

            print(f"👀 [DEBUG] 收到文件预览请求:")
            print(f"  文件名: {file_name}")
            print(f"  文件URL: {file_url}")
            print(f"  TaskToken: {task_token}")

            if not all([file_url, task_token, file_id]):
                print("❌ [DEBUG] 预览请求参数不完整")
                return

            # 暂时仅打印URL，不下载
            print(f"🔗 [PREVIEW LINK] {file_url}")
            
            # 自动触发提交打印参数（模拟用户点击打印）
            # 在实际UI中，这里应该等待用户操作
            # 为了测试流程，这里使用定时器延时触发
            threading.Timer(2.0, self._auto_submit_print_params, args=[file_id, task_token]).start()

        except Exception as e:
            print(f"❌ [DEBUG] 处理文件预览请求异常: {e}")

    def _auto_submit_print_params(self, file_id: str, task_token: str):
        """自动提交打印参数（测试用）"""
        try:
            print(f"🤖 [DEBUG] 自动提交打印参数 (FileID: {file_id})")
            
            # 获取默认打印机
            printers = self.printer_manager.get_printers()
            default_printer_id = None
            if printers:
                # 优先使用 printer_id (注册时生成的)，如果没有则 fallback 到 name (虽然不太可能)
                default_printer_id = printers[0].get('id', printers[0].get('name'))
            
            if not default_printer_id:
                print("❌ [DEBUG] 未找到可用打印机，无法提交打印参数")
                return

            print(f"🖨️ [DEBUG] 选择打印机ID: {default_printer_id}")

            payload = {
                "type": "submit_print_params",
                "node_id": self.node_id, # 补充 node_id
                "data": {
                    "task_token": task_token,
                    "file_id": file_id,
                    "printer_id": default_printer_id, 
                    "options": {
                        "copies": 1,
                        "color_mode": "color",
                        "paper_size": "A4"
                    }
                }
            }
            
            # 需要通过WebSocket发送
            if self.websocket_client:
                self.websocket_client.send_message_sync(payload)
                print(f"✅ [DEBUG] 打印参数已提交")
            else:
                print("❌ [DEBUG] WebSocket客户端未连接，无法提交参数")

        except Exception as e:
            print(f"❌ [DEBUG] 自动提交打印参数异常: {e}")

    def handle_print_job(self, message: Dict[str, Any]):
        """处理打印任务消息"""
        try:
            # 从WebSocket消息中提取实际的打印任务数据
            data = message.get("data", {})
            print(f"🔍 [DEBUG] 完整的WebSocket消息: {message}")
            print(f"🔍 [DEBUG] 提取的打印任务数据: {data}")
            
            job_id = data.get("job_id")
            printer_name = data.get("printer_name")
            file_url = data.get("file_url")
            job_name = data.get("name", f"CloudJob_{job_id}")  # 使用name字段作为任务名
            print_options = data.get("print_options", {})
            
            print(f"🖨️ [DEBUG] 处理云端打印任务:")
            print(f"  任务ID: {job_id}")
            print(f"  打印机: {printer_name}")
            print(f"  文件URL: {file_url}")
            print(f"  任务名称: {job_name}")
            
            if not all([job_id, printer_name, file_url]):
                print("❌ [DEBUG] 打印任务参数不完整")
                print(f"  job_id存在: {bool(job_id)}")
                print(f"  printer_name存在: {bool(printer_name)}")
                print(f"  file_url存在: {bool(file_url)}")
                return
            
            # 下载文件
            file_path = self._download_print_file(file_url, job_id)
            if not file_path:
                self._report_job_failure(job_id, "文件下载失败")
                return
            
            # 使用统一的打印任务提交方法（自动处理清理）
            result = self.printer_manager.submit_print_job_with_cleanup(
                printer_name, file_path, job_name, print_options, "云端WebSocket"
            )
            
            if result.get("success"):
                print(f"✅ [DEBUG] 云端打印任务提交成功: {job_id}")
                # 启动任务完成监控
                self._monitor_job_completion(job_id, printer_name, result.get("job_id"))
            else:
                error_msg = result.get("message", "未知错误")
                print(f"❌ [DEBUG] 云端打印任务提交失败: {error_msg}")
                self._report_job_failure(job_id, error_msg)
                
        except Exception as e:
            print(f"❌ [DEBUG] 处理云端打印任务异常: {e}")
            # 统一方法已经处理了异常清理
            self._report_job_failure(data.get("job_id"), str(e))
    
    def _download_print_file(self, file_url: str, job_id: str) -> Optional[str]:
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

            print(f"📥 [DEBUG] 下载打印文件: {file_url}")
            
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
                print(f"📊 [DEBUG] 响应内容: {response.text[:500]}")  # 打印前500字符的错误信息
            if response.status_code == 200:
                # 保存到临时文件
                temp_dir = tempfile.gettempdir()
                # 从URL路径中提取原始文件名，忽略查询参数
                from urllib.parse import urlparse
                parsed_url = urlparse(file_url)
                original_filename = os.path.basename(parsed_url.path)
                # 如果无法提取文件名，使用job_id作为备用
                if not original_filename or '.' not in original_filename:
                    original_filename = f"cloud_job_{job_id}.pdf"
                temp_file_path = os.path.join(temp_dir, original_filename)
                
                with open(temp_file_path, 'wb') as f:
                    f.write(response.content)
                
                print(f"✅ [DEBUG] 文件下载成功: {temp_file_path}")
                return temp_file_path
            else:
                print(f"❌ [DEBUG] 文件下载失败: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ [DEBUG] 下载打印文件异常: {e}")
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
                        print(f"✅ [DEBUG] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        return
                    elif job_status.get("status") in ["completed", "completed_or_failed"]:
                        print(f"✅ [DEBUG] 云端任务完成: {cloud_job_id}")
                        self._report_job_success(cloud_job_id)
                        return
                    else:
                        print(f"🔍 [DEBUG] 云端任务 {cloud_job_id} 仍在处理中，状态: {job_status.get('status', 'unknown')}")
                
                # 超时后报告成功（假设长时间运行的任务已完成）
                print(f"⏰ [DEBUG] 云端任务监控超时，假设已完成: {cloud_job_id}")
                self._report_job_success(cloud_job_id)
                
            except Exception as e:
                print(f"❌ [DEBUG] 监控云端任务完成异常: {e}")
                # 异常时也报告成功，避免任务一直处于分发状态
                self._report_job_success(cloud_job_id)
        
        # 在后台线程中监控
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
    
    def _report_job_success(self, job_id: str):
        """通过WebSocket报告任务成功"""
        if job_id:
            try:
                from datetime import datetime, timezone
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "job_id": job_id,
                        "status": "completed",
                        "progress": 100,
                        "error_message": None
                    }
                }
                # 通过现有的WebSocket连接发送
                print(f"🔍 [DEBUG] WebSocket客户端引用: {self.websocket_client}")
                if self.websocket_client:
                    print(f"🔍 [DEBUG] WebSocket运行状态: {self.websocket_client.running}")
                    self.websocket_client.send_message_sync(message)
                    print(f"✅ [DEBUG] 任务成功状态已通过WebSocket上报: {job_id}")
                else:
                    print(f"⚠️ [DEBUG] WebSocket连接不可用，无法上报任务状态: {job_id}")
            except Exception as e:
                print(f"❌ [DEBUG] 通过WebSocket报告任务成功异常: {e}")
    
    def _report_job_failure(self, job_id: str, error_message: str):
        """通过WebSocket报告任务失败"""
        if job_id:
            try:
                from datetime import datetime, timezone
                message = {
                    "type": "job_update",
                    "node_id": self.api_client.node_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "job_id": job_id,
                        "status": "failed",
                        "progress": 0,
                        "error_message": error_message
                    }
                }
                # 通过现有的WebSocket连接发送
                if self.websocket_client:
                    self.websocket_client.send_message_sync(message)
                    print(f"✅ [DEBUG] 任务失败状态已通过WebSocket上报: {job_id}")
                else:
                    print(f"⚠️ [DEBUG] WebSocket连接不可用，无法上报任务状态: {job_id}")
            except Exception as e:
                print(f"❌ [DEBUG] 通过WebSocket报告任务失败异常: {e}")
