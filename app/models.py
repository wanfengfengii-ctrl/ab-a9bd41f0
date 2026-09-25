"""POST /api/drainage-plans 的请求/响应模型与输入校验。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# 允许的来水量序列长度（6 至 12 个按发生顺序的周期）。
MIN_PERIODS = 6
MAX_PERIODS = 12


class PumpInput(BaseModel):
    discharge: int = Field(..., description="每周期排水量（正整数）")
    power: int = Field(..., description="每运行一周期的耗电量（非负整数）")
    rest: int = Field(..., description="运行后必须停歇的整数周期数（非负整数）")

    @field_validator("discharge", "power", "rest", mode="before")
    @classmethod
    def _reject_bool(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("必须是整数，不能是布尔值")
        return v

    @model_validator(mode="after")
    def _check_ranges(self) -> "PumpInput":
        if self.discharge <= 0:
            raise ValueError("每周期排水量必须为正整数")
        if self.power < 0:
            raise ValueError("耗电量不能为负")
        if self.rest < 0:
            raise ValueError("停歇周期数不能为负")
        return self


class PlanRequest(BaseModel):
    inflows: list[int] = Field(..., description="按发生顺序排列的各周期来水量")
    initial_water: int = Field(..., description="第 1 周期开始前的集水井水量")
    safe_low: int = Field(..., description="安全水位闭区间下限")
    safe_high: int = Field(..., description="安全水位闭区间上限")
    pumps: list[PumpInput] = Field(..., description="两台排水泵参数，按泵编号顺序")

    @field_validator("inflows", mode="before")
    @classmethod
    def _inflows_not_bool_elements(cls, v: object) -> object:
        if isinstance(v, list):
            for item in v:
                if isinstance(item, bool):
                    raise ValueError("来水量必须全部为整数，不能包含布尔值")
        return v

    @field_validator("initial_water", "safe_low", "safe_high", mode="before")
    @classmethod
    def _reject_bool_scalar(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("必须是整数，不能是布尔值")
        return v

    @model_validator(mode="before")
    @classmethod
    def _check_request_raw(cls, data: object) -> object:
        """跨字段请求级校验在原始输入上完成，可与字段级错误同时暴露。"""
        if not isinstance(data, dict):
            return data
        problems: list[str] = []

        inflows = data.get("inflows")
        if isinstance(inflows, list):
            n = len(inflows)
            if not MIN_PERIODS <= n <= MAX_PERIODS:
                problems.append(
                    f"来水量个数必须在 {MIN_PERIODS} 至 {MAX_PERIODS} 之间，当前为 {n}"
                )
            elif any(
                isinstance(x, int) and not isinstance(x, bool) and x < 0
                for x in inflows
            ):
                problems.append("来水量不能为负")

        def as_int(key: str) -> object:
            value = data.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            return value

        initial = as_int("initial_water")
        if initial is not None and initial < 0:
            problems.append("初始水量不能为负")
        safe_low = as_int("safe_low")
        if safe_low is not None and safe_low < 0:
            problems.append("安全水位下限不能为负")
        safe_high = as_int("safe_high")
        if safe_low is not None and safe_high is not None and safe_low > safe_high:
            problems.append("安全水位下限不能高于上限")

        pumps = data.get("pumps")
        if isinstance(pumps, list) and len(pumps) != 2:
            problems.append(f"必须提供恰好 2 台泵的参数，当前为 {len(pumps)} 台")

        if problems:
            raise ValueError("；".join(problems))
        return data


class PumpStateOut(BaseModel):
    pump: int
    state: Literal["running", "cooling", "ready"]
    state_label: str
    cooldown_remaining: int


class PeriodOut(BaseModel):
    period: int
    inflow: int
    action: Literal[0, 1, 2]
    action_label: str
    start_water: int
    end_water: int
    total_power: int
    pump_states: list[PumpStateOut]


class PlanSummary(BaseModel):
    periods: int
    total_power: int
    max_water: int
    final_water: int


class PlanResponse(BaseModel):
    feasible: bool
    reason: str | None = None
    summary: PlanSummary | None = None
    plan: list[PeriodOut] = Field(default_factory=list)
    conclusion: str
