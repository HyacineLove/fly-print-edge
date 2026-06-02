# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FlyPrint Edge Kiosk — a Windows/Linux edge node that runs a local FastAPI server as a print kiosk. It integrates with a cloud backend (OAuth2 + REST + WebSocket) for remote print job management, provides in-browser file preview (including Word→PDF conversion), and serves both user-facing (print) and admin (config/printer management) SPAs.

## Commands

```bash
# Run the edge server (defaults to 127.0.0.1:7860, configurable in config.json)
python main.py

# Run all tests (use venv Python — system Python lacks zeroconf)
venv/Scripts/python.exe -m unittest discover tests

# Run a single test file
venv/Scripts/python.exe -m unittest tests/test_config_service.py

# Build Windows installer (PyInstaller + Inno Setup — auto-detects venv)
# NOTE: PyInstaller must run via venv Python to discover all deps (fitz etc.)
python release/build_installer.py
```

Tests use the standard library `unittest` module (no pytest). Each test file has `if __name__ == "__main__": unittest.main()` so they can also be run directly.

## Architecture

### Entry Point & Server (`main.py`)

The monolithic FastAPI application. All route handlers live in this file (not split across modules). Key sections:

- **Startup**: initializes `PrinterManager`, `ConfigService`, `FileManager` (background cleanup thread), and `CloudService` with WebSocket message listeners wired to SSE broadcast
- **User routes**: `/api/qr_code` (generates upload QR), `/api/events` (SSE stream), `/api/preview` (file→image with caching), `/api/print` (submit to cloud), `/api/cleanup` (cancel/session cleanup), `/api/session/current`
- **Admin routes** (`/api/admin/*` via APIRouter): config get/save, cloud connection test/register, managed printer CRUD, discovered printer listing, node re-registration
- **SSE**: all connected clients get broadcasts for `preview_file`, `error`, `cloud_error`, `job_status`, `printer_added`, `printer_deleted`, `default_printer_changed`, `node_status_changed`
- **Preview pipeline**: download file → cache source → Word→PDF conversion (WPS COM → LibreOffice CLI → Word COM fallback) → render PDF page via `pymupdf` → apply paper-size layout → base64 PNG

### Cloud Integration Layer

All cloud modules live in dedicated files at the project root:

| File | Role |
|---|---|
| `cloud_auth.py` | OAuth2 client credentials flow, token caching with 5-min refresh window |
| `cloud_api_client.py` | REST calls: node registration, printer registration/unregistration |
| `cloud_websocket_client.py` | Persistent WebSocket for receiving cloud push messages (print jobs, commands). Runs its own asyncio event loop in a daemon thread. Has message handler registration and dedup cache for completed jobs |
| `cloud_heartbeat_service.py` | Sends periodic WebSocket heartbeats with system metrics (CPU, memory, disk via `psutil`) |
| `cloud_service.py` | Coordinator: wires auth + API + WebSocket + heartbeat together. Handles re-registration, stale node detection, printer cloud sync |

### Printer Management

- `printer_config.py` — `PrinterConfig`: JSON file read/write (`config.json`), printer list management, default printer tracking
- `printer_utils.py` — `PrinterManager` (top-level facade) and `PrinterDiscovery` (local + network via zeroconf). Platform dispatch: imports `WindowsEnterprisePrinter` or `LinuxPrinter`
- `printer_windows.py` — Large module (~102KB): Win32 print queue operations, driver info, capabilities queries
- `printer_linux.py` — CUPS-based printer operations
- `printer_parsers.py` — `PrinterParameterParser` base class with brand-specific subclasses (e.g., Hiti) for parsing printer capability output

### Session & File Lifecycle

- `interactive_session.py` — `InteractiveSessionManager`: thread-safe state machine tracking a single active user session through states: `awaiting_preview` → `preview_ready` → `print_submitted` → `printing` → `completed`/`failed`. Ties upload tokens to file previews and cloud job IDs.
- `file_manager.py` — `FileManager`: singleton managing temporary file lifecycle. Background thread cleans up files older than TTL (default 30 min). Tracks preview source files, generated PDFs, print artifacts, and file access tokens.

### Config & Settings

- `config_service.py` — `ConfigService`: validates and applies admin config changes. Categories: `RESTART_REQUIRED_FIELDS` (network bind, port, discovery mode) need server restart; all others apply live. Masks `client_secret` in public config. Normalizes copy limits, log levels, upscale values.

### Frontend (`static/`)

- **`/`** → redirects to `static/user/Index.html`
- **`/admin`** → serves `static/admin/html/index.html`
- **User SPA**: custom ES module router (`app-controller.js` → `router.js` → per-view modules). Views: login (QR code display), preview (file pages, paper size, copies, duplex, color), printing (progress), done. Shared modules: SSE client, API wrapper, session state, capabilities, toast, touch-guard (idle timeout)
- **Admin SPA**: state-render pattern (`main.js` creates state, binds actions, calls render on change). Modules: config form, managed/discovered printer tables, cloud status, toast, loading overlay
- Both SPAs consume the same SSE stream at `/api/events`

### Windows ZIP Release (`release/windows_zip/`)

- `build_release.py` — copies app Python files + static dir + template scripts/launchers into a portable directory, then ZIPs it
- Templates include `bootstrap.ps1` (creates venv, installs requirements), `launch.ps1`, `runtime.ps1`, `.cmd` launchers, and `README-runtime.md`

## Key Patterns

- **No database**: all persistent state is in `config.json` (UTF-8 with BOM). The `PrinterConfig` class is the single source of truth for disk I/O.
- **In-memory caches**: `preview_cache` (rendered page data URLs), `preview_page_cache` (per-file PIL Image objects for PDF pages). Cleaned up by `FileManager` background thread.
- **Thread safety**: `InteractiveSessionManager` uses `threading.RLock`; `FileManager` uses locks for preview_files, tokens, and artifacts dicts.
- **Cloud WebSocket threading**: runs its own `asyncio` loop in a daemon thread. Callbacks are dispatched via `main_loop.call_soon_threadsafe()` to touch the SSE queues.
- **Word→PDF conversion** (Windows only): tries WPS COM (`Kwps.Application`) → LibreOffice CLI (`soffice --headless`) → Word COM (`Word.Application`). All COM calls wrapped in `pythoncom.CoInitialize/Uninitialize`.
- **Portable temp**: uses `<project>/temp/` instead of system temp dir (`portable_temp.py`). Cleaned on startup (24h max age) and periodically by `FileManager`.
