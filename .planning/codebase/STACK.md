# Technology Stack

**Analysis Date:** 2025-03-17

## Languages

**Primary:**
- Python 3.x - Entire application runtime (backend, services, printer management)

**Secondary:**
- HTML/CSS/JavaScript - Frontend user and admin interfaces
- Shell/PowerShell - Startup scripts (`start.sh`, `start.ps1`, `cleanup.bat`)

## Runtime

**Environment:**
- Python 3.x
- Cross-platform support: Windows, Linux

**Package Manager:**
- pip (standard Python package manager)
- Lockfile: Not present (only `requirements.txt`)

## Frameworks

**Core:**
- FastAPI 0.129.0+ - Web framework for REST API
- Uvicorn 0.41.0+ - ASGI server for FastAPI
- Gradio 4.7.0+ - Web UI framework

**WebSocket:**
- websockets 14.0+ - WebSocket client for cloud communication

**Printer Management:**
- Platform-specific: Windows uses `win32print`/`win32com`, Linux uses `cups`

**Testing:**
- Not detected (test files exist in `tests/` but framework not specified)

**Build/Dev:**
- No build process - Python runs directly from source

## Key Dependencies

**Critical:**
- `fastapi>=0.129.0` - Web API framework
- `uvicorn>=0.41.0` - ASGI server
- `gradio>=4.7.0` - Web UI framework
- `websockets>=14.0` - WebSocket client for real-time cloud communication

**Printer Operations:**
- `pywin32>=306` - Windows printer API access (Windows only)
- `WMI>=1.5.1` - Windows Management Instrumentation (Windows only)

**PDF/Image Processing:**
- `PyPDF2>=3.0.0` - PDF manipulation
- `pymupdf>=1.24.0` - PDF rendering (`fitz`)
- `Pillow>=10.0.0` - Image processing

**Document Conversion:**
- LibreOffice/WPS COM automation on Windows for Word to PDF conversion

**Network Discovery:**
- `zeroconf>=0.131.0` - mDNS/Bonjour service discovery for network printers

**System Monitoring:**
- `psutil>=5.8.0` - System resource monitoring (CPU, memory, disk)

**Utilities:**
- `pandas>=2.0.0` - Data manipulation for printer lists
- `requests>=2.25.0` - HTTP client
- `qrcode>=7.4.2` - QR code generation for uploads

## Configuration

**Environment:**
- JSON-based configuration: `config.json` (not committed, created at runtime)
- Template: `config.example.json`
- Configuration managed by `printer_config.py`

**Key Configuration Sections:**
- `network`: bind_address, port (default: 127.0.0.1:7860)
- `printers`: discovery_mode (auto/static), static_list
- `cloud`: enabled, base_url, auth_url, client_id, client_secret, node_name, location
- `managed_printers`: List of configured printers
- `default_printer_id`: Currently selected default printer

**Build:**
- No build configuration - Python is interpreted

**Deployment:**
- Portable mode: Uses project-local `temp/` directory
- `portable_temp.py` - Custom temp directory management

## Platform Requirements

**Development:**
- Python 3.x
- pip
- Platform-specific: Windows requires `pywin32` and `WMI`

**Production:**
- Target: Edge print servers (kiosks)
- Deployment: Standalone Python application
- Web server: Uvicorn (built-in)
- Default port: 7860

**External Dependencies (Runtime):**
- LibreOffice or WPS Office (for Word document conversion to PDF)
- CUPS (Linux) or Windows Print Spooler (Windows)
- Network: WebSocket connection to cloud service

---

*Stack analysis: 2025-03-17*
