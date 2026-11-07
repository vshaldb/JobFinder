"""
JobFinder Local HTTP Server & Applied Jobs API
==============================================
Serves job_data/ directory and provides REST endpoints for live tracking
of applied jobs directly from the browser report.
"""

import json
import logging
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from jobfinder.applied import (
    load_applied_jobs,
    mark_job_applied,
    unmark_job_applied,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
JOB_DATA_DIR = PROJECT_ROOT / "job_data"


class JobFinderHTTPHandler(SimpleHTTPRequestHandler):
    """Custom HTTP request handler serving job_data and handling /api/applied."""

    def __init__(self, *args, **kwargs):
        # Set base directory to job_data
        super().__init__(*args, directory=str(JOB_DATA_DIR), **kwargs)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, data: dict, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        """Route GET requests to API or static files."""
        parsed = urlparse(self.path)

        if parsed.path in ("/api/applied", "/applied_jobs.json"):
            applied = load_applied_jobs()
            self._send_json_response({
                "status": "ok",
                "count": len(applied),
                "applied_jobs": applied,
            })
            return

        # Redirect root to index.html
        if parsed.path == "/":
            self.path = "/index.html"

        # Add CORS headers to all responses so file:// requests work too
        super().do_GET()

    def end_headers(self) -> None:
        self._send_cors_headers()
        # Add Cache-Control so refreshes always fetch fresh data
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_POST(self) -> None:
        """Handle POST requests for marking or unmarking applied jobs."""
        parsed = urlparse(self.path)

        if parsed.path in ("/api/applied", "/api/apply"):
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body) if body else {}

                company = data.get("company", "").strip()
                job_id = str(data.get("job_id", "")).strip()
                role = data.get("role", "").strip()
                job_id_full = data.get("job_id_full")

                if not company or not job_id:
                    self._send_json_response(
                        {"status": "error", "message": "Missing company or job_id"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

                is_new, item = mark_job_applied(
                    company=company,
                    job_id=job_id,
                    role=role,
                    job_id_full=job_id_full,
                )
                applied = load_applied_jobs()

                self._send_json_response({
                    "status": "ok",
                    "is_new": is_new,
                    "item": item,
                    "count": len(applied),
                    "applied_jobs": applied,
                })
            except Exception as e:
                logger.error(f"Error handling POST /api/applied: {e}")
                self._send_json_response(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        elif parsed.path in ("/api/unapply", "/api/applied/delete"):
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body) if body else {}

                company = data.get("company", "").strip()
                job_id = str(data.get("job_id", "")).strip()

                if not company or not job_id:
                    self._send_json_response(
                        {"status": "error", "message": "Missing company or job_id"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

                removed = unmark_job_applied(company=company, job_id=job_id)
                applied = load_applied_jobs()

                self._send_json_response({
                    "status": "ok",
                    "removed": removed,
                    "count": len(applied),
                    "applied_jobs": applied,
                })
            except Exception as e:
                logger.error(f"Error handling POST /api/unapply: {e}")
                self._send_json_response(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        self._send_json_response(
            {"status": "error", "message": f"Endpoint not found: {parsed.path}"},
            status=HTTPStatus.NOT_FOUND,
        )

    def do_DELETE(self) -> None:
        """Handle DELETE /api/applied."""
        parsed = urlparse(self.path)
        if parsed.path == "/api/applied":
            params = parse_qs(parsed.query)
            company = (params.get("company") or [""])[0].strip()
            job_id = (params.get("job_id") or [""])[0].strip()

            if not company or not job_id:
                # Also try body
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                    if content_length > 0:
                        body = self.rfile.read(content_length).decode("utf-8")
                        data = json.loads(body)
                        company = company or data.get("company", "").strip()
                        job_id = job_id or str(data.get("job_id", "")).strip()
                except Exception:
                    pass

            if not company or not job_id:
                self._send_json_response(
                    {"status": "error", "message": "Missing company or job_id query parameter"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            removed = unmark_job_applied(company=company, job_id=job_id)
            applied = load_applied_jobs()
            self._send_json_response({
                "status": "ok",
                "removed": removed,
                "count": len(applied),
                "applied_jobs": applied,
            })
            return

        self._send_json_response(
            {"status": "error", "message": f"Endpoint not found: {parsed.path}"},
            status=HTTPStatus.NOT_FOUND,
        )

    def log_message(self, format: str, *args) -> None:
        # Keep logs clean; only log errors or when debug is enabled
        if logger.isEnabledFor(logging.DEBUG):
            super().log_message(format, *args)


def start_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Start and return the ThreadingHTTPServer."""
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, JobFinderHTTPHandler)
    return httpd


def run_server_forever(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run server in foreground."""
    httpd = start_server(host, port)
    print(f"JobFinder Web Server listening on http://{host}:{port}/")
    print(f"Applied jobs REST API active at http://{host}:{port}/api/applied")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.shutdown()

