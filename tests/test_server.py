"""HTTP 层测试：真实启动 ThreadingHTTPServer 并通过 socket 发请求。"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from app.server import create_server

PAYLOAD = {
    "inflows": [8, 12, 6, 15, 10, 7],
    "initial_water": 5,
    "low_water": 0,
    "high_water": 20,
    "pumps": [
        {"name": "1号泵", "capacity": 10, "energy": 4, "cooldown": 1},
        {"name": "2号泵", "capacity": 14, "energy": 7, "cooldown": 2},
    ],
}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = create_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def _request(self, method, path, body=None, raw=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None
        headers = {}
        if raw is not None:
            data = raw
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health(self):
        status, data = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"status": "ok"})

    def test_index_page(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            html = resp.read().decode("utf-8")
        self.assertEqual(resp.status, 200)
        self.assertIn("/api/drainage-plans", html)

    def test_plan_ok(self):
        status, data = self._request("POST", "/api/drainage-plans", PAYLOAD)
        self.assertEqual(status, 200)
        self.assertTrue(data["feasible"])
        self.assertEqual(len(data["periods"]), 6)
        self.assertIn("conclusion", data)

    def test_plan_invalid_returns_400(self):
        bad = dict(PAYLOAD, inflows=[1, 2, 3])
        status, data = self._request("POST", "/api/drainage-plans", bad)
        self.assertEqual(status, 400)
        self.assertIn("6 到 12", data["error"])

    def test_plan_infeasible_returns_200_false(self):
        body = {
            **PAYLOAD,
            "inflows": [20] * 6,
            "high_water": 10,
            "pumps": [
                {"capacity": 3, "energy": 1, "cooldown": 0},
                {"capacity": 4, "energy": 1, "cooldown": 0},
            ],
        }
        status, data = self._request("POST", "/api/drainage-plans", body)
        self.assertEqual(status, 200)
        self.assertFalse(data["feasible"])

    def test_malformed_json(self):
        status, data = self._request("POST", "/api/drainage-plans", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("JSON", data["error"])

    def test_unknown_route(self):
        status, _ = self._request("GET", "/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
