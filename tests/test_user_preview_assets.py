import pathlib
import re
import unittest
from functools import lru_cache


BASE_DIR = pathlib.Path("static/user")
REQUIRED_SPA_FILES = [
    "app.js",
    "modules/views/login-view.js",
    "modules/views/preview-view.js",
    "modules/views/printing-view.js",
    "modules/views/done-view.js",
    "modules/app/sse-client.js",
]
FULL_PAGE_NAVIGATION_PATTERNS = [
    r"window\.location\.href\s*=",
    r"window\.location\.replace\s*\(",
    r"window\.location\.assign\s*\(",
    r"location\.href\s*=",
    r"location\.replace\s*\(",
    r"location\.assign\s*\(",
]


@lru_cache(maxsize=None)
def read_source(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


class UserPreviewAssetTests(unittest.TestCase):
    def _require_existing_files(self, relative_paths, message_prefix):
        missing = [str(BASE_DIR / relative_path) for relative_path in relative_paths if not (BASE_DIR / relative_path).exists()]
        self.assertEqual([], missing, f"{message_prefix}: {missing}")

    def test_user_spa_required_files_exist(self):
        self._require_existing_files(REQUIRED_SPA_FILES, "missing SPA files")

    def test_user_index_shell_contains_app_mount_and_module_entry(self):
        path = BASE_DIR / "index.html"
        self.assertTrue(path.exists(), f"missing SPA shell: {path}")
        self._require_existing_files(["app.js"], "missing SPA entry required by shell")

        html = read_source(path)
        self.assertIn('id="app"', html, "SPA shell should expose a single #app mount node")
        self.assertIn('type="module"', html, "SPA shell should load the frontend through a module script")
        self.assertRegex(
            html,
            r'src=["\']/static/user/app\.js["\']',
            "SPA shell should bootstrap /static/user/app.js so it also works when served from /",
        )
        self.assertIn('href="/static/user/css/login.css"', html, "SPA shell should use absolute CSS paths")
        for pattern in FULL_PAGE_NAVIGATION_PATTERNS:
            self.assertNotRegex(html, pattern, f"SPA shell should not trigger full-page navigation via pattern {pattern}")

    def test_user_app_entry_exists_and_is_not_empty(self):
        path = BASE_DIR / "app.js"
        self.assertTrue(path.exists(), f"missing SPA entry: {path}")

        script = read_source(path)
        self.assertTrue(script.strip(), "SPA entry app.js should not be empty")

    def test_user_spa_entry_and_views_avoid_full_page_navigation(self):
        navigation_files = ["app.js", *REQUIRED_SPA_FILES[1:5]]
        self._require_existing_files(navigation_files, "missing SPA files for navigation contract")

        for relative_path in navigation_files:
            path = BASE_DIR / relative_path
            script = read_source(path)
            for pattern in FULL_PAGE_NAVIGATION_PATTERNS:
                with self.subTest(path=str(path), pattern=pattern):
                    self.assertNotRegex(script, pattern, f"{path} should not trigger full-page navigation via pattern {pattern}")

    def test_sse_client_module_uses_eventsource_api(self):
        path = BASE_DIR / "modules/app/sse-client.js"
        self.assertTrue(path.exists(), f"missing SSE client: {path}")

        script = read_source(path)
        self.assertIn("EventSource", script, "sse-client.js should use the EventSource API")

    def test_printer_fault_locking_contract_is_present_in_user_views(self):
        done_view = read_source(BASE_DIR / "modules/views/done-view.js")
        login_view = read_source(BASE_DIR / "modules/views/login-view.js")
        runtime = read_source(BASE_DIR / "modules/shared/runtime.js")
        api = read_source(BASE_DIR / "modules/shared/api.js")

        self.assertIn("printerAvailability", api)
        self.assertIn('qr: "/api/qr_code"', api)
        self.assertIn("printer_fault", runtime)
        self.assertNotIn("media-needed-error", runtime)
        self.assertIn("isPrinterFaultResult", done_view)
        self.assertIn("printer_out_of_paper", done_view)
        self.assertIn("printer_out_of_toner", done_view)
        self.assertIn("availabilityPollTimer", done_view)
        self.assertIn("printerAvailability", login_view)
        self.assertIn("setPrinterFaultLocked", login_view)

    def test_cloud_availability_errors_use_the_countdown_without_retry_toast_text(self):
        login_view = read_source(BASE_DIR / "modules/views/login-view.js")
        runtime = read_source(BASE_DIR / "modules/shared/runtime.js")
        api = read_source(BASE_DIR / "modules/shared/api.js")

        self.assertIn("cloudAccessLocked", login_view)
        self.assertIn("terminalActivationRequired", login_view)
        self.assertIn("refreshQrCode({ automatic: true })", login_view)
        self.assertNotIn("loginQrRetrySuffix", login_view)
        self.assertNotIn("loginQrRetrySuffix", runtime)
        self.assertIn('error.code = json?.error_code || json?.code || ""', api)
        self.assertIn("cloud_response_timeout", runtime)

    def test_print_error_mapping_covers_cloud_availability_errors(self):
        runtime = read_source(BASE_DIR / "modules/shared/runtime.js")

        for error_code in ("node_disabled", "node_not_found", "printer_disabled", "printer_not_found"):
            with self.subTest(error_code=error_code):
                self.assertIn(f"{error_code}:", runtime)

    def test_printer_fault_done_view_does_not_auto_restart_until_recovered(self):
        done_view = read_source(BASE_DIR / "modules/views/done-view.js")

        self.assertRegex(
            done_view,
            r"if\s*\(\s*isPrinterFaultResult\(\)\s*\|\|\s*isUnconfirmedResult\(\)\s*\)\s*\{[\s\S]*?return;",
            "printer fault result should short-circuit normal countdown restart",
        )
        self.assertIn("打印机已恢复", done_view)

    def test_printer_fault_done_view_hides_countdown_accessory_before_and_after_recovery(self):
        done_view = read_source(BASE_DIR / "modules/views/done-view.js")

        self.assertIn("function setCountdownAccessoryVisible", done_view)
        self.assertRegex(
            done_view,
            r"if\s*\(\s*isPrinterFaultResult\(\)\s*\|\|\s*isUnconfirmedResult\(\)\s*\)\s*\{[\s\S]*?setCountdownAccessoryVisible\(false\)",
        )
        self.assertRegex(
            done_view,
            r"打印机已恢复[\s\S]*?setCountdownAccessoryVisible\(false\)",
        )
        self.assertRegex(
            done_view,
            r"if\s*\(\s*result\.type\s*===\s*\"error\"[\s\S]*?setCountdownAccessoryVisible\(true\)",
        )

    def test_app_controller_failed_snapshot_uses_snapshot_error_fields(self):
        controller = read_source(BASE_DIR / "modules/app/app-controller.js")

        self.assertNotIn("normalized.error_code", controller)
        self.assertNotIn("normalized.error_message", controller)
        self.assertIn("snapshot.error_code", controller)
        self.assertIn("snapshot.error_message", controller)

    def test_print_error_mapping_sanitizes_driver_and_job_tracking_errors(self):
        runtime = read_source(BASE_DIR / "modules/shared/runtime.js")

        self.assertNotIn("PCL XL", runtime)
        self.assertNotIn("MemAllocError", runtime)
        self.assertNotIn("ReadImage", runtime)
        self.assertNotIn("无法获取本地打印任务ID", runtime)
        self.assertNotIn("print_spooler_error", runtime)
        self.assertIn("无法确认本次打印结果，请勿重复提交", runtime)

    def test_default_scale_mode_is_actual_size_shrink_only_in_frontend(self):
        session_state = read_source(BASE_DIR / "modules/shared/session-state.js")
        admin_settings = read_source("static/admin/modules/render-sections.js")

        self.assertIn('defaultScaleMode = "actual"', session_state)
        self.assertIn("原始尺寸/过大缩小", admin_settings)
        self.assertIn('cfg.default_scale_mode || "actual"', admin_settings)

    def test_printing_indicator_is_full_width_and_uses_device_page_progress(self):
        view = read_source(BASE_DIR / "modules/views/printing-view.js")
        runtime = read_source(BASE_DIR / "modules/shared/runtime.js")
        controller = read_source(BASE_DIR / "modules/app/app-controller.js")
        css = read_source(BASE_DIR / "css/printing.css")

        self.assertIn("renderPrintingIndicator", view)
        self.assertIn("current_page", view)
        self.assertIn("total_pages", view)
        self.assertIn("正在打印，第", view)
        self.assertIn("页……", view)
        self.assertIn("completedPages + 1", view)
        self.assertIn("Math.min(completedPages + 1, totalPages)", view)
        self.assertIn("data.current_page !== null", view)
        self.assertNotIn("张……", view)
        self.assertNotIn("printing-indicator-label", view)
        self.assertIn('aria-live="polite"', view)
        self.assertIn('id="printing_status_message"', view)
        self.assertIn('q("printing_status_message")', view)
        self.assertRegex(css, r"\.printing-status-message\s*\{[^}]*top:\s*1148px")
        self.assertNotIn(".Pixso-paragraph-115_26", css)
        self.assertNotIn("renderPrintingProgress", runtime)
        self.assertNotIn("progress >= 100", controller)
        self.assertRegex(css, r"\.Pixso-rectangle-77_20\s*\{[^}]*width:\s*556px")


    def test_preview_flow_preserves_content_hash_from_cloud_to_preview_api(self):
        controller = read_source(BASE_DIR / "modules/app/app-controller.js")
        preview_view = read_source(BASE_DIR / "modules/views/preview-view.js")

        self.assertIn("content_hash: data.content_hash", controller)
        self.assertIn("content_hash: normalized.content_hash", controller)
        self.assertIn("content_hash: session.file.content_hash", preview_view)

    def test_removed_legacy_pages_do_not_reintroduce_duplicate_frontend_logic(self):
        self.assertFalse((BASE_DIR / "main.js").exists())
        self.assertEqual([], list((BASE_DIR / "modules/pages").glob("*.js")))


if __name__ == "__main__":
    unittest.main()
