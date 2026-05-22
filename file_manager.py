"""
文件管理模块
负责临时文件的生命周期管理和自动清理
"""

import os
import time
import threading
from typing import Any, Dict, Optional
from datetime import datetime, timezone


class FileManager:
    """文件生命周期管理器"""
    
    def __init__(
        self,
        cleanup_interval: int = 300,
        file_ttl: int = 1800,
        preview_cache: Optional[Dict] = None,
        preview_page_cache: Optional[Dict] = None,
        preview_page_meta: Optional[Dict] = None,
    ):
        """
        初始化文件管理器
        
        Args:
            cleanup_interval: 清理检查间隔（秒），默认5分钟
            file_ttl: 文件存活时间（秒），默认30分钟
            preview_cache: 预览图内存缓存的引用（用于定期清理）
        """
        self.cleanup_interval = cleanup_interval
        self.file_ttl = file_ttl
        self.preview_cache = preview_cache if preview_cache is not None else {}
        self.preview_page_cache = preview_page_cache if preview_page_cache is not None else {}
        self.preview_page_meta = preview_page_meta if preview_page_meta is not None else {}
        
        # 跟踪预览文件
        self.preview_files: Dict[str, Dict[str, Any]] = {}
        self.preview_lock = threading.Lock()

        # 访问 token
        self.file_access_tokens: Dict[str, Dict[str, str]] = {}
        self.token_lock = threading.Lock()

        # 打印临时文件
        self.print_artifacts: Dict[str, Dict[str, Optional[str]]] = {}
        self.print_lock = threading.Lock()
        
        # 后台清理线程
        self.running = False
        self.cleanup_thread: Optional[threading.Thread] = None
        
        print(f" [FileManager] 初始化: 清理间隔={cleanup_interval}s, 文件TTL={file_ttl}s")
    
    def start(self):
        """启动后台清理线程"""
        if self.running:
            print(" [FileManager] 清理线程已在运行")
            return
        
        self.running = True
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        print(" [FileManager] 后台清理线程已启动")
    
    def stop(self):
        """停止后台清理线程"""
        self.running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        print(" [FileManager] 后台清理线程已停止")
    
    def _cleanup_loop(self):
        """后台清理循环"""
        while self.running:
            try:
                time.sleep(self.cleanup_interval)
                if self.running:
                    self.cleanup_expired_files()
            except Exception as e:
                print(f" [FileManager] 清理循环异常: {e}")
    
    def register_preview_resource(self, file_id: str, file_url: str, source_path: str, pdf_path: Optional[str] = None):
        """注册或更新预览资源。"""
        with self.preview_lock:
            now = time.time()
            self.preview_files[file_id] = {
                "file_url": file_url,
                "source_path": source_path,
                "pdf_path": pdf_path,
                "created_at": now,
                "last_access": now
            }
            print(f" [FileManager] 注册预览文件: {file_id} -> {os.path.basename(source_path)}")
    
    def register_preview_file(self, file_id: str, file_path: str, pdf_path: Optional[str] = None):
        """兼容旧接口。"""
        existing = self.get_preview_resource(file_id)
        file_url = existing.get("file_url") if existing else ""
        self.register_preview_resource(file_id, file_url, file_path, pdf_path)

    def touch_preview_resource(self, file_id: str):
        """更新预览资源最后访问时间。"""
        with self.preview_lock:
            if file_id in self.preview_files:
                self.preview_files[file_id]["last_access"] = time.time()
    
    def update_file_access(self, file_id: str):
        """兼容旧接口。"""
        self.touch_preview_resource(file_id)

    def get_preview_resource(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取预览资源信息。"""
        with self.preview_lock:
            file_info = self.preview_files.get(file_id)
            return dict(file_info) if file_info else None

    def get_file_info(self, file_id: str) -> Optional[Dict]:
        """兼容旧接口。"""
        return self.get_preview_resource(file_id)
    
    def release_preview_resource(self, file_id: str, reason: str = "manual") -> bool:
        """释放预览资源及其关联缓存。"""
        with self.preview_lock:
            file_info = self.preview_files.pop(file_id, None)

        if not file_info:
            self._clear_preview_cache_entries(file_id)
            return False

        success = True
        file_path = file_info.get("source_path")
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f" [FileManager] [{reason}] 删除预览文件: {os.path.basename(file_path)}")
            except Exception as e:
                print(f" [FileManager] 删除文件失败: {file_path}, 错误: {e}")
                success = False

        pdf_path = file_info.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                print(f" [FileManager] [{reason}] 删除PDF文件: {os.path.basename(pdf_path)}")
            except Exception as e:
                print(f" [FileManager] 删除PDF失败: {pdf_path}, 错误: {e}")
                success = False

        self._clear_preview_cache_entries(file_id)
        return success

    def cleanup_file(self, file_id: str, source: str = "manual") -> bool:
        """兼容旧接口。"""
        return self.release_preview_resource(file_id, reason=source)

    def _clear_preview_cache_entries(self, file_id: str):
        keys = [key for key in list(self.preview_cache.keys()) if key.startswith(f"{file_id}:")]
        for key in keys:
            self.preview_cache.pop(key, None)
        self.preview_page_cache.pop(file_id, None)
        self.preview_page_meta.pop(file_id, None)

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
            print(f" [FileManager] 发现 {len(expired_files)} 个过期文件，开始清理...")
            for file_id in expired_files:
                self.release_preview_resource(file_id, reason="expired")

        self._cleanup_expired_preview_cache(now)
        self.cleanup_expired_tokens()

    def _cleanup_expired_preview_cache(self, now: float):
        """清理过期的预览图内存缓存"""
        if not self.preview_cache:
            return

        expired_keys = []
        for key, value in list(self.preview_cache.items()):
            if isinstance(value, dict) and "timestamp" in value:
                age = now - value["timestamp"]
                if age > self.file_ttl:
                    expired_keys.append(key)

        if expired_keys:
            for key in expired_keys:
                self.preview_cache.pop(key, None)
            print(f" [FileManager] 清理 {len(expired_keys)} 个过期预览图缓存")

    def cleanup_all_preview_files(self):
        """清理所有预览文件（关闭时调用）"""
        with self.preview_lock:
            file_ids = list(self.preview_files.keys())

        if file_ids:
            print(f" [FileManager] 清理所有预览文件: {len(file_ids)} 个")
            for file_id in file_ids:
                self.release_preview_resource(file_id, reason="shutdown")

    def store_file_access_token(self, file_id: str, token: str, expires_at: Optional[str]):
        if not file_id or not token:
            return
        with self.token_lock:
            self.file_access_tokens[file_id] = {"token": token, "expires_at": expires_at or ""}

    def consume_file_access_token(self, file_id: str) -> Optional[str]:
        with self.token_lock:
            token_info = self.file_access_tokens.pop(file_id, None)
        if not token_info:
            return None
        if self._token_is_expired(token_info.get("expires_at")):
            return None
        return token_info.get("token")

    def cleanup_expired_tokens(self):
        with self.token_lock:
            expired_keys = [
                file_id
                for file_id, info in self.file_access_tokens.items()
                if self._token_is_expired(info.get("expires_at"))
            ]
            for file_id in expired_keys:
                self.file_access_tokens.pop(file_id, None)

    def register_print_artifact(self, artifact_key: str, source_path: str, converted_path: Optional[str] = None):
        if not artifact_key or not source_path:
            return
        with self.print_lock:
            self.print_artifacts[artifact_key] = {
                "source_path": source_path,
                "converted_path": converted_path,
            }

    def update_print_artifact(self, artifact_key: str, converted_path: Optional[str]):
        if not artifact_key:
            return
        with self.print_lock:
            if artifact_key in self.print_artifacts:
                self.print_artifacts[artifact_key]["converted_path"] = converted_path

    def release_print_artifact(self, artifact_key: str, reason: str = "manual") -> bool:
        with self.print_lock:
            artifact_info = self.print_artifacts.pop(artifact_key, None)
        if not artifact_info:
            return False
        success = True
        for path_key in ("source_path", "converted_path"):
            file_path = artifact_info.get(path_key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f" [FileManager] [{reason}] 删除打印文件: {os.path.basename(file_path)}")
                except Exception as e:
                    print(f" [FileManager] 删除文件失败: {file_path}, 错误: {e}")
                    success = False
        return success

    def _token_is_expired(self, expires_at: Optional[str]) -> bool:
        if not expires_at:
            return False
        try:
            normalized = expires_at.replace("Z", "+00:00")
            expire_time = datetime.fromisoformat(normalized)
            if expire_time.tzinfo is None:
                expire_time = expire_time.replace(tzinfo=timezone.utc)
            return expire_time <= datetime.now(timezone.utc)
        except Exception:
            return False
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        with self.preview_lock:
            total_files = len(self.preview_files)
            total_size = 0
            
            for info in self.preview_files.values():
                file_path = info.get("source_path")
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


def init_file_manager(
    cleanup_interval: int = 300,
    file_ttl: int = 1800,
    preview_cache: Optional[Dict] = None,
    preview_page_cache: Optional[Dict] = None,
    preview_page_meta: Optional[Dict] = None,
) -> FileManager:
    """初始化全局文件管理器"""
    global file_manager
    file_manager = FileManager(
        cleanup_interval=cleanup_interval,
        file_ttl=file_ttl,
        preview_cache=preview_cache,
        preview_page_cache=preview_page_cache,
        preview_page_meta=preview_page_meta,
    )
    return file_manager
