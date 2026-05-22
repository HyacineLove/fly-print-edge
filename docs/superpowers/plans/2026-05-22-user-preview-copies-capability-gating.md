# User Preview Copies Capability Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable global copy-count limits to the user preview flow and gate preview options against default printer capabilities.

**Architecture:** Extend the existing `settings` config model with `copies_min` and `copies_max`, expose those values through the current initialization payload, and clamp submitted print copies on the backend. Update the admin config UI to edit the new settings, then refactor the user preview page so copies are controlled by increment/decrement buttons and unsupported duplex/color options render as disabled while preserving the current preview workflow.

**Tech Stack:** Python, FastAPI, unittest/pytest, vanilla JavaScript, static HTML/CSS

---

### Task 1: Lock Down Backend Config Behavior

**Files:**
- Modify: `config_service.py`
- Modify: `printer_config.py`
- Modify: `tests/test_config_service.py`

- [ ] **Step 1: Write the failing config tests**

```python
    def test_build_public_config_supplies_default_copy_limits(self):
        payload = self.service.build_public_config(self.raw_config)
        self.assertEqual(payload["settings"]["copies_min"], 1)
        self.assertEqual(payload["settings"]["copies_max"], 3)

    def test_validate_rejects_invalid_copy_limit_ranges(self):
        changed = {
            **self.raw_config,
            "settings": {"copies_min": 4, "copies_max": 2},
        }
        errors = self.service.validate(changed)
        self.assertIn("settings.copies_max must be an integer and >= settings.copies_min", errors)
```

- [ ] **Step 2: Run the targeted config tests and verify they fail**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_config_service.py -q`

Expected: failing assertions because `copies_min` / `copies_max` are not normalized or validated yet.

- [ ] **Step 3: Implement minimal config defaults and validation**

```python
        settings = data.setdefault("settings", {})
        settings["copies_min"], settings["copies_max"] = self._normalize_copy_limits(
            settings.get("copies_min"),
            settings.get("copies_max"),
        )
```

```python
        copies_min, copies_max = self._normalize_copy_limits(
            settings.get("copies_min"),
            settings.get("copies_max"),
        )
        if settings.get("copies_min") not in (None, "", copies_min):
            errors.append("settings.copies_min must be an integer >= 1")
        if settings.get("copies_max") not in (None, "", copies_max):
            errors.append("settings.copies_max must be an integer and >= settings.copies_min")
```

- [ ] **Step 4: Re-run the targeted config tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_config_service.py -q`

Expected: PASS with zero failures.

### Task 2: Expose Copy Limits And Clamp Print Submission

**Files:**
- Modify: `main.py`
- Modify: `tests/test_admin_config_api.py`
- Create: `tests/test_user_preview_print_api.py`

- [ ] **Step 1: Write the failing API tests for public config and print clamping**

```python
    def test_get_config_exposes_copy_limits(self):
        with patch.object(main, "printer_manager", self.printer_manager):
            result = asyncio.run(main.get_admin_config())
        self.assertEqual(result["settings"]["copies_min"], 1)
        self.assertEqual(result["settings"]["copies_max"], 3)
```

```python
    def test_submit_print_clamps_copies_to_settings_max(self):
        request = DummyRequest({
            "session_id": "session-1",
            "file_id": "file-1",
            "options": {"copies": 99, "duplex": "simplex", "color_mode": "color"},
        })
        response = asyncio.run(main.submit_print(request))
        self.assertEqual(response["success"], True)
        sent = self.websocket.sent_messages[0]["data"]["options"]
        self.assertEqual(sent["copies"], 3)
```

- [ ] **Step 2: Run the targeted API tests and verify they fail**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_config_api.py tests/test_user_preview_print_api.py -q`

Expected: failure because copy limits are not exposed and `/api/print` does not clamp `copies`.

- [ ] **Step 3: Implement minimal backend exposure and clamping**

```python
def _normalize_copy_limits(settings: Dict[str, Any]) -> Tuple[int, int]:
    copies_min = _safe_int(settings.get("copies_min"), 1)
    copies_min = max(1, copies_min)
    copies_max = _safe_int(settings.get("copies_max"), 3)
    copies_max = max(copies_min, copies_max)
    return copies_min, copies_max
```

```python
        settings = _get_runtime_settings()
        copies_min, copies_max = _normalize_copy_limits(settings)
        options["copies"] = min(copies_max, max(copies_min, _safe_int(options.get("copies"), copies_min)))
```

- [ ] **Step 4: Re-run the targeted API tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_config_api.py tests/test_user_preview_print_api.py -q`

Expected: PASS with zero failures.

### Task 3: Extend The Admin Settings UI

**Files:**
- Modify: `static/admin/main.js`
- Modify: `tests/test_admin_shell_structure.py`

- [ ] **Step 1: Write the failing admin UI assertions**

```python
    def test_admin_main_renders_copy_limit_settings(self):
        script = pathlib.Path("static/admin/main.js").read_text(encoding="utf-8")
        self.assertIn("settings_copies_min", script)
        self.assertIn("settings_copies_max", script)
```

- [ ] **Step 2: Run the targeted admin shell test and verify it fails**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_shell_structure.py -q`

Expected: failure because the new settings fields are not present yet.

- [ ] **Step 3: Implement the admin payload and settings section updates**

```javascript
      settings: {
        default_paper_size: cfg.settings.default_paper_size || "",
        default_scale_mode: cfg.settings.default_scale_mode || "",
        default_max_upscale: normalizedMaxUpscale,
        copies_min: Number(cfg.settings.copies_min || 1),
        copies_max: Number(cfg.settings.copies_max || 3),
        libreoffice_path: cfg.settings.libreoffice_path || "",
        pdf_printer_path: cfg.settings.pdf_printer_path || "",
      },
```

```javascript
        <div class="field">
          <label for="settings_copies_min">最小打印份数</label>
          <input id="settings_copies_min" type="number" min="1" data-section="settings" data-key="copies_min" value="${cfg.copies_min ?? 1}">
        </div>
```

- [ ] **Step 4: Re-run the targeted admin shell test and verify it passes**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_admin_shell_structure.py -q`

Expected: PASS with zero failures.

### Task 4: Refactor The User Preview Page Controls

**Files:**
- Modify: `static/user/html/preview.html`
- Modify: `static/user/main.js`
- Modify: `static/user/css/preview.css`
- Create: `tests/test_user_preview_assets.py`

- [ ] **Step 1: Write the failing user asset assertions**

```python
    def test_preview_html_uses_increment_decrement_copy_controls(self):
        html = pathlib.Path("static/user/html/preview.html").read_text(encoding="utf-8")
        self.assertIn('id="55_118"', html)
        self.assertIn('id="55_119"', html)
        self.assertNotIn(">2<", html)
        self.assertNotIn(">3<", html)
```

```python
    def test_preview_script_keeps_copy_and_duplex_changes_off_preview_refresh(self):
        script = pathlib.Path("static/user/main.js").read_text(encoding="utf-8")
        self.assertIn("resetPreviewCountdown()", script)
        self.assertIn("applyPrinterCapabilityState", script)
```

- [ ] **Step 2: Run the targeted preview asset tests and verify they fail**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: failure because the preview page still uses fixed `1/2/3` buttons and weak capability gating.

- [ ] **Step 3: Implement the preview control refactor**

```javascript
  function getCopyLimitState() {
    const settings = state.runtimeSettings || {};
    const min = Math.max(1, Number(settings.copies_min || 1));
    const max = Math.max(min, Number(settings.copies_max || 3));
    return { min, max };
  }
```

```javascript
    const changeCopies = (delta) => {
      if (!previewFirstLoadDone || previewFailureMode) return;
      const { min, max } = getCopyLimitState();
      state.options.copies = Math.min(max, Math.max(min, Number(state.options.copies || min) + delta));
      saveState();
      renderOptionsUI();
      resumePreviewCountdown(true);
    };
```

```javascript
    const pickDuplex = (value) => {
      if (!previewFirstLoadDone || previewFailureMode || !state.capabilityState.duplexSupported && value !== "simplex") return;
      state.options.duplex = value;
      saveState();
      renderOptionsUI();
      resumePreviewCountdown(true);
    };
```

- [ ] **Step 4: Re-run the targeted preview asset tests and verify they pass**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_user_preview_assets.py -q`

Expected: PASS with zero failures.

### Task 5: Run Regression Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-05-22-user-preview-copies-capability-gating.md`

- [ ] **Step 1: Run the focused regression suite**

Run: `.\\venv\\Scripts\\python.exe -m pytest tests/test_config_service.py tests/test_admin_config_api.py tests/test_admin_shell_structure.py tests/test_user_preview_print_api.py tests/test_user_preview_assets.py -q`

Expected: PASS with zero failures.

- [ ] **Step 2: Run the full project test suite**

Run: `.\\venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS with the existing deprecation warnings only.

- [ ] **Step 3: Review git diff for requirement coverage**

Run: `git diff --stat`

Expected: config, admin UI, user UI, and tests all represented.

- [ ] **Step 4: Commit the implementation**

```bash
git add config_service.py printer_config.py main.py static/admin/main.js static/user/html/preview.html static/user/main.js static/user/css/preview.css tests/test_config_service.py tests/test_admin_config_api.py tests/test_admin_shell_structure.py tests/test_user_preview_print_api.py tests/test_user_preview_assets.py docs/superpowers/plans/2026-05-22-user-preview-copies-capability-gating.md
git commit -m "feat: add configurable preview copy controls"
```
