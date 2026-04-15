import json
import threading
import time
from pathlib import Path
from typing import Dict, List

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT_DIR / "output" / "test-results"
SAMPLES_DIR = ROOT_DIR / "output" / "test-samples"
EDGE_BASE_URL = "http://127.0.0.1:7860"
CLOUD_BASE_URL = "http://127.0.0.1:8012"


def ensure_dirs() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def wait_for_preview_event(timeout: int = 20) -> Dict[str, object]:
    result: Dict[str, object] = {}

    def listener() -> None:
        with requests.get(f"{EDGE_BASE_URL}/api/events", stream=True, timeout=timeout + 5) as response:
            for line in response.iter_lines(decode_unicode=True):
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if payload.get("type") == "preview_file":
                    result["payload"] = payload
                    result["received_at"] = time.perf_counter()
                    return

    thread = threading.Thread(target=listener, daemon=True)
    thread.start()
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if "payload" in result:
            return result
        time.sleep(0.05)
    raise TimeoutError("preview_file event not received in time")


def upload_and_preview(file_path: Path, file_type: str) -> Dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(2):
        event_result: Dict[str, object] = {}
        listener_thread = threading.Thread(
            target=lambda: event_result.update(wait_for_preview_event(timeout=20)),
            daemon=True,
        )
        listener_thread.start()
        time.sleep(0.3)

        qr_resp = requests.get(f"{EDGE_BASE_URL}/api/qr_code", timeout=20)
        qr_resp.raise_for_status()
        qr_data = qr_resp.json()
        if not qr_data.get("success"):
            raise RuntimeError(f"failed to get qr token: {qr_data}")

        upload_started = time.perf_counter()
        with open(file_path, "rb") as handle:
            upload_resp = requests.post(
                f"{CLOUD_BASE_URL}/api/v1/files?token={qr_data['token']}",
                files={"file": (file_path.name, handle, file_type)},
                timeout=30,
            )
        if upload_resp.status_code == 401 and attempt == 0:
            last_error = RuntimeError(f"upload token rejected: {upload_resp.text}")
            time.sleep(0.8)
            continue
        upload_resp.raise_for_status()

        listener_thread.join(timeout=25)
        if "payload" not in event_result or "received_at" not in event_result:
            raise TimeoutError("preview_file event was not captured")

        break
    else:
        raise last_error or RuntimeError("upload failed after retries")

    preview_event_ms = round((event_result["received_at"] - upload_started) * 1000, 2)

    event_payload = event_result["payload"]["data"]
    preview_resp = requests.post(
        f"{EDGE_BASE_URL}/api/preview",
        json={
            "file_id": event_payload["file_id"],
            "file_url": event_payload["file_url"],
            "file_name": event_payload["file_name"],
            "file_type": event_payload["file_type"],
            "options": {
                "page_index": 0,
                "paper_size": "A4",
                "scale_mode": "fit",
                "max_upscale": 2.0,
            },
        },
        timeout=60,
    )
    preview_resp.raise_for_status()
    preview_body = preview_resp.json()
    if not preview_body.get("success"):
        raise RuntimeError(preview_body.get("message", "preview render failed"))

    preview_render_ms = round((time.perf_counter() - upload_started) * 1000, 2)
    return {
        "file_name": file_path.name,
        "file_type": file_type,
        "upload_to_preview_event_ms": preview_event_ms,
        "upload_to_preview_render_ms": preview_render_ms,
        "page_count": preview_body.get("page_count"),
    }


def main() -> int:
    ensure_dirs()
    samples = [
        (SAMPLES_DIR / "pdf_1p.pdf", "application/pdf"),
        (SAMPLES_DIR / "image_preview.png", "image/png"),
    ]
    records: List[Dict[str, object]] = []
    for file_path, file_type in samples:
        if not file_path.exists():
            raise FileNotFoundError(f"sample file not found: {file_path}")
        record = upload_and_preview(file_path, file_type)
        records.append(record)
        print(
            f"{file_path.name}: event={record['upload_to_preview_event_ms']} ms, "
            f"render={record['upload_to_preview_render_ms']} ms"
        )

    output_path = RESULTS_DIR / f"edge_upload_preview_e2e_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"E2E upload-preview result file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
