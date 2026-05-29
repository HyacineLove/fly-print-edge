# User 端 SPA 与 SSE 生命周期稳定化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `static/user/` 重构为单入口原生 JS SPA，并让 SSE 连接在二维码、预览、打印、完成、返回二维码的整条流程中保持应用级单例，不再因页面切换重建。

**Architecture:** 新增一个用户端应用壳 `static/user/index.html` 和应用入口 `app.js`，把现有四个页面拆成四个独立视图模块，由应用级状态机驱动内部视图切换。后端保留现有 `/api/events` 协议，同时新增 `/api/session/current` 作为刷新或真实断线后的会话恢复兜底。

**Tech Stack:** Python, FastAPI, pytest/unittest, vanilla JavaScript ES modules, static HTML/CSS, Server-Sent Events

---

### Task 1: 用失败测试锁定单入口 SPA 与“无整页跳转”约束

**Files:**
- Modify: `tests/test_user_preview_assets.py`
- Create: `tests/test_user_session_snapshot_api.py`

- [ ] **Step 1: 在静态资源测试中加入单入口壳与应用入口断言**

```python
import pathlib
import unittest


class UserSpaShellStructureTests(unittest.TestCase):
    def test_user_index_shell_contains_single_app_mount(self):
        html = pathlib.Path("static/user/index.html").read_text(encoding="utf-8")
        self.assertIn('id="app"', html)
        self.assertIn('src="./app.js"', html)
        self.assertNotIn('window.location.replace', html)

    def test_app_entry_uses_router_and_singleton_sse(self):
        script = pathlib.Path("static/user/app.js").read_text(encoding="utf-8")
        self.assertIn('from "./modules/app/app-controller.js"', script)
        self.assertIn("createAppController", script)
```

- [ ] **Step 2: 在现有用户端脚本测试中加入“禁止整页跳转”的约束**

```python
    def test_user_views_no_longer_navigate_with_window_location(self):
        for path in [
            "static/user/modules/views/login-view.js",
            "static/user/modules/views/preview-view.js",
            "static/user/modules/views/printing-view.js",
            "static/user/modules/views/done-view.js",
        ]:
            script = pathlib.Path(path).read_text(encoding="utf-8")
            self.assertNotIn("window.location.href", script)
            self.assertNotIn("window.location.replace", script)

    def test_singleton_sse_client_owns_eventsource(self):
        script = pathlib.Path("static/user/modules/app/sse-client.js").read_text(encoding="utf-8")
        self.assertIn("new EventSource", script)
        self.assertIn("class UserSseClient", script)
```

- [ ] **Step 3: 新增后端会话快照接口测试**

```python
import asyncio
from unittest.mock import patch
import unittest

import main
from interactive_session import InteractiveSessionManager


class UserSessionSnapshotApiTests(unittest.TestCase):
    def setUp(self):
        self.manager = InteractiveSessionManager()

    def test_session_snapshot_returns_inactive_when_no_session(self):
        with patch.object(main, "interactive_session_manager", self.manager):
            result = asyncio.run(main.get_current_user_session())
        self.assertEqual(False, result["active"])
        self.assertIsNone(result["session_id"])

    def test_session_snapshot_returns_preview_ready_session(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        })
        with patch.object(main, "interactive_session_manager", self.manager):
            result = asyncio.run(main.get_current_user_session())
        self.assertEqual(True, result["active"])
        self.assertEqual(session["session_id"], result["session_id"])
        self.assertEqual("preview_ready", result["state"])
        self.assertEqual("file-1", result["file_id"])
```

- [ ] **Step 4: 运行定向测试，确认当前版本按预期失败**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py tests/test_user_session_snapshot_api.py -q`

Expected: FAIL，原因应包括：

- `static/user/index.html` 或 `app.js` 尚不存在
- 视图模块路径尚不存在
- `/api/session/current` 尚未实现

- [ ] **Step 5: 提交测试基线**

```bash
git add tests/test_user_preview_assets.py tests/test_user_session_snapshot_api.py
git commit -m "test: lock user spa shell and session snapshot contract"
```

### Task 2: 建立用户端单入口壳与应用骨架

**Files:**
- Create: `static/user/index.html`
- Create: `static/user/app.js`
- Create: `static/user/modules/app/app-state.js`
- Create: `static/user/modules/app/router.js`
- Create: `static/user/modules/app/app-controller.js`
- Modify: `static/user/Index.html`
- Modify: `static/index.html`

- [ ] **Step 1: 创建新的用户端单入口 HTML 壳**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fly Print</title>
  <link rel="stylesheet" href="./css/login.css">
  <link rel="stylesheet" href="./css/preview.css">
  <link rel="stylesheet" href="./css/printing.css">
  <link rel="stylesheet" href="./css/done.css">
</head>
<body data-app="user-spa">
  <div id="userToast" class="user-toast is-hidden" aria-live="polite"></div>
  <div id="app"></div>
  <script src="./app.js" type="module"></script>
</body>
</html>
```

- [ ] **Step 2: 创建应用级状态与内部路由骨架**

```javascript
// static/user/modules/app/app-state.js
export function createAppState() {
  return {
    currentView: "login",
    sessionId: null,
    sessionPhase: "idle",
    file: {},
    options: {},
    runtimeSettings: {},
    capabilityState: null,
    doneResult: null,
    loading: false,
    sse: {
      connected: false,
      connecting: false,
      retryCount: 0,
      lastMessageAt: 0,
    },
  };
}
```

```javascript
// static/user/modules/app/router.js
export function createRouter(state, render) {
  return {
    go(viewName) {
      state.currentView = viewName;
      render();
    },
  };
}
```

- [ ] **Step 3: 创建应用入口与 controller 启动代码**

```javascript
// static/user/app.js
import { createAppController } from "./modules/app/app-controller.js";

const controller = createAppController({
  mountNode: document.getElementById("app"),
});

controller.start();
```

```javascript
// static/user/modules/app/app-controller.js
import { createAppState } from "./app-state.js";
import { createRouter } from "./router.js";

export function createAppController({ mountNode }) {
  const state = createAppState();

  const render = () => {
    mountNode.dataset.view = state.currentView;
  };

  const router = createRouter(state, render);

  return {
    state,
    router,
    start() {
      render();
    },
  };
}
```

- [ ] **Step 4: 把旧入口改成跳转到新的 SPA 壳**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url=/static/user/index.html">
  <title>Fly Print</title>
</head>
<body>
  <script>window.location.replace('/static/user/index.html');</script>
</body>
</html>
```

- [ ] **Step 5: 运行壳结构测试，确认骨架通过**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: 部分 PASS。`index.html`、`app.js`、路由骨架相关断言通过，其余视图和后端快照相关断言仍失败。

- [ ] **Step 6: 提交骨架**

```bash
git add static/user/index.html static/user/app.js static/user/modules/app static/user/Index.html static/index.html
git commit -m "feat: add user spa shell and app skeleton"
```

### Task 3: 将四个业务页面迁移为四个视图模块

**Files:**
- Create: `static/user/modules/views/login-view.js`
- Create: `static/user/modules/views/preview-view.js`
- Create: `static/user/modules/views/printing-view.js`
- Create: `static/user/modules/views/done-view.js`
- Modify: `static/user/modules/shared/runtime.js`
- Modify: `static/user/modules/shared/session-state.js`
- Modify: `static/user/modules/shared/dom.js`

- [ ] **Step 1: 先写视图级渲染约束测试**

```python
    def test_login_view_renders_qr_actions_without_page_jump(self):
        script = pathlib.Path("static/user/modules/views/login-view.js").read_text(encoding="utf-8")
        self.assertIn("export function renderLoginView", script)
        self.assertIn("refreshQrCode", script)

    def test_preview_view_renders_print_action_without_direct_print_submit(self):
        script = pathlib.Path("static/user/modules/views/preview-view.js").read_text(encoding="utf-8")
        self.assertIn("export function renderPreviewView", script)
        self.assertNotIn('postJson("/api/print"', script)

    def test_printing_view_owns_print_submission(self):
        script = pathlib.Path("static/user/modules/views/printing-view.js").read_text(encoding="utf-8")
        self.assertIn('postJson("/api/print"', script)
```

- [ ] **Step 2: 迁移二维码视图为局部模板函数**

```javascript
export function renderLoginView(state) {
  return `
    <div class="scroll-container-0_1" data-view="login">
      <div id="3_37" class="Pixso-rectangle-3_37"></div>
      <div id="3_28" class="Pixso-group-3_28" style="cursor: pointer;"></div>
      <p id="77_56" class="Pixso-paragraph-77_56">0</p>
    </div>
  `;
}
```

- [ ] **Step 3: 迁移预览、打印中、完成视图为局部模板函数**

```javascript
export function renderPreviewView(state) {
  return `
    <div class="scroll-container-0_1" data-view="preview">
      <div id="115_58" class="Pixso-rectangle-115_58"></div>
      <button id="115_61" type="button">&#8249;</button>
      <button id="115_62" type="button">&#8250;</button>
      <div id="97_460" class="Pixso-group-97_460"></div>
    </div>
  `;
}
```

```javascript
export function renderPrintingView(state) {
  return `
    <div class="scroll-container-0_1" data-view="printing">
      <div id="77_19" class="Pixso-rectangle-77_19"></div>
      <div id="77_20" class="Pixso-rectangle-77_20"></div>
    </div>
  `;
}
```

```javascript
export function renderDoneView(state) {
  return `
    <div class="scroll-container-0_1" data-view="done">
      <p id="115_26">${state.doneResult?.message || ""}</p>
      <div id="115_42" class="Pixso-group-115_42"></div>
    </div>
  `;
}
```

- [ ] **Step 4: 在 controller 中接入视图渲染分发**

```javascript
import { renderLoginView } from "../views/login-view.js";
import { renderPreviewView } from "../views/preview-view.js";
import { renderPrintingView } from "../views/printing-view.js";
import { renderDoneView } from "../views/done-view.js";

function renderView(state) {
  if (state.currentView === "login") return renderLoginView(state);
  if (state.currentView === "preview") return renderPreviewView(state);
  if (state.currentView === "printing") return renderPrintingView(state);
  return renderDoneView(state);
}
```

- [ ] **Step 5: 运行定向测试，确认视图模块落位**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: 视图文件存在且路径正确；后续失败应集中在单例 SSE、业务事件编排和后端快照接口。

- [ ] **Step 6: 提交视图迁移**

```bash
git add static/user/modules/views static/user/modules/app/app-controller.js static/user/modules/shared/runtime.js static/user/modules/shared/session-state.js static/user/modules/shared/dom.js
git commit -m "feat: migrate user pages into spa view modules"
```

### Task 4: 将 SSE 提升为应用级单例，并移除业务流程中的整页跳转

**Files:**
- Create: `static/user/modules/app/sse-client.js`
- Modify: `static/user/modules/app/app-controller.js`
- Modify: `static/user/modules/shared/runtime.js`
- Modify: `static/user/modules/shared/api.js`
- Modify: `static/user/modules/views/login-view.js`
- Modify: `static/user/modules/views/preview-view.js`
- Modify: `static/user/modules/views/printing-view.js`
- Modify: `static/user/modules/views/done-view.js`

- [ ] **Step 1: 先写“单例 SSE + 无跳页”行为约束测试**

```python
    def test_app_controller_uses_single_sse_client(self):
        script = pathlib.Path("static/user/modules/app/app-controller.js").read_text(encoding="utf-8")
        self.assertIn("new UserSseClient", script)
        self.assertNotIn("createSseConnection(", script)

    def test_runtime_no_longer_exports_goto_page_with_window_location(self):
        script = pathlib.Path("static/user/modules/shared/runtime.js").read_text(encoding="utf-8")
        self.assertNotIn("window.location.href", script)
        self.assertNotIn("gotoPage(", script)
```

- [ ] **Step 2: 创建应用级 SSE 客户端**

```javascript
import { api } from "../shared/api.js";

export class UserSseClient {
  constructor({ onMessage, onStatusChange }) {
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange;
    this.eventSource = null;
    this.retryTimer = null;
    this.closed = false;
  }

  start() {
    this.closed = false;
    this.#connect();
  }

  stop() {
    this.closed = true;
    if (this.retryTimer) window.clearTimeout(this.retryTimer);
    if (this.eventSource) this.eventSource.close();
    this.retryTimer = null;
    this.eventSource = null;
  }

  #connect() {
    this.onStatusChange?.({ connecting: true, connected: false });
    const es = new EventSource(api.events);
    this.eventSource = es;

    es.onopen = () => {
      this.onStatusChange?.({ connecting: false, connected: true });
    };

    es.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      this.onMessage?.(payload);
    };

    es.onerror = () => {
      this.onStatusChange?.({ connecting: false, connected: false });
      if (this.closed) return;
      this.retryTimer = window.setTimeout(() => this.#connect(), 2000);
    };
  }
}
```

- [ ] **Step 3: 在 controller 中持有唯一 SSE 实例，并按状态切换内部视图**

```javascript
import { UserSseClient } from "./sse-client.js";

const sse = new UserSseClient({
  onMessage: (payload) => {
    const type = payload?.type || "";
    const data = payload?.data || {};
    if (type === "preview_file") {
      state.sessionId = data.session_id || state.sessionId;
      state.file = {
        file_id: data.file_id,
        file_url: data.file_url,
        file_name: data.file_name,
        file_type: data.file_type,
        task_token: data.task_token || null,
        job_id: data.job_id || null,
      };
      state.sessionPhase = "preview_ready";
      router.go("preview");
      return;
    }
    if (type === "job_status") {
      state.file.job_id = data.job_id || state.file.job_id || null;
      if (String(data.status || "").toLowerCase().includes("complete") || Number(data.progress || 0) >= 100) {
        state.sessionPhase = "completed";
        state.doneResult = { status: "success", message: "" };
        router.go("done");
      }
    }
  },
  onStatusChange: ({ connecting, connected }) => {
    state.sse.connecting = connecting;
    state.sse.connected = connected;
  },
});
```

- [ ] **Step 4: 将视图中的流程跳转替换为内部路由动作**

```javascript
// preview-view.js
export function bindPreviewViewEvents({ state, router, submitPrintRequest }) {
  document.getElementById("97_460")?.addEventListener("click", async () => {
    await submitPrintRequest();
    router.go("printing");
  });
}
```

```javascript
// done-view.js
export function bindDoneViewEvents({ restartCycle }) {
  document.getElementById("115_42")?.addEventListener("click", () => {
    restartCycle();
  });
}
```

- [ ] **Step 5: 在完成页返回二维码时只重置应用状态，不关闭 SSE**

```javascript
function restartCycle() {
  state.sessionId = null;
  state.sessionPhase = "idle";
  state.file = {};
  state.doneResult = null;
  router.go("login");
  void refreshQrCode();
}
```

- [ ] **Step 6: 运行用户端定向测试，确认不存在应用自身导致的重连点**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: PASS，或仅剩与 `/api/session/current` 和恢复逻辑相关的断言失败。

- [ ] **Step 7: 提交单例 SSE 与无跳页迁移**

```bash
git add static/user/modules/app/sse-client.js static/user/modules/app/app-controller.js static/user/modules/shared/runtime.js static/user/modules/shared/api.js static/user/modules/views
git commit -m "feat: keep user sse alive across spa view transitions"
```

### Task 5: 后端补会话快照接口，并给 SSE 响应增加稳定性 Header

**Files:**
- Modify: `interactive_session.py`
- Modify: `main.py`
- Modify: `tests/test_interactive_session.py`
- Modify: `tests/test_user_session_snapshot_api.py`

- [ ] **Step 1: 先在会话管理器测试中锁定快照形状**

```python
    def test_build_snapshot_reports_current_phase_and_file(self):
        session = self.manager.start_session(upload_token="token-1")
        self.manager.accept_preview_event({
            "file_id": "file-1",
            "file_url": "/api/v1/files/file-1",
            "file_name": "demo.pdf",
            "file_type": "application/pdf",
        })
        snapshot = self.manager.build_snapshot()
        self.assertEqual(session["session_id"], snapshot["session_id"])
        self.assertEqual("preview_ready", snapshot["state"])
        self.assertEqual("file-1", snapshot["file_id"])
```

- [ ] **Step 2: 在 `InteractiveSessionManager` 中增加快照方法**

```python
    def build_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            if not self._active_session:
                return {
                    "active": False,
                    "session_id": None,
                    "state": "idle",
                    "file_id": None,
                    "file_url": None,
                    "file_name": None,
                    "file_type": None,
                    "job_id": None,
                    "submitted": False,
                }
            session = deepcopy(self._active_session)
            return {
                "active": True,
                "session_id": session["session_id"],
                "state": session.get("state", "idle"),
                "file_id": session.get("file_id"),
                "file_url": session.get("file_url"),
                "file_name": session.get("file_name"),
                "file_type": session.get("file_type"),
                "job_id": session.get("job_id"),
                "submitted": bool(session.get("submitted")),
            }
```

- [ ] **Step 3: 在预览事件绑定时保存文件名和文件类型**

```python
            self._active_session["file_id"] = file_id
            self._active_session["file_url"] = file_url
            self._active_session["file_name"] = data.get("file_name")
            self._active_session["file_type"] = data.get("file_type")
            self._active_session["state"] = "preview_ready"
```

- [ ] **Step 4: 新增会话快照 API，并补上 SSE Header**

```python
@app.get("/api/session/current")
async def get_current_user_session():
    return interactive_session_manager.build_snapshot()
```

```python
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 5: 运行后端定向测试，确认快照和 SSE 接口通过**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_interactive_session.py tests/test_user_session_snapshot_api.py -q`

Expected: PASS。

- [ ] **Step 6: 提交后端配合能力**

```bash
git add interactive_session.py main.py tests/test_interactive_session.py tests/test_user_session_snapshot_api.py
git commit -m "feat: add user session snapshot api for spa recovery"
```

### Task 6: 接入刷新恢复、完成页回环与最终回归验证

**Files:**
- Modify: `static/user/modules/app/app-controller.js`
- Modify: `static/user/modules/shared/api.js`
- Modify: `tests/test_user_preview_assets.py`
- Modify: `tests/test_user_preview_print_api.py`

- [ ] **Step 1: 先写启动恢复与回环约束测试**

```python
    def test_app_controller_bootstraps_from_session_snapshot(self):
        script = pathlib.Path("static/user/modules/app/app-controller.js").read_text(encoding="utf-8")
        self.assertIn('getJson("/api/session/current")', script)
        self.assertIn('state.sessionPhase = snapshot.state', script)
        self.assertIn('router.go("preview")', script)
```

- [ ] **Step 2: 在 controller 启动时读取当前会话快照**

```javascript
import { getJson } from "../shared/api.js";

async function bootstrapFromSnapshot() {
  const snapshot = await getJson("/api/session/current");
  if (!snapshot?.active) {
    router.go("login");
    return;
  }
  state.sessionId = snapshot.session_id;
  state.sessionPhase = snapshot.state;
  state.file = {
    file_id: snapshot.file_id,
    file_url: snapshot.file_url,
    file_name: snapshot.file_name,
    file_type: snapshot.file_type,
    job_id: snapshot.job_id,
  };
  if (snapshot.state === "preview_ready") router.go("preview");
  else if (snapshot.state === "printing" || snapshot.state === "print_submitted") router.go("printing");
  else if (snapshot.state === "completed" || snapshot.state === "failed") router.go("done");
  else router.go("login");
}
```

- [ ] **Step 3: 在完成页回到二维码时重新请求二维码，而不是刷新页面**

```javascript
async function restartCycle() {
  state.file = {};
  state.doneResult = null;
  state.sessionId = null;
  state.sessionPhase = "idle";
  router.go("login");
  await refreshQrCode();
}
```

- [ ] **Step 4: 运行用户端相关回归测试**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py tests/test_user_preview_print_api.py -q`

Expected: PASS。

- [ ] **Step 5: 运行完整聚焦回归**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_interactive_session.py tests/test_user_preview_assets.py tests/test_user_preview_print_api.py tests/test_user_session_snapshot_api.py -q`

Expected: PASS。

- [ ] **Step 6: 运行全量测试**

Run: `.\\venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS，若有 warning，应为既有 warning，不应新增回归失败。

- [ ] **Step 7: 检查最终差异覆盖**

Run: `git diff --stat`

Expected: `static/user/`、`interactive_session.py`、`main.py`、相关测试文件均在变更范围内。

- [ ] **Step 8: 提交最终实现**

```bash
git add static/user static/index.html interactive_session.py main.py tests/test_user_preview_assets.py tests/test_user_preview_print_api.py tests/test_user_session_snapshot_api.py tests/test_interactive_session.py
git commit -m "feat: convert user flow to spa with stable sse lifecycle"
```
