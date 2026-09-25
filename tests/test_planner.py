"""planner 单元测试：含与独立暴力参考实现的随机对拍。"""

from __future__ import annotations

import random
import unittest
from itertools import product

from app.planner import IDLE, PUMP_A, PUMP_B, ValidationError, plan, validate

BASE_PAYLOAD = {
    "inflows": [8, 12, 6, 15, 10, 7],
    "initial_water": 5,
    "low_water": 0,
    "high_water": 20,
    "pumps": [
        {"name": "1号泵", "capacity": 10, "energy": 4, "cooldown": 1},
        {"name": "2号泵", "capacity": 14, "energy": 7, "cooldown": 2},
    ],
}


def reference_solve(spec):
    """独立暴力实现：枚举全部 3**T 个动作序列，按 (耗电, 峰值, 序列) 取最小。"""
    inflows = spec["inflows"]
    caps = [p["capacity"] for p in spec["pumps"]]
    energies = [p["energy"] for p in spec["pumps"]]
    cooldowns = [p["cooldown"] for p in spec["pumps"]]
    periods = len(inflows)
    best = None

    for actions in product((IDLE, PUMP_A, PUMP_B), repeat=periods):
        level = spec["initial_water"]
        cd = [0, 0]
        used = 0
        peak = level
        feasible = True
        for i, action in enumerate(actions):
            if action != IDLE and cd[action - 1] > 0:
                feasible = False
                break
            drain = caps[action - 1] if action != IDLE else 0
            spent = energies[action - 1] if action != IDLE else 0
            end = level + inflows[i] - drain
            if end < spec["low_water"] or end > spec["high_water"]:
                feasible = False
                break
            used += spent
            peak = max(peak, end)
            cd = [max(c - 1, 0) for c in cd]
            if action != IDLE:
                cd[action - 1] = cooldowns[action - 1]
            level = end
        if feasible:
            candidate = (used, peak, actions)
            if best is None or candidate < best:
                best = candidate
    return best


def engine_tuple(result):
    return (
        result["summary"]["total_energy"],
        result["summary"]["peak_water"],
        tuple(r["action"] for r in result["periods"]),
    )


class FeasiblePlanTests(unittest.TestCase):
    def test_default_scenario_is_feasible_and_consistent(self):
        result = plan(BASE_PAYLOAD)
        self.assertTrue(result["feasible"])
        spec = result["spec"]
        self.assertEqual(len(result["periods"]), 6)

        cumulative = 0
        for row in result["periods"]:
            # 逐周期水量恒等式
            expected_end = (
                row["water_start"] + row["inflow"] - row["drain"]
            )
            self.assertEqual(row["water_end"], expected_end)
            self.assertGreaterEqual(row["water_end"], spec["low_water"])
            self.assertLessEqual(row["water_end"], spec["high_water"])
            cumulative += row["energy_used"]
            self.assertEqual(row["cumulative_energy"], cumulative)

            # 启动的泵周期初必须可用
            if row["action"] != IDLE:
                name = spec["pumps"][row["action"] - 1]["name"]
                self.assertTrue(row["pump_available"][name])

        # 冷却状态：运行后剩余停歇数等于 cooldown，之后逐周期递减
        rows = result["periods"]
        for i, row in enumerate(rows):
            if row["action"] != IDLE:
                pidx = row["action"] - 1
                name = spec["pumps"][pidx]["name"]
                cd = spec["pumps"][pidx]["cooldown"]
                self.assertEqual(row["cooling_remaining"][name], cd)
                for k in range(1, cd + 1):
                    if i + k < len(rows):
                        self.assertEqual(
                            rows[i + k]["cooling_remaining"][name], cd - k
                        )
                        # 停歇未结束不得再次启动
                        if k <= cd:
                            self.assertNotEqual(rows[i + k]["action"], pidx + 1)

        self.assertEqual(result["summary"]["total_energy"], cumulative)
        # 峰值包含初始水量
        self.assertGreaterEqual(result["summary"]["peak_water"], spec["initial_water"])
        self.assertEqual(
            result["summary"]["peak_water"],
            max([spec["initial_water"]] + [r["water_end"] for r in rows]),
        )

    def test_matches_independent_brute_force(self):
        result = plan(BASE_PAYLOAD)
        ref = reference_solve(result["spec"])
        self.assertIsNotNone(ref)
        self.assertEqual(engine_tuple(result), ref)

    def test_peak_breakbefore_action_order(self):
        # 两泵耗电量相同且每周期都必须开泵（区间极窄）：
        # 2 号泵排量更大使周期末水量更低，峰值目标必然全程选 2 号泵。
        payload = {
            "inflows": [6, 6, 6, 6, 6, 6],
            "initial_water": 0,
            "low_water": 0,
            "high_water": 1,
            "pumps": [
                {"capacity": 5, "energy": 1, "cooldown": 0},
                {"capacity": 6, "energy": 1, "cooldown": 0},
            ],
        }
        result = plan(payload)
        ref = reference_solve(result["spec"])
        self.assertEqual(engine_tuple(result), ref)
        self.assertTrue(all(r["action"] == PUMP_B for r in result["periods"]))
        self.assertEqual(result["summary"]["peak_water"], 0)

    def test_action_lexicographic_prefers_pump_one_when_fully_tied(self):
        # 每周期必须排水、两泵参数完全等价：耗电与峰值全同时，
        # 动作序列字典序应全部选 1 号泵。
        payload = {
            "inflows": [5, 5, 5, 5, 5, 5],
            "initial_water": 0,
            "low_water": 0,
            "high_water": 0,
            "pumps": [
                {"capacity": 5, "energy": 2, "cooldown": 0},
                {"capacity": 5, "energy": 2, "cooldown": 0},
            ],
        }
        result = plan(payload)
        self.assertTrue(result["feasible"])
        self.assertTrue(all(r["action"] == PUMP_A for r in result["periods"]))

    def test_idle_only_when_energy_optimal(self):
        # 来水为 0 且水位本就在区间内：全程待机耗电 0 为最优。
        payload = {
            "inflows": [0, 0, 0, 0, 0, 0],
            "initial_water": 3,
            "low_water": 0,
            "high_water": 10,
            "pumps": [
                {"capacity": 1, "energy": 1, "cooldown": 0},
                {"capacity": 1, "energy": 1, "cooldown": 0},
            ],
        }
        result = plan(payload)
        self.assertTrue(all(r["action"] == IDLE for r in result["periods"]))
        self.assertEqual(result["summary"]["total_energy"], 0)

    def test_twelve_periods_runs_full_space(self):
        payload = dict(BASE_PAYLOAD)
        payload["inflows"] = [8, 12, 6, 15, 10, 7, 9, 11, 5, 14, 8, 6]
        result = plan(payload)
        self.assertTrue(result["feasible"])
        self.assertEqual(len(result["periods"]), 12)
        ref = reference_solve(result["spec"])
        self.assertEqual(engine_tuple(result), ref)


class InfeasibleTests(unittest.TestCase):
    def test_inflow_beyond_capacity(self):
        payload = {
            "inflows": [20] * 6,
            "initial_water": 0,
            "low_water": 0,
            "high_water": 10,
            "pumps": [
                {"capacity": 3, "energy": 1, "cooldown": 0},
                {"capacity": 4, "energy": 1, "cooldown": 0},
            ],
        }
        result = plan(payload)
        self.assertFalse(result["feasible"])
        self.assertIn("不存在可行方案", result["reason"])

    def test_initial_above_high_is_infeasible(self):
        payload = dict(BASE_PAYLOAD)
        payload["initial_water"] = 21
        result = plan(payload)
        # 初始 21、上限 20：首周期末水量 = 21 + inflow - drain，
        # 两泵合计至多排 14（且不能同开），无法回到区间。
        self.assertFalse(result["feasible"])

    def test_cooldown_makes_it_infeasible(self):
        # 每周期都必须排 10，仅 1 号泵能排 10，但其需要停歇 1 周期 → 不可行。
        payload = {
            "inflows": [10, 10, 10, 10, 10, 10],
            "initial_water": 0,
            "low_water": 0,
            "high_water": 0,
            "pumps": [
                {"capacity": 10, "energy": 1, "cooldown": 1},
                {"capacity": 1, "energy": 1, "cooldown": 0},
            ],
        }
        result = plan(payload)
        self.assertFalse(result["feasible"])


class ValidationTests(unittest.TestCase):
    def _expect(self, mutator, fragment):
        payload = {k: (v.copy() if isinstance(v, list) else v)
                   for k, v in BASE_PAYLOAD.items()}
        payload["pumps"] = [dict(p) for p in BASE_PAYLOAD["pumps"]]
        mutator(payload)
        with self.assertRaises(ValidationError) as ctx:
            validate(payload)
        self.assertIn(fragment, str(ctx.exception))

    def test_wrong_period_counts(self):
        self._expect(lambda p: p.update(inflows=[1] * 5), "6 到 12")
        self._expect(lambda p: p.update(inflows=[1] * 13), "6 到 12")

    def test_non_integer_rejected(self):
        self._expect(lambda p: p.update(initial_water=1.5), "整数")
        self._expect(lambda p: p.update(inflows=[1, 2, 3, 4, 5, 6.0]), "整数")

    def test_bool_is_not_integer(self):
        self._expect(lambda p: p.update(initial_water=True), "整数")

    def test_negative_and_zero(self):
        def neg_inflow(p):
            p["inflows"] = [-1, 0, 0, 0, 0, 0]

        def zero_capacity(p):
            p["pumps"][1]["capacity"] = 0

        def zero_energy(p):
            p["pumps"][0]["energy"] = 0

        self._expect(neg_inflow, "不能小于 0")
        self._expect(zero_capacity, "不能小于 1")
        self._expect(zero_energy, "不能小于 1")

    def test_level_range_and_missing(self):
        self._expect(lambda p: p.update(low_water=21), "下限不能大于上限")
        with self.assertRaises(ValidationError):
            validate({})
        self._expect(lambda p: p.update(pumps=[p["pumps"][0]]), "两台泵")

    def test_unknown_field(self):
        self._expect(lambda p: p.update(extra=1), "不支持的字段")

    def test_invalid_cooldown(self):
        self._expect(lambda p: p.__setitem__("pumps", [
            {**p["pumps"][0], "cooldown": -1}, dict(p["pumps"][1])]), "不能小于 0")


class RandomizedAgainstBruteForce(unittest.TestCase):
    def test_random_instances(self):
        rng = random.Random(20260925)
        for trial in range(60):
            periods = rng.randint(6, 10)
            payload = {
                "inflows": [rng.randint(0, 12) for _ in range(periods)],
                "initial_water": rng.randint(0, 8),
                "low_water": 0,
                "high_water": rng.randint(8, 22),
                "pumps": [
                    {"capacity": rng.randint(4, 14), "energy": rng.randint(1, 9),
                     "cooldown": rng.randint(0, 3)},
                    {"capacity": rng.randint(4, 14), "energy": rng.randint(1, 9),
                     "cooldown": rng.randint(0, 3)},
                ],
            }
            with self.subTest(trial=trial, payload=payload):
                result = plan(payload)
                spec = result["spec"]
                ref = reference_solve(spec)
                if ref is None:
                    self.assertFalse(result["feasible"])
                else:
                    self.assertTrue(result["feasible"])
                    self.assertEqual(engine_tuple(result), ref)


if __name__ == "__main__":
    unittest.main()
