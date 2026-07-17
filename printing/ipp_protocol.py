"""Minimal production IPP/2.0 client for direct PDF printing."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
from pathlib import Path
import struct
import threading
from typing import Any, Iterable
from urllib.parse import urlsplit


OP_PRINT_JOB = 0x0002
OP_CANCEL_JOB = 0x0008
OP_GET_JOB_ATTRIBUTES = 0x0009
OP_GET_JOBS = 0x000A
OP_GET_PRINTER_ATTRIBUTES = 0x000B

GROUP_OPERATION = 0x01
GROUP_JOB = 0x02
GROUP_END = 0x03
GROUP_PRINTER = 0x04
GROUP_UNSUPPORTED = 0x05

TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_OCTET_STRING = 0x30
TAG_RANGE = 0x33
TAG_TEXT_WITH_LANGUAGE = 0x35
TAG_NAME_WITH_LANGUAGE = 0x36
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49

GROUP_NAMES = {
    GROUP_OPERATION: "operation",
    GROUP_JOB: "job",
    GROUP_PRINTER: "printer",
    GROUP_UNSUPPORTED: "unsupported",
    0x06: "subscription",
    0x07: "event-notification",
    0x09: "document",
}
TEXT_TAGS = {TAG_TEXT, TAG_NAME, TAG_KEYWORD, TAG_URI, TAG_CHARSET, TAG_LANGUAGE, TAG_MIME}
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


class IppError(RuntimeError):
    pass


class IppUriError(IppError):
    pass


class IppTransportError(IppError):
    pass


class IppResponseError(IppError):
    def __init__(self, operation: int, response: "IppResponse"):
        self.operation = operation
        self.response = response
        super().__init__(
            f"IPP operation 0x{operation:04X} failed: status=0x{response.status_code:04X} "
            f"message={response.first('status-message', '')!r} parse_error={response.parse_error!r}"
        )


def validate_ipp_uri(value: str) -> str:
    uri = str(value or "").strip()
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "ipp" or not parsed.hostname or not parsed.path or parsed.username or parsed.password:
        raise IppUriError("a complete ipp:// URI with an explicit resource path is required")
    if parsed.query or parsed.fragment:
        raise IppUriError("IPP URI must not contain a query string or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise IppUriError("IPP URI contains an invalid port") from exc
    return uri


def _value_bytes(tag: int, value: Any) -> bytes:
    if tag in {TAG_INTEGER, TAG_ENUM}:
        return struct.pack(">i", int(value))
    if tag == TAG_BOOLEAN:
        return b"\x01" if bool(value) else b"\x00"
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def encode_attribute(tag: int, name: str, value: Any) -> bytes:
    name_raw, value_raw = name.encode("utf-8"), _value_bytes(tag, value)
    if len(name_raw) > 65535 or len(value_raw) > 65535:
        raise IppError(f"IPP attribute is too large: {name}")
    return bytes([tag]) + struct.pack(">H", len(name_raw)) + name_raw + struct.pack(">H", len(value_raw)) + value_raw


def encode_values(tag: int, name: str, values: Iterable[Any]) -> bytes:
    return b"".join(encode_attribute(tag, name if index == 0 else "", value) for index, value in enumerate(values))


def operation_attributes(printer_uri: str, user: str) -> bytes:
    return b"".join((
        encode_attribute(TAG_CHARSET, "attributes-charset", "utf-8"),
        encode_attribute(TAG_LANGUAGE, "attributes-natural-language", "zh-cn"),
        encode_attribute(TAG_URI, "printer-uri", printer_uri),
        encode_attribute(TAG_NAME, "requesting-user-name", user),
    ))


def request_prefix(operation: int, request_id: int, operation_attrs: bytes, job_attrs: bytes = b"") -> bytes:
    payload = bytearray(b"\x02\x00" + struct.pack(">H", operation) + struct.pack(">I", request_id))
    payload += bytes([GROUP_OPERATION]) + operation_attrs
    if job_attrs:
        payload += bytes([GROUP_JOB]) + job_attrs
    payload += bytes([GROUP_END])
    return bytes(payload)


def decode_value(tag: int, raw: bytes) -> Any:
    if tag in {TAG_INTEGER, TAG_ENUM} and len(raw) == 4:
        return int.from_bytes(raw, "big", signed=True)
    if tag == TAG_BOOLEAN:
        return bool(raw and raw[0])
    if tag == TAG_RANGE and len(raw) == 8:
        return [int.from_bytes(raw[:4], "big", signed=True), int.from_bytes(raw[4:], "big", signed=True)]
    if tag in {TAG_TEXT_WITH_LANGUAGE, TAG_NAME_WITH_LANGUAGE} and len(raw) >= 4:
        language_length = int.from_bytes(raw[:2], "big")
        text_length_offset = 2 + language_length
        if text_length_offset + 2 <= len(raw):
            text_length = int.from_bytes(raw[text_length_offset:text_length_offset + 2], "big")
            text_offset = text_length_offset + 2
            if text_offset + text_length <= len(raw):
                return raw[text_offset:text_offset + text_length].decode("utf-8", errors="replace")
    if tag == TAG_OCTET_STRING:
        try:
            value = raw.decode("utf-8")
            return value if value.isprintable() else raw.hex()
        except UnicodeDecodeError:
            return raw.hex()
    if tag in TEXT_TAGS:
        return raw.decode("utf-8", errors="replace")
    return raw.hex()


@dataclass(frozen=True)
class IppGroup:
    tag: int
    name: str
    attributes: dict[str, list[Any]]


@dataclass(frozen=True)
class IppResponse:
    version: str
    status_code: int
    request_id: int
    groups: list[IppGroup]
    parse_error: str = ""

    @property
    def successful(self) -> bool:
        return 0 <= self.status_code <= 0x00FF and not self.parse_error

    def values(self, name: str) -> list[Any]:
        result: list[Any] = []
        for group in self.groups:
            result.extend(group.attributes.get(name, []))
        return result

    def first(self, name: str, default: Any = None) -> Any:
        values = self.values(name)
        return values[0] if values else default


def parse_response(raw: bytes) -> IppResponse:
    if len(raw) < 8:
        raise IppError("IPP response is shorter than its header")
    version = f"{raw[0]}.{raw[1]}"
    status_code = int.from_bytes(raw[2:4], "big")
    request_id = int.from_bytes(raw[4:8], "big")
    groups: list[IppGroup] = []
    current: dict[str, list[Any]] | None = None
    current_tag, current_name, last_name, offset, parse_error = 0, "", "", 8, ""
    found_end = False
    while offset < len(raw):
        tag, offset = raw[offset], offset + 1
        if tag == GROUP_END:
            found_end = True
            break
        if tag in GROUP_NAMES:
            if current is not None:
                groups.append(IppGroup(current_tag, current_name, current))
            current_tag, current_name, current, last_name = tag, GROUP_NAMES[tag], {}, ""
            continue
        if current is None:
            parse_error = f"value tag 0x{tag:02X} before group"
            break
        if offset + 2 > len(raw):
            parse_error = "truncated attribute name length"
            break
        name_length, offset = int.from_bytes(raw[offset:offset + 2], "big"), offset + 2
        if offset + name_length + 2 > len(raw):
            parse_error = "truncated attribute name"
            break
        name_raw, offset = raw[offset:offset + name_length], offset + name_length
        name = name_raw.decode("utf-8", errors="replace") if name_raw else last_name
        if not name:
            parse_error = "attribute continuation has no preceding name"
            break
        if name_raw:
            last_name = name
        value_length, offset = int.from_bytes(raw[offset:offset + 2], "big"), offset + 2
        if offset + value_length > len(raw):
            parse_error = "truncated attribute value"
            break
        current.setdefault(name, []).append(decode_value(tag, raw[offset:offset + value_length]))
        offset += value_length
    if current is not None:
        groups.append(IppGroup(current_tag, current_name, current))
    if not parse_error and not found_end:
        parse_error = "IPP response is missing the end-of-attributes tag"
    if not parse_error and offset != len(raw):
        parse_error = "IPP response contains unexpected bytes after end-of-attributes"
    return IppResponse(version, status_code, request_id, groups, parse_error)


class IppClient:
    def __init__(self, printer_uri: str, *, timeout: float = 15.0, user: str = "FlyPrint"):
        self.printer_uri = validate_ipp_uri(printer_uri)
        parsed = urlsplit(self.printer_uri)
        self.host, self.port, self.path = parsed.hostname or "", parsed.port or 631, parsed.path
        self.timeout, self.user = timeout, user
        self._request_id = 0
        self._id_lock = threading.Lock()

    def _next_id(self) -> int:
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def _send(self, operation: int, request_id: int, prefix: bytes, document_path: Path | None = None) -> IppResponse:
        document_size = document_path.stat().st_size if document_path else 0
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.putrequest("POST", self.path)
            connection.putheader("Content-Type", "application/ipp")
            connection.putheader("Accept", "application/ipp")
            connection.putheader("Content-Length", str(len(prefix) + document_size))
            connection.endheaders()
            connection.send(prefix)
            if document_path:
                with document_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                        connection.send(chunk)
            http_response = connection.getresponse()
            raw = http_response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise IppTransportError("IPP response exceeded the size limit")
            if http_response.status >= 400:
                raise IppTransportError(f"IPP HTTP response was {http_response.status} {http_response.reason}")
            content_type = str(http_response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/ipp":
                raise IppTransportError(f"IPP HTTP response had unexpected Content-Type {content_type!r}")
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise IppTransportError(f"IPP transport failed for {self.printer_uri}: {exc}") from exc
        finally:
            connection.close()
        response = parse_response(raw)
        if response.request_id != request_id:
            raise IppTransportError(f"IPP request-id mismatch: expected {request_id}, got {response.request_id}")
        if not response.successful:
            raise IppResponseError(operation, response)
        return response

    def get_printer_attributes(self, requested: list[str]) -> IppResponse:
        request_id = self._next_id()
        attrs = operation_attributes(self.printer_uri, self.user) + encode_values(TAG_KEYWORD, "requested-attributes", requested)
        return self._send(OP_GET_PRINTER_ATTRIBUTES, request_id, request_prefix(OP_GET_PRINTER_ATTRIBUTES, request_id, attrs))

    def print_pdf(self, pdf_path: Path, job_name: str, document_name: str, job_attributes: list[tuple[int, str, Any]]) -> IppResponse:
        request_id = self._next_id()
        attrs = operation_attributes(self.printer_uri, self.user)
        attrs += encode_attribute(TAG_NAME, "job-name", job_name)
        attrs += encode_attribute(TAG_NAME, "document-name", document_name)
        attrs += encode_attribute(TAG_MIME, "document-format", "application/pdf")
        attrs += encode_attribute(TAG_BOOLEAN, "ipp-attribute-fidelity", True)
        job_attrs = b"".join(encode_attribute(tag, name, value) for tag, name, value in job_attributes)
        return self._send(OP_PRINT_JOB, request_id, request_prefix(OP_PRINT_JOB, request_id, attrs, job_attrs), Path(pdf_path))

    def get_job_attributes(self, job_id: int, requested: list[str]) -> IppResponse:
        request_id = self._next_id()
        attrs = operation_attributes(self.printer_uri, self.user)
        attrs += encode_attribute(TAG_INTEGER, "job-id", job_id)
        attrs += encode_values(TAG_KEYWORD, "requested-attributes", requested)
        return self._send(OP_GET_JOB_ATTRIBUTES, request_id, request_prefix(OP_GET_JOB_ATTRIBUTES, request_id, attrs))

    def cancel_job(self, job_id: int) -> IppResponse:
        request_id = self._next_id()
        attrs = operation_attributes(self.printer_uri, self.user) + encode_attribute(TAG_INTEGER, "job-id", job_id)
        return self._send(OP_CANCEL_JOB, request_id, request_prefix(OP_CANCEL_JOB, request_id, attrs))
