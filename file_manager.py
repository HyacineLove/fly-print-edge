"""
文件管理模块
负责临时文件的生命周期管理和自动清理
"""

import os
import time
import threading
import glob
import tempfile
from typing import Dict, Optional, List
from datetime import datetime


class FileManager:
    """文件生命周期管理器"""
    
    def __init__(self, cleanup_interval: int = 300, file_ttl: int = 1800):
        """
        初始化文件管理器
        
        Args:
            cleanup_interval: 清理检查间隔（秒），默认5分钟
            file_ttl: 文件存活时间（秒），默认30分钟
        """
        self.cleanup_interval = cleanup_interval
        self.file_ttl = file_ttl
        
        # 跟踪预览文件
        self.preview_files: Dict[str, Dict] = {}  # file_id -> {path, pdf_path, created_at, last_access}
        self.preview_lock = threading.Lock()
        
        # 后台清理线程
        self.running = False
        self.cleanup_thread: Optional[threading.Thread] = None
        
        print(f"📁 [FileManager] 初始化: 清理间隔={cleanup_interval}s, 文件TTL={file_ttl}s")
    
    def start(self):
        """启动后台清理线程"""
        if self.running:
            print("⚠️ [FileManager] 清理线程已在运行")
            return
        
        self.running = True
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        print("✅ [FileManager] 后台清理线程已启动")
    
    def stop(self):
        """停止后台清理线程"""
        self.running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        print("🛑 [FileManager] 后台清理线程已停止")
    
    def _cleanup_loop(self):
        """后台清理循环"""
        while self.running:
            try:
                time.sleep(self.cleanup_interval)
                if self.running:
                    self.cleanup_expired_files()
            except Exception as e:
                print(f"❌ [FileManager] 清理循环异常: {e}")
    
    def register_preview_file(self, file_id: str, file_path: str, pdf_path: Optional[str] = None):
        """
        注册预览文件
        
        Args:
            file_id: 文件ID
            file_path: 原始文件路径
            pdf_path: PDF转换文件路径（如果有）
        """
        with self.preview_lock:
            now = time.time()
            self.preview_files[file_id] = {
                "path": file_path,
                "pdf_path": pdf_path,
                "created_at": now,
                "last_access": now
            }
            print(f"📝 [FileManager] 注册预览文件: {file_id} -> {os.path.basename(file_path)}")
    
    def update_file_access(self, file_id: str):
        """更新文件最后访问时间"""
        with self.preview_lock:
            if file_id in self.preview_files:
                self.preview_files[file_id]["last_access"] = time.time()
    
    def get_file_info(self, file_id: str) -> Optional[Dict]:
        """获取文件信息"""
        with self.preview_lock:
            return self.preview_files.get(file_id)
    
    def cleanup_file(self, file_id: str, source: str = "manual") -> bool:
        """
        清理指定文件（事件触发）
        
        Args:
            file_id: 文件ID
            source: 触发来源（manual/print/cancel/expired）
        
        Returns:
            是否成功清理
        """
        with self.preview_lock:
            file_info = self.preview_files.get(file_id)
            if not file_info:
                return False
            
            success = True
            
            # 删除原始文件
            file_path = file_info.get("path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"🗑️ [FileManager] [{source}] 删除预览文件: {os.path.basename(file_path)}")
                except Exception as e:
                    print(f"⚠️ [FileManager] 删除文件失败: {file_path}, 错误: {e}")
                    success = False
            
            # 删除PDF转换文件
            pdf_path = file_info.get("pdf_path")
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    print(f"🗑️ [FileManager] [{source}] 删除PDF文件: {os.path.basename(pdf_path)}")
                except Exception as e:
                    print(f"⚠️ [FileManager] 删除PDF失败: {pdf_path}, 错误: {e}")
                    success = False
            
            # 从跟踪列表移除
            self.preview_files.pop(file_id, None)
            
            return success
    
    def cleanup_expired_files(self):
        """清理过期文件（定时触发）"""
        now = time.time()
        expired_files = []
        
        with self.preview_lock:
            for file_id, info in self.preview_files.items():
                age = now - info["last_access"]
                if age > self.file_ttl:
                    expired_files.append(file_id)
        
        if expired_files:
            print(f"🕐 [FileManager] 发现 {len(expired_files)} 个过期文件，开始清理...")
            for file_id in expired_files:
                self.cleanup_file(file_id, source="expired")
        else:
            # print(f"✅ [FileManager] 定时检查: 无过期文件")
            pass
    
    def cleanup_all_preview_files(self):
        """清理所有预览文件（关闭时调用）"""
        with self.preview_lock:
            file_ids = list(self.preview_files.keys())
        
        if file_ids:
            print(f"🧹 [FileManager] 清理所有预览文件: {len(file_ids)} 个")
            for file_id in file_ids:
                self.cleanup_file(file_id, source="shutdown")
    
    def cleanup_old_temp_files(self, pattern: str = "tmp*", max_age_hours: int = 24):
        """
        清理遗留的旧临时文件（启动时调用）
        
        Args:
            pattern: 文件名模式
            max_age_hours: 最大文件年龄（小时）
        """
        try:
            temp_dir = tempfile.gettempdir()
            pattern_path = os.path.join(temp_dir, pattern)
            files = glob.glob(pattern_path)
            
            now = time.time()
            max_age_seconds = max_age_hours * 3600
            cleaned_count = 0
            
            for file_path in files:
                try:
                    # 检查文件年龄
                    file_age = now - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        cleaned_count += 1
                except Exception as e:
                    # 忽略单个文件清理失败
                    pass
            
            if cleaned_count > 0:
                print(f"🧹 [FileManager] 启动清理: 删除 {cleaned_count} 个遗留临时文件")
        except Exception as e:
            print(f"⚠️ [FileManager] 启动清理失败: {e}")
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        with self.preview_lock:
            total_files = len(self.preview_files)
            total_size = 0
            
            for info in self.preview_files.values():
                file_path = info.get("path")
                if file_path and os.path.exists(file_path):
                    try:
                        total_size += os.path.getsize(file_path)
                    except:
                        pass
                
                pdf_path = info.get("pdf_path")
                if pdf_path and os.path.exists(pdf_path):
                    try:
                        total_size += os.path.getsize(pdf_path)
                    except:
                        pass
            
            return {
                "total_files": total_files,
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "file_ttl": self.file_ttl,
                "cleanup_interval": self.cleanup_interval
            }


# 全局实例（由 main.py 初始化）
file_manager: Optional[FileManager] = None


def get_file_manager() -> Optional[FileManager]:
    """获取全局文件管理器实例"""
    return file_manager


def init_file_manager(cleanup_interval: int = 300, file_ttl: int = 1800) -> FileManager:
    """初始化全局文件管理器"""
    global file_manager
    file_manager = FileManager(cleanup_interval=cleanup_interval, file_ttl=file_ttl)
    return file_manager
