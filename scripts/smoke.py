"""verify 服务使用的 HTTP 冒烟脚本：对运行中的服务做端到端断言。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://web:8000").rstrip("/")
failures: list[str] = []


def call(method: str, path: str, body: object | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


status, data = call("GET", "/health")
check("GET /health 返回 200 且 status=ok",
      status == 200 and data.get("status") == "ok", f"status={status}")

feasible_body = {
    "inflows": [30, 45, 50, 35, 20, 15, 10, 8],
    "initial_water": 7,
    "safe_low": 0,
    "safe_high": 73,
    "pumps": [
        {"discharge": 35, "power": 5, "rest": 1},
        {"discharge": 50, "power": 10, "rest": 3},
    ],
}
status, data = call("POST", "/api/drainage-plans", feasible_body)
rows = data.get("plan", []) if status == 200 else []
end_ok = all(0 <= r["end_water"] <= 73 for r in rows)
no_parallel = all(isinstance(r["action"], int) and 0 <= r["action"] <= 2 for r in rows)
check("可行方案：200、feasible=true、8 个周期",
      status == 200 and data.get("feasible") is True and len(rows) == 8)
check("逐周期末水量均在闭区间 [0,73]", end_ok)
check("同一周期至多运行一台泵（动作仅 0/1/2）", no_parallel)
check("汇总耗电与逐周期累计一致",
      bool(rows) and data.get("summary", {}).get("total_power") == rows[-1]["total_power"])

invalid_body = {
    "inflows": [1, 2, 3],  # 少于 6 个
    "initial_water": -5,
    "safe_low": 9,
    "safe_high": 5,
    "pumps": [{"discharge": 0, "power": 5, "rest": 0}],  # 仅 1 台且排水量非正
}
status, data = call("POST", "/api/drainage-plans", invalid_body)
reasons = data.get("reasons", []) if isinstance(data, dict) else []
check("非法输入返回 422 并给出中文原因",
      status == 422 and data.get("feasible") is False and len(reasons) >= 1,
      f"reasons={reasons}")

infeasible_body = {
    "inflows": [100, 0, 0, 0, 0, 0],
    "initial_water": 0,
    "safe_low": 0,
    "safe_high": 60,
    "pumps": [
        {"discharge": 30, "power": 5, "rest": 0},
        {"discharge": 30, "power": 5, "rest": 0},
    ],
}
status, data = call("POST", "/api/drainage-plans", infeasible_body)
check("无可行方案：200、feasible=false 且带原因",
      status == 200 and data.get("feasible") is False and bool(data.get("reason")))

if failures:
    print(f"\n冒烟失败 {len(failures)} 项：{failures}", file=sys.stderr)
    sys.exit(1)
print("\nHTTP 冒烟全部通过")
