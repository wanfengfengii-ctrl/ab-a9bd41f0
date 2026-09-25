# 沿海档案馆地下库 · 排水泵轮换排程服务

暴潮暴雨期间按调度周期排空集水井的两台排水泵轮换编排服务。值守员录入
6–12 个按发生顺序的整数来水量、初始水量、安全水位闭区间，以及两台泵各自的
**每周期排水量 / 耗电量 / 运行后必须停歇的整数周期数**；页面调用真实的
`POST /api/drainage-plans`，逐周期展示待机或所用泵、周期末水量、各泵冷却状态、
累计耗电与最终结论。

服务在**完整排程空间**中寻优，不会按当前周期的最低耗电贪心决定。

## 排程模型

- 共 N 个调度周期（6 ≤ N ≤ 12），按来水发生顺序编号 1…N。
- 每个周期先进入该周期来水量，随后**至多一台泵**运行：
  - 待机：周期末水量 = 周期初水量 + 来水量；
  - 泵 p 运行：周期末水量 = max(0, 周期初水量 + 来水量 − 泵 p 排水量)。
- 每个周期末水量必须落在闭区间 `[safe_low, safe_high]`。
- 泵 p 在周期 r 运行后必须停歇 `rest_p` 个完整周期，即周期 q 可再次启动
  当且仅当 `q > r + rest_p`；停歇未结束的泵不得再次启动。
- 水量不为负（排水多于来水+存量时按 0 截断）。

## 寻优目标（严格按顺序做字典序最小化）

1. **累计耗电**最小；
2. 累计耗电相同则**全程最高水量**（各周期末水量的最大值）最低；
3. 再相同则**按泵编号排列的动作序列**字典序最小（编码：待机=0、1 号泵=1、2 号泵=2）。

求解器（`app/scheduler.py`）在完整动作空间上深度优先穷举：每周期至多 3 个
分支（待机 / 1 号泵 / 2 号泵），N=12 时叶节点至多 3¹²=531441，毫秒至亚秒级
返回。仅使用“累计耗电不可能再低于当前最优”这一单调界剪枝（耗电只增不减，
不改变可达最优），**不做任何“本周期最省电”的贪心决策**。测试以独立的
3^N 暴力枚举对 40 组随机用例与 12 周期用例交叉验证全局最优键完全一致。

## API

### `POST /api/drainage-plans`

```json
{
  "inflows": [30, 45, 50, 35, 20, 15, 10, 8],
  "initial_water": 7,
  "safe_low": 0,
  "safe_high": 73,
  "pumps": [
    {"discharge": 35, "power": 5, "rest": 1},
    {"discharge": 50, "power": 10, "rest": 3}
  ]
}
```

- 可行：`200`，`feasible=true`，含 `summary`（周期数 / 累计耗电 / 全程最高水量 /
  最终水量）、逐周期 `plan`（动作、周期初末水量、两台泵状态、累计耗电）与
  `conclusion`。
- 无可行方案：`200`，`feasible=false`，`reason` 说明在完整排程空间中无解。
- 输入非法：`422`，`{"feasible": false, "reasons": [...]}`，中文原因逐条列出
  （周期数不在 6–12、负值、下限高于上限、泵数量不为 2、排水量非正、非整数等）。

### `GET /health`

返回 `{"status": "ok"}`，供 Docker / Compose 健康检查使用。

### 页面

`GET /` 返回录入与结果页面；提交后调用上述真实接口。无可行方案或输入非法时，
页面会撤下旧方案并显示原因。

## 本地运行（不使用 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

运行测试：

```bash
.venv/bin/python -m pytest -q
```

## Docker 部署

构建并启动（宿主机端口默认 8000，可配置）：

```bash
docker compose up --build
# 自定义宿主机端口：
HOST_PORT=9090 docker compose up --build
# 或复制 .env.example 为 .env 后修改 HOST_PORT
```

- 镜像内置 `HEALTHCHECK`（轮询 `/health`）；Compose 的 `web` 服务也配置了
  健康检查与可配置宿主机端口 `${HOST_PORT:-8000}:8000`。
- `verify` 为**一次性服务**：等待 `web` 健康后依次执行
  1. 代码测试（`pytest`，61 个用例）；
  2. 构建/导入检查（应用模块导入、关键路由已注册）；
  3. HTTP 冒烟（健康检查、可行方案逐周期约束、非法输入 422、无可行方案响应）；

  全部通过以退出码 0 自行退出，任一失败以非零退出码报告结果：

  ```bash
  docker compose up --build verify          # 会连带启动 web
  docker compose run --build --rm verify    # 等价的一次性运行
  docker inspect ... --format '{{.State.ExitCode}}'   # 查看退出码
  ```

## 项目结构

```
app/
  scheduler.py      完整排程空间穷举求解器（耗电→峰值→动作序列）
  models.py         请求/响应模型与输入校验
  main.py           FastAPI 路由、中文校验错误、健康检查、静态页
  static/index.html 录入与逐周期结果页面
tests/              求解器（含独立暴力枚举交叉验证）与 API 测试
scripts/verify.sh   verify 一次性服务入口（测试+构建检查+冒烟）
scripts/smoke.py    HTTP 冒烟断言脚本
Dockerfile          python:3.12-slim，内置 HEALTHCHECK
docker-compose.yml  web（可配置宿主机端口）+ 一次性 verify
```
