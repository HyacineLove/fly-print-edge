# Architecture

**Analysis Date:** 2026-03-17

## Pattern Overview

**Overall:** Modular Edge Service with Layered Cloud Integration

**Key Characteristics:**
- FastAPI-based HTTP server with WebSocket cloud connectivity
- Platform-specific printer abstractions (Windows/Linux)
- Async/sync hybrid architecture for I/O and hardware operations
- Event-driven message passing via SSE (Server-Sent Events)
- Single-file JSON configuration management

## Layers

**Presentation Layer:**
- Purpose: Web UI for kiosk mode and admin management
- Location: `static/user/`, `static/admin/`
- Contains: HTML pages, CSS, JavaScript, fonts, images
- Depends on: FastAPI static file serving, API endpoints
- Used by: Browser clients (kiosk users, administrators)

**API Layer (FastAPI):**
- Purpose: HTTP API for UI interactions and system operations
- Location: `main.py`
- Contains: Route handlers, request validation, response formatting
- Depends on: PrinterManager, CloudService, FileManager
- Used by: Frontend JavaScript, admin UI

**Service Layer:**
- Purpose: Business logic orchestration and cloud integration
- Location: `cloud_service.py`, `cloud_*.py` modules
- Contains: Cloud authentication, WebSocket client, heartbeat service, print job handling
- Depends on: PrinterManager, API clients
- Used by: API layer, background threads

**Printer Management Layer:**
- Purpose: Printer discovery, configuration, and print operations
- Location: `printer_utils.py`, `printer_config.py`
- Contains: PrinterManager, PrinterDiscovery, PrinterConfig
- Depends on: Platform-specific printer implementations
- Used by: API layer, CloudService

**Platform Abstraction Layer:**
- Purpose: OS-specific printer operations
- Location: `printer_windows.py`, `printer_linux.py`
- Contains: WindowsEnterprisePrinter, LinuxPrinter classes
- Depends on: OS-specific APIs (win32print, WMI, CUPS)
- Used by: PrinterManager

**Infrastructure Layer:**
- Purpose: Cross-cutting concerns (file management, temp storage, auth)
- Location: `file_manager.py`, `portable_temp.py`, `cloud_auth.py`
- Contains: FileManager, portable temp utilities, CloudAuthClient
- Depends on: Filesystem, external auth services
- Used by: All upper layers

## Data Flow

**Print Job Flow (Cloud → Local):**

1. Cloud sends print job via WebSocket (`cloud_websocket_client.py`)
2. PrintJobHandler receives and validates job
3. File is downloaded via authenticated API call
4. PrinterManager queues and executes print job
5. Platform-specific printer class sends to hardware
6. Status updates sent back to cloud via WebSocket

**Preview Flow (User Upload → Display):**

1. User scans QR code, uploads to cloud
2. Cloud sends `preview_file` message via WebSocket
3. `handle_cloud_message()` in `main.py` broadcasts via SSE
4. Frontend receives SSE event, displays preview interface
5. File is downloaded from cloud to portable temp directory
6. PDF/image is rendered to preview (cached in memory)

**Printer Registration Flow:**

1. Admin selects printers in admin UI
2. API sends to `cloud_service.py` register methods
3. Node registration (if not already registered)
4. Individual printer registration to cloud API
5. Local config updated with cloud printer IDs

## Key Abstractions

**PrinterManager:**
- Purpose: Central coordinator for all printer operations
- Location: `printer_utils.py`
- Pattern: Facade over platform-specific implementations
- Responsibilities: Discovery, status monitoring, print submission, queue management

**CloudService:**
- Purpose: Unified cloud connectivity manager
- Location: `cloud_service.py`
- Pattern: Service orchestrator (combines auth, WebSocket, heartbeat, API)
- Responsibilities: Node lifecycle, cloud message routing, status reporting

**CloudAuthClient:**
- Purpose: OAuth2 client credentials flow management
- Location: `cloud_auth.py`
- Pattern: Token manager with automatic refresh
- Responsibilities: Token acquisition, caching, expiration handling

**FileManager:**
- Purpose: Temporary file lifecycle management
- Location: `file_manager.py`
- Pattern: Background cleanup service
- Responsibilities: File registration, TTL-based cleanup, cache coordination

**Platform Printer Classes:**
- Purpose: OS-specific printer operations
- Location: `printer_windows.py`, `printer_linux.py`
- Pattern: Strategy/Adapter for platform differences
- Responsibilities: System printer enumeration, job submission, status querying

## Entry Points

**Application Entry:**
- Location: `main.py`
- Triggers: `python main.py` or `start.sh`/`start.ps1`
- Responsibilities:
  - Initialize FastAPI app
  - Start printer manager
  - Initialize file manager with cleanup
  - Start cloud service (if enabled)
  - Begin Uvicorn server

**Admin UI Entry:**
- Location: `static/admin/html/index.html`
- Route: `GET /admin`
- Responsibilities: Printer management, cloud status, node operations

**User/Kiosk Entry:**
- Location: `static/user/html/index.html` (redirected from `/`)
- Route: `GET /`
- Responsibilities: QR code display, preview, print submission

**Cloud WebSocket Connection:**
- Location: `cloud_websocket_client.py`
- Triggered by: CloudService.start()
- Responsibilities: Bidirectional cloud communication, message dispatch

**Heartbeat Service:**
- Location: `cloud_heartbeat_service.py`
- Triggered by: CloudService (separate thread)
- Responsibilities: Periodic node health pings via WebSocket

## Error Handling

**Strategy:** Layer-specific with propagation to SSE clients

**Patterns:**
- FastAPI exception handlers return JSON error responses
- Cloud errors forwarded to WebSocket error handlers
- Background thread exceptions logged, service continues
- Printer errors stored in job status, reported to cloud
- File operations wrapped in try/except with cleanup on failure

## Cross-Cutting Concerns

**Logging:**
- Tool: Python `logging` module
- Pattern: Module-level loggers with consistent format
- Config: Basic config in `main.py`, INFO level default

**Configuration:**
- Tool: Single JSON file (`config.json`)
- Pattern: `PrinterConfig` class manages reads/writes
- Sections: managed_printers, settings, network, printers, cloud, default_printer_id

**Authentication:**
- Internal API: No authentication (disabled in code)
- Cloud API: OAuth2 client credentials flow
- File access: Time-limited tokens from cloud

**Temp File Management:**
- Location: Project-relative `temp/` directory
- Pattern: Portable temp with automatic cleanup (30 min TTL)
- Registration: Files tracked in FileManager with access timestamps

---

*Architecture analysis: 2026-03-17*
