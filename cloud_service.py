"""
fly-print-cloud 云端服务集成模块
整合所有云端功能：认证、注册、心跳、WebSocket等
"""

import time
import threading
from typing import Dict, Any, Optional
from cloud_auth import CloudAuthClient
from cloud_api_client import CloudAPIClient
from cloud_websocket_client import CloudWebSocketClient, PrintJobHandler
from cloud_heartbeat_service import HeartbeatService
from edge_node_info import EdgeNodeInfo


class CloudService:
    """云端服务管理器"""
    
    def __init__(self, config: Dict[str, Any], printer_manager=None):
        self.config = config
        self.printer_manager = printer_manager
        self.enabled = config.get("enabled", False)
        
        # 初始化各个组件
        self.auth_client = None
        self.api_client = None
        self.websocket_client = None
        self.heartbeat_service = None
        self.print_job_handler = None
        self.status_reporter = None
        
        # 状态跟踪
        self.registered = False
        self.node_id = None
        
        if self.enabled:
            self._initialize_components()
    
    def _initialize_components(self):
        """初始化云端服务组件"""
        try:
            print("🌐 [DEBUG] 初始化云端服务组件...")
            
            # 初始化认证客户端
            self.auth_client = CloudAuthClient(
                auth_url=self.config["auth_url"],
                client_id=self.config["client_id"],
                client_secret=self.config["client_secret"]
            )
            
            # 初始化API客户端
            self.api_client = CloudAPIClient(
                base_url=self.config["base_url"],
                auth_client=self.auth_client
            )
            
            # 初始化心跳服务
            heartbeat_interval = self.config.get("heartbeat_interval", 30)
            self.heartbeat_service = HeartbeatService(
                api_client=self.api_client,
                interval=heartbeat_interval
            )
            
            # 初始化打印任务处理器
            if self.printer_manager:
                self.print_job_handler = PrintJobHandler(
                    printer_manager=self.printer_manager,
                    api_client=self.api_client,
                    websocket_client=self.websocket_client,
                    auth_client=self.auth_client,
                    node_id=self.node_id
                )
            
            print("✅ [DEBUG] 云端服务组件初始化完成")
            
        except Exception as e:
            print(f"❌ [DEBUG] 云端服务组件初始化失败: {e}")
            self.enabled = False
    
    def start(self) -> Dict[str, Any]:
        """启动云端服务"""
        if not self.enabled:
            return {"success": False, "message": "云端服务未启用"}
        
        try:
            print("🚀 [DEBUG] 启动云端服务...")
            
            # 1. 如果启用自动注册，先注册边缘节点
            if self.config.get("auto_register", True):
                register_result = self._register_node()
                if not register_result["success"]:
                    return register_result
            
            # 2. 启动心跳服务
            self.heartbeat_service.start()
            
            # 3. 如果启用自动注册打印机，注册当前管理的打印机
            if self.config.get("auto_register_printers", True) and self.printer_manager:
                self._register_current_printers()
            
            # 4. 启动WebSocket客户端
            self._start_websocket()
            
            # 5. 启动状态上报服务
            if self.websocket_client and self.node_id:
                self.status_reporter = PrinterStatusReporter(
                    self.websocket_client, self.printer_manager, self.node_id
                )
                self.status_reporter.start()
                print("✅ [DEBUG] 打印机状态上报服务已启动")
            
            print("✅ [DEBUG] 云端服务启动成功")
            return {"success": True, "message": "云端服务启动成功", "node_id": self.node_id}
            
        except Exception as e:
            print(f"❌ [DEBUG] 云端服务启动失败: {e}")
            return {"success": False, "message": str(e)}
    
    def stop(self):
        """停止云端服务"""
        print("🛑 [DEBUG] 停止云端服务...")
        
        if self.websocket_client:
            self.websocket_client.stop()
        
        if self.heartbeat_service:
            self.heartbeat_service.stop()
        
        if self.status_reporter:
            self.status_reporter.stop()
        
        self.registered = False
        print("✅ [DEBUG] 云端服务已停止")
    
    def _register_node(self) -> Dict[str, Any]:
        """注册边缘节点"""
        try:
            print("📝 [DEBUG] 注册边缘节点...")
            
            node_name = self.config.get("node_name") or None
            location = self.config.get("location") or None
            
            result = self.api_client.register_edge_node(node_name, location)
            
            if result["success"]:
                self.registered = True
                self.node_id = result["node_id"]
                
                # 更新PrintJobHandler的node_id
                if self.print_job_handler:
                    self.print_job_handler.node_id = self.node_id
                    
                print(f"✅ [DEBUG] 边缘节点注册成功: {self.node_id}")
                return {"success": True, "node_id": self.node_id}
            else:
                print(f"❌ [DEBUG] 边缘节点注册失败: {result.get('error')}")
                return {"success": False, "message": result.get("error")}
                
        except Exception as e:
            print(f"❌ [DEBUG] 边缘节点注册异常: {e}")
            return {"success": False, "message": str(e)}
    
    def _register_current_printers(self):
        """注册当前管理的打印机"""
        try:
            if not self.printer_manager:
                return
            
            print("🖨️ [DEBUG] 注册当前管理的打印机...")
            
            # 获取当前管理的打印机
            managed_printers = self.printer_manager.config.get_managed_printers()
            
            if not managed_printers:
                print("📝 [DEBUG] 没有管理的打印机需要注册")
                return
            
            # 获取打印机详细信息
            printer_data = []
            for printer in managed_printers:
                printer_name = printer.get("name")
                if printer_name:
                    # 获取打印机状态、能力和端口信息
                    status = self.printer_manager.get_printer_status(printer_name)
                    capabilities = self.printer_manager.get_printer_capabilities(printer_name)
                    port_info = self.printer_manager.get_printer_port_info(printer_name)
                    
                    # 转换capabilities为云端格式
                    raw_capabilities = capabilities
                    cloud_capabilities = {
                        "paper_sizes": raw_capabilities.get("page_size", ["A4"])[:10],  # 限制数量
                        "color_support": "RGB" in str(raw_capabilities.get("color_model", [])) or "Color" in str(raw_capabilities.get("color_model", [])),
                        "duplex_support": any(d != "None" for d in raw_capabilities.get("duplex", ["None"])),
                        "resolution": self._get_resolution_string(raw_capabilities.get("resolution", ["600dpi"])),
                        "print_speed": "unknown",
                        "media_types": raw_capabilities.get("media_type", ["Plain"])[:8]  # 限制数量
                    }
                    
                    printer_info = {
                        "name": printer_name,
                        "model": printer.get("make_model", ""),
                        "serial_number": "",
                        "firmware_version": "",
                        "port_info": port_info,
                        "ip_address": None,
                        "mac_address": "",
                        "capabilities": cloud_capabilities
                    }
                    printer_data.append(printer_info)
            
            # 注册到云端
            result = self.api_client.register_printers(printer_data)
            
            if result["success"]:
                print(f"✅ [DEBUG] 打印机注册成功，数量: {len(printer_data)}")
                
                # 更新本地打印机ID
                registered_printers = result.get("registered_printers", {})
                if registered_printers and self.printer_manager:
                    print(f"🔄 [DEBUG] 同步云端打印机ID到本地配置...")
                    update_count = 0
                    for name, cloud_id in registered_printers.items():
                        if self.printer_manager.config.update_printer_id(name, cloud_id):
                            update_count += 1
                    
                    if update_count > 0:
                        print(f"✅ [DEBUG] 已更新 {update_count} 个打印机的云端ID")
            else:
                print(f"❌ [DEBUG] 打印机注册失败: {result.get('error')}")
                
        except Exception as e:
            print(f"❌ [DEBUG] 注册打印机异常: {e}")
    
    def _start_websocket(self):
        """启动WebSocket客户端"""
        try:
            if not self.registered:
                print("⚠️ [DEBUG] 节点未注册，跳过WebSocket连接")
                return
            
            print("🔌 [DEBUG] 启动WebSocket客户端...")
            
            # 获取WebSocket URL
            ws_url = self.api_client.get_websocket_url()
            if not ws_url:
                print("❌ [DEBUG] 无法获取WebSocket URL")
                return
            
            # 初始化WebSocket客户端
            self.websocket_client = CloudWebSocketClient(ws_url, self.auth_client)
            
            # 更新PrintJobHandler的WebSocket客户端引用
            if self.print_job_handler:
                self.print_job_handler.websocket_client = self.websocket_client
                self.websocket_client.add_message_handler("print_job", self.print_job_handler.handle_print_job)
            
            # 添加预览文件消息处理器
            if self.print_job_handler:
                self.websocket_client.add_message_handler("preview_file", self.print_job_handler.handle_preview_file)
            
            # 启动WebSocket客户端
            self.websocket_client.start()
            
            # 应用待处理的监听器
            if hasattr(self, 'pending_listeners'):
                for msg_type, handler in self.pending_listeners:
                    self.websocket_client.add_message_handler(msg_type, handler)
                self.pending_listeners = []
            
            print("✅ [DEBUG] WebSocket客户端启动成功")
            
        except Exception as e:
            print(f"❌ [DEBUG] WebSocket客户端启动失败: {e}")
    
    def add_message_listener(self, message_type: str, handler):
        """添加消息监听器"""
        print(f"➕ [DEBUG] CloudService添加消息监听器: {message_type}")
        if self.websocket_client:
            print(f"  ↳ 直接添加到WebSocket客户端")
            self.websocket_client.add_message_handler(message_type, handler)
        else:
            # 如果WebSocket未初始化，先保存
            print(f"  ↳ WebSocket未就绪，加入待处理列表")
            if not hasattr(self, 'pending_listeners'):
                self.pending_listeners = []
            self.pending_listeners.append((message_type, handler))

    def submit_print_params(self, task_token: str, options: Dict[str, Any]):
        """提交打印参数"""
        if self.websocket_client:
            self.websocket_client.submit_print_params(task_token, options)
        else:
            print("⚠️ [DEBUG] WebSocket未连接，无法提交打印参数")

    def get_status(self) -> Dict[str, Any]:
        """获取云端服务状态"""
        status = {
            "enabled": self.enabled,
            "registered": self.registered,
            "node_id": self.node_id,
            "heartbeat": None,
            "websocket": None
        }
        
        if self.heartbeat_service:
            status["heartbeat"] = self.heartbeat_service.get_status()
        
        if self.websocket_client:
            status["websocket"] = {
                "running": self.websocket_client.running,
                "url": self.websocket_client.websocket_url
            }
        
        return status
    
    def force_heartbeat(self) -> Dict[str, Any]:
        """强制发送心跳"""
        if not self.heartbeat_service:
            return {"success": False, "message": "心跳服务未启动"}
        
        return self.heartbeat_service.force_heartbeat()
    
    def register_printer(self, printer_info: Dict[str, Any]) -> Dict[str, Any]:
        """注册单个打印机到云端"""
        if not self.registered:
            return {"success": False, "message": "节点未注册"}
        
        try:
            # 获取打印机详细信息
            printer_name = printer_info.get("name")
            if not printer_name:
                return {"success": False, "message": "打印机名称不能为空"}
            
            # 获取打印机状态和能力
            status = self.printer_manager.get_printer_status(printer_name)
            capabilities = self.printer_manager.get_printer_capabilities(printer_name)
            
            enhanced_info = {
                **printer_info,
                "status": status,
                "capabilities": capabilities
            }
            
            result = self.api_client.register_printers([enhanced_info])
            return result
            
        except Exception as e:
            print(f"❌ [DEBUG] 注册打印机异常: {e}")
            return {"success": False, "message": str(e)}

    def register_managed_printer(self, managed_printer: Dict[str, Any]) -> Dict[str, Any]:
        if not self.registered or not self.printer_manager:
            return {"success": False, "message": "服务未就绪"}
        try:
            printer_name = managed_printer.get("name")
            if not printer_name:
                return {"success": False, "message": "打印机名称不能为空"}
            raw_capabilities = self.printer_manager.get_printer_capabilities(printer_name)
            port_info = self.printer_manager.get_printer_port_info(printer_name)
            cloud_capabilities = {
                "paper_sizes": raw_capabilities.get("page_size", ["A4"])[:10],
                "color_support": "RGB" in str(raw_capabilities.get("color_model", [])) or "Color" in str(raw_capabilities.get("color_model", [])),
                "duplex_support": any(d != "None" for d in raw_capabilities.get("duplex", ["None"])),
                "resolution": self._get_resolution_string(raw_capabilities.get("resolution", ["600dpi"])),
                "print_speed": "unknown",
                "media_types": raw_capabilities.get("media_type", ["Plain"])[:8]
            }
            printer_info = {
                "name": printer_name,
                "model": managed_printer.get("make_model", ""),
                "serial_number": "",
                "firmware_version": "",
                "port_info": port_info,
                "ip_address": None,
                "mac_address": "",
                "capabilities": cloud_capabilities
            }
            result = self.api_client.register_printers([printer_info])
            if result.get("success"):
                registered_printers = result.get("registered_printers", {})
                cloud_id = registered_printers.get(printer_name)
                if cloud_id:
                    self.printer_manager.config.update_printer_id(printer_name, cloud_id)
            return result
        except Exception as e:
            print(f"❌ [DEBUG] 注册打印机异常: {e}")
            return {"success": False, "message": str(e)}

    def delete_printer_from_cloud(self, printer_id: str) -> Dict[str, Any]:
        if not self.registered or not self.api_client:
            return {"success": False, "message": "服务未就绪"}
        return self.api_client.delete_printer(printer_id)
    
    def update_printer_status(self, printer_name: str) -> Dict[str, Any]:
        """更新打印机状态到云端"""
        if not self.registered or not self.printer_manager:
            return {"success": False, "message": "服务未就绪"}
        
        try:
            # 获取打印机状态和队列信息
            status = self.printer_manager.get_printer_status(printer_name)
            queue = self.printer_manager.get_print_queue(printer_name)
            job_count = len(queue) if queue else 0
            
            return self.api_client.update_printer_status(printer_name, status, job_count)
            
        except Exception as e:
            print(f"❌ [DEBUG] 更新打印机状态异常: {e}")
            return {"success": False, "message": str(e)}
    
    def _get_resolution_string(self, resolution_list):
        """从分辨率列表中提取标准格式的分辨率字符串"""
        if not resolution_list:
            return "600dpi"
        
        res = resolution_list[0]
        if "dpi" in res.lower():
            return res
        elif res.lower() in ["fast", "normal", "best"]:
            resolution_map = {"fast": "300dpi", "normal": "600dpi", "best": "1200dpi"}
            return resolution_map.get(res.lower(), "600dpi")
        else:
            return "600dpi"


class PrinterStatusReporter:
    """打印机状态上报器"""
    
    def __init__(self, websocket_client, printer_manager, node_id):
        self.websocket_client = websocket_client
        self.printer_manager = printer_manager
        self.node_id = node_id
        self.last_status = {}  # 缓存上次状态
        self.running = False
        self.thread = None
        self.check_interval = 30  # 30秒检查一次
    
    def start(self):
        """启动状态上报服务"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        print("📊 [DEBUG] 打印机状态上报服务已启动")
    
    def stop(self):
        """停止状态上报服务"""
        self.running = False
        print("🛑 [DEBUG] 打印机状态上报服务已停止")
    
    def _monitor_loop(self):
        """状态监控循环"""
        while self.running:
            try:
                self._check_and_report_status()
                time.sleep(self.check_interval)
            except Exception as e:
                print(f"❌ [DEBUG] 状态监控异常: {e}")
                time.sleep(5)  # 出错后短暂等待
    
    def _check_and_report_status(self):
        """检查并上报状态变化"""
        if not self.printer_manager:
            return
        
        try:
            managed_printers = self.printer_manager.config.get_managed_printers()
            
            for printer in managed_printers:
                printer_name = printer.get("name")
                printer_id = printer.get("id")
                if not printer_name:
                    continue
                
                # 获取当前状态
                current_status = self.printer_manager.get_printer_status(printer_name)
                queue_jobs = self.printer_manager.get_print_queue(printer_name)
                
                current_queue_length = len(queue_jobs)
                error_code = None
                
                # 转换状态为云端格式
                cloud_status = self._convert_status_to_cloud_format(current_status)
                
                # 检查是否有变化
                last_status_key = printer_id or printer_name
                last_info = self.last_status.get(last_status_key, {})
                if (last_info.get("status") != cloud_status or 
                    last_info.get("queue_length") != current_queue_length):
                    
                    # 发送状态更新
                    sent = self.websocket_client.send_printer_status(
                        self.node_id, printer_id or printer_name, cloud_status, 
                        current_queue_length, error_code
                    )
                    
                    if sent:
                        # 更新缓存
                        self.last_status[last_status_key] = {
                            "status": cloud_status,
                            "queue_length": current_queue_length
                        }
                        
                        print(f"📊 [DEBUG] 上报打印机状态: {printer_id or printer_name} -> {cloud_status}, 队列: {current_queue_length}")
                    else:
                        print(f"⚠️ [WARNING] 打印机状态发送失败，跳过缓存更新: {printer_id or printer_name}")
                    
        except Exception as e:
            print(f"❌ [DEBUG] 检查打印机状态异常: {e}")
    
    def _convert_status_to_cloud_format(self, cups_status: str) -> str:
        """转换CUPS状态为云端标准格式: ready/printing/error/offline"""
        status_map = {
            # 英文状态
            "idle": "ready",
            "processing": "printing", 
            "stopped": "error",
            "unknown": "offline",
            # 中文状态
            "在线": "ready",
            "空闲": "ready", 
            "就绪": "ready",
            "准备就绪": "ready",
            "省电模式": "ready",
            "打印中": "printing",
            "正在打印": "printing",
            "离线": "offline",
            "停止": "error",
            "已禁用": "error",
            "错误": "error",
            "缺纸": "error",
            "门开": "error",
            "用户干预": "error",
            "未知": "offline",
            "未知状态": "offline"
        }
        return status_map.get(cups_status, "offline")
