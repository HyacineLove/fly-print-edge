"""
边缘节点信息收集模块
收集MAC地址、系统信息、硬件信息等
"""

import platform
import subprocess
import psutil
import socket
from typing import Dict, Any, Optional


class EdgeNodeInfo:
    """边缘节点信息收集器"""
    
    def __init__(self, node_name: str = None, location: str = None):
        self.node_name = node_name or self._generate_default_name()
        self.location = location or "未指定位置"
        self.version = "v1.0.0"  # 边缘节点版本
    
    def _generate_default_name(self) -> str:
        """生成默认节点名称"""
        hostname = socket.gethostname()
        return f"EdgeNode-{hostname}"
    
    def get_mac_address(self, interface: str = None) -> str:
        """获取MAC地址"""
        try:
            if platform.system() == "Windows":
                return self._get_windows_mac(interface)
            else:
                return self._get_linux_mac(interface)
        except Exception as e:
            print(f" [DEBUG] 获取MAC地址失败: {e}")
            return "00:00:00:00:00:00"
    
    def _get_linux_mac(self, interface: str = None) -> str:
        """获取Linux系统MAC地址"""
        try:
            # 如果指定了网络接口，直接获取
            if interface:
                result = subprocess.run(
                    ['cat', f'/sys/class/net/{interface}/address'],
                    capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            
            # 自动检测主要网络接口
            for iface in ['eth0', 'enp0s3', 'ens33', 'wlan0']:
                try:
                    result = subprocess.run(
                        ['cat', f'/sys/class/net/{iface}/address'],
                        capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5
                    )
                    if result.returncode == 0:
                        mac = result.stdout.strip()
                        if mac and mac != "00:00:00:00:00:00":
                            return mac
                except:
                    continue
            
            # 使用ip命令作为备选
            result = subprocess.run(
                ['ip', 'link', 'show'],
                capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'link/ether' in line and 'lo' not in line:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'link/ether' and i + 1 < len(parts):
                                return parts[i + 1]
        except Exception as e:
            print(f" [DEBUG] 获取Linux MAC地址失败: {e}")
        
        return "00:00:00:00:00:00"
    
    def _get_windows_mac(self, interface: str = None) -> str:
        """获取Windows系统MAC地址"""
        try:
            result = subprocess.run(
                ['getmac', '/fo', 'csv', '/nh'],
                capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line and ',' in line:
                        mac = line.split(',')[0].strip('"')
                        if mac and mac != "N/A":
                            return mac.replace('-', ':').lower()
        except Exception as e:
            print(f" [DEBUG] 获取Windows MAC地址失败: {e}")
        
        return "00:00:00:00:00:00"
    
    def get_network_interface(self) -> str:
        """获取主要网络接口名称"""
        try:
            if platform.system() == "Windows":
                return "以太网"
            else:
                # Linux系统
                interfaces = ['eth0', 'enp0s3', 'ens33', 'wlan0']
                for iface in interfaces:
                    try:
                        result = subprocess.run(
                            ['cat', f'/sys/class/net/{iface}/operstate'],
                            capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=2
                        )
                        if result.returncode == 0 and result.stdout.strip() == 'up':
                            return iface
                    except:
                        continue
                return 'eth0'  # 默认值
        except Exception as e:
            print(f" [DEBUG] 获取网络接口失败: {e}")
            return "eth0"
    
    def get_os_version(self) -> str:
        """获取操作系统版本"""
        try:
            system = platform.system()
            if system == "Linux":
                try:
                    # 尝试读取/etc/os-release
                    with open('/etc/os-release', 'r') as f:
                        lines = f.readlines()
                    
                    name = ""
                    version = ""
                    for line in lines:
                        if line.startswith('NAME='):
                            name = line.split('=')[1].strip().strip('"')
                        elif line.startswith('VERSION='):
                            version = line.split('=')[1].strip().strip('"')
                    
                    if name and version:
                        return f"{name} {version}"
                except:
                    pass
                
                # 备选方案
                return f"{platform.system()} {platform.release()}"
            else:
                return f"{platform.system()} {platform.release()}"
        except Exception as e:
            print(f" [DEBUG] 获取系统版本失败: {e}")
            return "Unknown OS"
    
    def get_cpu_info(self) -> str:
        """获取CPU信息"""
        try:
            if platform.system() == "Linux":
                with open('/proc/cpuinfo', 'r') as f:
                    lines = f.readlines()
                
                for line in lines:
                    if 'model name' in line:
                        return line.split(':')[1].strip()
            else:
                # Windows使用wmic命令
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'name', '/value'],
                    capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=5
                )
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'Name=' in line:
                            return line.split('=')[1].strip()
            
            # 备选方案
            return f"{platform.processor()}"
        except Exception as e:
            print(f" [DEBUG] 获取CPU信息失败: {e}")
            return "Unknown CPU"
    
    def get_memory_info(self) -> str:
        """获取内存信息"""
        try:
            memory = psutil.virtual_memory()
            total_gb = round(memory.total / (1024**3), 1)
            return f"{total_gb}GB RAM"
        except Exception as e:
            print(f" [DEBUG] 获取内存信息失败: {e}")
            return "Unknown Memory"
    
    def get_disk_info(self) -> str:
        """获取磁盘信息"""
        try:
            disk = psutil.disk_usage('/')
            total_gb = round(disk.total / (1024**3), 1)
            return f"{total_gb}GB Disk"
        except Exception as e:
            print(f" [DEBUG] 获取磁盘信息失败: {e}")
            return "Unknown Disk"
    
    def get_edge_node_data(self, interface: str = None) -> Dict[str, Any]:
        """获取完整的边缘节点数据"""
        network_interface = interface or self.get_network_interface()
        
        mac_address = self.get_mac_address(network_interface)
        
        data = {
            "node_id": mac_address.replace(":", ""),  # 使用MAC地址作为NodeID，去掉冒号
            "name": self.node_name,
            "location": self.location,
            "version": self.version,
            "mac_address": mac_address,
            "network_interface": network_interface,
            "os_version": self.get_os_version(),
            "cpu_info": self.get_cpu_info(),
            "memory_info": self.get_memory_info(),
            "disk_info": self.get_disk_info()
        }
        
        print(f" [DEBUG] 边缘节点信息收集完成:")
        for key, value in data.items():
            print(f"  {key}: {value}")
        
        return data
