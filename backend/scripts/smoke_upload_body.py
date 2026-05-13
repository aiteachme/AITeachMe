"""HTTP multipart upload smoke probe for deployment checks."""

from __future__ import annotations

import argparse
import contextlib
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from types import FrameType


DEFAULT_FILE_SIZE_BYTES = 1280 * 1024
DEFAULT_BODY_EXCERPT_BYTES = 1000


@dataclass(frozen=True)
class ProbeResult:
    status: int
    elapsed_seconds: float
    body_excerpt: str
    error: str | None = None


class _DeadlineExceeded(TimeoutError):
    pass


@contextlib.contextmanager
def _deadline(seconds: int):
    """Bound the full probe duration on Unix runners while staying importable elsewhere."""

    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(_signum: int, _frame: FrameType | None) -> None:
        raise _DeadlineExceeded(f"upload probe exceeded {seconds}s")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def build_multipart_body(*, file_size_bytes: int, boundary: str) -> bytes:
    if file_size_bytes <= 0:
        raise ValueError("file_size_bytes must be positive")
    if not boundary:
        raise ValueError("boundary must not be empty")

    boundary_bytes = boundary.encode("ascii")
    return b"".join(
        [
            b"--",
            boundary_bytes,
            b"\r\n",
            b'Content-Disposition: form-data; name="files"; filename="upload-body-probe.bin"\r\n',
            b"Content-Type: application/octet-stream\r\n\r\n",
            b"0" * file_size_bytes,
            b"\r\n--",
            boundary_bytes,
            b"--\r\n",
        ]
    )


def _decode_excerpt(body: bytes) -> str:
    return body.decode("utf-8", errors="replace").replace("\n", "\\n")


def post_upload_once(*, url: str, file_size_bytes: int, timeout_seconds: int) -> ProbeResult:
    boundary = f"----aiteachme-smoke-{uuid.uuid4().hex}"
    body = build_multipart_body(file_size_bytes=file_size_bytes, boundary=boundary)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "aiteachme-deploy-smoke/1.0",
        },
        method="POST",
    )

    started = time.monotonic()
    try:
        with _deadline(timeout_seconds):
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                excerpt = response.read(DEFAULT_BODY_EXCERPT_BYTES)
                return ProbeResult(
                    status=response.status,
                    elapsed_seconds=time.monotonic() - started,
                    body_excerpt=_decode_excerpt(excerpt),
                )
    except urllib.error.HTTPError as exc:
        excerpt = exc.read(DEFAULT_BODY_EXCERPT_BYTES)
        return ProbeResult(
            status=exc.code,
            elapsed_seconds=time.monotonic() - started,
            body_excerpt=_decode_excerpt(excerpt),
        )
    except (TimeoutError, _DeadlineExceeded, socket.timeout, urllib.error.URLError, OSError) as exc:
        return ProbeResult(
            status=0,
            elapsed_seconds=time.monotonic() - started,
            body_excerpt="",
            error=f"{type(exc).__name__}: {exc}",
        )


def run_probe(
    *,
    url: str,
    expected_status: int,
    file_size_bytes: int,
    label: str,
    attempts: int,
    timeout_seconds: int,
    sleep_seconds: int,
) -> int:
    for attempt in range(1, attempts + 1):
        result = post_upload_once(
            url=url,
            file_size_bytes=file_size_bytes,
            timeout_seconds=timeout_seconds,
        )
        print(
            "Upload body smoke attempt "
            f"{attempt}/{attempts}: {label} multipart -> "
            f"status={result.status} elapsed={result.elapsed_seconds:.3f}s"
        )
        if result.body_excerpt:
            print(f"Response body excerpt: {result.body_excerpt}")
        if result.error:
            print(f"Probe error: {result.error}")
        sys.stdout.flush()

        if result.status == expected_status:
            return 0
        if attempt < attempts:
            time.sleep(sleep_seconds)

    print(
        "Upload body smoke check did not pass: "
        f"expected HTTP {expected_status} from {url}",
        file=sys.stderr,
    )
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-status", type=int, default=422)
    parser.add_argument("--bytes", dest="file_size_bytes", type=int, default=DEFAULT_FILE_SIZE_BYTES)
    parser.add_argument("--label", default="1.25MiB")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--timeout", dest="timeout_seconds", type=int, default=120)
    parser.add_argument("--sleep", dest="sleep_seconds", type=int, default=15)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run_probe(
        url=args.url,
        expected_status=args.expected_status,
        file_size_bytes=args.file_size_bytes,
        label=args.label,
        attempts=args.attempts,
        timeout_seconds=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
