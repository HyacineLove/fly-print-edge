# Runtime Log Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make edge-runtime logs quiet by default, detailed on demand, and consistently controlled by standard logging instead of scattered `print(...)` statements.

**Architecture:** Add a single logging configuration entry point, then migrate the major backend modules from ad hoc `print(...)` output to module-level loggers. Keep important lifecycle and business events at `INFO`, move noisy success-path details to `DEBUG`, and keep warnings/errors visible in both modes.

**Tech Stack:** Python, FastAPI, standard `logging`, pytest/unittest, environment variables, existing config repository

---

### Task 1: Freeze Log-Level Configuration Behavior With Tests

**Files:**
- Create: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_logging_config.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\config_service.py`

- [ ] **Step 1: Write a failing test that defines the default logging configuration contract**

```python
import unittest

from logging_utils import resolve_log_settings


class LoggingConfigTests(unittest.TestCase):
    def test_resolve_log_settings_defaults_to_info(self):
        resolved = resolve_log_settings({})
        self.assertEqual("INFO", resolved["level_name"])
        self.assertEqual(False, resolved["debug_logging"])
```

- [ ] **Step 2: Write a failing test that proves config file values are accepted and normalized**

```python
    def test_resolve_log_settings_uses_config_values(self):
        resolved = resolve_log_settings(
            {
                "settings": {
                    "log_level": "debug",
                    "debug_logging": True,
                }
            }
        )
        self.assertEqual("DEBUG", resolved["level_name"])
        self.assertEqual(True, resolved["debug_logging"])
```

- [ ] **Step 3: Write a failing test that proves environment variables override config values**

```python
    def test_resolve_log_settings_env_overrides_config(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "INFO", "debug_logging": False}},
            env={"FLYPRINT_LOG_LEVEL": "WARNING", "FLYPRINT_DEBUG_LOGGING": "true"},
        )
        self.assertEqual("DEBUG", resolved["level_name"])
        self.assertEqual(True, resolved["debug_logging"])
```

- [ ] **Step 4: Write a failing test that proves invalid log levels fall back safely**

```python
    def test_resolve_log_settings_invalid_level_falls_back_to_info(self):
        resolved = resolve_log_settings(
            {"settings": {"log_level": "verbose", "debug_logging": False}}
        )
        self.assertEqual("INFO", resolved["level_name"])
```

- [ ] **Step 5: Extend config validation coverage so the admin/runtime config contract knows about the new fields**

```python
class ConfigServiceLoggingValidationTests(unittest.TestCase):
    def test_validate_rejects_invalid_log_level(self):
        service = ConfigService(config_repo=None)
        errors = service.validate(
            {
                "cloud": {"client_id": "edge"},
                "settings": {"log_level": "TRACE"},
                "network": {"bind_address": "127.0.0.1", "port": 7860},
                "printers": {"discovery_mode": "auto", "static_list": []},
            }
        )
        self.assertIn("settings.log_level must be DEBUG, INFO, WARNING, or ERROR", errors)
```

- [ ] **Step 6: Run the targeted tests and confirm they fail before implementation**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_logging_config.py tests/test_admin_config_api.py -q`

Expected: FAIL because `logging_utils.py` and the new settings validation do not exist yet.

### Task 2: Add A Unified Logging Configuration Module

**Files:**
- Create: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\logging_utils.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\config_service.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_logging_config.py`

- [ ] **Step 1: Create `logging_utils.py` with configuration resolution helpers**

```python
import logging
import os
from typing import Any, Dict, Mapping, Optional


VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_log_settings(config: Dict[str, Any], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    env_map = env if env is not None else os.environ
    settings = config.get("settings", {}) if isinstance(config, dict) else {}

    config_level = str(settings.get("log_level") or "INFO").strip().upper()
    config_debug = _parse_bool(settings.get("debug_logging"), default=False)

    env_level = str(env_map.get("FLYPRINT_LOG_LEVEL") or "").strip().upper()
    env_debug_raw = env_map.get("FLYPRINT_DEBUG_LOGGING")

    level_name = env_level or config_level or "INFO"
    if level_name not in VALID_LOG_LEVELS:
        level_name = "INFO"

    debug_logging = _parse_bool(env_debug_raw, default=config_debug)
    if debug_logging and level_name == "INFO":
        level_name = "DEBUG"

    return {
        "level_name": level_name,
        "level": getattr(logging, level_name, logging.INFO),
        "debug_logging": debug_logging,
    }
```

- [ ] **Step 2: Add a single logging bootstrap function that configures the root logger once**

```python
def configure_logging(config: Dict[str, Any], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    resolved = resolve_log_settings(config, env=env)
    logging.basicConfig(
        level=resolved["level"],
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )
    return resolved
```

- [ ] **Step 3: Extend config validation so `settings.log_level` and `settings.debug_logging` are legal runtime settings**

```python
if settings.get("log_level") not in (None, "", "DEBUG", "INFO", "WARNING", "ERROR"):
    errors.append("settings.log_level must be DEBUG, INFO, WARNING, or ERROR")

if settings.get("debug_logging") not in (None, "", True, False):
    errors.append("settings.debug_logging must be a boolean")
```

- [ ] **Step 4: Normalize public config output so the admin/runtime layer always sees explicit logging settings**

```python
settings["log_level"] = str(settings.get("log_level") or "INFO").strip().upper()
if settings["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
    settings["log_level"] = "INFO"
settings["debug_logging"] = bool(settings.get("debug_logging", False))
```

- [ ] **Step 5: Run the new logging tests and the config API tests**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_logging_config.py tests/test_admin_config_api.py -q`

Expected: PASS with the new resolver and config validation in place.

- [ ] **Step 6: Commit the logging configuration foundation**

```bash
git add logging_utils.py config_service.py tests/test_logging_config.py tests/test_admin_config_api.py
git commit -m "refactor: add configurable runtime log levels"
```

### Task 3: Switch Startup To The Unified Logger And Quiet The Core Runtime

**Files:**
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\main.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\printer_config.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_config_file_encoding.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_logging_config.py`

- [ ] **Step 1: Remove hard-coded global logging setup from `main.py` and initialize logging from loaded config**

```python
from logging_utils import configure_logging


initial_config = PrinterConfig().get_full_config()
log_settings = configure_logging(initial_config)
logger = logging.getLogger("EdgeServer")
logger.info(" Runtime logging initialized: level=%s debug=%s", log_settings["level_name"], log_settings["debug_logging"])
```

- [ ] **Step 2: Convert preview request and preview download `print(...)` calls in `main.py` into leveled logger messages**

```python
logger.debug(
    "Preview request started: file_id=%s file_type=%s page_index=%s option_keys=%s",
    file_id,
    file_type,
    page_index,
    sorted(options.keys()),
)

logger.info("Preview generated: file_id=%s page_index=%s cached=%s", file_id, page_index, bool(cached))
logger.warning("Preview token missing: file_id=%s", file_id)
logger.exception("Preview request failed: file_id=%s", file_id)
```

- [ ] **Step 3: Collapse multi-line preview download logging into one summary line plus optional debug details**

```python
logger.debug(
    "Downloading preview source: file_id=%s file_name=%s url=%s auth=%s path=%s",
    file_id,
    file_name,
    download_url,
    auth_mode,
    path,
)
logger.info(
    "Preview file downloaded: file_id=%s ext=%s status=%s",
    file_id,
    ext,
    resp.status_code,
)
```

- [ ] **Step 4: Move `printer_config.py` configuration read/write chatter from unconditional prints to module-level debug logging**

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Loading config file: %s", self.config_file)
logger.debug("Config file saved: %s", self.config_file)
logger.info("Config loaded: managed_printers=%s", len(config.get("managed_printers", [])))
```

- [ ] **Step 5: Run focused tests to ensure config loading still works**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_logging_config.py tests/test_config_file_encoding.py -q`

Expected: PASS and no config-loading regressions.

- [ ] **Step 6: Commit the startup/log-bootstrap migration**

```bash
git add main.py printer_config.py tests/test_logging_config.py tests/test_config_file_encoding.py
git commit -m "refactor: route runtime startup logs through logging"
```

### Task 4: Quiet WebSocket, SSE, And File-Manager Noise Without Losing Diagnostics

**Files:**
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\cloud_websocket_client.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\file_manager.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\main.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_interactive_session.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_file_manager_cleanup.py`

- [ ] **Step 1: Add module-level loggers and replace WebSocket lifecycle prints with leveled logging**

```python
logger.info("Connecting websocket: %s", self.websocket_url)
logger.info("WebSocket connected")
logger.warning("WebSocket closed: %s", exc)
logger.info("WebSocket reconnect scheduled in %ss", self.reconnect_interval)
logger.error("WebSocket message handling failed: %s", exc)
```

- [ ] **Step 2: Move heartbeat-success, SSE connect/disconnect, token store/consume, and single-file cleanup events to `DEBUG`**

```python
logger.debug("WebSocket heartbeat sent")
logger.debug("SSE client connected: clients=%s", len(sse_clients))
logger.debug("SSE client disconnected: clients=%s", len(sse_clients))
logger.debug("Stored preview file token: file_id=%s expires_at=%s", file_id, file_access_token_expires_at)
logger.debug("Released preview artifact: file_id=%s reason=%s", file_id, reason)
```

- [ ] **Step 3: Keep high-signal events at `INFO` and collapse repeated message sequences**

```python
logger.info("Received preview task: file_id=%s file_name=%s size=%s", file_id, file_name, file_size)
logger.info("Received print task: job_id=%s file_name=%s printer=%s", job_id, job_name, target_printer)
logger.info("Print file downloaded: job_id=%s auth=%s", job_id, auth_mode)
logger.info("Expired preview resources cleaned: count=%s", len(expired_files))
```

- [ ] **Step 4: Replace ad hoc exception prints with `logger.exception(...)` where traceback is valuable**

```python
try:
    ...
except Exception:
    logger.exception("Preview request failed: file_id=%s", file_id)
    return JSONResponse({"error": "preview failed"}, status_code=500)
```

- [ ] **Step 5: Run session and file-manager regressions**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_interactive_session.py tests/test_file_manager_cleanup.py -q`

Expected: PASS while behavior remains unchanged.

- [ ] **Step 6: Commit the WebSocket/SSE/file-manager log cleanup**

```bash
git add cloud_websocket_client.py file_manager.py main.py tests/test_interactive_session.py tests/test_file_manager_cleanup.py
git commit -m "refactor: reduce websocket and file lifecycle log noise"
```

### Task 5: Tame Print Monitoring And Printer Discovery Logging

**Files:**
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\printer_utils.py`
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\cloud_websocket_client.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_cloud_service_reconfigure.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_user_preview_print_api.py`

- [ ] **Step 1: Convert printer discovery chatter to `DEBUG`, keeping only summary information at `INFO`**

```python
logger.debug("Starting network printer discovery")
logger.debug("Discovered network service: %s", name)
logger.info("Network printer discovery complete: discovered=%s", len(discovered))
logger.warning("Network printer discovery failed: %s", exc)
```

- [ ] **Step 2: Collapse print submit logs into one business summary line**

```python
logger.info(
    "Submitting print job: source=%s printer=%s file=%s",
    cleanup_source,
    printer_name,
    os.path.basename(file_path),
)
```

- [ ] **Step 3: Change queue-polling logs so only state transitions or terminal outcomes are emitted**

```python
if jobs_count != last_jobs_count:
    logger.debug("Print queue count changed: job_id=%s count=%s", cloud_job_id, jobs_count)
    last_jobs_count = jobs_count

logger.info("Falling back to queue polling: job_id=%s", cloud_job_id)
logger.info("Print job completed via queue polling: job_id=%s", cloud_job_id)
logger.warning("Print job polling timed out: job_id=%s", cloud_job_id)
```

- [ ] **Step 4: Keep warnings and failures loud, including missing `job_id`, polling timeouts, and cleanup failures**

```python
logger.warning("Local print job id unavailable, switching to queue polling: job_id=%s", cloud_job_id)
logger.error("Failed to query print queue: job_id=%s error=%s", cloud_job_id, exc)
logger.exception("Print monitor crashed: job_id=%s", cloud_job_id)
```

- [ ] **Step 5: Run print-related regressions**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_user_preview_print_api.py tests/test_cloud_service_reconfigure.py -q`

Expected: PASS with unchanged print behavior.

- [ ] **Step 6: Commit the print-log cleanup**

```bash
git add printer_utils.py cloud_websocket_client.py tests/test_user_preview_print_api.py tests/test_cloud_service_reconfigure.py
git commit -m "refactor: compress print monitoring logs"
```

### Task 6: Verify Default vs Debug Runtime Behavior End To End

**Files:**
- Modify: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_admin_config_api.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_logging_config.py`
- Test: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\tests\test_config_service.py`

- [ ] **Step 1: Extend admin/config tests so public config includes explicit logging settings**

```python
def test_get_config_includes_logging_defaults(self):
    response = self.client.get("/api/admin/config")
    self.assertEqual("INFO", response.json()["settings"]["log_level"])
    self.assertEqual(False, response.json()["settings"]["debug_logging"])
```

- [ ] **Step 2: Run the targeted configuration and logging test suite**

Run: `venv\\Scripts\\python.exe -m pytest tests/test_logging_config.py tests/test_admin_config_api.py tests/test_config_service.py -q`

Expected: PASS

- [ ] **Step 3: Run the full test suite**

Run: `venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS with only pre-existing warnings, and no new business regressions.

- [ ] **Step 4: Perform a manual default-mode runtime check**

Run:

```bash
venv\Scripts\python.exe .\main.py
```

Expected:

- startup logs stay under roughly 10-15 high-signal lines before traffic arrives
- no per-heartbeat success spam
- no multi-line preview-step spam on idle startup

- [ ] **Step 5: Perform a manual debug-mode runtime check**

Run:

```bash
$env:FLYPRINT_DEBUG_LOGGING="true"
venv\Scripts\python.exe .\main.py
```

Expected:

- detailed preview/download/SSE/polling logs appear
- repeated queue polling only logs on state changes, not every second with identical content

- [ ] **Step 6: Commit the verification follow-up**

```bash
git add tests/test_admin_config_api.py tests/test_logging_config.py tests/test_config_service.py
git commit -m "test: cover runtime logging configuration"
```

### Task 7: Final Review And Merge Readiness

**Files:**
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\main.py`
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\cloud_websocket_client.py`
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\file_manager.py`
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\printer_utils.py`
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\printer_config.py`
- Review: `C:\Users\ShiroNeko\Desktop\FlyPrint\fly-print-edge\logging_utils.py`

- [ ] **Step 1: Search for leftover ad hoc debug prefixes and remaining `print(...)` calls in the targeted runtime modules**

Run: `rg -n "\\[DEBUG\\]|\\[INFO\\]|\\[WARNING\\]|print\\(" main.py cloud_websocket_client.py file_manager.py printer_utils.py printer_config.py logging_utils.py`

Expected: no remaining runtime-path `print(...)` calls or hand-written level prefixes in the targeted modules, except any deliberately documented bootstrap edge case.

- [ ] **Step 2: Re-read the spec and verify every requirement maps to code**

Checklist:

- default mode is concise
- debug mode is configurable
- env vars override config
- WebSocket/SSE/preview/polling noise is reduced
- warnings/errors remain visible

- [ ] **Step 3: Capture final verification evidence**

Run:

```bash
venv\Scripts\python.exe -m pytest -q
git status --short --branch
```

Expected:

- tests pass
- working tree only contains intended runtime logging changes

- [ ] **Step 4: Prepare merge summary**

Summary must include:

- which modules were migrated off `print(...)`
- which logs stayed at `INFO`
- which noisy paths were moved to `DEBUG`
- what config/env knobs now exist

