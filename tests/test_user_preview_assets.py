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


if __name__ == "__main__":
    unittest.main()
