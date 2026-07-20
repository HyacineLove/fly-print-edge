"""
fly-print-cloud API客户端
实现边缘节点注册、心跳、打印机注册等API调用
"""

import logging
import requests
import time
from typing import Dict, Any, List, Optional
from cloud_auth import CloudAuthClient
from edge_node_info import EdgeNodeInfo

logger = logging.getLogger(__name__)


class CloudAPIClient:
    """云端API客户端"""
    
    def __init__(self, base_url: str, auth_client: CloudAuthClient):
        self.base_url = base_url.rstrip('/')
        self.auth_client = auth_client
        self.node_id = None  # 注册后获得
        self.edge_info = EdgeNodeInfo()
    
    def register_edge_node(self, node_name: str = None, location: str = None) -> Dict[str, Any]:
        """注册边缘节点"""
        try:
            if node_name:
                self.edge_info.node_name = node_name
            if location:
                self.edge_info.location = location
            
            url = f"{self.base_url}/api/v1/edge/register"
            headers = self.auth_client.get_auth_headers()
            data = self.edge_info.get_edge_node_data()
            
            logger.debug("Registering edge node: url=%s payload_keys=%s", url, sorted(data.keys()))
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                # 按照后端接口定义，node_id在data.id字段中
                self.node_id = result['data']['id']
                logger.info("Edge node registered: node_id=%s", self.node_id)
                return {"success": True, "node_id": self.node_id, "data": result}
            else:
                logger.warning(
                    "Edge node registration failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return {"success": False, "error": response.text}
                
        except Exception as e:
            logger.exception("Edge node registration failed")
            return {"success": False, "error": str(e)}
    
    def register_printers(self, printers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """注册打印机到云端（逐个注册）"""
        if not self.node_id:
            return {"success": False, "error": "节点未注册"}
        
        try:
            url = f"{self.base_url}/api/v1/edge/{self.node_id}/printers"
            headers = self.auth_client.get_auth_headers()
            
            logger.debug("Registering printers: url=%s count=%s", url, len(printers))
            
            success_count = 0
            failed_printers = []
            registered_printers = {}  # 记录注册成功的打印机ID映射: name -> id
            
            # 逐个注册打印机
            for i, printer in enumerate(printers):
                logger.debug("Registering printer %s/%s: %s", i + 1, len(printers), printer["name"])
                
                response = requests.post(url, json=printer, headers=headers, timeout=10)
                
                if response.status_code in [200, 201]:
                    success_count += 1
                    logger.debug("Printer registered: name=%s", printer["name"])
                    try:
                        resp_data = response.json()
                        if 'data' in resp_data and 'id' in resp_data['data']:
                            printer_id = resp_data['data']['id']
                            registered_printers[printer['name']] = printer_id
                            logger.debug("Cloud printer id assigned: name=%s id=%s", printer["name"], printer_id)
                    except Exception as e:
                        logger.debug("Failed to parse registered printer id", exc_info=True)
                else:
                    failed_printers.append({
                        "name": printer['name'],
                        "error": response.text
                    })
                    logger.warning(
                        "Printer registration failed: name=%s status=%s body=%s payload_types=%s",
                        printer["name"],
                        response.status_code,
                        response.text,
                        {key: type(value).__name__ for key, value in printer.items()},
                    )
            
            return {
                "success": True, 
                "success_count": success_count, 
                "failed_count": len(failed_printers),
                "failed_printers": failed_printers,
                "registered_printers": registered_printers
            }
                
        except Exception as e:
            logger.exception("Printer registration failed")
            return {"success": False, "error": str(e)}

    def delete_printer(self, printer_id: str) -> Dict[str, Any]:
        if not self.node_id:
            return {"success": False, "error": "节点未注册"}
        if not printer_id:
            return {"success": False, "error": "printer_id 不能为空"}
        try:
            url = f"{self.base_url}/api/v1/edge/{self.node_id}/printers/{printer_id}"
            headers = self.auth_client.get_auth_headers()
            response = requests.delete(url, headers=headers, timeout=10)
            if response.status_code in [200, 204]:
                return {"success": True}
            return {"success": False, "error": response.text}
        except Exception as e:
            logger.exception("Delete printer failed: printer_id=%s", printer_id)
            return {"success": False, "error": str(e)}

    def batch_update_printer_status(self, printers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量更新打印机状态
        
        Args:
            printers: 打印机状态列表，每个元素包含:
                - printer_id: 打印机ID
                - printer_status: Edge归一化后的当前状态
                - source_observed_at: IPP采样时间
        
        Returns:
            包含 updated, failed, errors 的响应
        """
        if not self.node_id:
            return {"success": False, "error": "节点未注册"}
        
        if not printers:
            return {"success": True, "updated": 0, "failed": 0, "errors": []}
        
        try:
            url = f"{self.base_url}/api/v1/edge/{self.node_id}/printers/status"
            headers = self.auth_client.get_auth_headers()
            
            data = {"printers": printers}
            
            logger.debug("Batch printer status update: url=%s count=%s", url, len(printers))
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", {})
                logger.debug(
                    "Batch printer status updated: updated=%s failed=%s",
                    data.get("updated", 0),
                    data.get("failed", 0),
                )
                return {
                    "success": True,
                    "updated": data.get("updated", 0),
                    "failed": data.get("failed", 0),
                    "errors": data.get("errors", [])
                }
            else:
                logger.warning(
                    "Batch printer status update failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return {"success": False, "error": response.text}
                
        except Exception as e:
            logger.exception("Batch printer status update failed")
            return {"success": False, "error": str(e)}
    
    def get_websocket_url(self) -> str:
        """获取WebSocket连接URL"""
        if not self.node_id:
            return None
        
        # 将HTTP(S)协议转换为WS(S)协议
        ws_base = self.base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        return f"{ws_base}/api/v1/edge/ws?node_id={self.node_id}"

