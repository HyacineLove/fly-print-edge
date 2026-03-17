# Codebase Structure

**Analysis Date:** 2026-03-17

## Directory Layout

```
fly-print-edge/
├── main.py                    # Application entry point, FastAPI routes
├── config.json                # Runtime configuration (created from example)
├── config.example.json        # Configuration template
├── requirements.txt           # Python dependencies
├── start.sh                   # Linux/macOS startup script
├── start.ps1                  # PowerShell startup script
│
├── cloud_*.py                 # Cloud integration modules
│   ├── cloud_service.py       # Main cloud service orchestrator
│   ├── cloud_auth.py          # OAuth2 authentication client
│   ├── cloud_api_client.py    # REST API client
│   ├── cloud_websocket_client.py  # WebSocket connection handler
│   ├── cloud_heartbeat_service.py # Heartbeat/ping service
│   └── edge_node_info.py      # Edge node metadata collection
│
├── printer_*.py               # Printer management modules
│   ├── printer_utils.py       # PrinterManager core class
│   ├── printer_config.py      # Configuration management
│   ├── printer_parsers.py     # Parameter parsing utilities
│   ├── printer_windows.py     # Windows-specific implementation
│   └── printer_linux.py       # Linux-specific implementation
│
├── file_manager.py            # Temporary file lifecycle management
├── portable_temp.py           # Portable temp directory utilities
│
├── static/                    # Web UI assets
│   ├── index.html             # Root redirect to user interface
│   ├── user/                  # User kiosk interface
│   │   ├── Index.html         # Main user page entry
│   │   ├── main.js            # User interface JavaScript
│   │   ├── css/               # Stylesheets
│   │   ├── html/              # HTML partials
│   │   │   ├── done.html
│   │   │   ├── login.html
│   │   │   ├── preview.html
│   │   │   └── printing.html
│   │   ├── fonts/             # Font assets
│   │   └── images/            # Image assets
│   └── admin/                 # Admin management interface
│       ├── Index.html         # Admin page entry
│       ├── main.js            # Admin interface JavaScript
│       ├── css/               # Admin stylesheets
│       └── html/              # Admin HTML partials
│           └── index.html
│
├── tests/                     # Test and diagnostic scripts
│   ├── test_printer_system_check.py
│   ├── test_paper_detection.py
│   ├── test_letter_invoice_fix.py
│   └── error_detection_probe.py
│
└── temp/                      # Portable temp directory (created at runtime)
```

## Directory Purposes

**Root Directory (`./`):**
- Purpose: Application code and configuration
- Contains: Entry point, business logic modules, config files
- Key files: `main.py`, `config.json`, all `cloud_*.py`, all `printer_*.py`

**`static/`:**
- Purpose: Web UI static assets served by FastAPI
- Contains: HTML, CSS, JavaScript, fonts, images
- Served at: `/static` URL path
- Generated: No
- Committed: Yes (except user-generated content)

**`static/user/`:**
- Purpose: Kiosk/user-facing interface
- Contains: User HTML, JavaScript, styling for print kiosk
- Key files: `Index.html`, `main.js`, `html/preview.html`

**`static/admin/`:**
- Purpose: Administrative interface
- Contains: Printer management, cloud status, node configuration UI
- Key files: `Index.html`, `main.js`, `html/index.html`

**`tests/`:**
- Purpose: Diagnostic and test scripts
- Contains: Standalone test utilities for printer detection and debugging
- Run from: Project root (`python tests/test_xxx.py`)

**`temp/`:**
- Purpose: Portable temporary file storage
- Created by: `portable_temp.py` on first access
- Contains: Downloaded preview files, converted PDFs
- Generated: Yes (at runtime)
- Committed: No (in `.gitignore`)

## Key File Locations

**Entry Points:**
- `main.py`: Primary application entry (FastAPI + Uvicorn)
- `start.sh`: Unix startup wrapper with venv handling
- `start.ps1`: PowerShell startup wrapper with venv handling

**Configuration:**
- `config.json`: Live configuration (not committed)
- `config.example.json`: Template for new setups

**Core Logic:**
- `main.py`: FastAPI routes, request handlers, preview generation
- `cloud_service.py`: Cloud service lifecycle and orchestration
- `printer_utils.py`: PrinterManager class (discovery, printing)

**Platform Abstractions:**
- `printer_windows.py`: Windows printing (win32print, WMI)
- `printer_linux.py`: Linux printing (CUPS)

**Cloud Integration:**
- `cloud_auth.py`: OAuth2 token management
- `cloud_api_client.py`: REST API calls
- `cloud_websocket_client.py`: WebSocket communication
- `cloud_heartbeat_service.py`: Keepalive pings
- `edge_node_info.py`: System information gathering

**Infrastructure:**
- `file_manager.py`: Background file cleanup service
- `portable_temp.py`: Temp directory abstraction
- `printer_config.py`: Config file read/write operations
- `printer_parsers.py`: Print parameter parsing

**Frontend:**
- `static/user/main.js`: Kiosk UI logic, SSE handling
- `static/user/html/preview.html`: File preview interface
- `static/admin/main.js`: Admin UI, printer management

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `cloud_service.py`)
- HTML files: `PascalCase.html` for entry points (`Index.html`), `snake_case.html` for partials
- JavaScript: `main.js` for entry point, descriptive names for utilities
- Test files: `test_*.py` prefix

**Directories:**
- Lowercase with underscores: `cloud_websocket/`, `user/`, `admin/`

**Classes:**
- PascalCase: `PrinterManager`, `CloudService`, `CloudAuthClient`

**Functions:**
- snake_case: `get_printers()`, `register_node()`, `generate_preview()`

**Variables:**
- snake_case: `printer_manager`, `node_id`, `preview_cache`
- Global instances: lowercase with type name (e.g., `printer_manager`, `cloud_service`)

**Constants:**
- UPPER_CASE at module level: `BASE_DIR`, `STATIC_DIR`, `DEFAULT_PAPER_SIZE`

## Where to Add New Code

**New Cloud Integration:**
- Implementation: `cloud_*.py` module
- Integration: Add to `CloudService` initialization in `cloud_service.py`

**New Printer Features:**
- Cross-platform: Add to `printer_utils.py` PrinterManager
- Windows-specific: `printer_windows.py` WindowsEnterprisePrinter
- Linux-specific: `printer_linux.py` LinuxPrinter

**New API Endpoints:**
- User-facing: Add FastAPI route in `main.py` (public routes)
- Admin routes: Add to `admin_router` in `main.py` with `/api/admin` prefix

**New Frontend UI:**
- User interface: Add HTML to `static/user/html/`, logic to `static/user/main.js`
- Admin interface: Add HTML to `static/admin/html/`, logic to `static/admin/main.js`

**New Configuration Options:**
- Schema: Update `config.example.json`
- Loading: Update `printer_config.py` load_config()
- Default values: Add to default_config in `printer_config.py`

**New Background Services:**
- Implementation: New module or extend existing service class
- Lifecycle: Hook into `CloudService.start()` / `CloudService.stop()`
- Threading: Use daemon threads, store references for cleanup

## Special Directories

**`temp/`:**
- Purpose: Portable temporary storage
- Created: Automatically on first access via `portable_temp.py`
- Cleanup: Automatic via `FileManager` (30 min TTL) + startup cleanup (24h max age)
- Permissions: 700 (owner only)

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (by Python interpreter)
- Committed: No (in `.gitignore`)

**`.planning/codebase/`:**
- Purpose: Codebase documentation for GSD workflow
- Contains: Architecture and structure documentation
- Generated: No (maintained manually)

---

*Structure analysis: 2026-03-17*
