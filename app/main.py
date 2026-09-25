"""沿海档案馆地下库排水泵轮换排程服务。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import PlanRequest, PlanResponse, PeriodOut, PumpStateOut, PlanSummary
from .scheduler import PumpSpec, solve

app = FastAPI(title="排水泵轮换排程服务", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_STATE_LABELS = {
    "running": "运行",
    "cooling": "冷却中",
    "ready": "就绪",
}
_ACTION_LABELS = {0: "待机", 1: "1号泵", 2: "2号泵"}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把参数校验错误展开为中文原因列表，供页面撤下旧方案并展示。"""
    reasons: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body",))
        msg = err.get("msg", "输入不合法")
        msg = msg.removeprefix("Value error, ")
        reasons.append(f"{loc}：{msg}" if loc else msg)
    if not reasons:
        reasons.append("输入不合法")
    return JSONResponse(status_code=422, content={"feasible": False, "reasons": reasons})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/drainage-plans", response_model=PlanResponse)
async def create_drainage_plan(payload: PlanRequest) -> PlanResponse:
    specs = (
        PumpSpec(discharge=payload.pumps[0].discharge,
                 power=payload.pumps[0].power,
                 rest=payload.pumps[0].rest),
        PumpSpec(discharge=payload.pumps[1].discharge,
                 power=payload.pumps[1].power,
                 rest=payload.pumps[1].rest),
    )
    plan = solve(
        inflows=list(payload.inflows),
        initial_water=payload.initial_water,
        safe_low=payload.safe_low,
        safe_high=payload.safe_high,
        pumps=specs,
    )

    if plan is None:
        return PlanResponse(
            feasible=False,
            reason="在完整排程空间中不存在可行方案：无论如何安排两台泵的待机与轮换，"
                   "至少有一个周期末水量超出安全水位闭区间，或约束无法同时满足。",
            conclusion="无可行方案，请调整来水量预测、初始水量、安全区间或泵参数。",
        )

    periods_out: list[PeriodOut] = []
    for rec in plan.records:
        states_out = [
            PumpStateOut(
                pump=st.pump,
                state=st.state,
                state_label=_STATE_LABELS[st.state],
                cooldown_remaining=st.cooldown_remaining,
            )
            for st in rec.pump_states
        ]
        periods_out.append(
            PeriodOut(
                period=rec.period,
                inflow=rec.inflow,
                action=rec.action,
                action_label=_ACTION_LABELS[rec.action],
                start_water=rec.start_water,
                end_water=rec.end_water,
                total_power=rec.total_power,
                pump_states=states_out,
            )
        )

    summary = PlanSummary(
        periods=len(periods_out),
        total_power=plan.total_power,
        max_water=plan.max_water,
        final_water=periods_out[-1].end_water,
    )
    conclusion = (
        f"可行方案：{summary.periods} 个周期末水量全部位于闭区间 "
        f"[{payload.safe_low}, {payload.safe_high}]；累计耗电 {plan.total_power}，"
        f"全程最高水量 {plan.max_water}，期末水量 {summary.final_water}。"
        "该方案在完整排程空间中按累计耗电、全程最高水量、动作序列依次最小化得到。"
    )
    return PlanResponse(feasible=True, summary=summary, plan=periods_out, conclusion=conclusion)


# 页面与静态资源挂在最后，避免覆盖 /api 与 /health。
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
