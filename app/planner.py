"""排水泵轮换排程引擎。

时序约定
========
共有 ``T`` 个调度周期（6 <= T <= 12），每周期按如下顺序发生：

1. 该周期的来水量 ``inflows[i]`` 进入集水井；
2. 选择一个动作：待机(0)、运行 1 号泵(1)、运行 2 号泵(2)；
3. 得到周期末水量，其必须落在闭区间 ``[low_water, high_water]`` 内。

某泵在周期 ``i`` 运行后，必须完整停歇 ``cooldown`` 个周期，
即最早可在周期 ``i + cooldown + 1`` 再次启动。

优化目标（依次最小化，后者仅在前者持平时起作用）：
1. 累计耗电量；
2. 全程（含初始水量）最高水量；
3. 按周期顺序、以 待机(0) < 1号泵(1) < 2号泵(2) 排列的动作序列字典序。

搜索在 *完整* 排程空间上进行（每周期至多 3 个分支，T <= 12，
最多 3**12 个叶节点），不做任何单周期贪心剪枝。
"""

from __future__ import annotations

from typing import Any

IDLE = 0
PUMP_A = 1
PUMP_B = 2
ACTION_LABELS = {IDLE: "待机", PUMP_A: "1号泵", PUMP_B: "2号泵"}

MIN_PERIODS = 6
MAX_PERIODS = 12
MAX_BODY_VALUE = 10**9  # 防止滥用超大整数


class ValidationError(ValueError):
    """输入非法。message 可直接展示给值守员。"""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_int(value: Any, field: str, *, minimum: int | None = None,
               maximum: int | None = None) -> int:
    if not _is_int(value):
        raise ValidationError(f"{field}必须是整数")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{field}不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{field}不能大于 {maximum}")
    return value


def _check_level(value: int, field: str) -> int:
    return _check_int(value, field, minimum=0, maximum=MAX_BODY_VALUE)


def validate(payload: Any) -> dict[str, Any]:
    """校验并归一化请求载荷。"""
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是 JSON 对象")

    allowed = {"inflows", "initial_water", "low_water", "high_water", "pumps"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError(f"存在不支持的字段：{', '.join(sorted(unknown))}")

    # 来水量
    inflows_raw = payload.get("inflows")
    if not isinstance(inflows_raw, list):
        raise ValidationError("来水量必须是整数数组")
    if not (MIN_PERIODS <= len(inflows_raw) <= MAX_PERIODS):
        raise ValidationError(
            f"来水量个数必须在 {MIN_PERIODS} 到 {MAX_PERIODS} 之间，当前为 {len(inflows_raw)}"
        )
    inflows = [
        _check_int(v, f"第 {i + 1} 周期来水量", minimum=0, maximum=MAX_BODY_VALUE)
        for i, v in enumerate(inflows_raw)
    ]

    initial = _check_level(payload.get("initial_water"), "初始水量")
    low = _check_level(payload.get("low_water"), "安全水位下限")
    high = _check_level(payload.get("high_water"), "安全水位上限")
    if low > high:
        raise ValidationError("安全水位下限不能大于上限")

    # 泵参数
    pumps_raw = payload.get("pumps")
    if not isinstance(pumps_raw, list) or len(pumps_raw) != 2:
        raise ValidationError("必须且只能提供两台泵的参数")

    pumps: list[dict[str, Any]] = []
    for idx, raw in enumerate(pumps_raw):
        label = f"{idx + 1} 号泵"
        if not isinstance(raw, dict):
            raise ValidationError(f"{label}参数必须是对象")
        extra = set(raw) - {"name", "capacity", "energy", "cooldown"}
        if extra:
            raise ValidationError(f"{label}存在不支持的字段：{', '.join(sorted(extra))}")
        name = raw.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValidationError(f"{label}名称必须是非空字符串")
        capacity = _check_int(raw.get("capacity"), f"{label}每周期排水量",
                              minimum=1, maximum=MAX_BODY_VALUE)
        energy = _check_int(raw.get("energy"), f"{label}每周期耗电量",
                            minimum=1, maximum=MAX_BODY_VALUE)
        cooldown = _check_int(raw.get("cooldown"), f"{label}运行后停歇周期数",
                              minimum=0, maximum=MAX_PERIODS)
        pumps.append({
            "name": (name.strip() if name else f"{idx + 1}号泵"),
            "capacity": capacity,
            "energy": energy,
            "cooldown": cooldown,
        })

    return {
        "inflows": inflows,
        "initial_water": initial,
        "low_water": low,
        "high_water": high,
        "pumps": pumps,
    }


def _search(spec: dict[str, Any]) -> tuple[int, int, tuple[int, ...]] | None:
    """枚举完整排程空间，返回 (累计耗电, 全程最高水量, 动作序列)。"""
    inflows = spec["inflows"]
    low = spec["low_water"]
    high = spec["high_water"]
    capacities = (spec["pumps"][0]["capacity"], spec["pumps"][1]["capacity"])
    energies = (spec["pumps"][0]["energy"], spec["pumps"][1]["energy"])
    cooldowns = (spec["pumps"][0]["cooldown"], spec["pumps"][1]["cooldown"])
    periods = len(inflows)

    actions = [0] * periods
    best: tuple[int, int, tuple[int, ...]] | None = None

    def dfs(i: int, level: int, cd_a: int, cd_b: int,
            used_energy: int, peak: int) -> None:
        nonlocal best
        water_before_action = level + inflows[i]

        # 按字典序 0 < 1 < 2 尝试；最优解按完整目标元组比较，顺序仅影响首次命中。
        for action in (IDLE, PUMP_A, PUMP_B):
            if action == PUMP_A and cd_a > 0:
                continue
            if action == PUMP_B and cd_b > 0:
                continue

            if action == IDLE:
                end = water_before_action
                spent = 0
            elif action == PUMP_A:
                end = water_before_action - capacities[0]
                spent = energies[0]
            else:
                end = water_before_action - capacities[1]
                spent = energies[1]

            if end < low or end > high:
                continue  # 周期末水量越界，该分支不可行

            next_cd_a = max(cd_a - 1, 0)
            next_cd_b = max(cd_b - 1, 0)
            if action == PUMP_A:
                next_cd_a = cooldowns[0]
            elif action == PUMP_B:
                next_cd_b = cooldowns[1]

            actions[i] = action
            next_peak = max(peak, end)
            next_energy = used_energy + spent

            if i + 1 == periods:
                candidate = (next_energy, next_peak, tuple(actions))
                if best is None or candidate < best:
                    best = candidate
            else:
                dfs(i + 1, end, next_cd_a, next_cd_b, next_energy, next_peak)

    dfs(0, spec["initial_water"], 0, 0, 0, spec["initial_water"])
    return best


def plan(payload: Any) -> dict[str, Any]:
    """校验输入并求解，返回可直接 JSON 序列化的结果。"""
    spec = validate(payload)
    best = _search(spec)

    if best is None:
        return {
            "feasible": False,
            "reason": (
                "已遍历完整排程空间，不存在可行方案：无法在满足各泵停歇要求的同时，"
                "使每个周期末水量都落在安全水位闭区间内。请调整来水预判、水位区间或泵参数。"
            ),
            "spec": spec,
        }

    total_energy, peak, actions = best
    pumps = spec["pumps"]
    rows: list[dict[str, Any]] = []

    level = spec["initial_water"]
    cumulative = 0
    cd = [0, 0]
    pump_runs = [0, 0]

    for i, action in enumerate(actions):
        inflow = spec["inflows"][i]
        start = level
        available = [cd[0] == 0, cd[1] == 0]

        if action == IDLE:
            pump_index = None
            drain = 0
            spent = 0
            end = start + inflow
        else:
            pump_index = action - 1
            drain = pumps[pump_index]["capacity"]
            spent = pumps[pump_index]["energy"]
            end = start + inflow - drain
            pump_runs[pump_index] += 1

        cumulative += spent

        # 周期结束后：先自然消减一个停歇周期，运行泵再重新进入完整停歇。
        cd = [max(c - 1, 0) for c in cd]
        if pump_index is not None:
            cd[pump_index] = pumps[pump_index]["cooldown"]

        rows.append({
            "period": i + 1,
            "action": action,
            "action_label": ACTION_LABELS[action],
            "pump": action if action != IDLE else None,
            "inflow": inflow,
            "water_start": start,
            "drain": drain,
            "water_end": end,
            "energy_used": spent,
            "cumulative_energy": cumulative,
            "pump_available": {
                pumps[0]["name"]: available[0],
                pumps[1]["name"]: available[1],
            },
            "cooling_remaining": {
                pumps[0]["name"]: cd[0],
                pumps[1]["name"]: cd[1],
            },
        })
        level = end

    summary = {
        "periods": len(actions),
        "total_energy": total_energy,
        "peak_water": peak,
        "final_water": level,
        "pump_runs": {pumps[0]["name"]: pump_runs[0], pumps[1]["name"]: pump_runs[1]},
    }
    conclusion = (
        f"存在可行轮换方案：累计耗电 {total_energy}，全程最高水量 {peak}，"
        f"末期水量 {level}，全部 {len(actions)} 个周期末水量均位于安全区间 "
        f"[{spec['low_water']}, {spec['high_water']}] 内。"
    )

    return {
        "feasible": True,
        "spec": spec,
        "periods": rows,
        "summary": summary,
        "conclusion": conclusion,
    }
