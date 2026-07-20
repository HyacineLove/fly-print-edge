"""Windows DPAPI storage for the Edge node's Cloud credential bundle.

The bundle is written by the activation flow only.  The configuration file
contains an opaque ciphertext and can never be used to recover credentials on
another Windows account or device.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from typing import Any, Dict

_DESCRIPTION = "FlyPrint Edge Cloud credentials"
_ENTROPY = b"FlyPrint.Edge.Cloud.Credentials.v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Cloud credentials are supported only on Windows DPAPI")


def protect_credentials(credentials: Dict[str, str]) -> str:
    _ensure_windows()
    payload = json.dumps(credentials, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    input_blob, input_buffer = _blob(payload)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob), _DESCRIPTION, ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def unprotect_credentials(ciphertext: str) -> Dict[str, str]:
    _ensure_windows()
    try:
        protected = base64.b64decode(ciphertext.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("invalid protected Cloud credentials") from exc
    input_blob, input_buffer = _blob(protected)
    entropy_blob, entropy_buffer = _blob(_ENTROPY)
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), ctypes.byref(description), ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        data = json.loads(ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8"))
    finally:
        kernel32.LocalFree(output_blob.pbData)
        if description:
            kernel32.LocalFree(description)
    if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data[key] for key in ("client_id", "client_secret")):
        raise ValueError("protected Cloud credential bundle is incomplete")
    return {"client_id": data["client_id"], "client_secret": data["client_secret"]}
