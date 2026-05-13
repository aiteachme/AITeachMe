from __future__ import annotations

import http.server
import socketserver
import threading

from scripts import smoke_upload_body


class _UploadProbeHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.server.last_body = self.rfile.read(length)  # type: ignore[attr-defined]
        self.send_response(422)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error_code":"UNSUPPORTED_FILE_TYPE"}')

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_build_multipart_body_contains_file_field() -> None:
    body = smoke_upload_body.build_multipart_body(file_size_bytes=16, boundary="test-boundary")

    assert b'name="files"; filename="upload-body-probe.bin"' in body
    assert b"Content-Type: application/octet-stream" in body
    assert body.endswith(b"--test-boundary--\r\n")


def test_run_probe_accepts_expected_upload_rejection() -> None:
    with socketserver.TCPServer(("127.0.0.1", 0), _UploadProbeHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status = smoke_upload_body.run_probe(
                url=f"http://127.0.0.1:{server.server_address[1]}/api/v1/files/upload",
                expected_status=422,
                file_size_bytes=16,
                label="16B",
                attempts=1,
                timeout_seconds=5,
                sleep_seconds=0,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert status == 0
    assert b"0" * 16 in server.last_body  # type: ignore[attr-defined]
