"""排水泵轮换排程 HTTP 服务（Python 标准库实现，无第三方运行时依赖）。

路由：
* ``GET  /``                     值守员录入页面
* ``GET  /healthz``              健康检查
* ``POST /api/drainage-plans``   提交排程参数并返回逐周期方案
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .planner import ValidationError, plan

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "DrainagePlan/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_file(200, (STATIC_DIR / "index.html").read_bytes(),
                            "text/html; charset=utf-8")
        elif path == "/healthz":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "资源不存在"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/drainage-plans":
            self._send_json(404, {"error": "资源不存在"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send_json(400, {"error": "请求体为空"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "请求体过大"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "请求体不是合法的 UTF-8 JSON"})
            return

        try:
            result = plan(payload)
        except ValidationError as exc:
            # 输入非法：显式标记，页面据此撤下旧方案并显示原因。
            self._send_json(400, {"error": str(exc)})
            return

        # 无可行方案属于正常求解结果（200 + feasible=false）。
        self._send_json(200, result)

    def log_message(self, fmt: str, *args: object) -> None:
        if os.environ.get("QUIET_LOGS") != "1":
            super().log_message(fmt, *args)


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.environ.get("HOST", "0.0.0.0")
    port = int(port if port is not None else os.environ.get("PORT", "8000"))
    httpd = create_server(host, port)
    print(f"排水排程服务监听于 http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
