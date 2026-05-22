# File Cleanup Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify preview-file, preview-cache, token, and print-artifact cleanup so the edge node has a single authoritative temporary-resource manager instead of scattered deletion logic.

**Architecture:** Keep `file_manager.py` as the central lifecycle owner and expand it from a preview-file cleaner into a broader transient-resource manager. Migrate preview resources first, then token lifecycle, then print artifacts, while preserving current API behavior and current print-monitor timing.

**Tech Stack:** Python, FastAPI, pytest/unittest, project-local `temp/` directory, existing `FileManager`

---

### Task 1: Freeze The Cleanup Contract With Focused Failing Tests

**Files:**
- Create: `tests/test_file_manager_cleanup.py`
- Modify: `tests/test_user_preview_print_api.py`

- [ ] **Step 1: Add a unit test that proves preview resource release must remove both disk files and all preview caches together**

```python
import os
import tempfile
import unittest

from file_manager import FileManager


class FileManagerCleanupTests(unittest.TestCase):
    def test_release_preview_resource_removes_files_and_related_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "preview.bin")
            pdf_path = os.path.join(tmpdir, "preview.pdf")
            with open(source_path, "wb") as fh:
                fh.write(b"preview")
            with open(pdf_path, "wb") as fh:
                fh.write(b"pdf")

            preview_cache = {
                'file-1:{"page_index": 0}': {"preview_url": "data:image/png;base64,xxx", "timestamp": 1.0}
            }
            preview_page_cache = {"file-1": {0: object()}}
            preview_page_meta = {"file-1": {"page_count": 1}}

            manager = FileManager(
                cleanup_interval=300,
                file_ttl=1800,
                preview_cache=preview_cache,
                preview_page_cache=preview_page_cache,
                preview_page_meta=preview_page_meta,
            )
            manager.register_preview_resource("file-1", "url-1", source_path, pdf_path)

            released = manager.release_preview_resource("file-1", reason="test")

            self.assertTrue(released)
            self.assertFalse(os.path.exists(source_path))
            self.assertFalse(os.path.exists(pdf_path))
            self.assertEqual({}, preview_cache)
            self.assertEqual({}, preview_page_cache)
            self.assertEqual({}, preview_page_meta)
```

- [ ] **Step 2: Add a unit test that proves consumed tokens disappear immediately and expired tokens are purged**

```python
    def test_consume_and_expire_file_access_tokens(self):
        manager = FileManager(cleanup_interval=300, file_ttl=1800)
        manager.store_file_access_token("file-1", "token-1", "2099-01-01T00:00:00Z")
        consumed = manager.consume_file_access_token("file-1")
        self.assertEqual("token-1", consumed)
        self.assertIsNone(manager.consume_file_access_token("file-1"))

        manager.store_file_access_token("file-2", "token-2", "2000-01-01T00:00:00Z")
        manager.cleanup_expired_tokens()
        self.assertIsNone(manager.consume_file_access_token("file-2"))
```

- [ ] **Step 3: Add a unit test that proves print artifacts can be released independently from preview resources**

```python
    def test_release_print_artifact_removes_source_and_converted_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "print.bin")
            converted_path = os.path.join(tmpdir, "print.pdf")
            with open(source_path, "wb") as fh:
                fh.write(b"print")
            with open(converted_path, "wb") as fh:
                fh.write(b"pdf")

            manager = FileManager(cleanup_interval=300, file_ttl=1800)
            manager.register_print_artifact("job-1", source_path, converted_path)
            released = manager.release_print_artifact("job-1", reason="test")

            self.assertTrue(released)
            self.assertFalse(os.path.exists(source_path))
            self.assertFalse(os.path.exists(converted_path))
```

- [ ] **Step 4: Extend the API regression test so `/api/print` still clears preview resources through the unified manager**

```python
    def test_submit_print_clears_registered_preview_resource(self):
        preview_cache = {'file-1:{"page_index": 0}': {"preview_url": "data", "timestamp": 1.0}}
        preview_page_cache = {"file-1": {0: object()}}
        preview_page_meta = {"file-1": {"page_count": 1}}
        main.preview_cache = preview_cache
        main.preview_page_cache = preview_page_cache
        main.preview_page_meta = preview_page_meta

        source_path = os.path.join(self.temp_dir.name, "preview.bin")
        with open(source_path, "wb") as fh:
            fh.write(b"preview")

        self.file_manager.register_preview_resource("file-1", "/api/v1/files/file-1", source_path)

        response = self.client.post(
            "/api/print",
            json={
                "session_id": self.session["session_id"],
                "file_id": "file-1",
                "options": {"copies": 1, "duplex": "simplex", "color_mode": "mono"},
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertFalse(os.path.exists(source_path))
        self.assertEqual({}, main.preview_cache)
        self.assertEqual({}, main.preview_page_cache)
        self.assertEqual({}, main.preview_page_meta)
```

- [ ] **Step 5: Run the targeted tests and verify they fail before implementation**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_file_manager_cleanup.py tests/test_user_preview_print_api.py -q`

Expected: FAIL because `FileManager` does not yet manage preview-page caches, tokens, or print artifacts with the required API surface.

### Task 2: Make FileManager The Authoritative Owner Of Preview Resources

**Files:**
- Modify: `file_manager.py`
- Modify: `main.py`
- Test: `tests/test_file_manager_cleanup.py`
- Test: `tests/test_user_preview_print_api.py`

- [ ] **Step 1: Expand `FileManager.__init__` to accept the additional preview cache references it must own**

```python
class FileManager:
    def __init__(
        self,
        cleanup_interval: int = 300,
        file_ttl: int = 1800,
        preview_cache: Optional[Dict] = None,
        preview_page_cache: Optional[Dict] = None,
        preview_page_meta: Optional[Dict] = None,
    ):
        self.cleanup_interval = cleanup_interval
        self.file_ttl = file_ttl
        self.preview_cache = preview_cache if preview_cache is not None else {}
        self.preview_page_cache = preview_page_cache if preview_page_cache is not None else {}
        self.preview_page_meta = preview_page_meta if preview_page_meta is not None else {}
        self.preview_files: Dict[str, Dict[str, Any]] = {}
        self.preview_lock = threading.Lock()
```

- [ ] **Step 2: Replace the old preview registration and cleanup API with explicit preview-resource methods**

```python
    def register_preview_resource(self, file_id: str, file_url: str, source_path: str, pdf_path: Optional[str] = None):
        with self.preview_lock:
            now = time.time()
            self.preview_files[file_id] = {
                "file_url": file_url,
                "source_path": source_path,
                "pdf_path": pdf_path,
                "created_at": now,
                "last_access": now,
            }

    def touch_preview_resource(self, file_id: str):
        with self.preview_lock:
            if file_id in self.preview_files:
                self.preview_files[file_id]["last_access"] = time.time()

    def get_preview_resource(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self.preview_lock:
            info = self.preview_files.get(file_id)
            return dict(info) if info else None
```

- [ ] **Step 3: Implement a single preview-release method that removes disk files and all related caches by `file_id`**

```python
    def release_preview_resource(self, file_id: str, reason: str = "manual") -> bool:
        with self.preview_lock:
            info = self.preview_files.pop(file_id, None)
        if not info:
            self._clear_preview_cache_entries(file_id)
            return False

        success = True
        for path_key in ("source_path", "pdf_path"):
            file_path = info.get(path_key)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    success = False
        self._clear_preview_cache_entries(file_id)
        return success

    def _clear_preview_cache_entries(self, file_id: str):
        keys = [key for key in list(self.preview_cache.keys()) if key.startswith(f"{file_id}:")]
        for key in keys:
            self.preview_cache.pop(key, None)
        self.preview_page_cache.pop(file_id, None)
        self.preview_page_meta.pop(file_id, None)
```

- [ ] **Step 4: Make expired-preview cleanup call the unified release method instead of deleting files and caches separately**

```python
    def cleanup_expired_files(self):
        now = time.time()
        with self.preview_lock:
            expired = [
                file_id
                for file_id, info in self.preview_files.items()
                if now - info["last_access"] > self.file_ttl
            ]
        for file_id in expired:
            self.release_preview_resource(file_id, reason="expired")
        self.cleanup_expired_tokens()
```

- [ ] **Step 5: Rewire `main.py` startup to hand all preview cache references to `FileManager`**

```python
file_mgr = init_file_manager(
    cleanup_interval=300,
    file_ttl=1800,
    preview_cache=preview_cache,
    preview_page_cache=preview_page_cache,
    preview_page_meta=preview_page_meta,
)
```

- [ ] **Step 6: Rewire `/api/preview`, URL-change cleanup, `/api/print`, `/api/cleanup`, and shutdown to use `FileManager` as the only preview-resource owner**

```python
resource = file_mgr.get_preview_resource(file_id) if file_mgr else None
file_path = resource.get("source_path") if resource else None

if resource and resource.get("file_url") != file_url:
    file_mgr.release_preview_resource(file_id, reason="url_changed")
    resource = None

if not resource or not os.path.exists(file_path):
    file_path, err = _download_preview_file(file_url, file_name, file_id)
    if file_path:
        file_mgr.register_preview_resource(file_id, file_url, file_path, cached_pdf)
else:
    file_mgr.touch_preview_resource(file_id)
```

```python
if file_mgr:
    file_mgr.release_preview_resource(file_id, reason="print")
```

```python
if file_mgr:
    file_mgr.release_preview_resource(file_id, reason="cancel")
```

- [ ] **Step 7: Run the focused tests and verify the preview cleanup contract now passes**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_file_manager_cleanup.py tests/test_user_preview_print_api.py -q`

Expected: PASS for the preview-resource and preview-cache lifecycle checks.

### Task 3: Unify File Access Token Storage And Expiry

**Files:**
- Modify: `file_manager.py`
- Modify: `main.py`
- Modify: `cloud_websocket_client.py`
- Test: `tests/test_file_manager_cleanup.py`
- Test: `tests/test_user_preview_print_api.py`

- [ ] **Step 1: Add token storage, consume, and expiry helpers to `FileManager`**

```python
class FileManager:
    def __init__(...):
        ...
        self.file_access_tokens: Dict[str, Dict[str, str]] = {}

    def store_file_access_token(self, file_id: str, token: str, expires_at: Optional[str]):
        if not file_id or not token:
            return
        self.file_access_tokens[file_id] = {"token": token, "expires_at": expires_at or ""}

    def consume_file_access_token(self, file_id: str) -> Optional[str]:
        info = self.file_access_tokens.pop(file_id, None)
        if not info:
            return None
        if self._token_is_expired(info.get("expires_at")):
            return None
        return info.get("token")

    def cleanup_expired_tokens(self):
        expired = [
            file_id
            for file_id, info in list(self.file_access_tokens.items())
            if self._token_is_expired(info.get("expires_at"))
        ]
        for file_id in expired:
            self.file_access_tokens.pop(file_id, None)
```

- [ ] **Step 2: Make preview-file messages store tokens through `FileManager` instead of the global dictionary**

```python
file_mgr = main.get_file_manager()
if file_mgr and file_access_token:
    file_mgr.store_file_access_token(file_id, file_access_token, file_access_token_expires_at)
```

- [ ] **Step 3: Make `_download_preview_file` consume tokens through `FileManager` and remove the direct global mutation**

```python
file_mgr = get_file_manager()
file_access_token = file_mgr.consume_file_access_token(file_id) if file_mgr and file_id else None
if file_access_token:
    query_params["token"] = [file_access_token]
```

- [ ] **Step 4: Remove the now-obsolete `file_access_tokens` global from `main.py` and update any logs accordingly**

```python
# delete:
file_access_tokens: Dict[str, Dict[str, str]] = {}
```

- [ ] **Step 5: Re-run the focused lifecycle tests**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_file_manager_cleanup.py tests/test_user_preview_print_api.py -q`

Expected: PASS, including the new token consume-and-expire assertions.

### Task 4: Register And Release Print Artifacts Through FileManager

**Files:**
- Modify: `file_manager.py`
- Modify: `printer_utils.py`
- Modify: `cloud_websocket_client.py`
- Test: `tests/test_file_manager_cleanup.py`

- [ ] **Step 1: Add a print-artifact registry to `FileManager`**

```python
class FileManager:
    def __init__(...):
        ...
        self.print_artifacts: Dict[str, Dict[str, Optional[str]]] = {}
        self.print_lock = threading.Lock()

    def register_print_artifact(self, artifact_key: str, source_path: str, converted_path: Optional[str] = None):
        with self.print_lock:
            self.print_artifacts[artifact_key] = {
                "source_path": source_path,
                "converted_path": converted_path,
            }

    def update_print_artifact(self, artifact_key: str, converted_path: Optional[str]):
        with self.print_lock:
            if artifact_key in self.print_artifacts:
                self.print_artifacts[artifact_key]["converted_path"] = converted_path

    def release_print_artifact(self, artifact_key: str, reason: str = "manual") -> bool:
        with self.print_lock:
            info = self.print_artifacts.pop(artifact_key, None)
        if not info:
            return False
        success = True
        for key in ("source_path", "converted_path"):
            path = info.get(key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    success = False
        return success
```

- [ ] **Step 2: Register print downloads as soon as `cloud_websocket_client.py` finishes downloading them**

```python
file_mgr = get_file_manager()
if file_mgr and file_path:
    file_mgr.register_print_artifact(job_id, file_path)
```

- [ ] **Step 3: Extend `submit_print_job_with_cleanup()` with an explicit artifact key so cleanup does not depend on printer IDs or job names**

```python
def submit_print_job_with_cleanup(
    self,
    printer_name: str,
    file_path: str,
    job_name: str,
    print_options: Dict[str, str] = None,
    cleanup_source: str = "unknown",
    printer_id: str = None,
    artifact_key: str = None,
) -> Dict[str, Any]:
    cleanup_key = artifact_key or job_name
```

```python
file_mgr = get_file_manager()
if converted_file and file_mgr and cleanup_key:
    file_mgr.update_print_artifact(cleanup_key, converted_file)
```

- [ ] **Step 4: Replace the remaining direct `os.remove(...)` print-artifact cleanup branches with `release_print_artifact(...)`**

```python
if not result.get("success", False):
    if file_mgr and cleanup_key:
        file_mgr.release_print_artifact(cleanup_key, reason=f"{cleanup_source}:submit_failed")
    return
```

```python
if cleanup_source == "云端WebSocket":
    time.sleep(180)
    if file_mgr and cleanup_key:
        file_mgr.release_print_artifact(cleanup_key, reason=f"{cleanup_source}:delayed")
    return
```

```python
if file_mgr and cleanup_key:
    file_mgr.release_print_artifact(cleanup_key, reason=f"{cleanup_source}:job_finished")
    return
```

- [ ] **Step 5: Pass the cloud job ID into `submit_print_job_with_cleanup()` so the print artifact key is stable across the cloud print flow**

```python
result = self.printer_manager.submit_print_job_with_cleanup(
    printer_name,
    file_path,
    job_name,
    print_options,
    "云端WebSocket",
    printer_id,
    artifact_key=job_id,
)
```

- [ ] **Step 6: Run the dedicated cleanup tests again**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_file_manager_cleanup.py -q`

Expected: PASS, including the print-artifact lifecycle assertion.

### Task 5: Final Regression Verification

**Files:**
- Test: `tests/test_file_manager_cleanup.py`
- Test: `tests/test_user_preview_print_api.py`
- Test: `tests/test_interactive_session.py`

- [ ] **Step 1: Run the focused regression suite**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_file_manager_cleanup.py tests/test_user_preview_print_api.py tests/test_interactive_session.py -q`

Expected: PASS

- [ ] **Step 2: Run the full test suite on the final integrated result**

Run: `venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS with no new failures; existing FastAPI `on_event` deprecation warnings may remain.

- [ ] **Step 3: Commit the cleanup unification work**

```bash
git add file_manager.py main.py cloud_websocket_client.py printer_utils.py tests/test_file_manager_cleanup.py tests/test_user_preview_print_api.py
git commit -m "refactor: unify transient file cleanup ownership"
```
