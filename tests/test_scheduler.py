"""求解器测试：约束满足、全局最优（独立暴力枚举交叉验证）、贪心反例与 tie-break。"""
from __future__ import annotations

import itertools
import random

import pytest

from app.scheduler import PumpSpec, solve


def simulate(inflows, initial, pumps, actions):
    """独立的动作序列复演：违反冷却约束返回 None，否则返回 (耗电, 峰值, 末值, 各期末值)。"""
    water = initial
    last_run: dict[int, int] = {}
    power = 0
    peak = 0
    ends: list[int] = []
    for t, action in enumerate(actions, start=1):
        if action != 0:
            r = last_run.get(action)
            spec = pumps[action - 1]
            if r is not None and not t > r + spec.rest:
                return None
            water = max(0, water + inflows[t - 1] - spec.discharge)
            power += spec.power
            last_run[action] = t
        else:
            water += inflows[t - 1]
        peak = max(peak, water)
        ends.append(water)
    return power, peak, water, ends


def brute_force_optimum(inflows, initial, safe_low, safe_high, pumps):
    """完整枚举 3^N 个动作序列，返回最小键 (耗电, 最高水量, 动作序列)。"""
    best = None
    for actions in itertools.product((0, 1, 2), repeat=len(inflows)):
        result = simulate(inflows, initial, pumps, actions)
        if result is None:
            continue
        power, peak, _final, ends = result
        if any(not safe_low <= w <= safe_high for w in ends):
            continue
        key = (power, peak, actions)
        if best is None or key < best:
            best = key
    return best


def assert_plan_valid(plan, inflows, initial, safe_low, safe_high, pumps):
    assert plan is not None
    assert len(plan.records) == len(inflows)
    water = initial
    last_run: dict[int, int] = {}
    power = 0
    for t, rec in enumerate(plan.records, start=1):
        assert rec.period == t
        assert rec.start_water == water
        assert rec.inflow == inflows[t - 1]
        if rec.action != 0:
            r = last_run.get(rec.action)
            spec = pumps[rec.action - 1]
            if r is not None:
                assert t > r + spec.rest, f"周期 {t} 泵 {rec.action} 冷却未满"
            water = max(0, water + rec.inflow - spec.discharge)
            power += spec.power
            last_run[rec.action] = t
        else:
            water += rec.inflow
        assert rec.end_water == water
        assert safe_low <= rec.end_water <= safe_high, f"周期 {t} 末水量越界"
        assert rec.total_power == power
    assert plan.total_power == power
    assert plan.max_water == max(r.end_water for r in plan.records)


PUMPS_FIXTURE = (
    PumpSpec(discharge=35, power=5, rest=1),
    PumpSpec(discharge=50, power=10, rest=3),
)


def test_frontend_default_scenario_is_feasible_and_valid():
    inflows = [30, 45, 50, 35, 20, 15, 10, 8]
    plan = solve(inflows, 7, 0, 73, PUMPS_FIXTURE)
    assert_plan_valid(plan, inflows, 7, 0, 73, PUMPS_FIXTURE)
    # 两台泵都被调度，且中途有待机；全局耗电 25、峰值 65。
    assert plan.actions == (1, 0, 1, 2, 1, 0, 0, 0)
    assert plan.total_power == 25
    assert plan.max_water == 65


def test_greedy_counterexample_global_optimum_beats_cheapest_now():
    """只按当前周期最低耗电决策会得 105，全局最优仅 10。

    贪心：前两周期能待机就待机 → 第 3 周期被迫启动昂贵的 2 号泵；
    全局：第 1 周期提前用便宜小泵腾出缓冲，全程无需 2 号泵。
    """
    pumps = (PumpSpec(20, 5, 1), PumpSpec(50, 100, 2))
    inflows = [30, 40, 20, 0, 0, 0]
    plan = solve(inflows, 0, 0, 55, pumps)
    assert_plan_valid(plan, inflows, 0, 0, 55, pumps)
    assert plan.total_power == 10
    assert plan.actions == (1, 0, 1, 0, 0, 0)

    greedy_actions = (0, 1, 2, 0, 0, 0)
    greedy_result = simulate(inflows, 0, pumps, greedy_actions)
    assert greedy_result is not None
    assert greedy_result[0] == 105  # 贪心方案可行但耗电高得多


def test_tie_break_peak_when_power_equal():
    """耗电相同的两方案之间，选择全程最高水量更低者。"""
    pumps = (PumpSpec(30, 5, 0), PumpSpec(50, 100, 0))
    inflows = [45, 10, 45, 0, 0, 0]
    plan = solve(inflows, 0, 0, 60, pumps)
    assert_plan_valid(plan, inflows, 0, 0, 60, pumps)
    assert plan.total_power == 10
    assert plan.max_water == 40
    assert plan.actions == (1, 0, 1, 0, 0, 0)


def test_tie_break_action_sequence_prefers_pump_1():
    """两台泵完全相同（耗电、峰值一致）时，动作序列字典序偏向 1 号泵。"""
    pumps = (PumpSpec(30, 5, 1), PumpSpec(30, 5, 1))
    inflows = [70, 0, 0, 0, 0, 0]
    plan = solve(inflows, 0, 0, 60, pumps)
    assert_plan_valid(plan, inflows, 0, 0, 60, pumps)
    assert plan.actions[0] == 1
    assert plan.actions == (1, 0, 0, 0, 0, 0)


def test_infeasible_returns_none():
    pumps = (PumpSpec(30, 5, 0), PumpSpec(30, 5, 0))
    inflows = [100, 0, 0, 0, 0, 0]
    assert solve(inflows, 0, 0, 60, pumps) is None


def test_cooldown_state_labels_span_rest_periods():
    """rest=2：运行周期之后恰有 2 个 cooling 周期，第 4 周期起 ready。"""
    pumps = (PumpSpec(60, 9, 2), PumpSpec(1000, 1000, 0))
    inflows = [70, 0, 0, 0, 0, 0]
    plan = solve(inflows, 0, 0, 60, pumps)
    assert plan is not None
    p1_states = [rec.pump_states[0] for rec in plan.records]
    assert [s.state for s in p1_states[:4]] == ["running", "cooling", "cooling", "ready"]
    assert p1_states[0].cooldown_remaining == 2
    assert p1_states[1].cooldown_remaining == 1
    assert p1_states[2].cooldown_remaining == 0
    # 未运行过的 2 号泵全程就绪。
    assert all(rec.pump_states[1].state == "ready" for rec in plan.records)


def test_rest_zero_running_pump_ready_next_period():
    pumps = (PumpSpec(60, 9, 0), PumpSpec(1000, 1000, 0))
    inflows = [70, 0, 0, 0, 0, 0]
    plan = solve(inflows, 0, 0, 60, pumps)
    assert plan is not None
    states = [rec.pump_states[0].state for rec in plan.records]
    assert states[0] == "running"
    assert states[1] == "ready"


def test_cooldown_blocks_immediate_restart():
    """rest=2 的泵运行后两个周期内不能再次启动。"""
    pumps = (PumpSpec(10, 1, 2), PumpSpec(1000, 1000, 0))
    # 来水很小：任何方案都可行；最优应待机，耗电 0。
    inflows = [5, 5, 5, 5, 5, 5]
    plan = solve(inflows, 0, 0, 100, pumps)
    assert plan.actions == (0, 0, 0, 0, 0, 0)
    assert plan.total_power == 0


def test_rest_zero_allows_consecutive_runs():
    pumps = (PumpSpec(10, 1, 0), PumpSpec(1000, 1000, 0))
    inflows = [15, 15, 0, 0, 0, 0]
    plan = solve(inflows, 0, 0, 10, pumps)
    assert_plan_valid(plan, inflows, 0, 0, 10, pumps)
    # 前两周期连续来水 15，1 号泵 rest=0 可连续运行把水位压在上限内。
    assert plan.actions[:2] == (1, 1)
    assert plan.records[0].end_water == 5
    assert plan.records[1].end_water == 10


@pytest.mark.parametrize("seed", range(40))
def test_random_cases_match_independent_brute_force(seed):
    rng = random.Random(seed)
    n = rng.randint(6, 7)
    inflows = [rng.randint(0, 50) for _ in range(n)]
    initial = rng.randint(0, 20)
    safe_low, safe_high = 0, rng.randint(30, 70)
    pumps = (
        PumpSpec(rng.randint(5, 35), rng.randint(1, 12), rng.randint(0, 2)),
        PumpSpec(rng.randint(5, 45), rng.randint(1, 20), rng.randint(0, 3)),
    )
    plan = solve(inflows, initial, safe_low, safe_high, pumps)
    best = brute_force_optimum(inflows, initial, safe_low, safe_high, pumps)
    if best is None:
        assert plan is None, f"seed {seed}: 暴力枚举认为不可行"
    else:
        assert_plan_valid(plan, inflows, initial, safe_low, safe_high, pumps)
        assert (plan.total_power, plan.max_water, plan.actions) == best, (
            f"seed {seed} 未达全局最优")


def test_max_twelve_periods_runs_and_matches_brute_force():
    inflows = [12, 18, 22, 9, 30, 14, 8, 20, 11, 7, 16, 10]
    pumps = (PumpSpec(20, 6, 1), PumpSpec(35, 13, 2))
    plan = solve(inflows, 10, 0, 55, pumps)
    assert_plan_valid(plan, inflows, 10, 0, 55, pumps)
    best = brute_force_optimum(inflows, 10, 0, 55, pumps)
    assert (plan.total_power, plan.max_water, plan.actions) == best
