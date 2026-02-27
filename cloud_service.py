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
        # 如果配置中已经缓存了 node_id，则认为节点已经注册过，避免重复注册
        self.node_id = config.get("node_id")
        self.registered = bool(self.node_id)
        
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
            # 如果本地已缓存 node_id，则同步到 API 客户端，避免重复注册
            if self.node_id:
                self.api_client.node_id = self.node_id
            
            # 心跳服务稍后初始化（需要等待WebSocket和node_id）
            self.heartbeat_interval = self.config.get("heartbeat_interval", 30)
            
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
            
            # 1. 如果启用自动注册，且本地尚未有 node_id，则注册边缘节点
            if self.config.get("auto_register", True) and not self.registered:
                register_result = self._register_node()
                if not register_result["success"]:
                    return register_result
            
            # 2. 启动WebSocket客户端（心跳服务需要它）
            self._start_websocket()
            
            # 3. 初始化并启动心跳服务（需要WebSocket和node_id）
            if self.websocket_client and self.node_id:
                self.heartbeat_service = HeartbeatService(
                    websocket_client=self.websocket_client,
                    node_id=self.node_id,
                    interval=self.heartbeat_interval,
                    base_url=self.config.get("base_url")
                )
                self.heartbeat_service.start()
                print("💓 [DEBUG] 心跳服务已启动 (WebSocket模式)")
            else:
                print("⚠️ [WARNING] WebSocket未就绪，跳过心跳服务启动")
            
            # 4. 启动时不再自动注册打印机，注册逻辑由管理端显式触发
            
            # 5. 启动状态上报服务
            if self.websocket_client and self.node_id:
                self.status_reporter = PrinterStatusReporter(
                    self.websocket_client, self.printer_manager, self.node_id, self.api_client
                )
                self.status_reporter.start()
                # 将status_reporter传递给PrintJobHandler
                if self.print_job_handler:
                    self.print_job_handler.status_reporter = self.status_reporter
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
                
                # 将 node_id 缓存到配置，避免重复注册
                try:
                    self.config["node_id"] = self.node_id
                    if self.printer_manager and hasattr(self.printer_manager, "config"):
                        cloud_cfg = self.printer_manager.config.config.get("cloud", {})
                        cloud_cfg["node_id"] = self.node_id
                        self.printer_manager.config.save_config()
                except Exception as e:
                    print(f"⚠️ [DEBUG] 缓存 node_id 到配置失败: {e}")
                
                # 更新PrintJobHandler的node_id
                if self.print_job_handler:
                    self.print_job_handler.node_id = self.node_id
                
                # 同步到 API 客户端
                if self.api_client:
                    self.api_client.node_id = self.node_id
                    
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
            
            # 获取打印机详细信息，仅为未在云端注册的打印机构造注册数据
            printer_data = []
            for printer in managed_printers:
                printer_name = printer.get("name")
                if not printer_name:
                    continue
                
                # 如果本地标记已经注册到云端，则跳过
                if printer.get("cloud_registered"):
                    print(f"🔁 [DEBUG] 打印机 {printer_name} 已标记为云端注册，跳过")
                    continue
                
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
            
            if not printer_data:
                print("📝 [DEBUG] 没有需要新注册的打印机，全部已在云端")
                return
            
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
            
            # 注册核心业务处理器（由 PrintJobHandler 处理云端下行指令）
            if self.print_job_handler:
                self.print_job_handler.websocket_client = self.websocket_client
                self.websocket_client.add_message_handler("print_job", self.print_job_handler.handle_print_job)
            
            # 添加预览文件业务处理器
            if self.print_job_handler:
                self.websocket_client.add_message_handler("preview_file", self.print_job_handler.handle_preview_file)
            
            # 添加错误消息业务处理器
            if self.print_job_handler:
                self.websocket_client.add_message_handler("error", self.print_job_handler.handle_error_message)
            
            # 添加上传凭证响应处理器
            if self.print_job_handler:
                self.websocket_client.add_message_handler("upload_token", self.print_job_handler.handle_upload_token)
            
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

    def submit_print_params(self, file_id: str, printer_id: str, options: Dict[str, Any]):
        """提交打印参数
        
        Args:
            file_id: 已上传的文件ID
            printer_id: 目标打印机ID
            options: 打印参数
        """
        if self.websocket_client and self.node_id:
            self.websocket_client.submit_print_params(self.node_id, file_id, printer_id, options)
        else:
            print("⚠️ [DEBUG] WebSocket未连接或节点未注册，无法提交打印参数")

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
                "connected": self.websocket_client.connected,  # 使用真实连接状态
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
            
            # 检查批量注册结果
            if result.get("success"):
                # 即使 success=True，也要检查是否有失败的打印机
                failed_printers = result.get("failed_printers", [])
                if failed_printers:
                    # 找到当前打印机的错误信息
                    error_info = None
                    for failed in failed_printers:
                        if failed.get("name") == printer_name:
                            error_info = failed.get("error", "")
                            break
                    
                    if error_info:
                        # 尝试解析 JSON 错误信息
                        try:
                            import json
                            error_json = json.loads(error_info)
                            error_message = error_json.get("message") or error_json.get("error") or error_info
                        except:
                            error_message = error_info
                        
                        return {"success": False, "message": error_message, "error": error_message}
                
                # 注册成功，更新本地 ID
                registered_printers = result.get("registered_printers", {})
                cloud_id = registered_printers.get(printer_name)
                if cloud_id:
                    self.printer_manager.config.update_printer_id(printer_name, cloud_id)
                    return {"success": True, "cloud_id": cloud_id}
                else:
                    # 没有获取到 cloud_id，表示注册失败
                    return {"success": False, "message": "未获取到云端打印机ID"}
            else:
                # 批量注册操作本身失败
                return {"success": False, "message": result.get("error") or "注册失败"}
            
        except Exception as e:
            print(f"❌ [DEBUG] 注册打印机异常: {e}")
            return {"success": False, "message": str(e)}

    def delete_printer_from_cloud(self, printer_id: str) -> Dict[str, Any]:
        if not self.registered or not self.api_client:
            return {"success": False, "message": "服务未就绪"}
        return self.api_client.delete_printer(printer_id)
    
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
    """打印机状态上报器 - 使用批量HTTP接口上报"""
    
    def __init__(self, websocket_client, printer_manager, node_id, api_client=None):
        self.websocket_client = websocket_client
        self.printer_manager = printer_manager
        self.node_id = node_id
        self.api_client = api_client  # 用于批量HTTP上报
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
    
    def force_report_printer(self, printer_id: str = None, printer_name: str = None):
        """立即上报指定打印机的状态（用于打印任务开始/结束时）
        
        Args:
            printer_id: 打印机ID（优先使用）
            printer_name: 打印机名称（作为备选）
        """
        if not self.printer_manager or not self.api_client:
            return
        
        try:
            managed_printers = self.printer_manager.config.get_managed_printers()
            
            # 查找目标打印机
            target_printer = None
            for printer in managed_printers:
                if printer_id and printer.get("id") == printer_id:
                    target_printer = printer
                    break
                elif printer_name and printer.get("name") == printer_name:
                    target_printer = printer
                    break
            
            if not target_printer:
                print(f"⚠️ [DEBUG] 未找到打印机: id={printer_id}, name={printer_name}")
                return
            
            p_id = target_printer.get("id")
            p_name = target_printer.get("name")
            
            # 获取当前状态
            current_status = self.printer_manager.get_printer_status(p_name)
            queue_jobs = self.printer_manager.get_print_queue(p_name)
            current_queue_length = len(queue_jobs) if queue_jobs else 0
            cloud_status = self._convert_status_to_cloud_format(current_status)
            
            # 立即上报（不检查缓存）
            printers_to_report = [{
                "printer_id": p_id,
                "status": cloud_status,
                "queue_length": current_queue_length
            }]
            
            result = self.api_client.batch_update_printer_status(printers_to_report)
            
            if result.get("success"):
                # 更新缓存
                self.last_status[p_id] = {
                    "status": cloud_status,
                    "queue_length": current_queue_length
                }
                print(f"📊 [DEBUG] 立即上报打印机状态成功: {p_name} ({cloud_status})")
            else:
                print(f"⚠️ [WARNING] 立即上报打印机状态失败: {result.get('error')}")
                
        except Exception as e:
            print(f"❌ [DEBUG] 立即上报打印机状态异常: {e}")
    
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
        """检查并批量上报状态变化"""
        if not self.printer_manager:
            return
        
        try:
            managed_printers = self.printer_manager.config.get_managed_printers()
            
            # 收集需要上报的打印机状态
            printers_to_report = []
            
            for printer in managed_printers:
                printer_name = printer.get("name")
                printer_id = printer.get("id")
                if not printer_name or not printer_id:
                    continue
                
                # 获取当前状态
                current_status = self.printer_manager.get_printer_status(printer_name)
                queue_jobs = self.printer_manager.get_print_queue(printer_name)
                
                current_queue_length = len(queue_jobs) if queue_jobs else 0
                
                # 转换状态为云端格式
                cloud_status = self._convert_status_to_cloud_format(current_status)
                
                # 检查是否有变化
                last_info = self.last_status.get(printer_id, {})
                if (last_info.get("status") != cloud_status or 
                    last_info.get("queue_length") != current_queue_length):
                    
                    printers_to_report.append({
                        "printer_id": printer_id,
                        "status": cloud_status,
                        "queue_length": current_queue_length
                    })
            
            # 批量上报（如果有变化）
            if printers_to_report and self.api_client:
                result = self.api_client.batch_update_printer_status(printers_to_report)
                
                if result.get("success"):
                    # 更新缓存
                    for printer_status in printers_to_report:
                        self.last_status[printer_status["printer_id"]] = {
                            "status": printer_status["status"],
                            "queue_length": printer_status["queue_length"]
                        }
                    print(f"📊 [DEBUG] 批量状态上报成功: {len(printers_to_report)} 个打印机")
                else:
                    print(f"⚠️ [WARNING] 批量状态上报失败: {result.get('error')}")
                    
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
