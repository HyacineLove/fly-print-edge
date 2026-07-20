"""
打印机配置管理
负责配置文件的读写和打印机列表管理
"""

import json
import uuid
import os
import logging
from copy import deepcopy
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

class PrinterConfig:
    """打印机配置管理"""

    @staticmethod
    def _migrate_printer_schema(config: Dict) -> bool:
        """Migrate once to the direct-IPP inventory schema."""
        if int(config.get("printer_schema_version") or 0) >= 2:
            return False
        config["printer_schema_version"] = 2
        config["managed_printers"] = []
        config["default_printer_id"] = None
        config.pop("printers", None)
        return True
    
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self) -> Dict:
        """加载配置文件"""
        try:
            logger.debug("Loading config file: %s", self.config_file)
            with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                config_updated = self._migrate_printer_schema(config)
                if "default_printer_id" not in config:
                    config["default_printer_id"] = None
                
                # 初始化网络配置
                if "network" not in config:
                    config["network"] = {
                        "bind_address": "127.0.0.1",
                        "port": 7860
                    }
                
                if "cloud" in config:
                    config["cloud"].pop("enabled", None)
                    config["cloud"].pop("auto_register", None)
                    # Credentials are no longer accepted from or written to
                    # config.json. Activation stores the device-only bundle in
                    # a Windows DPAPI ciphertext instead.
                    for key in ("auth_url", "client_id", "client_secret"):
                        if key in config["cloud"]:
                            config["cloud"].pop(key, None)
                            config_updated = True
                    config["cloud"].setdefault("credential_blob", "")
                    config["cloud"].setdefault("profile_pending", False)

                # (已移除环境变量读取逻辑，完全依赖 config.json)
                
                settings = config.setdefault("settings", {})
                for removed_key in ("pdf_printer_path", "sumatra_path"):
                    if removed_key in settings:
                        settings.pop(removed_key, None)
                        config_updated = True
                if "copies_min" not in settings:
                    settings["copies_min"] = 1
                    config_updated = True
                if "copies_max" not in settings:
                    settings["copies_max"] = 3
                    config_updated = True
                if "log_level" not in settings:
                    settings["log_level"] = "INFO"
                    config_updated = True
                if "debug_logging" not in settings:
                    settings["debug_logging"] = False
                    config_updated = True
                for printer in config.get("managed_printers", []):
                    if "enabled" not in printer:
                        printer["enabled"] = True
                        config_updated = True
                    if "cloud_registered" not in printer:
                        printer["cloud_registered"] = False
                        config_updated = True
                if config_updated:
                    with open(self.config_file, 'w', encoding='utf-8') as wf:
                        json.dump(config, wf, indent=4, ensure_ascii=False)
                logger.debug(
                    "Config loaded: file=%s managed_printers=%s",
                    self.config_file,
                    len(config.get("managed_printers", [])),
                )
                return config
        except FileNotFoundError:
            logger.warning("Config file missing, creating default config: %s", self.config_file)
            default_config = {
                "printer_schema_version": 2,
                "managed_printers": [], 
                "settings": {
                    "copies_min": 1,
                    "copies_max": 3,
                    "log_level": "INFO",
                    "debug_logging": False,
                },
                "network": {
                    "bind_address": "127.0.0.1",
                    "port": 7860
                },
                "cloud": {
                    "base_url": "",
                    "credential_blob": "",
                    "profile_pending": False,
                    "node_name": "",
                    "location": "",
                    "heartbeat_interval": 30
                },
                "default_printer_id": None
            }
            # 立即保存默认配置到文件
            self.config = default_config
            self.save_config()
            return default_config
    
    def save_config(self):
        """保存配置文件"""
        logger.debug("Saving config file: %s", self.config_file)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
        logger.debug("Config file saved: %s", self.config_file)

    def get_full_config(self) -> Dict:
        return deepcopy(self.config)

    def replace_full_config(self, new_config: Dict):
        self.config = deepcopy(new_config)
        self._migrate_printer_schema(self.config)
        settings = self.config.setdefault("settings", {})
        settings.pop("pdf_printer_path", None)
        settings.pop("sumatra_path", None)
        self.save_config()
    
    def add_printer(self, printer_info: Dict):
        """添加打印机到管理列表"""
        printer_info["added_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        printer_info["id"] = str(printer_info.get("id") or uuid.uuid4())
        printer_info.setdefault("cloud_id", None)
        if "enabled" not in printer_info:
            printer_info["enabled"] = True
        if "cloud_registered" not in printer_info:
            printer_info["cloud_registered"] = False
        for key in ("print_readiness", "uri", "device_uri", "port", "driver"):
            printer_info.pop(key, None)
        logger.debug("Adding printer to config: name=%s id=%s", printer_info["name"], printer_info["id"])
        self.config["managed_printers"].append(printer_info)
        self.save_config()
    
    def remove_printer(self, printer_id: str):
        """从管理列表移除打印机"""
        logger.debug("Removing printer from config: id=%s", printer_id)
        original_count = len(self.config["managed_printers"])
        self.config["managed_printers"] = [
            p for p in self.config["managed_printers"] 
            if p.get("id") != printer_id
        ]
        new_count = len(self.config["managed_printers"])
        logger.debug("Removed printer from config: before=%s after=%s", original_count, new_count)
        self.save_config()
    
    def update_printer_id(self, printer_name: str, new_id: str):
        """更新打印机ID（用于同步云端ID）"""
        updated = False
        for printer in self.config["managed_printers"]:
            if printer.get("name") == printer_name:
                old_id = printer.get("cloud_id")
                if old_id != new_id:
                    logger.debug(
                        "Updating printer id: name=%s old_id=%s new_id=%s",
                        printer_name,
                        old_id,
                        new_id,
                    )
                    printer["cloud_id"] = new_id
                # 无论ID是否变化，都标记为已在云端注册，避免重复注册
                printer["cloud_registered"] = True
                updated = True
                break
        
        if updated:
            self.save_config()
            return True
        return False

    def clear_cloud_registration(self) -> None:
        """Clear only the Cloud-side printer identity before node reactivation."""
        for printer in self.config["managed_printers"]:
            printer["cloud_id"] = None
            printer["cloud_registered"] = False
        self.save_config()

    def get_managed_printers(self) -> List[Dict]:
        """获取管理的打印机列表"""
        return self.config["managed_printers"]
    
    def clear_all_printers(self):
        """清空所有管理的打印机"""
        logger.debug("Clearing all managed printers")
        original_count = len(self.config["managed_printers"])
        self.config["managed_printers"] = []
        logger.debug("Cleared all managed printers: before=%s after=0", original_count)
        self.save_config()

    def get_default_printer_id(self):
        return self.config.get("default_printer_id")

    def set_default_printer_id(self, printer_id: str):
        printer = self.get_printer_by_id(printer_id)
        if not printer or not printer.get("enabled", True):
            raise ValueError("default printer must exist and be enabled")
        self.config["default_printer_id"] = printer_id
        for printer in self.config["managed_printers"]:
            printer["is_default"] = printer.get("id") == printer_id
        self.save_config()

    def clear_default_printer_id(self):
        self.config["default_printer_id"] = None
        for printer in self.config["managed_printers"]:
            printer["is_default"] = False
        self.save_config()

    def get_printer_by_id(self, printer_id: str):
        for printer in self.config.get("managed_printers", []):
            if printer.get("id") == printer_id or printer.get("cloud_id") == printer_id:
                return printer
        return None

    def get_printer_by_uuid(self, printer_uuid: str):
        identity = str(printer_uuid or "").casefold()
        for printer in self.config.get("managed_printers", []):
            if str(printer.get("printer_uuid") or "").casefold() == identity:
                return printer
        return None

    def update_ipp_uri(self, printer_uuid: str, ipp_uri: str, capabilities: Dict = None) -> bool:
        printer = self.get_printer_by_uuid(printer_uuid)
        if not printer:
            return False
        printer["ipp_uri"] = ipp_uri
        if capabilities is not None:
            printer["capabilities"] = deepcopy(capabilities)
        self.save_config()
        return True

    def get_printer_by_name(self, printer_name: str):
        for printer in self.config.get("managed_printers", []):
            if printer.get("name") == printer_name:
                return printer
        return None

    def set_printer_enabled(self, printer_id: str, enabled: bool) -> bool:
        printer = self.get_printer_by_id(printer_id)
        if not printer:
            return False
        if printer.get("enabled") == enabled:
            return True
        printer["enabled"] = enabled
        self.save_config()
        return True

    def is_printer_enabled(self, printer_id: str = None, printer_name: str = None) -> bool:
        printer = None
        if printer_id:
            printer = self.get_printer_by_id(printer_id)
        if not printer and printer_name:
            printer = self.get_printer_by_name(printer_name)
        if not printer:
            return False
        return printer.get("enabled", True)
