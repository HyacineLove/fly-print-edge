"""
打印机配置管理
负责配置文件的读写和打印机列表管理
"""

import json
import uuid
from datetime import datetime
from typing import List, Dict


class PrinterConfig:
    """打印机配置管理"""
    
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self) -> Dict:
        """加载配置文件"""
        try:
            print(f"📖 [DEBUG] 加载配置文件: {self.config_file}")
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                print(f"✅ [DEBUG] 配置文件加载成功，管理的打印机数量: {len(config.get('managed_printers', []))}")
                return config
        except FileNotFoundError:
            print(f"⚠️ [DEBUG] 配置文件不存在，创建默认配置")
            return {
                "managed_printers": [], 
                "settings": {},
                "cloud": {
                    "enabled": False,
                    "base_url": "",
                    "auth_url": "https://oauth.021hqit.com/keycloak/realms/master/protocol/openid-connect/token",
                    "client_id": "fly-print-edge",
                    "client_secret": "",
                    "node_name": "",
                    "location": "",
                    "heartbeat_interval": 30,
                    "auto_register": True,
                    "auto_register_printers": True
                }
            }
    
    def save_config(self):
        """保存配置文件"""
        print(f"💾 [DEBUG] 保存配置到: {self.config_file}")
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
        print(f"✅ [DEBUG] 配置文件保存成功")
    
    def add_printer(self, printer_info: Dict):
        """添加打印机到管理列表"""
        printer_info["added_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        printer_info["id"] = str(uuid.uuid4())
        print(f"➕ [DEBUG] 添加打印机到配置: {printer_info['name']} (ID: {printer_info['id']})")
        self.config["managed_printers"].append(printer_info)
        self.save_config()
    
    def remove_printer(self, printer_id: str):
        """从管理列表移除打印机"""
        print(f"🗑️ [DEBUG] 移除打印机: {printer_id}")
        original_count = len(self.config["managed_printers"])
        self.config["managed_printers"] = [
            p for p in self.config["managed_printers"] 
            if p.get("id") != printer_id
        ]
        new_count = len(self.config["managed_printers"])
        print(f"📊 [DEBUG] 移除结果: {original_count} -> {new_count}")
        self.save_config()
    
    def update_printer_id(self, printer_name: str, new_id: str):
        """更新打印机ID（用于同步云端ID）"""
        updated = False
        for printer in self.config["managed_printers"]:
            if printer.get("name") == printer_name and printer.get("id") != new_id:
                print(f"🔄 [DEBUG] 更新打印机ID: {printer_name} ({printer.get('id')} -> {new_id})")
                printer["id"] = new_id
                updated = True
                break
        
        if updated:
            self.save_config()
            return True
        return False

    def get_managed_printers(self) -> List[Dict]:
        """获取管理的打印机列表"""
        return self.config["managed_printers"]
    
    def clear_all_printers(self):
        """清空所有管理的打印机"""
        print(f"🧹 [DEBUG] 清空所有管理的打印机")
        original_count = len(self.config["managed_printers"])
        self.config["managed_printers"] = []
        print(f"📊 [DEBUG] 清空结果: {original_count} -> 0")
        self.save_config()
