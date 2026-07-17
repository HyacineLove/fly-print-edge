"""Session-only file state; canonical PDFs belong exclusively to DocumentPipeline."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def is_valid_content_hash(content_hash: Optional[str]) -> bool:
    return isinstance(content_hash, str) and bool(CONTENT_HASH_RE.fullmatch(content_hash))


class FileManager:
    """Owns session previews, access tokens and job-scoped downloaded sources."""

    def __init__(
        self,
        cleanup_interval: int = 300,
        file_ttl: int = 1800,
        preview_cache: Optional[Dict] = None,
    ):
        self.cleanup_interval = cleanup_interval
        self.file_ttl = file_ttl
        self.preview_cache = preview_cache if preview_cache is not None else {}
        self.preview_lock = threading.Lock()
        self.file_access_tokens: Dict[str, Dict[str, str]] = {}
        self.token_lock = threading.Lock()
        self.print_artifacts: Dict[str, Dict[str, Optional[str]]] = {}
        self.print_lock = threading.Lock()
        self.running = False
        self._stop_event = threading.Event()
        self.cleanup_thread: Optional[threading.Thread] = None
        logger.info("FileManager initialized: cleanup_interval=%ss file_ttl=%ss", cleanup_interval, file_ttl)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, name="session-file-cleanup", daemon=True)
        self.cleanup_thread.start()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=1.0)

    def _cleanup_loop(self) -> None:
        while not self._stop_event.wait(self.cleanup_interval):
            self.cleanup_expired_files()

    def release_preview_resource(self, file_id: str, reason: str = "manual") -> bool:
        del reason
        removed = False
        with self.preview_lock:
            keys = [key for key in self.preview_cache if key.startswith(f"{file_id}:")]
            for key in keys:
                self.preview_cache.pop(key, None)
                removed = True
        return removed

    def cleanup_expired_files(self) -> None:
        now = time.time()
        with self.preview_lock:
            expired = [
                key
                for key, value in self.preview_cache.items()
                if isinstance(value, dict)
                and "timestamp" in value
                and now - float(value["timestamp"]) > self.file_ttl
            ]
            for key in expired:
                self.preview_cache.pop(key, None)
        self.cleanup_expired_tokens()

    def cleanup_all_preview_files(self) -> None:
        with self.preview_lock:
            self.preview_cache.clear()

    def store_file_access_token(self, file_id: str, token: str, expires_at: Optional[str]) -> None:
        if not file_id or not token:
            return
        with self.token_lock:
            self.file_access_tokens[file_id] = {"token": token, "expires_at": expires_at or ""}

    def consume_file_access_token(self, file_id: str) -> Optional[str]:
        with self.token_lock:
            token_info = self.file_access_tokens.pop(file_id, None)
        if not token_info or self._token_is_expired(token_info.get("expires_at")):
            return None
        return token_info.get("token")

    def cleanup_expired_tokens(self) -> None:
        with self.token_lock:
            expired = [
                file_id
                for file_id, info in self.file_access_tokens.items()
                if self._token_is_expired(info.get("expires_at"))
            ]
            for file_id in expired:
                self.file_access_tokens.pop(file_id, None)

    def register_print_artifact(
        self,
        artifact_key: str,
        source_path: str,
        converted_path: Optional[str] = None,
        owns_source: bool = True,
    ) -> None:
        if not artifact_key or not source_path:
            return
        with self.print_lock:
            self.print_artifacts[artifact_key] = {
                "source_path": source_path,
                "converted_path": converted_path,
                "owns_source": owns_source,
            }

    def update_print_artifact(self, artifact_key: str, converted_path: Optional[str]) -> None:
        with self.print_lock:
            if artifact_key in self.print_artifacts:
                self.print_artifacts[artifact_key]["converted_path"] = converted_path

    def release_print_artifact(self, artifact_key: str, reason: str = "manual") -> bool:
        with self.print_lock:
            artifact = self.print_artifacts.pop(artifact_key, None)
        if not artifact:
            return False
        success = True
        for path_key in ("source_path", "converted_path"):
            if path_key == "source_path" and not artifact.get("owns_source", True):
                continue
            path = artifact.get(path_key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(
                        "Released print artifact: artifact_key=%s reason=%s file=%s",
                        artifact_key,
                        reason,
                        os.path.basename(path),
                    )
                except OSError as exc:
                    logger.warning("Failed to delete print artifact: file=%s error=%s", path, exc)
                    success = False
        return success

    @staticmethod
    def _token_is_expired(expires_at: Optional[str]) -> bool:
        if not expires_at:
            return False
        try:
            value = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value <= datetime.now(timezone.utc)
        except Exception:
            return False

    def get_statistics(self) -> Dict[str, Any]:
        with self.preview_lock:
            return {
                "preview_entries": len(self.preview_cache),
                "file_ttl": self.file_ttl,
                "cleanup_interval": self.cleanup_interval,
            }


file_manager: Optional[FileManager] = None


def get_file_manager() -> Optional[FileManager]:
    return file_manager


def init_file_manager(
    cleanup_interval: int = 300,
    file_ttl: int = 1800,
    preview_cache: Optional[Dict] = None,
) -> FileManager:
    global file_manager
    file_manager = FileManager(
        cleanup_interval,
        file_ttl,
        preview_cache,
    )
    return file_manager
