#!/usr/bin/env python3
# Copyright 2025 Google LLC
"""Serve the Angular SPA and proxy /api to backend Cloud Run.

Cloud Run service-to-service auth: attaches an identity token for the
frontend runtime SA (roles/run.invoker on the backend). Forwards IAP
user identity headers for application-level auth.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_ROOT = Path(os.environ.get("STATIC_ROOT", "/usr/share/nginx/html"))
BACKEND_HOST = os.environ["BACKEND_HOST"].strip()
BACKEND_BASE = f"https://{BACKEND_HOST}"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    f"service-accounts/default/identity?audience={BACKEND_BASE}"
)

_token: str | None = None
_token_expiry = 0.0


def _fetch_identity_token() -> str:
    global _token, _token_expiry
    now = time.time()
    if _token and now < _token_expiry:
        return _token

    req = urllib.request.Request(
        METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        _token = resp.read().decode("utf-8").strip()
    # Identity tokens typically last ~1h; refresh early.
    _token_expiry = now + 45 * 60
    return _token


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[fe-proxy] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        if self.path.startswith("/api/") or self.path == "/api":
            self._proxy()
            return
        # SPA fallback: missing files → index.html
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_HEAD(self) -> None:
        if self.path.startswith("/api/") or self.path == "/api":
            self._proxy()
            return
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = "/index.html"
        return SimpleHTTPRequestHandler.do_HEAD(self)

    def do_POST(self) -> None:
        self._proxy()

    def do_PUT(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def do_OPTIONS(self) -> None:
        self._proxy()

    def _proxy(self) -> None:
        if not (self.path.startswith("/api/") or self.path == "/api"):
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        target = f"{BACKEND_BASE}{self.path}"
        if self.path.find("?") == -1 and getattr(self, "query", None):
            pass

        headers = {}
        for key in ("Content-Type", "Accept"):
            val = self.headers.get(key)
            if val:
                headers[key] = val

        # Cloud Run strips X-Goog-IAP-* on service-to-service calls, so copy
        # the user JWT into a custom header the backend will verify.
        iap_jwt = self.headers.get("X-Goog-IAP-JWT-Assertion")
        iap_email = self.headers.get("X-Goog-Authenticated-User-Email")
        if iap_jwt:
            headers["X-CS-IAP-JWT"] = iap_jwt
        if iap_email:
            headers["X-CS-IAP-Email"] = iap_email
        if not iap_jwt:
            print(
                f"[fe-proxy] WARNING: no X-Goog-IAP-JWT-Assertion on "
                f"{self.command} {self.path} (email_header={'yes' if iap_email else 'no'})"
            )

        try:
            headers["Authorization"] = f"Bearer {_fetch_identity_token()}"
            req = urllib.request.Request(
                target,
                data=body,
                headers=headers,
                method=self.command,
            )
            with urllib.request.urlopen(req, timeout=3600) as resp:
                payload = resp.read()
                self.send_response(resp.status)
                for hk, hv in resp.headers.items():
                    if hk.lower() in {
                        "transfer-encoding",
                        "connection",
                        "content-encoding",
                    }:
                        continue
                    self.send_header(hk, hv)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for hk, hv in exc.headers.items():
                if hk.lower() in {"transfer-encoding", "connection"}:
                    continue
                self.send_header(hk, hv)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[fe-proxy] proxy error: {exc}")
            self.send_error(502, f"Bad Gateway: {exc}")


def main() -> None:
    if not BACKEND_HOST or BACKEND_HOST.startswith("BACKEND_"):
        raise SystemExit("BACKEND_HOST env var must be set to the backend Cloud Run host")
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[fe-proxy] serving {STATIC_ROOT} on :{port}, api → {BACKEND_BASE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
