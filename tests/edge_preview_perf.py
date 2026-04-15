import argparse
import json
import threading
import time
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List

import fitz
import requests
from PIL import Image, ImageDraw


ROOT_DIR = Path(__file__).resolve().parents[2]
SAMPLES_DIR = ROOT_DIR / "output" / "test-samples"
RESULTS_DIR = ROOT_DIR / "output" / "test-results"


def ensure_dirs() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def create_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for idx in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"FlyPrint Preview Test PDF - page {idx + 1}/{pages}", fontsize=18)
        page.insert_text((72, 120), "This file is generated for preview performance testing.", fontsize=12)
    doc.save(path)
    doc.close()


def create_image(path: Path) -> None:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, 1180, 1694), outline="black", width=4)
    draw.text((100, 120), "FlyPrint Preview Test Image", fill="black")
    draw.text((100, 200), "Used for edge preview generation timing.", fill="black")
    image.save(path)


def prepare_samples() -> Dict[str, Path]:
    ensure_dirs()
    files = {
        "pdf_1p": SAMPLES_DIR / "pdf_1p.pdf",
        "pdf_3p": SAMPLES_DIR / "pdf_3p.pdf",
        "pdf_5p": SAMPLES_DIR / "pdf_5p.pdf",
        "image_png": SAMPLES_DIR / "image_preview.png",
    }
    if not files["pdf_1p"].exists():
        create_pdf(files["pdf_1p"], 1)
    if not files["pdf_3p"].exists():
        create_pdf(files["pdf_3p"], 3)
    if not files["pdf_5p"].exists():
        create_pdf(files["pdf_5p"], 5)
    if not files["image_png"].exists():
        create_image(files["image_png"])
    return files


def infer_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".bmp"}:
        return "image/png"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".doc":
        return "application/msword"
    return "application/octet-stream"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def start_file_server(directory: Path) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    handler = partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def call_preview(edge_base_url: str, file_id: str, file_url: str, file_name: str, file_type: str) -> Dict[str, float]:
    payload = {
        "file_id": file_id,
        "file_url": file_url,
        "file_name": file_name,
        "file_type": file_type,
        "options": {
            "page_index": 0,
            "paper_size": "A4",
            "scale_mode": "fit",
            "max_upscale": 2.0,
        },
    }
    started = time.perf_counter()
    response = requests.post(f"{edge_base_url}/api/preview", json=payload, timeout=60)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(body.get("message", "preview failed"))
    return {
        "elapsed_ms": round(elapsed_ms, 2),
        "page_count": body.get("page_count", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure FlyPrint edge preview performance.")
    parser.add_argument("--edge-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--custom-file", help="Optional custom file for manual preview timing, such as a DOCX resume.")
    args = parser.parse_args()

    status_resp = requests.get(f"{args.edge_base_url}/api/status", timeout=5)
    status_resp.raise_for_status()

    files = prepare_samples()
    file_server, _thread, port = start_file_server(SAMPLES_DIR)
    records: List[Dict[str, object]] = []

    try:
        scenarios = [
            ("pdf_1p_cold", files["pdf_1p"], "application/pdf"),
            ("pdf_3p_cold", files["pdf_3p"], "application/pdf"),
            ("pdf_5p_cold", files["pdf_5p"], "application/pdf"),
            ("image_png_cold", files["image_png"], "image/png"),
        ]
        if args.custom_file:
            custom_path = Path(args.custom_file).expanduser().resolve()
            if not custom_path.exists():
                raise FileNotFoundError(f"custom file not found: {custom_path}")
            scenarios.append((f"custom_{custom_path.suffix.lstrip('.').lower()}_cold", custom_path, infer_file_type(custom_path)))

        for scenario, path, file_type in scenarios:
            file_id = str(uuid.uuid4())
            if path.parent == SAMPLES_DIR:
                file_url = f"http://127.0.0.1:{port}/{path.name}"
            else:
                copied_path = SAMPLES_DIR / path.name
                copied_path.write_bytes(path.read_bytes())
                file_url = f"http://127.0.0.1:{port}/{copied_path.name}"
            result = call_preview(args.edge_base_url, file_id, file_url, path.name, file_type)
            records.append(
                {
                    "scenario": scenario,
                    "file_name": path.name,
                    "file_type": file_type,
                    "elapsed_ms": result["elapsed_ms"],
                    "page_count": result["page_count"],
                }
            )
            print(f"{scenario}: {result['elapsed_ms']} ms")

            if scenario == "pdf_1p_cold":
                second = call_preview(args.edge_base_url, file_id, file_url, path.name, file_type)
                records.append(
                    {
                        "scenario": "pdf_1p_hot",
                        "file_name": path.name,
                        "file_type": file_type,
                        "elapsed_ms": second["elapsed_ms"],
                        "page_count": second["page_count"],
                    }
                )
                print(f"pdf_1p_hot: {second['elapsed_ms']} ms")

        output_path = RESULTS_DIR / f"edge_preview_perf_{time.strftime('%Y%m%d_%H%M%S')}.json"
        output_path.write_text(json.dumps({"edge_base_url": args.edge_base_url, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Preview performance result file: {output_path}")
        return 0
    finally:
        file_server.shutdown()
        file_server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
