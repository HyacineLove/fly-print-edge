import pathlib
import re
import unittest


class UserPreviewAssetTests(unittest.TestCase):
    def test_login_html_uses_module_entry_and_toast_shell(self):
        html = pathlib.Path("static/user/html/login.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('id="userToast"', html)
        self.assertNotIn("已连接到云端服务器", html)

    def test_preview_html_uses_triangle_copy_controls(self):
        html = pathlib.Path("static/user/html/preview.html").read_text(encoding="utf-8")
        self.assertIn('data-role="copies-decrement"', html)
        self.assertIn('data-role="copies-value"', html)
        self.assertIn('data-role="copies-increment"', html)
        self.assertIn("&#9664;", html)
        self.assertIn("&#9654;", html)
        self.assertNotIn(">-<", html)
        self.assertNotIn(">+<", html)
        self.assertNotIn(">2<", html)
        self.assertNotIn(">3<", html)

    def test_user_main_becomes_module_entry(self):
        script = pathlib.Path("static/user/main.js").read_text(encoding="utf-8")
        self.assertIn('from "./modules/shared/touch-guard.js"', script)
        self.assertIn('from "./modules/pages/login.js"', script)
        self.assertIn('from "./modules/pages/preview.js"', script)

    def test_login_script_uses_unified_qr_loading_copy(self):
        script = pathlib.Path("static/user/modules/pages/login.js").read_text(encoding="utf-8")
        self.assertIn("获取二维码中", script)
        self.assertNotIn("正在手动刷新二维码", script)

    def test_preview_script_keeps_copy_and_duplex_changes_off_preview_refresh(self):
        script = pathlib.Path("static/user/modules/pages/preview.js").read_text(encoding="utf-8")
        copies_handler = re.search(r"const changeCopies = \(delta\) => \{(?P<body>.*?)\n\s+\};", script, re.S)
        duplex_handler = re.search(r"const pickDuplex = \(value\) => \{(?P<body>.*?)\n\s+\};", script, re.S)
        color_handler = re.search(r"const pickColor = \(value\) => \{(?P<body>.*?)\n\s+\};", script, re.S)
        self.assertIsNotNone(copies_handler)
        self.assertIsNotNone(duplex_handler)
        self.assertIsNotNone(color_handler)
        self.assertNotIn("queuePreviewRefresh()", copies_handler.group("body"))
        self.assertNotIn("queuePreviewRefresh()", duplex_handler.group("body"))
        self.assertIn("queuePreviewRefresh()", color_handler.group("body"))

    def test_preview_script_reconnects_sse_and_defers_print_submission(self):
        script = pathlib.Path("static/user/modules/pages/preview.js").read_text(encoding="utf-8")
        self.assertIn('from "../shared/sse.js"', script)
        self.assertIn('page: "preview"', script)
        self.assertNotIn('postJson("/api/print"', script)

    def test_printing_script_owns_print_submission(self):
        script = pathlib.Path("static/user/modules/pages/printing.js").read_text(encoding="utf-8")
        self.assertIn('createSseConnection', script)
        self.assertIn('postJson("/api/print"', script)

    def test_done_button_layout_uses_flex_alignment(self):
        css = pathlib.Path("static/user/css/done.css").read_text(encoding="utf-8")
        self.assertIn("width: 418px;", css)
        self.assertIn("height: 110px;", css)
        self.assertIn("justify-content: center;", css)
        self.assertIn("right: 24px;", css)
        self.assertIn("transform: translateY(-50%);", css)
        self.assertIn("line-height: 1;", css)


if __name__ == "__main__":
    unittest.main()
