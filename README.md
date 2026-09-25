# 沿海档案馆地下库 · 排水泵轮换排程服务

暴潮暴雨期间，值守员在页面录入 6–12 个调度周期的来水预判、初始水量、安全水位
闭区间以及两台排水泵的参数。服务在 **完整排程空间**（每周期待机 / 1 号泵 / 2 号泵，
最多 3^12 个方案）中求最优轮换，**不做任何单周期低耗电贪心**。

## 优化目标（按优先级依次最小化）

1. **累计耗电**；
2. **全程最高水量**（含初始水量与各周期末水量）；
3. **动作序列字典序**（按周期排列，待机 `0` < 1 号泵 `1` < 2 号泵 `2`）。

约束：

- 每个周期末水量必须落在安全水位 **闭区间** `[low_water, high_water]`；
- 同一周期最多运行一台泵；
- 泵运行后必须完整停歇其设定的整数周期数，停歇未结束不得再次启动。

## 时序模型

每个周期：① 来水入井 → ② 至多启动一台泵排水 → ③ 得到周期末水量并校验区间。
某泵在周期 `i` 运行（停歇 `c` 周期）后，最早可在周期 `i+c+1` 再次启动。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 参数录入与结果展示页面 |
| GET | `/healthz` | 健康检查，返回 `{"status":"ok"}` |
| POST | `/api/drainage-plans` | 提交排程参数，返回逐周期方案 |

请求示例：

```json
{
  "inflows": [8, 12, 6, 15, 10, 7],
  "initial_water": 5,
  "low_water": 0,
  "high_water": 20,
  "pumps": [
    {"name": "1号泵", "capacity": 10, "energy": 4, "cooldown": 1},
    {"name": "2号泵", "capacity": 14, "energy": 7, "cooldown": 2}
  ]
}
```

- 输入非法 → HTTP 400 `{"error": "原因"}`，页面撤下旧方案并显示原因；
- 无可行方案 → HTTP 200 `{"feasible": false, "reason": "..."}`，页面撤下旧方案并说明；
- 成功 → `feasible: true`，含逐周期的动作、期初/末水量、各泵冷却剩余周期、
  本周期与累计耗电，以及汇总结论。

## 本地运行（无需 Docker）

需要 Python 3.11+，无第三方依赖：

```bash
python -m app.server            # 默认 0.0.0.0:8000
PORT=9000 python -m app.server  # 自定义端口
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## Docker 与 Docker Compose

```bash
cp .env.example .env            # 可选：修改 HOST_PORT
docker compose up -d --build web
# 浏览器打开 http://localhost:8080
```

宿主机端口通过 `HOST_PORT` 配置（默认 `8080`），容器内固定监听 8000。
镜像自带 `HEALTHCHECK`，Compose 也为 `web` 配置了健康检查。

### verify 一次性服务

```bash
docker compose up --build verify
docker compose ps -a            # 查看 verify 退出码
```

`verify` 服务等待 `web` 健康后，依次执行 **构建检查（compileall）→ 单元测试
（unittest，含与独立暴力实现的随机对拍）→ HTTP 冒烟**，随后自行退出，
以退出码报告结果（0 全部通过，非 0 失败）。它不会常驻：

```bash
docker compose up --build verify; echo "verify exit code: $?"
```

## 目录结构

```
app/
  planner.py          # 输入校验 + 完整空间搜索（核心引擎）
  server.py           # 标准库 HTTP 服务（页面 / healthz / API）
  static/index.html   # 值守员页面
tests/                # unittest：引擎、对拍、HTTP
scripts/verify.py     # Compose verify 一次性入口
Dockerfile
docker-compose.yml
.env.example
```
