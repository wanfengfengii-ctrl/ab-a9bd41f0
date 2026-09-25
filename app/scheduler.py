"""排水泵轮换排程求解器。

约定（与 README / 页面文案一致）：
- 共 N 个调度周期，按来水发生顺序编号 1..N。
- 每个周期先进入该周期来水量，随后至多一台泵运行；周期末水量为
  ``w + inflow - discharge``（不为负，下限截断为 0），待机时不扣减。
- 每个周期末水量必须落在闭区间 [safe_low, safe_high]。
- 泵 p 在周期 r 运行后，必须停歇 rest_p 个完整周期，即周期 q 可再次
  启动当且仅当 ``q > r + rest_p``。
- 目标按字典序依次最小化：累计耗电、全程最高水量（各周期末水量的
  最大值）、动作序列（编码：待机=0、1号泵=1、2号泵=2）。

求解方式：在完整动作空间上深度优先穷举（每周期至多 3 个分支，
N<=12 时叶节点至多 3^12=531441 个），按上述键字典序取全局最优，
不做任何“本周期最省电”的贪心剪枝（仅用累计耗电不可能再低于当前
最优这一单调界排除注定劣于 incumbent 的分支）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

IDLE = 0
RUNNING = "running"
COOLING = "cooling"
READY = "ready"


@dataclass(frozen=True)
class PumpSpec:
    discharge: int
    power: int
    rest: int


@dataclass(frozen=True)
class PumpState:
    pump: int
    state: str  # running=本周期运行 / cooling=本周期处于强制停歇 / ready=本周期可启动
    # running：本周期之后仍须停歇的周期数（=rest）；
    # cooling：本周期之后仍须停歇的周期数（最后一个冷却周期为 0）；ready：0。
    cooldown_remaining: int


@dataclass(frozen=True)
class PeriodRecord:
    period: int
    inflow: int
    action: int  # 0 待机，1/2 为泵编号
    start_water: int
    end_water: int
    total_power: int
    pump_states: tuple[PumpState, PumpState]


@dataclass(frozen=True)
class Plan:
    actions: tuple[int, ...]
    total_power: int
    max_water: int
    records: tuple[PeriodRecord, ...]


def _available(pump_idx: int, current_period: int, last_run: tuple[Optional[int], Optional[int]],
               pumps: tuple[PumpSpec, PumpSpec]) -> bool:
    """泵（0-based 下标）能否在 current_period（1-based）启动。"""
    r = last_run[pump_idx]
    return r is None or current_period > r + pumps[pump_idx].rest


def solve(inflows: list[int], initial_water: int, safe_low: int, safe_high: int,
          pumps: tuple[PumpSpec, PumpSpec]) -> Optional[Plan]:
    """在完整排程空间中求全局最优；无可行方案返回 None。"""
    n = len(inflows)
    best_key: Optional[tuple[int, int, tuple[int, ...]]] = None
    best_actions: Optional[tuple[int, ...]] = None

    def dfs(t: int, water: int, last_run: tuple[Optional[int], Optional[int]],
            power_sum: int, peak: int, actions: tuple[int, ...]) -> None:
        nonlocal best_key, best_actions
        # 单调界：耗电只增不减，若已严格超过 incumbent 的耗电，无需再展开。
        if best_key is not None and power_sum > best_key[0]:
            return

        period_no = t + 1
        inflow = inflows[t]
        candidates: list[int] = [IDLE]
        for p in (0, 1):
            if _available(p, period_no, last_run, pumps):
                candidates.append(p + 1)

        for action in candidates:
            if action == IDLE:
                end_water = water + inflow
                cost = 0
            else:
                spec = pumps[action - 1]
                end_water = max(0, water + inflow - spec.discharge)
                cost = spec.power

            # 闭区间约束：任一周末越界即剪除该分支。
            if end_water < safe_low or end_water > safe_high:
                continue

            new_power = power_sum + cost
            new_peak = max(peak, end_water)
            new_actions = actions + (action,)

            if t + 1 == n:
                key = (new_power, new_peak, new_actions)
                if best_key is None or key < best_key:
                    best_key = key
                    best_actions = new_actions
                continue

            if action == IDLE:
                next_last = last_run
            else:
                updated = list(last_run)
                updated[action - 1] = period_no
                next_last = (updated[0], updated[1])

            dfs(t + 1, end_water, next_last, new_power, new_peak, new_actions)

    dfs(0, initial_water, (None, None), 0, 0, ())

    if best_actions is None:
        return None

    total_power, max_water, records = _simulate(
        inflows, initial_water, pumps, best_actions
    )
    return Plan(
        actions=best_actions,
        total_power=total_power,
        max_water=max_water,
        records=records,
    )


def _simulate(inflows: list[int], initial_water: int, pumps: tuple[PumpSpec, PumpSpec],
              actions: tuple[int, ...]) -> tuple[int, int, tuple[PeriodRecord, ...]]:
    """按给定动作序列复演，生成逐周期明细并复算汇总值。"""
    records: list[PeriodRecord] = []
    water = initial_water
    last_run: list[Optional[int]] = [None, None]
    total_power = 0

    for t, action in enumerate(actions):
        period_no = t + 1
        start_water = water
        if action == IDLE:
            end_water = water + inflows[t]
        else:
            spec = pumps[action - 1]
            end_water = max(0, water + inflows[t] - spec.discharge)
            last_run[action - 1] = period_no
            total_power += spec.power

        states: list[PumpState] = []
        for p in (0, 1):
            r = last_run[p]
            if r is not None and r == period_no:
                # 本周期运行：运行结束后按 rest 进入冷却；
                # cooldown_remaining = 本周期之后仍须停歇的周期数。
                state, remaining = RUNNING, pumps[p].rest
            elif r is not None and period_no <= r + pumps[p].rest:
                # 本周期处于强制停歇中（本周期不可启动）。
                state = COOLING
                remaining = r + pumps[p].rest - period_no
            else:
                state, remaining = READY, 0
            states.append(PumpState(pump=p + 1, state=state, cooldown_remaining=remaining))

        records.append(
            PeriodRecord(
                period=period_no,
                inflow=inflows[t],
                action=action,
                start_water=start_water,
                end_water=end_water,
                total_power=total_power,
                pump_states=(states[0], states[1]),
            )
        )
        water = end_water

    max_water = max(record.end_water for record in records)
    return total_power, max_water, tuple(records)
