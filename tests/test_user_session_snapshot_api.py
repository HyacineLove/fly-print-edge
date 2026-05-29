import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from interactive_session import InteractiveSessionManager


STUBBABLE_THIRD_PARTY_MODULES = {"fitz", "pandas"}


def _install_minimal_module_stub(module_name):
    if module_name in sys.modules:
        return
    sys.modules[module_name] = types.ModuleType(module_name)


def _import_main_module():
    if "main" in sys.modules:
        return sys.modules["main"]

    while True:
        try:
            return importlib.import_module("main")
        except ModuleNotFoundError as exc:
            missing_name = (exc.name or "").split(".", 1)[0]
            if missing_name not in STUBBABLE_THIRD_PARTY_MODULES:
                raise
            _install_minimal_module_stub(missing_name)


class UserSessionSnapshotContractTests(unittest.TestCase):
    def setUp(self):
        self.manager = InteractiveSessionManager()
        self.main = _import_main_module()

    def _get_current_session_snapshot(self):
        with patch.object(self.main, "interactive_session_manager", self.manager):
            with TestClient(self.main.app) as client:
                response = client.get("/api/session/current")
        return response

    def test_session_current_route_returns_http_200(self):
        response = self._get_current_session_snapshot()
        self.assertEqual(
            200,
            response.status_code,
            f"GET /api/session/current should be registered and return 200, got {response.status_code} with body {response.text!r}",
        )

    def test_session_current_contract_returns_idle_snapshot_without_active_session(self):
        response = self._get_current_session_snapshot()
        self.assertEqual(
            200,
            response.status_code,
            f"GET /api/session/current should return 200 for idle state, got {response.status_code} with body {response.text!r}",
        )
        self.assertEqual(
            {
                "active": False,
                "session_id": None,
                "state": "idle",
                "file_id": None,
                "file_url": None,
                "file_name": None,
                "file_type": None,
                "job_id": None,
                "submitted": False,
            },
            response.json(),
        )

    def test_session_current_contract_returns_preview_ready_snapshot(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event(
            {
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
            }
        )

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "preview_ready",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": None,
                "submitted": False,
            },
            response.json(),
        )

    def test_session_current_contract_returns_print_submitted_snapshot_before_job_binding(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "print_submitted",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": None,
                "submitted": True,
            },
            response.json(),
        )

    def test_session_current_contract_returns_preview_ready_snapshot_after_submission_revert(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.revert_print_submission(session["session_id"], "file-1")

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "preview_ready",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": None,
                "submitted": False,
            },
            response.json(),
        )

    def test_session_current_contract_clears_job_binding_after_submission_revert(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.attach_cloud_job("/api/v1/files/file-1", "job-42")
        self.manager.revert_print_submission(session["session_id"], "file-1")

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "preview_ready",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": None,
                "submitted": False,
            },
            response.json(),
        )

    def test_session_current_contract_returns_printing_snapshot_after_job_binding(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.attach_cloud_job("/api/v1/files/file-1", "job-42")

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "printing",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": "job-42",
                "submitted": True,
            },
            response.json(),
        )

    def test_session_current_contract_returns_completed_snapshot_after_terminal_job_event(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.attach_cloud_job("/api/v1/files/file-1", "job-42")
        self.manager.accept_job_status_event({"job_id": "job-42", "status": "completed"})

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "completed",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": "job-42",
                "submitted": True,
            },
            response.json(),
        )

    def test_session_current_contract_returns_failed_snapshot_after_failed_job_event(self):
        session = self.manager.start_session(upload_token="token-1")
        preview_payload = {
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        }
        self.manager.accept_preview_event(preview_payload)
        self.manager.mark_print_submitted(session["session_id"], "file-1")
        self.manager.attach_cloud_job("/api/v1/files/file-1", "job-42")
        self.manager.accept_job_status_event({"job_id": "job-42", "status": "failed"})

        response = self._get_current_session_snapshot()
        self.assertEqual(200, response.status_code, f"GET /api/session/current should return 200, got {response.status_code} with body {response.text!r}")
        self.assertEqual(
            {
                "active": True,
                "session_id": session["session_id"],
                "state": "failed",
                "file_id": "file-1",
                "file_url": "/api/v1/files/file-1",
                "file_name": "demo.pdf",
                "file_type": "application/pdf",
                "job_id": "job-42",
                "submitted": True,
            },
            response.json(),
        )


if __name__ == "__main__":
    unittest.main()
