"""
fly-print-cloud 云端服务集成模块
整合所有云端功能：认证、注册、心跳、WebSocket等
"""

import logging
import os
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from cloud_auth import CloudAuthClient
from cloud_api_client import CloudAPIClient
from cloud_websocket_client import CloudWebSocketClient, PrintJobHandler
from cloud_heartbeat_service import HeartbeatService
from edge_node_info import EdgeNodeInfo
from secure_credentials import protect_credentials, unprotect_credentials

logger = logging.getLogger(__name__)


class CloudService:
    """Cloud service coordinator."""

    def __init__(
        self,
        config: Dict[str, Any],
        printer_manager=None,
        interactive_job_binder=None,
    ):
        self.config = dict(config or {})
        self.printer_manager = printer_manager
        self.interactive_job_binder = interactive_job_binder

        self.auth_client = None
        self.api_client = None
        self.websocket_client = None
        self.heartbeat_service = None
        self.print_job_handler = None
        self.status_reporter = None
        self.last_error: Optional[str] = None
        self.node_missing_remote = False

        self.node_id = self.config.get("node_id")
        self.registered = bool(self.node_id)
        self.heartbeat_interval = self.config.get("heartbeat_interval", 30)
        self.pending_listeners = []

    @staticmethod
    def _cloud_port_info(port_info: Any) -> str:
        """Return the string value required by the cloud printer schema."""
        if isinstance(port_info, dict):
            return str(port_info.get("port") or "")
        return str(port_info or "")

    def _cloud_config_ready(self) -> tuple[bool, list[str]]:
        runtime = self._runtime_cloud_config()
        required_fields = ("base_url", "auth_url", "client_id", "client_secret")
        missing = [field for field in required_fields if not str(runtime.get(field) or "").strip()]
        return not missing, missing

    def _runtime_cloud_config(self) -> Dict[str, Any]:
        """Resolve the DPAPI bundle only in process memory."""
        runtime = dict(self.config)
        blob = str(runtime.get("credential_blob") or "")
        if not blob:
            return runtime
        try:
            runtime.update(unprotect_credentials(blob))
        except Exception as exc:
            self.last_error = f"unable to read protected cloud credentials: {exc}"
            return runtime
        runtime["auth_url"] = f"{str(runtime.get('base_url') or '').rstrip('/')}/auth/token"
        return runtime

    def has_stale_node_registration(self) -> bool:
        return self.node_missing_remote

    def _persist_node_id(self):
        if self.printer_manager and hasattr(self.printer_manager, "config"):
            cloud_cfg = self.printer_manager.config.config.get("cloud", {})
            if self.node_id:
                cloud_cfg["node_id"] = self.node_id
            else:
                cloud_cfg.pop("node_id", None)
            self.printer_manager.config.save_config()

    def _mark_remote_node_missing(self, detail: str):
        stale_node_id = self.node_id
        if not stale_node_id and self.node_missing_remote:
            return

        self.node_missing_remote = True
        self.last_error = f"remote node missing: {detail}"
        self.node_id = None
        self.registered = False
        self.config.pop("node_id", None)

        if self.api_client:
            self.api_client.node_id = None
        if self.print_job_handler:
            self.print_job_handler.node_id = None
        if self.heartbeat_service:
            self.heartbeat_service.stop()
            self.heartbeat_service = None
        if self.status_reporter:
            self.status_reporter.stop()
            self.status_reporter = None
        if self.websocket_client:
            self.websocket_client.running = False
            self.websocket_client.connected = False

        try:
            self._persist_node_id()
        except Exception as exc:
            logger.debug("Failed to persist cleared node_id", exc_info=True)

        logger.warning("Remote node missing; local node_id cleared: node_id=%s", stale_node_id)

    def _initialize_components(self):
        """Initialize cloud clients from the current configuration."""
        ready, missing_fields = self._cloud_config_ready()
        if not ready:
            self.last_error = f"missing cloud config: {', '.join(missing_fields)}"
            self.auth_client = None
            self.api_client = None
            self.websocket_client = None
            self.heartbeat_service = None
            self.print_job_handler = None
            self.status_reporter = None
            return {"success": False, "message": self.last_error}

        try:
            logger.debug("Initializing cloud service components")
            runtime = self._runtime_cloud_config()
            self.auth_client = CloudAuthClient(
                auth_url=runtime["auth_url"],
                client_id=runtime["client_id"],
                client_secret=runtime["client_secret"],
            )
            self.api_client = CloudAPIClient(
                base_url=runtime["base_url"],
                auth_client=self.auth_client,
            )
            self.api_client.edge_info = EdgeNodeInfo(
                self.config.get("node_name") or None,
                self.config.get("location") or None,
            )
            if self.node_id:
                self.api_client.node_id = self.node_id

            self.heartbeat_interval = self.config.get("heartbeat_interval", 30)

            if self.printer_manager:
                self.print_job_handler = PrintJobHandler(
                    printer_manager=self.printer_manager,
                    api_client=self.api_client,
                    websocket_client=self.websocket_client,
                    auth_client=self.auth_client,
                    node_id=self.node_id,
                    interactive_job_binder=self.interactive_job_binder,
                )

            self.last_error = None
            return {"success": True}
        except Exception as exc:
            logger.exception("Cloud service initialization failed")
            self.last_error = str(exc)
            return {"success": False, "message": str(exc)}

    def start(self) -> Dict[str, Any]:
        """Bring the cloud runtime online for the current node state."""
        try:
            logger.debug("Starting cloud service")

            if not self.auth_client or not self.api_client or not self.print_job_handler:
                init_result = self._initialize_components()
                if not init_result.get("success"):
                    return init_result

            if not self.registered or not self.node_id:
                self.last_error = "node registration required"
                return {
                    "success": True,
                    "message": "cloud configured, waiting for manual node registration",
                    "node_id": None,
                    "registered": False,
                    "connected": False,
                }

            if self.config.get("profile_pending"):
                profile = self.api_client.update_self_profile(
                    self.config.get("node_name") or None,
                    self.config.get("location") or None,
                )
                if not profile.get("success"):
                    self.last_error = profile.get("error") or "edge profile report failed"
                    return {"success": False, "message": self.last_error, "node_id": self.node_id}
                self.config["profile_pending"] = False
                if self.printer_manager and hasattr(self.printer_manager, "config"):
                    self.printer_manager.config.config.setdefault("cloud", {})["profile_pending"] = False
                    self.printer_manager.config.save_config()

            self._start_websocket()

            if self.websocket_client and self.node_id:
                if (
                    not self.heartbeat_service
                    or not self.heartbeat_service.running
                    or self.heartbeat_service.websocket_client is not self.websocket_client
                ):
                    if self.heartbeat_service and self.heartbeat_service.running:
                        self.heartbeat_service.stop()
                    self.heartbeat_service = HeartbeatService(
                        websocket_client=self.websocket_client,
                        node_id=self.node_id,
                        interval=self.heartbeat_interval,
                        base_url=self.config.get("base_url"),
                        config_repo=self.printer_manager.config if self.printer_manager else None,
                    )
                    self.heartbeat_service.start()
                    logger.debug("Heartbeat service started in websocket mode")
            else:
                logger.warning("WebSocket unavailable; skipping heartbeat startup")

            if self.websocket_client and self.node_id:
                if (
                    not self.status_reporter
                    or not self.status_reporter.running
                    or self.status_reporter.websocket_client is not self.websocket_client
                ):
                    if self.status_reporter and self.status_reporter.running:
                        self.status_reporter.stop()
                    self.status_reporter = PrinterStatusReporter(
                        self.websocket_client,
                        self.printer_manager,
                        self.node_id,
                        self.api_client,
                        node_missing_handler=self._mark_remote_node_missing,
                    )
                    self.status_reporter.start()
                    if self.print_job_handler:
                        self.print_job_handler.status_reporter = self.status_reporter
                    logger.debug("Printer status reporter started")

            self.last_error = None
            return {
                "success": True,
                "message": "cloud service started",
                "node_id": self.node_id,
                "registered": True,
                "connected": bool(self.websocket_client and self.websocket_client.connected),
            }
        except Exception as exc:
            logger.exception("Cloud service start failed")
            self.last_error = str(exc)
            return {"success": False, "message": str(exc)}

    def stop(self):
        """Stop active cloud runtime components."""
        logger.debug("Stopping cloud service")

        if self.heartbeat_service:
            self.heartbeat_service.stop()
            self.heartbeat_service = None

        if self.status_reporter:
            self.status_reporter.stop()
            self.status_reporter = None

        if self.websocket_client:
            self.websocket_client.stop()

        self.websocket_client = None
        self.registered = bool(self.node_id)

    def reconfigure(self, new_config: Dict[str, Any], preserve_node_id: bool = True) -> Dict[str, Any]:
        """Rebuild the runtime with updated cloud config."""
        old_node_id = self.node_id

        self.stop()
        self.config = dict(new_config or {})

        if preserve_node_id and old_node_id:
            self.config["node_id"] = old_node_id
            self.node_id = old_node_id
        else:
            self.node_id = self.config.get("node_id")
            if not self.node_id:
                self.node_missing_remote = False
        self.registered = bool(self.node_id)
        if self.registered:
            # Local name/location are Edge-owned facts. Re-report them before
            # reconnecting whenever an operator saves the management page.
            self.config["profile_pending"] = True

        self.auth_client = None
        self.api_client = None
        self.websocket_client = None
        self.heartbeat_service = None
        self.print_job_handler = None
        self.status_reporter = None

        init_result = self._initialize_components()
        if not init_result.get("success"):
            return {"success": False, "message": init_result.get("message"), "node_id": self.node_id}

        result = self.start()
        if result.get("success") and self.printer_manager and hasattr(self.printer_manager, "config"):
            cloud_cfg = self.printer_manager.config.config.get("cloud", {})
            cloud_cfg.update(self.config)
            if self.node_id:
                cloud_cfg["node_id"] = self.node_id
            self.printer_manager.config.save_config()
        return result

    def _register_current_printers(self):
        """注册当前管理的打印机"""
        try:
            if not self.printer_manager:
                return
            
            logger.debug("Registering managed printers")
            
            # 获取当前管理的打印机
            managed_printers = self.printer_manager.config.get_managed_printers()
            
            if not managed_printers:
                logger.debug("No managed printers need registration")
                return
            
            # 获取打印机详细信息，仅为未在云端注册的打印机构造注册数据
            printer_data = []
            for printer in managed_printers:
                printer_name = printer.get("name")
                if not printer_name:
                    continue
                
                # 如果本地标记已经注册到云端，则跳过
                if printer.get("cloud_registered"):
                    logger.debug("Skipping already cloud-registered printer: %s", printer_name)
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
                    "port_info": self._cloud_port_info(port_info),
                    "ip_address": None,
                    "mac_address": "",
                    "capabilities": cloud_capabilities
                }
                printer_data.append(printer_info)
            
            if not printer_data:
                logger.debug("No new managed printers need cloud registration")
                return
            
            # 注册到云端
            result = self.api_client.register_printers(printer_data)
            
            if result["success"]:
                logger.info("Managed printers registered: count=%s", len(printer_data))
                
                # 更新本地打印机ID
                registered_printers = result.get("registered_printers", {})
                if registered_printers and self.printer_manager:
                    logger.debug("Syncing cloud printer ids back to local config")
                    update_count = 0
                    for name, cloud_id in registered_printers.items():
                        if self.printer_manager.config.update_printer_id(name, cloud_id):
                            update_count += 1
                    
                    if update_count > 0:
                        logger.debug("Updated cloud printer ids in local config: count=%s", update_count)
            else:
                logger.warning("Managed printer registration failed: %s", result.get("error"))
                
        except Exception as e:
            logger.exception("Managed printer registration failed")
    
    def _start_websocket(self):
        """启动WebSocket客户端"""
        try:
            if not self.registered:
                logger.debug("Skipping websocket startup because node is not registered")
                return

            if self.websocket_client and self.websocket_client.running:
                logger.debug("WebSocket client already running; reusing existing connection")
                return
            
            logger.debug("Starting websocket client")
            
            # 获取WebSocket URL
            ws_url = self.api_client.get_websocket_url()
            if not ws_url:
                logger.warning("WebSocket URL unavailable")
                return
            
            # 初始化WebSocket客户端
            self.websocket_client = CloudWebSocketClient(
                ws_url,
                self.auth_client,
                node_missing_handler=self._mark_remote_node_missing,
                inbox_path=self._job_delivery_store_path(),
                node_id=self.node_id,
            )
            
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
            
            logger.debug("WebSocket client started")
            
        except Exception as e:
            logger.exception("WebSocket client start failed")

    def _job_delivery_store_path(self) -> str:
        """Keep the durable inbound and outbound delivery state under runtime."""
        config_file = getattr(getattr(self.printer_manager, "config", None), "config_file", "config.json")
        return str(Path(str(config_file)).parent / "runtime" / "edge_job_delivery.sqlite3")
    
    def add_message_listener(self, message_type: str, handler):
        """添加消息监听器"""
        logger.debug("Registering cloud message listener: %s", message_type)
        listener = (message_type, handler)
        if listener not in self.pending_listeners:
            self.pending_listeners.append(listener)

        if self.websocket_client:
            logger.debug("Attached listener directly to websocket client")
            self.websocket_client.add_message_handler(message_type, handler)
        else:
            logger.debug("Queued listener until websocket client is ready")

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
            logger.debug("Skipping print param submit because websocket or node is unavailable")

    def get_status(self) -> Dict[str, Any]:
        """Return current cloud runtime state."""
        configured, missing_fields = self._cloud_config_ready()
        status = {
            "configured": configured,
            "missing_fields": missing_fields,
            "registered": self.registered,
            "node_id": self.node_id,
            "node_missing_remote": self.node_missing_remote,
            "heartbeat": None,
            "websocket": None,
            "last_error": self.last_error,
        }

        if self.heartbeat_service:
            status["heartbeat"] = self.heartbeat_service.get_status()

        if self.websocket_client:
            status["websocket"] = {
                "running": self.websocket_client.running,
                "connected": self.websocket_client.connected,
                "url": self.websocket_client.websocket_url,
                "last_http_status": self.websocket_client.last_http_status,
                "last_error_message": self.websocket_client.last_error_message,
                "terminal_reports": self.websocket_client.terminal_report_summary(),
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
            logger.exception("Register printer failed")
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
                "color_support": bool(raw_capabilities.get("color_supported")),
                "duplex_support": bool(raw_capabilities.get("duplex_supported")),
                "resolution": self._get_resolution_string(raw_capabilities.get("resolution", ["600dpi"])),
                "print_speed": "unknown",
                "media_types": raw_capabilities.get("media_type", ["Plain"])[:8]
            }
            printer_info = {
                "name": printer_name,
                "model": managed_printer.get("make_model", ""),
                "serial_number": "",
                "firmware_version": "",
                "port_info": self._cloud_port_info(port_info),
                "ip_address": port_info.get("host") if isinstance(port_info, dict) else None,
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
            logger.exception("Register managed printer failed")
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

    def activate(self, base_url: str, activation_code: str) -> Dict[str, Any]:
        """Consume one Cloud-issued activation code and persist only DPAPI data."""
        base_url = str(base_url or "").strip().rstrip("/")
        activation_code = str(activation_code or "").strip()
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.netloc:
            return {"success": False, "message": "Cloud 地址必须是有效的 HTTP 地址"}
        if not activation_code:
            return {"success": False, "message": "请输入激活码"}
        try:
            health = requests.get(f"{base_url}/api/v1/health", timeout=10)
            if health.status_code >= 400:
                return {"success": False, "message": f"Cloud 健康检查失败: {health.status_code}"}
            response = requests.post(f"{base_url}/api/v1/edge/activate", json={"activation_code": activation_code}, timeout=10)
            if response.status_code not in (200, 201):
                return {"success": False, "message": "激活码无效、已过期或 Cloud 拒绝激活"}
            data = response.json().get("data") or {}
            node_id = str(data.get("node_id") or "")
            client_id = str(data.get("client_id") or "")
            client_secret = str(data.get("client_secret") or "")
            if not all((node_id, client_id, client_secret)):
                return {"success": False, "message": "Cloud 激活响应不完整"}
            protected = protect_credentials({"client_id": client_id, "client_secret": client_secret})
            staged = dict(self.config)
            staged.update({"base_url": base_url, "credential_blob": protected, "node_id": node_id, "profile_pending": True})
            self.stop()
            self.config = staged
            self.node_id = node_id
            self.registered = True
            self.node_missing_remote = False
            if self.printer_manager and hasattr(self.printer_manager, "config"):
                self.printer_manager.config.config.setdefault("cloud", {}).update(staged)
                self.printer_manager.config.save_config()
            self.auth_client = self.api_client = self.websocket_client = None
            self.heartbeat_service = self.print_job_handler = self.status_reporter = None
            return self.start()
        except Exception as exc:
            logger.exception("Edge activation failed")
            return {"success": False, "message": str(exc)}

    def unbind(self) -> Dict[str, Any]:
        """Remove this Edge's local node binding so it can be activated again."""
        self.stop()
        for key in ("node_id", "credential_blob", "profile_pending"):
            self.config.pop(key, None)
        self.node_id = None
        self.registered = False
        self.node_missing_remote = False
        self.last_error = None
        self.auth_client = None
        self.api_client = None
        self.websocket_client = None
        self.heartbeat_service = None
        self.print_job_handler = None
        self.status_reporter = None
        if self.printer_manager and hasattr(self.printer_manager, "config"):
            cloud_config = self.printer_manager.config.config.setdefault("cloud", {})
            for key in ("node_id", "credential_blob", "profile_pending"):
                cloud_config.pop(key, None)
            self.printer_manager.config.clear_cloud_registration()
        return {"success": True, "message": "已解除本机绑定，请重新激活终端"}


class PrinterStatusReporter:
    """打印机状态上报器 - 使用批量HTTP接口上报"""
    
    def __init__(self, websocket_client, printer_manager, node_id, api_client=None, node_missing_handler=None):
        self.websocket_client = websocket_client
        self.printer_manager = printer_manager
        self.node_id = node_id
        self.api_client = api_client  # 用于批量HTTP上报
        self.node_missing_handler = node_missing_handler
        self.running = False
        self.thread = None
        self.check_interval = 30
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._refresh_lock = threading.Lock()
        self._refresh_ids = set()
        self._refresh_waiters = {}

    def _is_remote_node_missing_error(self, error_text: Any) -> bool:
        text = str(error_text or "")
        return "Edge Node 不存在" in text or "Edge node not found" in text or "node_not_found" in text

    def _notify_node_missing(self, error_text: Any):
        if self.node_missing_handler:
            try:
                self.node_missing_handler(str(error_text or "printer status report node not found"))
            except Exception as e:
                logger.exception("Node missing callback failed")
    
    def start(self):
        """启动状态上报服务"""
        if self.running:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, name="printer-status-reporter", daemon=True)
        self.thread.start()
        logger.debug("Printer status reporter loop started")
    
    def stop(self):
        """停止状态上报服务"""
        self.running = False
        self._stop_event.set()
        self._wake_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join()
        self.thread = None
        self._complete_refresh_waiters(None, False)
        logger.debug("Printer status reporter loop stopped")
    
    def force_report_printer(
        self,
        printer_id: str = None,
        printer_name: str = None,
        *,
        wait: bool = False,
        timeout: float = 10.0,
    ) -> bool:
        """合并刷新请求，由唯一上报线程采样；关键节点可等待同步完成。"""
        if not self.running or not self.printer_manager or not self.api_client or not (printer_id or printer_name):
            return False
        key = (str(printer_id or ""), str(printer_name or ""))
        waiter = None
        result = None
        if wait:
            waiter = threading.Event()
            result = {"success": False}
        with self._refresh_lock:
            self._refresh_ids.add(key)
            if waiter is not None:
                self._refresh_waiters.setdefault(key, []).append((waiter, result))
        self._wake_event.set()
        if waiter is None:
            return True
        if not waiter.wait(max(0.0, float(timeout))):
            with self._refresh_lock:
                pending = self._refresh_waiters.get(key, [])
                self._refresh_waiters[key] = [item for item in pending if item[0] is not waiter]
                if not self._refresh_waiters[key]:
                    self._refresh_waiters.pop(key, None)
            return False
        return bool(result["success"])
    
    def _monitor_loop(self):
        """串行调度周期刷新和按需刷新，禁止重叠采样。"""
        next_full_refresh = 0.0
        while not self._stop_event.is_set():
            try:
                if time.monotonic() >= next_full_refresh:
                    requested = self._drain_refresh_requests()
                    success = self._check_and_report_status()
                    if requested:
                        self._complete_refresh_waiters(requested, success)
                    next_full_refresh = time.monotonic() + self.check_interval
                else:
                    requested = self._drain_refresh_requests()
                    if requested:
                        printers = self._select_requested_printers(requested)
                        success = bool(printers) and self._report_printers(printers)
                        self._complete_refresh_waiters(requested, success)
                self._wake_event.wait(max(0.0, next_full_refresh - time.monotonic()))
                self._wake_event.clear()
            except Exception:
                logger.debug("Printer status monitor loop failed", exc_info=True)
                self._stop_event.wait(5)
        self.running = False

    def _drain_refresh_requests(self):
        with self._refresh_lock:
            requests = set(self._refresh_ids)
            self._refresh_ids.clear()
        return requests

    def _select_requested_printers(self, requests):
        selected = {}
        for printer in self.printer_manager.config.get_managed_printers():
            local_id = str(printer.get("id") or "")
            cloud_id = str(printer.get("cloud_id") or "")
            name = str(printer.get("name") or "")
            if any((pid and pid in {local_id, cloud_id}) or (pname and pname == name) for pid, pname in requests):
                selected[local_id or cloud_id or name] = printer
        return list(selected.values())

    def _complete_refresh_waiters(self, requests, success):
        with self._refresh_lock:
            keys = list(self._refresh_waiters) if requests is None else list(requests)
            waiters = []
            for key in keys:
                waiters.extend(self._refresh_waiters.pop(key, []))
        for event, result in waiters:
            result["success"] = bool(success)
            event.set()
    
    def _check_and_report_status(self):
        """Report a fresh status lease for every managed printer."""
        if not self.printer_manager:
            return False
        
        try:
            return self._report_printers(self.printer_manager.config.get_managed_printers())
        except Exception:
            logger.debug("Checking printer status failed", exc_info=True)
            return False

    def _report_printers(self, printers):
        eligible = [p for p in printers if p.get("name") and (p.get("cloud_id") or p.get("id"))]
        if not eligible or not self.api_client:
            return False
        payloads = []
        with ThreadPoolExecutor(max_workers=min(4, len(eligible)), thread_name_prefix="printer-status") as pool:
            futures = {pool.submit(self._build_status_payload, printer): printer for printer in eligible}
            for future in as_completed(futures):
                try:
                    payloads.append(future.result())
                except Exception:
                    logger.warning("Printer status sampling failed: name=%s", futures[future].get("name"), exc_info=True)
        if not payloads:
            return False
        result = self.api_client.batch_update_printer_status(payloads)
        if result.get("success"):
            logger.debug("Printer status batch reported: count=%s", len(payloads))
            return True
        if self._is_remote_node_missing_error(result.get("error")):
            self._notify_node_missing(result.get("error"))
        logger.warning("Printer status batch report failed: %s", result.get("error"))
        return False

    def _build_status_payload(self, printer: Dict[str, Any]) -> Dict[str, Any]:
        detail = self.printer_manager.get_printer_status_detail(printer.get("name"))
        return {
            "printer_id": printer.get("cloud_id") or printer.get("id"),
            "printer_status": detail.get("printer_status") or "printer_state_unknown",
            "source_observed_at": detail.get("source_observed_at") or datetime.now(timezone.utc).isoformat(),
        }
