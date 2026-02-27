"""
fly-print-cloud 心跳服务
定期发送心跳到云端，报告边缘节点状态
通过WebSocket发送心跳消息
"""

import threading
import time
import psutil
from typing import Dict, Any, Optional


class HeartbeatService:
    """心跳服务 - 通过WebSocket发送心跳"""
    
    def __init__(self, websocket_client, node_id: str, interval: int = 30, base_url: str = None):
        """初始化心跳服务
        
        Args:
            websocket_client: WebSocket客户端实例
            node_id: 节点ID
            interval: 心跳间隔（秒）
            base_url: 云端服务基础URL（用于测量延迟）
        """
        self.websocket_client = websocket_client
        self.node_id = node_id
        self.interval = interval
        self.base_url = base_url
        self.running = False
        self.thread = None
        self.last_heartbeat_time = 0
        self.heartbeat_failures = 0
        self.max_failures = 3  # 最大连续失败次数
        
    def start(self):
        """启动心跳服务"""
        if self.running:
            print("⚠️ [DEBUG] 心跳服务已经在运行")
            return
        
        self.running = True
        self.heartbeat_failures = 0
        self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.thread.start()
        print(f"💓 [DEBUG] 心跳服务已启动，间隔: {self.interval}秒")
    
    def stop(self):
        """停止心跳服务"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("🛑 [DEBUG] 心跳服务已停止")
    
    def _heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                # 发送心跳
                success = self._send_heartbeat()
                
                if success:
                    self.heartbeat_failures = 0
                    self.last_heartbeat_time = time.time()
                else:
                    self.heartbeat_failures += 1
                    print(f"⚠️ [DEBUG] 心跳失败次数: {self.heartbeat_failures}/{self.max_failures}")
                
                # 如果连续失败次数过多，可以触发重连或其他恢复机制
                if self.heartbeat_failures >= self.max_failures:
                    print("❌ [DEBUG] 心跳连续失败，可能需要重新注册节点")
                    # 这里可以添加重新注册逻辑或者通知主程序
                
            except Exception as e:
                print(f"❌ [DEBUG] 心跳循环异常: {e}")
                self.heartbeat_failures += 1
            
            # 等待下次心跳
            time.sleep(self.interval)
    
    def _send_heartbeat(self) -> bool:
        """通过WebSocket发送心跳"""
        try:
            # 检查WebSocket是否可用
            if not self.websocket_client or not self.websocket_client.running:
                print("⚠️ [DEBUG] WebSocket未连接，跳过心跳发送")
                return False
            
            # 收集系统状态信息
            system_info = self._collect_system_info()
            
            # 通过WebSocket发送心跳
            result = self.websocket_client.send_heartbeat(self.node_id, system_info)
            
            if result:
                print(f"💓 [DEBUG] 心跳发送成功 (WebSocket)")
            
            return result
            
        except Exception as e:
            print(f"❌ [DEBUG] 发送心跳异常: {e}")
            return False
    
    def _collect_system_info(self) -> Dict[str, Any]:
        """收集系统信息，符合API文档格式
        
        Returns:
            system_info字典，包含:
            - cpu_usage: float (%)
            - memory_usage: float (%)
            - disk_usage: float (%)
            - network_quality: str (good/fair/poor)
            - latency: int (ms)
        """
        try:
            # 获取CPU使用率
            cpu_usage = psutil.cpu_percent(interval=1)
            
            # 获取内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            
            # 获取磁盘使用率
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            
            # 评估网络质量
            network_quality = self._evaluate_network_quality()
            
            # 测量延迟
            latency = self._measure_latency()
            
            return {
                "cpu_usage": round(cpu_usage, 1),
                "memory_usage": round(memory_usage, 1),
                "disk_usage": round(disk_usage, 1),
                "network_quality": network_quality,
                "latency": latency
            }
            
        except Exception as e:
            print(f"❌ [DEBUG] 收集系统信息异常: {e}")
            return {
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "disk_usage": 0.0,
                "network_quality": "poor",
                "latency": 0
            }
    
    def _evaluate_network_quality(self) -> str:
        """评估网络质量
        
        Returns:
            str: good/fair/poor
        """
        # 基于最近的心跳成功率评估
        if self.heartbeat_failures == 0:
            return "good"
        elif self.heartbeat_failures == 1:
            return "fair"
        else:
            return "poor"
    
    def _measure_latency(self) -> int:
        """测量到云端的延迟（毫秒）"""
        try:
            if not self.base_url:
                return 0
                
            import requests
            start_time = time.time()
            
            # 简单的HEAD请求测量延迟
            response = requests.head(f"{self.base_url}/api/v1/health", timeout=3)
            
            end_time = time.time()
            latency_ms = int((end_time - start_time) * 1000)
            
            return latency_ms
            
        except Exception as e:
            print(f"⚠️ [DEBUG] 测量延迟失败: {e}")
            return 0  # 返回0表示无法测量
    
    def get_status(self) -> Dict[str, Any]:
        """获取心跳服务状态"""
        return {
            "running": self.running,
            "interval": self.interval,
            "last_heartbeat": self.last_heartbeat_time,
            "failures": self.heartbeat_failures,
            "max_failures": self.max_failures
        }
    
    def force_heartbeat(self) -> Dict[str, Any]:
        """强制发送一次心跳"""
        try:
            print("💓 [DEBUG] 强制发送心跳")
            success = self._send_heartbeat()
            
            if success:
                self.heartbeat_failures = 0
                self.last_heartbeat_time = time.time()
                return {"success": True, "message": "心跳发送成功"}
            else:
                self.heartbeat_failures += 1
                return {"success": False, "message": "心跳发送失败"}
                
        except Exception as e:
            print(f"❌ [DEBUG] 强制心跳异常: {e}")
            return {"success": False, "message": str(e)}
