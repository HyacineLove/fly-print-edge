# Edge Admin Config Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified `/admin` configuration center that manages most Edge settings through UI, applies cloud and print defaults immediately where safe, and preserves the existing `node_id` unless the user explicitly re-registers the node.

**Architecture:** Add a backend `ConfigService` that sits between `PrinterConfig` and the admin API, so configuration reads, masking, validation, persistence, and apply-results all happen in one place. Extend `CloudService` with a reconfigure path that rebuilds runtime clients while preserving `node_id`, then refactor the admin page into a single UTF-8 workbench that combines config groups and printer management.

**Tech Stack:** Python 3, FastAPI, existing `PrinterConfig`/`CloudService`, vanilla HTML/CSS/JavaScript admin UI, `unittest`, `node --check`.

---

## File Structure

### Backend config and runtime

- Create: `config_service.py`
  - Owns config serialization for UI, secret masking, validation, merge logic, and apply-result classification.
- Modify: `printer_config.py`
  - Add safe full-config read/write helpers that preserve current behavior for printer management.
- Modify: `cloud_service.py`
  - Add runtime reconfigure support that preserves `node_id` by default and only re-registers on explicit request.
- Modify: `main.py`
  - Add `/api/admin/config` and `/api/admin/config/test-cloud`, wire `ConfigService`, and keep existing printer admin endpoints working under the new page.
- Modify: `config.example.json`
  - Add representative defaults for config-center-managed sections.

### Admin frontend

- Modify: `static/admin/html/index.html`
  - Replace printer-only shell with unified workbench layout.
- Modify: `static/admin/css/admin.css`
  - Style grouped navigation, form panels, result banners, and restart-required states.
- Modify: `static/admin/main.js`
  - Fetch config, track dirty state, submit saves, test cloud connectivity, render grouped forms, and preserve existing printer-management actions.

### Tests

- Create: `tests/test_config_service.py`
  - Covers masking, secret merge semantics, restart-required classification, and config validation.
- Create: `tests/test_admin_config_api.py`
  - Covers config GET/POST/test-cloud endpoints and apply-result payloads.
- Create: `tests/test_cloud_service_reconfigure.py`
  - Covers `node_id` preservation and runtime reinitialization behavior.
- Create: `tests/test_admin_shell_structure.py`
  - Lightweight structural assertions for the new admin HTML/JS shell.

## Task 1: Build the backend config foundation

**Files:**
- Create: `config_service.py`
- Create: `tests/test_config_service.py`
- Modify: `printer_config.py`
- Modify: `config.example.json`

- [ ] **Step 1: Write the failing config-service tests**

```python
import unittest

from config_service import ConfigService


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self.raw_config = {
            "cloud": {
                "enabled": True,
                "base_url": "http://localhost:8012",
                "auth_url": "http://localhost:8012/auth/token",
                "client_id": "edge-default",
                "client_secret": "top-secret",
                "node_name": "edge-a",
                "location": "",
                "heartbeat_interval": 30,
                "auto_register": True,
                "node_id": "node-123",
            },
            "settings": {},
            "network": {"bind_address": "127.0.0.1", "port": 7860},
            "printers": {"discovery_mode": "auto", "static_list": []},
        }
        self.service = ConfigService(config_repo=None)

    def test_build_public_config_masks_secret(self):
        payload = self.service.build_public_config(self.raw_config)
        self.assertEqual(payload["cloud"]["client_secret"], "")
        self.assertTrue(payload["cloud"]["client_secret_configured"])

    def test_merge_update_keeps_existing_secret_when_blank(self):
        merged = self.service.merge_update(
            self.raw_config,
            {"cloud": {"client_secret": "", "base_url": "http://example.com"}},
        )
        self.assertEqual(merged["cloud"]["client_secret"], "top-secret")
        self.assertEqual(merged["cloud"]["base_url"], "http://example.com")

    def test_restart_required_fields_are_classified(self):
        result = self.service.classify_changes(
            before=self.raw_config,
            after={
                **self.raw_config,
                "network": {"bind_address": "0.0.0.0", "port": 9000},
            },
        )
        self.assertIn("network.bind_address", result["restart_required"])
        self.assertIn("network.port", result["restart_required"])
```

- [ ] **Step 2: Run the config-service tests to verify they fail**

Run: `python -m unittest tests.test_config_service -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'config_service'` or missing method errors.

- [ ] **Step 3: Implement the minimal config-service and repo helpers**

```python
# config_service.py
from copy import deepcopy
from typing import Any, Dict, List
from urllib.parse import urlparse


class ConfigService:
    RESTART_REQUIRED_FIELDS = {
        "network.bind_address",
        "network.port",
        "printers.discovery_mode",
        "printers.static_list",
    }

    def __init__(self, config_repo):
        self.config_repo = config_repo

    def build_public_config(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        data = deepcopy(raw)
        cloud = data.setdefault("cloud", {})
        secret = str(cloud.get("client_secret") or "")
        cloud["client_secret"] = ""
        cloud["client_secret_configured"] = bool(secret)
        return data

    def merge_update(self, raw: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        merged = deepcopy(raw)
        for section in ("cloud", "settings", "network", "printers"):
            if section not in update:
                continue
            merged.setdefault(section, {})
            for key, value in update[section].items():
                if section == "cloud" and key == "client_secret" and value == "":
                    continue
                merged[section][key] = value
        return merged

    def validate(self, raw: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for field in ("base_url", "auth_url"):
            value = str(raw.get("cloud", {}).get(field) or "").strip()
            if value and not urlparse(value).scheme:
                errors.append(f"cloud.{field} must be a valid URL")
        return errors
```

```python
# printer_config.py
from copy import deepcopy

def get_full_config(self) -> Dict:
    return deepcopy(self.config)

def replace_full_config(self, new_config: Dict):
    self.config = deepcopy(new_config)
    self.save_config()
```

```json
{
  "settings": {
    "default_paper_size": "A4",
    "default_scale_mode": "fit",
    "default_max_upscale": 3.0,
    "libreoffice_path": "",
    "pdf_printer_path": ""
  }
}
```

- [ ] **Step 4: Run the config-service tests to verify they pass**

Run: `python -m unittest tests.test_config_service -v`

Expected: PASS for masking, secret merge, and restart-required classification tests.

- [ ] **Step 5: Commit the backend config foundation**

```bash
git add config_service.py printer_config.py config.example.json tests/test_config_service.py
git commit -m "feat: add admin config service foundation"
```

## Task 2: Add admin config APIs and cloud runtime reconfigure

**Files:**
- Create: `tests/test_cloud_service_reconfigure.py`
- Create: `tests/test_admin_config_api.py`
- Modify: `cloud_service.py`
- Modify: `main.py`
- Modify: `config_service.py`

- [ ] **Step 1: Write the failing cloud/runtime and admin API tests**

```python
import unittest

from cloud_service import CloudService


class CloudServiceReconfigureTests(unittest.TestCase):
    def test_reconfigure_preserves_existing_node_id(self):
        service = CloudService(
            {
                "enabled": True,
                "base_url": "http://old",
                "auth_url": "http://old/auth",
                "client_id": "edge",
                "client_secret": "secret",
                "node_id": "node-123",
            }
        )
        result = service.reconfigure(
            {
                "enabled": True,
                "base_url": "http://new",
                "auth_url": "http://new/auth",
                "client_id": "edge",
                "client_secret": "secret",
                "node_id": "node-123",
            },
            preserve_node_id=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(service.node_id, "node-123")
```

```python
import unittest
from fastapi.testclient import TestClient

import main


class AdminConfigApiTests(unittest.TestCase):
    def test_get_config_masks_secret(self):
        client = TestClient(main.app)
        response = client.get("/api/admin/config")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cloud"]["client_secret"], "")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m unittest tests.test_cloud_service_reconfigure tests.test_admin_config_api -v`

Expected: FAIL because `CloudService.reconfigure` and `/api/admin/config` do not exist yet.

- [ ] **Step 3: Implement runtime reconfigure and config endpoints**

```python
# cloud_service.py
def reconfigure(self, new_config: Dict[str, Any], preserve_node_id: bool = True) -> Dict[str, Any]:
    old_node_id = self.node_id
    self.stop()
    self.config = dict(new_config)
    if preserve_node_id and old_node_id:
        self.config["node_id"] = old_node_id
        self.node_id = old_node_id
        self.registered = True
    else:
        self.node_id = self.config.get("node_id")
        self.registered = bool(self.node_id)
    self.enabled = self.config.get("enabled", False)
    self._initialize_components()
    return self.start()
```

```python
# main.py
@admin_router.get("/config")
async def get_admin_config():
    service = _get_config_service()
    payload = service.get_public_config()
    return {"success": True, **payload}


@admin_router.post("/config")
async def save_admin_config(request: Request):
    body = await request.json()
    service = _get_config_service()
    result = service.save_and_apply(body, cloud_service=cloud_service)
    status = 200 if result.get("success") else 400
    return JSONResponse(status_code=status, content=result)


@admin_router.post("/config/test-cloud")
async def test_admin_cloud_config(request: Request):
    body = await request.json()
    service = _get_config_service()
    result = service.test_cloud_connection(body)
    status = 200 if result.get("success") else 400
    return JSONResponse(status_code=status, content=result)
```

```python
# config_service.py
def save_and_apply(self, update: Dict[str, Any], cloud_service) -> Dict[str, Any]:
    current = self.config_repo.get_full_config()
    merged = self.merge_update(current, update)
    errors = self.validate(merged)
    if errors:
        return {"success": False, "saved": False, "errors": errors}

    changes = self.classify_changes(current, merged)
    self.config_repo.replace_full_config(merged)

    cloud_reconnected = False
    warnings = []
    if changes["cloud_changed"] and cloud_service:
        result = cloud_service.reconfigure(merged.get("cloud", {}), preserve_node_id=True)
        cloud_reconnected = bool(result.get("success"))
        if not cloud_reconnected:
            warnings.append(result.get("message") or "cloud reconfigure failed")

    return {
        "success": True,
        "saved": True,
        "applied_now": changes["applied_now"],
        "restart_required": changes["restart_required"],
        "cloud_reconnected": cloud_reconnected,
        "warnings": warnings,
        "errors": [],
    }
```

- [ ] **Step 4: Run the API and cloud tests to verify they pass**

Run: `python -m unittest tests.test_cloud_service_reconfigure tests.test_admin_config_api -v`

Expected: PASS with preserved `node_id`, masked config payloads, and structured save/apply responses.

- [ ] **Step 5: Commit the runtime/API layer**

```bash
git add cloud_service.py main.py config_service.py tests/test_cloud_service_reconfigure.py tests/test_admin_config_api.py
git commit -m "feat: add admin config APIs and cloud reconfigure"
```

## Task 3: Rebuild `/admin` into the unified workbench

**Files:**
- Create: `tests/test_admin_shell_structure.py`
- Modify: `static/admin/html/index.html`
- Modify: `static/admin/css/admin.css`
- Modify: `static/admin/main.js`

- [ ] **Step 1: Write a failing structural test for the new admin shell**

```python
import pathlib
import unittest


class AdminShellStructureTests(unittest.TestCase):
    def test_admin_index_contains_config_navigation_targets(self):
        html = pathlib.Path("static/admin/html/index.html").read_text(encoding="utf-8")
        self.assertIn('data-section="cloud"', html)
        self.assertIn('id="configSaveBtn"', html)
        self.assertIn('id="configPanel"', html)
```

- [ ] **Step 2: Run the structural test to verify it fails**

Run: `python -m unittest tests.test_admin_shell_structure -v`

Expected: FAIL because the current admin HTML does not yet include config-center navigation and actions.

- [ ] **Step 3: Implement the unified UTF-8 admin shell**

```html
<!-- static/admin/html/index.html -->
<main class="admin-shell">
  <header class="admin-header">
    <h1>Fly Print Edge 管理中心</h1>
    <p>统一管理云端连接、打印默认设置、运行参数与打印机。</p>
  </header>

  <section class="admin-toolbar">
    <button id="configSaveBtn" type="button" class="btn btn-primary">保存配置</button>
    <button id="configTestCloudBtn" type="button" class="btn">测试云端连接</button>
    <button id="nodeReregisterBtn" type="button" class="btn btn-danger">重新注册节点</button>
    <span id="configStatusText" class="status-pill">配置状态：未加载</span>
  </section>

  <section class="admin-layout">
    <nav class="admin-nav">
      <button data-section="overview">概览</button>
      <button data-section="cloud">云端配置</button>
      <button data-section="settings">打印默认设置</button>
      <button data-section="runtime">运行设置</button>
      <button data-section="discovery">打印机发现</button>
      <button data-section="printers">打印机管理</button>
    </nav>
    <section id="configPanel" class="admin-panel"></section>
  </section>
</main>
```

```javascript
// static/admin/main.js
const state = {
  config: null,
  initialConfig: null,
  activeSection: "overview",
  saving: false,
  dirty: false,
  lastApplyResult: null,
  managed: [],
  discovered: [],
  defaultPrinterId: "",
  pendingActions: new Set(),
};

async function loadConfig() {
  const data = await request("/config");
  state.config = {
    cloud: data.cloud,
    settings: data.settings,
    network: data.network,
    printers: data.printers,
    meta: data.meta,
  };
  state.initialConfig = JSON.parse(JSON.stringify(state.config));
  render();
}

async function saveConfig() {
  if (state.saving) return;
  state.saving = true;
  render();
  try {
    const payload = buildConfigPayload();
    const result = await request("/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.lastApplyResult = result;
    await loadConfig();
  } finally {
    state.saving = false;
    render();
  }
}
```

```css
/* static/admin/css/admin.css */
.admin-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 20px;
}

.admin-nav {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-banner.restart-required {
  background: #fef3c7;
  color: #92400e;
}
```

- [ ] **Step 4: Run frontend structure and syntax verification**

Run: `python -m unittest tests.test_admin_shell_structure -v`

Expected: PASS for shell structure.

Run: `node --check C:\\Users\\ShiroNeko\\Desktop\\FlyPrint\\fly-print-edge\\static\\admin\\main.js`

Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit the unified admin workbench**

```bash
git add static/admin/html/index.html static/admin/css/admin.css static/admin/main.js tests/test_admin_shell_structure.py
git commit -m "feat: build unified admin config workbench"
```

## Task 4: Final verification and cleanup

**Files:**
- Modify: `docs/superpowers/specs/2026-05-21-edge-admin-config-center-design.md` (only if implementation forces spec corrections)
- Verify: `main.py`, `cloud_service.py`, `config_service.py`, `printer_config.py`, `static/admin/*`, `tests/*`

- [ ] **Step 1: Run the full targeted verification suite**

Run: `python -m unittest tests.test_config_service tests.test_cloud_service_reconfigure tests.test_admin_config_api tests.test_admin_shell_structure tests.test_interactive_session -v`

Expected: PASS for all backend, admin config, and existing interaction-session tests.

Run: `python -m py_compile config_service.py interactive_session.py main.py cloud_service.py printer_config.py tests/test_config_service.py tests/test_cloud_service_reconfigure.py tests/test_admin_config_api.py tests/test_admin_shell_structure.py`

Expected: PASS with no syntax errors.

Run: `node --check C:\\Users\\ShiroNeko\\Desktop\\FlyPrint\\fly-print-edge\\static\\admin\\main.js`

Expected: PASS.

Run: `node --check C:\\Users\\ShiroNeko\\Desktop\\FlyPrint\\fly-print-edge\\static\\user\\main.js`

Expected: PASS to ensure no regression in the user-side script.

- [ ] **Step 2: Execute manual verification against a local Edge instance**

```text
1. 打开 /admin，确认中文无乱码且导航完整。
2. 修改 default_paper_size，保存后刷新页面，确认无需重启。
3. 修改 client_secret 为空提交，确认旧值仍保留。
4. 修改 base_url/auth_url 为可用地址，保存后云端自动重连且 node_id 不变。
5. 修改 base_url/auth_url 为不可用地址，确认页面收到“保存成功但应用失败”的反馈。
6. 修改 network.port，确认页面展示“需重启 Edge 才生效”。
7. 只有点击“重新注册节点”时，node_id 才会被清空并重新注册。
```

- [ ] **Step 3: Commit any final fixes discovered during verification**

```bash
git add config_service.py main.py cloud_service.py printer_config.py static/admin/html/index.html static/admin/css/admin.css static/admin/main.js tests
git commit -m "test: verify admin config center rollout"
```

- [ ] **Step 4: Check for doc drift and update only if implementation changed design**

Run: `git diff -- docs/superpowers/specs/2026-05-21-edge-admin-config-center-design.md`

Expected: no diff. If there is a required design correction, update the spec in the same branch before handing off.
