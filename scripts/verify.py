#!/usr/bin/env python3
"""Compose verify 一次性服务入口。

依次完成：
1. 构建检查：compileall 编译全部源码与测试；
2. 代码测试：unittest 全量用例；
3. HTTP 冒烟：等待 web 服务健康，依次验证健康检查、
   POST /api/drainage-plans 成功求解、非法输入返回 400、无可行方案返回 feasible=false。

全部通过退出码 0，任一失败退出码 1。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
BASE_URL = os.environ.get("BASE_URL", "http://web:8000")


def log(msg: str) -> None:
    print(f"[verify] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[verify] 失败：{msg}", file=sys.stderr)
    sys.exit(1)


def request(method: str, path: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def step_build_check() -> None:
    log("构建检查：compileall 编译源码与测试 …")
    import compileall
    ok = (compileall.compile_dir(str(REPO_ROOT / "app"), quiet=1)
          and compileall.compile_dir(str(REPO_ROOT / "tests"), quiet=1))
    if not ok:
        fail("compileall 发现语法错误")
    log("构建检查通过")


def step_unit_tests() -> None:
    log("代码测试：运行 unittest …")
    import unittest
    loader = unittest.TestLoader()
    suite = loader.discover(str(REPO_ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        fail("单元测试未全部通过")
    log("代码测试通过")


def step_http_smoke() -> None:
    log(f"HTTP 冒烟：等待 {BASE_URL}/healthz …")
    last_err = None
    for _ in range(30):
        try:
            status, data = request("GET", "/healthz")
            if status == 200 and data.get("status") == "ok":
                break
        except Exception as exc:  # noqa: BLE001 - 冒烟阶段任何异常都重试
            last_err = exc
        time.sleep(1)
    else:
        fail(f"服务未在预期时间内变为健康：{last_err}")

    log("冒烟 1/4：首页可访问 …")
    with urllib.request.urlopen(BASE_URL + "/", timeout=5) as resp:
        html = resp.read().decode("utf-8")
    if resp.status != 200 or "/api/drainage-plans" not in html:
        fail("首页内容异常")

    log("冒烟 2/4：合法排程请求返回完整方案 …")
    payload = {
        "inflows": [8, 12, 6, 15, 10, 7],
        "initial_water": 5,
        "low_water": 0,
        "high_water": 20,
        "pumps": [
            {"name": "1号泵", "capacity": 10, "energy": 4, "cooldown": 1},
            {"name": "2号泵", "capacity": 14, "energy": 7, "cooldown": 2},
        ],
    }
    status, data = request("POST", "/api/drainage-plans", payload)
    if status != 200 or not data.get("feasible"):
        fail(f"合法请求未得到可行方案：status={status}, body={data}")
    rows = data.get("periods", [])
    if len(rows) != 6:
        fail(f"逐周期结果数量错误：{len(rows)}")
    for row in rows:
        if not (0 <= row["water_end"] <= 20):
            fail("出现越界周期末水量")
        if row["action"] not in (0, 1, 2):
            fail("动作编码非法")
    log(f"  累计耗电 {data['summary']['total_energy']}，峰值 {data['summary']['peak_water']}")

    log("冒烟 3/4：非法输入返回 400 并说明原因 …")
    status, data = request("POST", "/api/drainage-plans", {**payload, "inflows": [1, 2, 3]})
    if status != 400 or "error" not in data:
        fail(f"非法输入未被拒绝：status={status}, body={data}")

    log("冒烟 4/4：无可行方案时 feasible=false …")
    infeasible = {
        **payload,
        "inflows": [20] * 6,
        "high_water": 10,
        "pumps": [
            {"capacity": 3, "energy": 1, "cooldown": 0},
            {"capacity": 4, "energy": 1, "cooldown": 0},
        ],
    }
    status, data = request("POST", "/api/drainage-plans", infeasible)
    if status != 200 or data.get("feasible") is not False or "reason" not in data:
        fail(f"无可行方案响应异常：status={status}, body={data}")

    log("HTTP 冒烟全部通过")


def main() -> int:
    step_build_check()
    step_unit_tests()
    step_http_smoke()
    log("全部验证通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
