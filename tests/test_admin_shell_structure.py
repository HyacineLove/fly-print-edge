import pathlib
import unittest
from functools import lru_cache


@lru_cache(maxsize=None)
def read_source(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


class AdminShellStructureTests(unittest.TestCase):
    def test_admin_index_contains_trimmed_navigation_and_feedback_shells(self):
        html = read_source("static/admin/html/index.html")
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
        self.assertNotIn('data-section="readiness"', html)
        self.assertNotIn("configTestCloudBtn", html)
        self.assertNotIn("nodeReregisterBtn", html)

    def test_admin_main_becomes_module_entry(self):
        script = read_source("static/admin/main.js")
        self.assertIn('from "./modules/state.js"', script)
        self.assertIn('from "./modules/render-sections.js"', script)
        self.assertIn('from "./modules/config-actions.js"', script)
        self.assertIn('from "./modules/printer-actions.js"', script)

    def test_runtime_section_contains_startup_toggle(self):
        render_script = read_source("static/admin/modules/render-sections.js")
        self.assertIn("runtime_autostart_enabled", render_script)
        self.assertIn("开机自启并自动打开用户页", render_script)

    def test_admin_overlay_flows_do_not_duplicate_progress_toasts(self):
        config_script = read_source("static/admin/modules/config-actions.js")
        printer_script = read_source("static/admin/modules/printer-actions.js")
        self.assertNotIn('showAdminToast("保存中', config_script)
        self.assertNotIn('showAdminToast("检查连接并注册节点中', config_script)
        self.assertNotIn('showAdminToast("刷新打印机中"', printer_script)
        self.assertIn('withPrinterOverlay("刷新打印机中...', printer_script)
        self.assertIn('withPrinterOverlay("添加中...', printer_script)
        self.assertIn('withPrinterOverlay("删除中...', printer_script)
        self.assertIn('withPrinterOverlay("重新注册中...', printer_script)

    def test_admin_printer_section_uses_single_refresh_action(self):
        html = read_source("static/admin/html/index.html")
        script = read_source("static/admin/main.js")
        self.assertNotIn("刷新全部", html)
        self.assertNotIn("刷新已管理", script)
        self.assertNotIn("刷新可添加", script)

    def test_admin_printer_section_has_direct_ipp_management(self):
        render_script = read_source("static/admin/modules/render-sections.js")
        printer_script = read_source("static/admin/modules/printer-actions.js")
        self.assertIn("测试打印", render_script)
        self.assertIn("test-printer", render_script)
        self.assertIn("/printer-tests/", printer_script)
        self.assertNotIn("打印就绪", render_script)
        self.assertIn("IPP", render_script)
        self.assertIn("probe-ipp", render_script)
        self.assertIn("add-probed", render_script)
        self.assertIn("isPrinterActionPending", render_script)
        self.assertIn("确认后可添加", printer_script)
        self.assertNotIn("WSD", render_script)
        self.assertNotIn("Windows 队列", render_script)

    def test_managed_printer_table_displays_device_model(self):
        render_script = read_source("static/admin/modules/render-sections.js")
        self.assertIn("<th>型号</th>", render_script)
        self.assertIn('item.make_model || "-"', render_script)

    def test_discovered_printer_table_displays_device_model(self):
        render_script = read_source("static/admin/modules/render-sections.js")
        discovered_start = render_script.index("function renderDiscoveredTable")
        discovered_end = render_script.index("function renderPrintersSection", discovered_start)
        discovered_block = render_script[discovered_start:discovered_end]
        self.assertIn("<th>型号</th>", render_script)
        self.assertIn('item.make_model || "-"', discovered_block)
        self.assertIn('colspan="6"', discovered_block)

    def test_admin_input_updates_only_refresh_toolbar_state(self):
        config_script = read_source("static/admin/modules/config-actions.js")
        render_script = read_source("static/admin/modules/render-sections.js")
        normalized = config_script.replace("\r\n", "\n")
        input_block_start = normalized.index('panel?.addEventListener("input", (event) => {')
        input_block_end = normalized.index("\n  });\n}", input_block_start)
        input_block = normalized[input_block_start:input_block_end]

        self.assertIn("export function renderAdminToolbar(state)", render_script)
        self.assertIn("renderAdminToolbar(state);", config_script)
        self.assertNotIn("render();", input_block)

    def test_initial_load_does_not_preload_printers(self):
        config_script = read_source("static/admin/modules/config-actions.js")
        normalized = config_script.replace("\r\n", "\n")
        start = normalized.index("export async function loadInitialAdminData")
        block = normalized[start:]
        self.assertNotIn("refreshPrinters(", block)
        self.assertIn("loadStartupState", block)

    def test_printers_load_only_when_printer_section_is_opened(self):
        config_script = read_source("static/admin/modules/config-actions.js")
        state_script = read_source("static/admin/modules/state.js")
        self.assertIn("ensurePrintersLoaded", config_script)
        self.assertIn('section === "printers"', config_script)
        self.assertIn("printersLoadedOnce", state_script)
        self.assertIn("printersInvalidated", state_script)


if __name__ == "__main__":
    unittest.main()
