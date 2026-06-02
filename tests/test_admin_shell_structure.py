import pathlib
import unittest


class AdminShellStructureTests(unittest.TestCase):
    def test_admin_index_contains_trimmed_navigation_and_feedback_shells(self):
        html = pathlib.Path("static/admin/html/index.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('data-section="cloud"', html)
        self.assertIn('data-section="settings"', html)
        self.assertIn('data-section="runtime"', html)
        self.assertIn('data-section="printers"', html)
        self.assertIn('id="configSaveBtn"', html)
        self.assertIn('id="cloudCheckRegisterBtn"', html)
        self.assertIn('id="configPanel"', html)
        self.assertIn('id="adminToast"', html)
        self.assertIn('id="adminLoadingOverlay"', html)
        self.assertNotIn('data-section="overview"', html)
        self.assertNotIn('data-section="discovery"', html)
        self.assertNotIn("configTestCloudBtn", html)
        self.assertNotIn("nodeReregisterBtn", html)

    def test_admin_main_becomes_module_entry(self):
        script = pathlib.Path("static/admin/main.js").read_text(encoding="utf-8")
        self.assertIn('from "./modules/state.js"', script)
        self.assertIn('from "./modules/render-sections.js"', script)
        self.assertIn('from "./modules/config-actions.js"', script)
        self.assertIn('from "./modules/printer-actions.js"', script)

    def test_admin_overlay_flows_do_not_duplicate_progress_toasts(self):
        config_script = pathlib.Path("static/admin/modules/config-actions.js").read_text(encoding="utf-8")
        printer_script = pathlib.Path("static/admin/modules/printer-actions.js").read_text(encoding="utf-8")
        self.assertNotIn('showAdminToast("保存中', config_script)
        self.assertNotIn('showAdminToast("检查连接并注册节点中', config_script)
        self.assertNotIn('showAdminToast("刷新打印机中"', printer_script)
        self.assertIn('withPrinterOverlay("刷新打印机中...', printer_script)
        self.assertIn('withPrinterOverlay("添加中..', printer_script)
        self.assertIn('withPrinterOverlay("删除中..', printer_script)
        self.assertIn('withPrinterOverlay("重新注册中..', printer_script)

    def test_admin_printer_section_uses_single_refresh_action(self):
        html = pathlib.Path("static/admin/html/index.html").read_text(encoding="utf-8")
        script = pathlib.Path("static/admin/main.js").read_text(encoding="utf-8")
        self.assertNotIn("刷新全部", html)
        self.assertNotIn("刷新已管理", script)
        self.assertNotIn("刷新可添加", script)

    def test_admin_input_updates_only_refresh_toolbar_state(self):
        config_script = pathlib.Path("static/admin/modules/config-actions.js").read_text(encoding="utf-8")
        render_script = pathlib.Path("static/admin/modules/render-sections.js").read_text(encoding="utf-8")
        normalized = config_script.replace("\r\n", "\n")
        input_block_start = normalized.index('panel?.addEventListener("input", (event) => {')
        input_block_end = normalized.index('  panel?.addEventListener("click", (event) => {')
        input_block = normalized[input_block_start:input_block_end]

        self.assertIn("export function renderAdminToolbar(state)", render_script)
        self.assertIn("renderAdminToolbar(state);", config_script)
        self.assertNotIn("render();", input_block)


if __name__ == "__main__":
    unittest.main()
