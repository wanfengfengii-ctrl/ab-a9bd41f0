#!/bin/sh
# Compose 中的一次性 verify 服务入口：
#   1) 代码测试（pytest）
#   2) 构建/导入检查（应用模块可导入、路由已注册）
#   3) HTTP 冒烟（健康检查、可行方案、非法输入、无可行方案）
# 任一步失败即以非零退出码退出。
set -eu

PYTHON="${PYTHON:-python}"
BASE_URL="${BASE_URL:-http://web:8000}"

echo "== [1/3] 代码测试 =="
"$PYTHON" -m pytest -q

echo "== [2/3] 构建/导入检查 =="
"$PYTHON" - <<'PY'
from app.main import app
routes = {r.path for r in app.routes}
assert "/health" in routes, "缺少 /health 路由"
assert "/api/drainage-plans" in routes, "缺少 /api/drainage-plans 路由"
print("路由检查通过：/health、/api/drainage-plans")
PY

echo "== [3/3] HTTP 冒烟：$BASE_URL =="
BASE_URL="$BASE_URL" "$PYTHON" scripts/smoke.py

echo "== verify 全部通过 =="
