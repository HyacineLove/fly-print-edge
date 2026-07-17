import pathlib
import re
import unittest


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

        html = path.read_text(encoding="utf-8")
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

        script = path.read_text(encoding="utf-8")
        self.assertTrue(script.strip(), "SPA entry app.js should not be empty")

    def test_user_spa_entry_and_views_avoid_full_page_navigation(self):
        navigation_files = ["app.js", *REQUIRED_SPA_FILES[1:5]]
        self._require_existing_files(navigation_files, "missing SPA files for navigation contract")

        for relative_path in navigation_files:
            path = BASE_DIR / relative_path
            script = path.read_text(encoding="utf-8")
            for pattern in FULL_PAGE_NAVIGATION_PATTERNS:
                with self.subTest(path=str(path), pattern=pattern):
                    self.assertNotRegex(script, pattern, f"{path} should not trigger full-page navigation via pattern {pattern}")

    def test_sse_client_module_uses_eventsource_api(self):
        path = BASE_DIR / "modules/app/sse-client.js"
        self.assertTrue(path.exists(), f"missing SSE client: {path}")

        script = path.read_text(encoding="utf-8")
        self.assertIn("EventSource", script, "sse-client.js should use the EventSource API")

    def test_printer_fault_locking_contract_is_present_in_user_views(self):
        done_view = (BASE_DIR / "modules/views/done-view.js").read_text(encoding="utf-8")
        login_view = (BASE_DIR / "modules/views/login-view.js").read_text(encoding="utf-8")
        runtime = (BASE_DIR / "modules/shared/runtime.js").read_text(encoding="utf-8")
        api = (BASE_DIR / "modules/shared/api.js").read_text(encoding="utf-8")

        self.assertIn("printerAvailability", api)
        self.assertIn("printer_fault", runtime)
        self.assertNotIn("media-needed-error", runtime)
        self.assertIn("isPrinterFaultResult", done_view)
        self.assertIn("printer_out_of_paper", done_view)
        self.assertIn("printer_out_of_toner", done_view)
        self.assertIn("availabilityPollTimer", done_view)
        self.assertIn("printerAvailability", login_view)
        self.assertIn("setPrinterFaultLocked", login_view)

    def test_printer_fault_done_view_does_not_auto_restart_until_recovered(self):
        done_view = (BASE_DIR / "modules/views/done-view.js").read_text(encoding="utf-8")

        self.assertRegex(
            done_view,
            r"if\s*\(\s*isPrinterFaultResult\(\)\s*\)\s*\{[\s\S]*?return;",
            "printer fault result should short-circuit normal countdown restart",
        )
        self.assertIn("打印机已恢复", done_view)

    def test_printer_fault_done_view_hides_countdown_accessory_before_and_after_recovery(self):
        done_view = (BASE_DIR / "modules/views/done-view.js").read_text(encoding="utf-8")

        self.assertIn("function setCountdownAccessoryVisible", done_view)
        self.assertRegex(
            done_view,
            r"if\s*\(\s*isPrinterFaultResult\(\)\s*\)\s*\{[\s\S]*?setCountdownAccessoryVisible\(false\)",
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
        controller = (BASE_DIR / "modules/app/app-controller.js").read_text(encoding="utf-8")

        self.assertNotIn("normalized.error_code", controller)
        self.assertNotIn("normalized.error_message", controller)
        self.assertIn("snapshot.error_code", controller)
        self.assertIn("snapshot.error_message", controller)

    def test_print_error_mapping_sanitizes_driver_and_job_tracking_errors(self):
        runtime = (BASE_DIR / "modules/shared/runtime.js").read_text(encoding="utf-8")

        self.assertNotIn("PCL XL", runtime)
        self.assertNotIn("MemAllocError", runtime)
        self.assertNotIn("ReadImage", runtime)
        self.assertNotIn("无法获取本地打印任务ID", runtime)
        self.assertNotIn("print_spooler_error", runtime)
        self.assertIn("无法确认本次打印结果，请勿重复提交", runtime)

    def test_default_scale_mode_is_actual_size_shrink_only_in_frontend(self):
        session_state = (BASE_DIR / "modules/shared/session-state.js").read_text(encoding="utf-8")
        admin_settings = pathlib.Path("static/admin/modules/render-sections.js").read_text(encoding="utf-8")

        self.assertIn('defaultScaleMode = "actual"', session_state)
        self.assertIn("原始尺寸/过大缩小", admin_settings)
        self.assertIn('cfg.default_scale_mode || "actual"', admin_settings)

    def test_printing_indicator_is_full_width_and_not_page_progress(self):
        view = (BASE_DIR / "modules/views/printing-view.js").read_text(encoding="utf-8")
        legacy = (BASE_DIR / "modules/pages/printing.js").read_text(encoding="utf-8")
        runtime = (BASE_DIR / "modules/shared/runtime.js").read_text(encoding="utf-8")
        controller = (BASE_DIR / "modules/app/app-controller.js").read_text(encoding="utf-8")
        css = (BASE_DIR / "css/printing.css").read_text(encoding="utf-8")

        self.assertIn("renderPrintingIndicator", view)
        self.assertIn("renderPrintingIndicator", legacy)
        self.assertNotIn("cur / all", view)
        self.assertNotIn("cur / all", legacy)
        self.assertNotIn("renderPrintingProgress", runtime)
        self.assertNotIn("progress >= 100", controller)
        self.assertRegex(css, r"\.Pixso-rectangle-77_20\s*\{[^}]*width:\s*556px")


    def test_preview_flow_preserves_content_hash_from_cloud_to_preview_api(self):
        controller = (BASE_DIR / "modules/app/app-controller.js").read_text(encoding="utf-8")
        preview_view = (BASE_DIR / "modules/views/preview-view.js").read_text(encoding="utf-8")

        self.assertIn("content_hash: data.content_hash", controller)
        self.assertIn("content_hash: normalized.content_hash", controller)
        self.assertIn("content_hash: session.file.content_hash", preview_view)

    def test_legacy_preview_flow_preserves_content_hash_from_cloud_to_preview_api(self):
        runtime = (BASE_DIR / "modules/shared/runtime.js").read_text(encoding="utf-8")
        preview = (BASE_DIR / "modules/pages/preview.js").read_text(encoding="utf-8")

        self.assertIn("content_hash: data.content_hash", runtime)
        self.assertIn("content_hash: state.file.content_hash", preview)


if __name__ == "__main__":
    unittest.main()
