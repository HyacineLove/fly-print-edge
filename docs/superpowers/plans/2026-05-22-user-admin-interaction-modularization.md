# User And Admin Interaction Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the oversized user/admin frontend entry scripts into native browser modules, then implement the approved QR, preview, admin feedback, and printer-capability interaction improvements.

**Architecture:** Keep the existing FastAPI + static-file architecture, but convert both frontend surfaces to single `type="module"` entry points that dispatch into focused modules. After the split is stable, layer in a shared toast/loading pattern, simplify the admin navigation and refresh flow, and extend admin printer APIs with capability-summary fields so the UI can render concise support status without duplicating parser logic.

**Tech Stack:** Python, FastAPI, pytest/unittest, vanilla JavaScript ES modules, static HTML/CSS

---

### Task 1: Lock The New UI Contract With Failing Tests

**Files:**
- Modify: `tests/test_admin_shell_structure.py`
- Modify: `tests/test_user_preview_assets.py`
- Create: `tests/test_admin_printer_capabilities_api.py`

- [ ] **Step 1: Extend the admin shell structure test with the new navigation, module entry, and overlay requirements**

```python
    def test_admin_shell_uses_module_entry_and_trimmed_navigation(self):
        html = pathlib.Path("static/admin/html/index.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('data-section="cloud"', html)
        self.assertIn('data-section="settings"', html)
        self.assertIn('data-section="runtime"', html)
        self.assertIn('data-section="printers"', html)
        self.assertNotIn('data-section="overview"', html)
        self.assertNotIn('data-section="discovery"', html)
        self.assertIn('id="adminToast"', html)
        self.assertIn('id="adminLoadingOverlay"', html)
```

- [ ] **Step 2: Extend the user preview asset test with the new login toast/icon and preview-triangle requirements**

```python
    def test_login_html_uses_module_entry_and_toast_shell(self):
        html = pathlib.Path("static/user/html/login.html").read_text(encoding="utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('id="userToast"', html)
        self.assertNotIn("已连接到云端服务器", html)
```

```python
    def test_preview_html_uses_triangle_copy_controls(self):
        html = pathlib.Path("static/user/html/preview.html").read_text(encoding="utf-8")
        self.assertIn("&#9664;", html)
        self.assertIn("&#9654;", html)
        self.assertNotIn(">+</p>", html)
        self.assertNotIn(">-</p>", html)
```

- [ ] **Step 3: Add a new failing admin printer capability API test**

```python
    def test_managed_printers_include_capability_summary(self):
        self.printer_manager.get_printer_capabilities.return_value = {
            "duplex": ["simplex", "duplex"],
            "color_model": ["Gray", "RGB"],
        }
        result = asyncio.run(main.get_managed_printers())
        item = result["items"][0]
        self.assertEqual(item["duplex_supported"], True)
        self.assertEqual(item["color_supported"], True)
        self.assertIn("单双面: 支持", item["capability_summary"])
        self.assertIn("彩色: 支持", item["capability_summary"])
```

- [ ] **Step 4: Run the targeted tests and verify they fail for the expected reasons**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_shell_structure.py tests/test_user_preview_assets.py tests/test_admin_printer_capabilities_api.py -q`

Expected: FAIL because the current HTML still uses legacy script loading, the QR page still contains the old status presentation, the preview page still uses text `- / +`, and the admin printer APIs do not return capability summary fields yet.

### Task 2: Split The User Frontend Into Native Modules

**Files:**
- Modify: `static/user/main.js`
- Modify: `static/user/html/login.html`
- Modify: `static/user/html/preview.html`
- Modify: `static/user/html/printing.html`
- Modify: `static/user/html/done.html`
- Create: `static/user/modules/shared/api.js`
- Create: `static/user/modules/shared/session-state.js`
- Create: `static/user/modules/shared/toast.js`
- Create: `static/user/modules/shared/clock.js`
- Create: `static/user/modules/shared/touch-guard.js`
- Create: `static/user/modules/shared/capabilities.js`
- Create: `static/user/modules/pages/login.js`
- Create: `static/user/modules/pages/preview.js`
- Create: `static/user/modules/pages/printing.js`
- Create: `static/user/modules/pages/done.js`

- [ ] **Step 1: Run the existing user preview asset tests first to establish the red baseline**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: FAIL or partial PASS, confirming the old single-file script and pre-change markup are still in place.

- [ ] **Step 2: Replace the single-file user script with a module entry that dispatches by page**

```javascript
import { initTouchRestrictions } from "./modules/shared/touch-guard.js";
import { tickClockLoop } from "./modules/shared/clock.js";
import { initLoginPage } from "./modules/pages/login.js";
import { initPreviewPage } from "./modules/pages/preview.js";
import { initPrintingPage } from "./modules/pages/printing.js";
import { initDonePage } from "./modules/pages/done.js";

const page = document.body?.dataset?.page || "";
initTouchRestrictions();
tickClockLoop();

if (page === "login") initLoginPage();
if (page === "preview") initPreviewPage();
if (page === "printing") initPrintingPage();
if (page === "done") initDonePage();
```

- [ ] **Step 3: Move the existing shared helpers into focused user modules without changing behavior yet**

```javascript
export function getJson(url) { /* existing fetch helper */ }
export function postJson(url, data) { /* existing fetch helper */ }
export function loadSessionState() { /* existing sessionStorage logic */ }
export function saveSessionState(state) { /* existing sessionStorage logic */ }
```

- [ ] **Step 4: Convert each user HTML page to `type="module"` loading**

```html
<script src="../main.js" type="module"></script>
```

- [ ] **Step 5: Re-run the targeted user asset test and verify the module-entry expectations now pass before interaction changes**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: remaining failures should now be about the QR/preview interaction markup, not about missing module entry support.

### Task 3: Implement QR Page Toast Feedback And Preview Triangle Controls

**Files:**
- Modify: `static/user/html/login.html`
- Modify: `static/user/css/login.css`
- Modify: `static/user/html/preview.html`
- Modify: `static/user/css/preview.css`
- Modify: `static/user/modules/shared/toast.js`
- Modify: `static/user/modules/pages/login.js`
- Modify: `static/user/modules/pages/preview.js`
- Modify: `tests/test_user_preview_assets.py`

- [ ] **Step 1: Keep the tests red by asserting the new QR and preview behaviors explicitly**

```python
    def test_user_script_contains_qr_loading_toast_copy(self):
        script = pathlib.Path("static/user/modules/pages/login.js").read_text(encoding="utf-8")
        self.assertIn("获取二维码中", script)
        self.assertNotIn("正在手动刷新二维码", script)
```

```python
    def test_preview_script_keeps_copy_and_duplex_changes_off_preview_refresh(self):
        script = pathlib.Path("static/user/modules/pages/preview.js").read_text(encoding="utf-8")
        copies_handler = re.search(r"const changeCopies = \\(delta\\) => \\{(?P<body>.*?)\\n    \\};", script, re.S)
        duplex_handler = re.search(r"const pickDuplex = \\(value\\) => \\{(?P<body>.*?)\\n    \\};", script, re.S)
        self.assertNotIn("queuePreviewRefresh()", copies_handler.group("body"))
        self.assertNotIn("queuePreviewRefresh()", duplex_handler.group("body"))
```

- [ ] **Step 2: Add the user toast shell and QR icon toggles in login markup/CSS**

```html
<div id="userToast" class="user-toast is-hidden" aria-live="polite"></div>
```

```css
.qr-center-art.is-hidden {
  display: none;
}
```

- [ ] **Step 3: Implement QR page status mapping to toast-only feedback**

```javascript
showUserToast("获取二维码中", "info");
setQrCenterVisible(false);
...
showUserToast(mapQrErrorMessage(...), "error");
...
setQrCenterVisible(true);
hideUserToast();
```

- [ ] **Step 4: Update the preview copies control markup and styling to triangles with aligned cells**

```html
<p id="55_117" class="Pixso-paragraph-55_117" data-role="copies-decrement">&#9664;</p>
<p id="55_118" class="Pixso-paragraph-55_118" data-role="copies-value">1</p>
<p id="55_119" class="Pixso-paragraph-55_119" data-role="copies-increment">&#9654;</p>
```

```css
.preview-option-cell {
  width: 114px;
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
}
```

- [ ] **Step 5: Keep the existing preview refresh semantics while moving them into the new page module**

```javascript
const changeCopies = (delta) => {
  state.options.copies = normalizeCopies(Number(state.options.copies || 1) + delta);
  saveSessionState(state);
  renderOptionsUI();
  resumePreviewCountdown(true);
};

const pickDuplex = (value) => {
  if (!state.capabilityState?.duplexSupported && value !== "simplex") return;
  state.options.duplex = value;
  saveSessionState(state);
  renderOptionsUI();
  resumePreviewCountdown(true);
};
```

- [ ] **Step 6: Re-run the targeted user asset tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: PASS with the login toast, QR icon visibility, triangle controls, and refresh-policy assertions all green.

### Task 4: Split The Admin Frontend And Add Toast/Loading Feedback

**Files:**
- Modify: `static/admin/main.js`
- Modify: `static/admin/html/index.html`
- Modify: `static/admin/css/admin.css`
- Create: `static/admin/modules/api.js`
- Create: `static/admin/modules/state.js`
- Create: `static/admin/modules/toast.js`
- Create: `static/admin/modules/loading-overlay.js`
- Create: `static/admin/modules/render-sections.js`
- Create: `static/admin/modules/config-actions.js`
- Create: `static/admin/modules/printer-actions.js`
- Create: `static/admin/modules/printer-capabilities.js`
- Modify: `tests/test_admin_shell_structure.py`

- [ ] **Step 1: Run the admin shell tests first to keep the navigation and module split work test-first**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_shell_structure.py -q`

Expected: FAIL until the HTML and JS are moved to the new module structure.

- [ ] **Step 2: Convert the admin HTML shell to the new navigation and global feedback containers**

```html
<section id="adminToast" class="admin-toast is-hidden" aria-live="polite"></section>
<section id="adminLoadingOverlay" class="admin-loading-overlay is-hidden">加载中...</section>
```

```html
<button type="button" class="nav-item is-active" data-section="cloud">云端配置</button>
<button type="button" class="nav-item" data-section="settings">打印默认设置</button>
<button type="button" class="nav-item" data-section="runtime">运行设置</button>
<button type="button" class="nav-item" data-section="printers">打印机管理</button>
```

- [ ] **Step 3: Replace the admin single-file script with a module entry and focused action/render helpers**

```javascript
import { createAdminState } from "./modules/state.js";
import { bindConfigActions } from "./modules/config-actions.js";
import { bindPrinterActions } from "./modules/printer-actions.js";
import { renderAdminApp } from "./modules/render-sections.js";

const state = createAdminState();
renderAdminApp(state);
bindConfigActions(state);
bindPrinterActions(state);
```

- [ ] **Step 4: Implement button-disable-without-label-change, toast, and overlay behavior**

```javascript
configSaveBtn.disabled = state.saving || !state.config || !isDirty(state);
cloudCheckRegisterBtn.disabled = state.testingCloud || !state.config;
showAdminToast("保存配置中", "info");
showAdminLoading("加载中...");
```

- [ ] **Step 5: Simplify printer management to a single refresh action**

```javascript
<button type="button" class="btn btn-primary" data-action="refresh-printers">刷新</button>
```

```javascript
if (action === "refresh-printers") {
  await refreshPrinterSections(state);
}
```

- [ ] **Step 6: Re-run the admin shell tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_shell_structure.py -q`

Expected: PASS with navigation removal, module entry, single refresh button, and toast/loading shell all verified.

### Task 5: Extend Admin Printer APIs With Capability Summary And Wire The UI

**Files:**
- Modify: `main.py`
- Modify: `tests/test_admin_printer_capabilities_api.py`
- Modify: `static/admin/modules/printer-capabilities.js`
- Modify: `static/admin/modules/render-sections.js`

- [ ] **Step 1: Run the new admin printer capability API test and verify the red baseline**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_printer_capabilities_api.py -q`

Expected: FAIL because the printer API responses do not yet include the new summary fields.

- [ ] **Step 2: Add a backend helper that normalizes capability data into a tri-state summary**

```python
def _build_printer_capability_summary(capabilities: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    duplex_supported = _capability_tristate_from_duplex(capabilities)
    color_supported = _capability_tristate_from_color(capabilities)
    return {
        "duplex_supported": duplex_supported,
        "color_supported": color_supported,
        "capability_summary": f"单双面: {_capability_label(duplex_supported)}, 彩色: {_capability_label(color_supported)}",
    }
```

- [ ] **Step 3: Include the summary fields in both managed and discovered printer payloads**

```python
    items.append({
        **printer,
        **_build_printer_capability_summary(printer_manager.get_printer_capabilities(printer.get("name"))),
    })
```

- [ ] **Step 4: Render the new capability column in admin printer tables**

```javascript
<th>能力</th>
...
<td>${item.capability_summary || "单双面: 未知, 彩色: 未知"}</td>
```

- [ ] **Step 5: Re-run the targeted capability API and admin shell tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_printer_capabilities_api.py tests/test_admin_shell_structure.py -q`

Expected: PASS with the API summary and UI column both green.

### Task 6: Run Focused Regression And Full Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-05-22-user-admin-interaction-modularization.md`

- [ ] **Step 1: Run the focused regression suite for all touched behavior**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_config_service.py tests/test_admin_config_api.py tests/test_admin_shell_structure.py tests/test_user_preview_print_api.py tests/test_user_preview_assets.py tests/test_admin_printer_capabilities_api.py -q`

Expected: PASS with no failures; any warnings should be existing framework warnings only.

- [ ] **Step 2: Run the full project test suite**

Run: `.\\venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS with the same warning profile as before this change.

- [ ] **Step 3: Review the final diff coverage**

Run: `git diff --stat`

Expected: user modules, admin modules, HTML/CSS, backend API, and tests all represented.

- [ ] **Step 4: Commit the implementation changes**

```bash
git add static/user/main.js static/user/html/login.html static/user/html/preview.html static/user/html/printing.html static/user/html/done.html static/user/css/login.css static/user/css/preview.css static/user/modules static/admin/main.js static/admin/html/index.html static/admin/css/admin.css static/admin/modules main.py tests/test_admin_shell_structure.py tests/test_user_preview_assets.py tests/test_admin_printer_capabilities_api.py docs/superpowers/plans/2026-05-22-user-admin-interaction-modularization.md
git commit -m "feat: modularize user and admin interaction flows"
```
