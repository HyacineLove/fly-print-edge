import threading
import time
import uuid
from copy import deepcopy
from typing import Any, Dict, Optional


class InteractiveSessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._active_session: Optional[Dict[str, Any]] = None

    def start_session(self, upload_token: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session_id = uuid.uuid4().hex
            self._active_session = {
                "session_id": session_id,
                "upload_token": upload_token,
                "state": "awaiting_preview",
                "file_id": None,
                "file_url": None,
                "file_name": None,
                "file_type": None,
                "job_id": None,
                "submitted": False,
                "error_code": None,
                "error_message": None,
                "printer_fault": None,
                "updated_at": time.time(),
            }
            return deepcopy(self._active_session)

    def get_active_session(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._active_session:
                return None
            return deepcopy(self._active_session)

    def update_upload_token(self, session_id: str, upload_token: Optional[str]) -> bool:
        with self._lock:
            if not self._active_session or self._active_session["session_id"] != session_id:
                return False
            self._active_session["upload_token"] = upload_token
            self._active_session["updated_at"] = time.time()
            return True

    def accept_preview_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        file_id = data.get("file_id")
        file_url = data.get("file_url")
        if not file_id or not file_url:
            return None

        with self._lock:
            if not self._active_session:
                return None

            current_file_id = self._active_session.get("file_id")
            if current_file_id and current_file_id != file_id:
                return None

            self._active_session["file_id"] = file_id
            self._active_session["file_url"] = file_url
            self._active_session["file_name"] = data.get("file_name")
            self._active_session["file_type"] = data.get("file_type")
            self._active_session["state"] = "preview_ready"
            self._active_session["error_code"] = None
            self._active_session["error_message"] = None
            self._active_session["printer_fault"] = None
            self._active_session["updated_at"] = time.time()

            enriched = deepcopy(data)
            enriched["session_id"] = self._active_session["session_id"]
            return enriched

    def mark_print_submitted(self, session_id: str, file_id: str) -> bool:
        with self._lock:
            if not self._active_session:
                return False
            if self._active_session["session_id"] != session_id:
                return False
            if self._active_session.get("file_id") != file_id:
                return False
            if self._active_session.get("submitted"):
                return False

            self._active_session["submitted"] = True
            self._active_session["state"] = "print_submitted"
            self._active_session["error_code"] = None
            self._active_session["error_message"] = None
            self._active_session["printer_fault"] = None
            self._active_session["updated_at"] = time.time()
            return True

    def attach_cloud_job(self, file_url: str, job_id: str) -> Optional[Dict[str, Any]]:
        if not file_url or not job_id:
            return None

        with self._lock:
            if not self._active_session:
                return None
            if self._active_session.get("file_url") != file_url:
                return None
            if not self._active_session.get("submitted"):
                return None

            self._active_session["job_id"] = job_id
            self._active_session["state"] = "printing"
            self._active_session["updated_at"] = time.time()

            return {
                "session_id": self._active_session["session_id"],
                "job_id": job_id,
            }

    def revert_print_submission(self, session_id: str, file_id: str) -> bool:
        with self._lock:
            if not self._active_session:
                return False
            if self._active_session["session_id"] != session_id:
                return False
            if self._active_session.get("file_id") != file_id:
                return False

            self._active_session["submitted"] = False
            self._active_session["job_id"] = None
            self._active_session["state"] = "preview_ready"
            self._active_session["error_code"] = None
            self._active_session["error_message"] = None
            self._active_session["printer_fault"] = None
            self._active_session["updated_at"] = time.time()
            return True

    def accept_job_status_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        job_id = data.get("job_id")
        if not job_id:
            return None

        with self._lock:
            if not self._active_session:
                return None
            if self._active_session.get("job_id") != job_id:
                return None

            status = str(data.get("status") or "").lower()
            if status in {"completed", "complete", "done", "success"} or int(data.get("progress") or 0) >= 100:
                self._active_session["state"] = "completed"
                self._active_session["error_code"] = None
                self._active_session["error_message"] = None
                self._active_session["printer_fault"] = None
            elif status in {"failed", "error"}:
                self._active_session["state"] = "failed"
                self._active_session["error_code"] = data.get("error_code")
                self._active_session["error_message"] = data.get("message") or data.get("error_message")
                self._active_session["printer_fault"] = deepcopy(data.get("printer_fault"))
            else:
                self._active_session["state"] = "printing"
            self._active_session["updated_at"] = time.time()

            enriched = deepcopy(data)
            enriched["session_id"] = self._active_session["session_id"]
            return enriched

    def matches(self, session_id: Optional[str], file_id: Optional[str] = None) -> bool:
        with self._lock:
            if not self._active_session or not session_id:
                return False
            if self._active_session["session_id"] != session_id:
                return False
            if file_id is not None and self._active_session.get("file_id") != file_id:
                return False
            return True

    def build_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            if not self._active_session:
                return {
                    "active": False,
                    "session_id": None,
                    "state": "idle",
                    "file_id": None,
                    "file_url": None,
                    "file_name": None,
                    "file_type": None,
                    "job_id": None,
                    "submitted": False,
                    "error_code": None,
                    "error_message": None,
                    "printer_fault": None,
                }

            return {
                "active": True,
                "session_id": self._active_session["session_id"],
                "state": self._active_session.get("state") or "idle",
                "file_id": self._active_session.get("file_id"),
                "file_url": self._active_session.get("file_url"),
                "file_name": self._active_session.get("file_name"),
                "file_type": self._active_session.get("file_type"),
                "job_id": self._active_session.get("job_id"),
                "submitted": bool(self._active_session.get("submitted")),
                "error_code": self._active_session.get("error_code"),
                "error_message": self._active_session.get("error_message"),
                "printer_fault": deepcopy(self._active_session.get("printer_fault")),
            }

    def clear_session(self, session_id: Optional[str] = None) -> bool:
        with self._lock:
            if not self._active_session:
                return False
            if session_id and self._active_session["session_id"] != session_id:
                return False
            self._active_session = None
            return True
