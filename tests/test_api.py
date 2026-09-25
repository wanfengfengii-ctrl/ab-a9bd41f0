"""POST /api/drainage-plans / GET /health 的接口测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DEFAULT_BODY = {
    "inflows": [30, 45, 50, 35, 20, 15, 10, 8],
    "initial_water": 7,
    "safe_low": 0,
    "safe_high": 73,
    "pumps": [
        {"discharge": 35, "power": 5, "rest": 1},
        {"discharge": 50, "power": 10, "rest": 3},
    ],
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_index_page_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "排水泵" in resp.text


def test_feasible_plan_response_shape():
    resp = client.post("/api/drainage-plans", json=DEFAULT_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is True
    assert data["reason"] is None
    assert data["summary"]["periods"] == 8
    assert len(data["plan"]) == 8
    first = data["plan"][0]
    assert {"period", "inflow", "action", "action_label", "start_water",
            "end_water", "total_power", "pump_states"} <= set(first)
    assert len(first["pump_states"]) == 2
    for row in data["plan"]:
        assert 0 <= row["end_water"] <= 73
    assert data["summary"]["total_power"] == sum(
        row["total_power"] for row in data["plan"][-1:]
    )
    assert "累计耗电" in data["conclusion"]


def test_response_power_and_cooldown_consistency():
    body = {
        **DEFAULT_BODY,
        "initial_water": 0,
        "inflows": [30, 40, 20, 0, 0, 0],
        "safe_high": 55,
        "pumps": [
            {"discharge": 20, "power": 5, "rest": 1},
            {"discharge": 50, "power": 100, "rest": 2},
        ],
    }
    resp = client.post("/api/drainage-plans", json=body)
    data = resp.json()
    assert resp.status_code == 200
    assert data["feasible"] is True
    assert [r["action"] for r in data["plan"]] == [1, 0, 1, 0, 0, 0]
    # 第 1 周期 1 号泵运行，rest=1 → 第 2 周期为最后一个强制停歇周期（冷却中、
    # 本周期不可用，之后剩余 0），第 3 周期就绪并可再次运行。
    assert data["plan"][0]["pump_states"][0]["state"] == "running"
    assert data["plan"][0]["pump_states"][0]["cooldown_remaining"] == 1
    assert data["plan"][1]["pump_states"][0]["state"] == "cooling"
    assert data["plan"][1]["pump_states"][0]["cooldown_remaining"] == 0
    assert data["plan"][2]["pump_states"][0]["state"] == "running"
    assert data["summary"]["total_power"] == 10


def test_infeasible_returns_200_with_reason():
    body = {
        **DEFAULT_BODY,
        "inflows": [100, 0, 0, 0, 0, 0],
        "pumps": [
            {"discharge": 30, "power": 5, "rest": 0},
            {"discharge": 30, "power": 5, "rest": 0},
        ],
    }
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is False
    assert data["reason"]
    assert data["plan"] == []
    assert data["summary"] is None


def test_invalid_period_count_rejected():
    body = {**DEFAULT_BODY, "inflows": [1, 2, 3, 4, 5]}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422
    data = resp.json()
    assert data["feasible"] is False
    assert any("6" in r and "12" in r for r in data["reasons"])


def test_invalid_pump_count_rejected():
    body = {**DEFAULT_BODY, "pumps": [DEFAULT_BODY["pumps"][0]]}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422
    assert any("2 台泵" in r for r in resp.json()["reasons"])


def test_safe_range_and_negative_rejected():
    body = {**DEFAULT_BODY, "safe_low": 70, "safe_high": 60}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422
    assert any("下限不能高于上限" in r for r in resp.json()["reasons"])

    body = {**DEFAULT_BODY, "inflows": [-1] + [0] * 7}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422

    body = {**DEFAULT_BODY, "pumps": [
        {"discharge": 0, "power": 8, "rest": 1},
        {"discharge": 40, "power": 14, "rest": 2},
    ]}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422
    assert any("正整数" in r for r in resp.json()["reasons"])


def test_non_integer_input_rejected():
    body = {**DEFAULT_BODY, "initial_water": 20.5}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422

    body = {**DEFAULT_BODY, "inflows": ["x", 0, 0, 0, 0, 0]}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422


def test_boolean_values_rejected():
    body = {**DEFAULT_BODY, "initial_water": True}
    assert client.post("/api/drainage-plans", json=body).status_code == 422

    body = {**DEFAULT_BODY, "inflows": [True, 0, 0, 0, 0, 0]}
    assert client.post("/api/drainage-plans", json=body).status_code == 422

    body = {**DEFAULT_BODY, "pumps": [
        {"discharge": True, "power": 5, "rest": 1},
        DEFAULT_BODY["pumps"][1],
    ]}
    assert client.post("/api/drainage-plans", json=body).status_code == 422


def test_missing_field_rejected():
    body = {k: v for k, v in DEFAULT_BODY.items() if k != "pumps"}
    resp = client.post("/api/drainage-plans", json=body)
    assert resp.status_code == 422
