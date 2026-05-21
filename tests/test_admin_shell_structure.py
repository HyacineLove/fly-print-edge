import pathlib
import unittest


class AdminShellStructureTests(unittest.TestCase):
    def test_admin_index_contains_config_navigation_targets(self):
        html = pathlib.Path("static/admin/html/index.html").read_text(encoding="utf-8")
        self.assertIn('data-section="cloud"', html)
        self.assertIn('id="configSaveBtn"', html)
        self.assertIn('id="cloudCheckRegisterBtn"', html)
        self.assertIn('id="configPanel"', html)
        self.assertNotIn('configTestCloudBtn', html)
        self.assertNotIn('nodeReregisterBtn', html)

    def test_admin_main_uses_chinese_labels_without_placeholder_garble(self):
        script = pathlib.Path("static/admin/main.js").read_text(encoding="utf-8")
        self.assertIn("云端配置", script)
        self.assertIn("打印机管理", script)
        self.assertIn("位置", script)
        self.assertIn("云端地址", script)
        self.assertIn("客户端密钥", script)
        self.assertIn("云端状态: 已连接", script)
        self.assertNotIn('label>??<', script)
        self.assertNotIn("Cloud Config", script)


if __name__ == "__main__":
    unittest.main()
