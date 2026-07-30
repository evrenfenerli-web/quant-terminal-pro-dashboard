import json
import os
import tempfile


def main():
    import app

    tmp = tempfile.mkdtemp()
    trade_file = os.path.join(tmp, "trade_analytics.jsonl")
    rejected_file = os.path.join(tmp, "rejected_analytics.jsonl")
    positions_file = os.path.join(tmp, "positions.json")
    trades = [
        {
            "trade_id": "1", "symbol": "BTC/USDT:USDT", "signal": "LONG",
            "regime": "TREND_UP", "exit_reason": "TP2_HIT", "exit_r": 2.0,
            "mfe_r": 2.5, "mae_r": 0.2, "bars_held": 8,
            "tp1_hit": True, "tp2_hit": True, "tp3_hit": False,
            "opened_at": 1785360000,
            "exit_trigger_candidates": ["K4", "TP2"],
        },
        {
            "trade_id": "2", "symbol": "SOL/USDT:USDT", "signal": "SHORT",
            "regime": "RANGE", "exit_reason": "SL_HIT", "exit_r": -1.0,
            "mfe_r": 0.2, "mae_r": 1.0, "bars_held": 4,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "opened_at": 1785363600,
        },
        {
            "trade_id": "3", "symbol": "ETH/USDT:USDT", "signal": "LONG",
            "regime": "TREND_DOWN", "exit_reason": "K4_BLEEDING", "exit_r": -0.5,
            "mfe_r": 0.4, "mae_r": 0.8, "bars_held": 25,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "opened_at": 1785367200,
        },
    ]
    with open(trade_file, "w", encoding="utf-8") as handle:
        for row in trades:
            handle.write(json.dumps(row) + "\n")
    with open(rejected_file, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "symbol": "SOL/USDT:USDT", "reason": "BTC_FILTER_TREND_MISMATCH",
            "regime": "TREND_UP",
        }) + "\n")
    with open(positions_file, "w", encoding="utf-8") as handle:
        json.dump({}, handle)

    app.CONFIG["analytics"] = {"okx": {
        "trade_analytics_file": trade_file,
        "rejected_analytics_file": rejected_file,
        "exit_analytics_file": "",
        "funding_analytics_file": "",
    }}
    app.CONFIG["okx"]["symbols"] = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    app.CONFIG["phase2"]["manual_actions_enabled"] = False
    app.registry.markets = {"okx": {
        "label": "OKX", "provider": None,
        "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
        "symbol_map": {}, "slug_map": {}, "positions_file": positions_file,
        "orders_file": "", "decision_file": "", "trade_events_file": "",
    }}

    client = app.app.test_client()
    assert client.get("/diagnostics").status_code == 200
    response = client.get("/api/diagnostics/okx")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["trades"] == 3
    assert data["summary"]["regime_violations"] == 1
    assert data["summary"]["counter_trend_violations"] == 1
    assert data["summary"]["position_side_conflicts"] == 0
    assert data["summary"]["btc_rejections"] == 1
    assert data["exit_trigger_priority"]["multiple_trigger_trades"] == 1
    assert data["coin_analytics"]["BTC/USDT:USDT"]["avg_r"] == 2.0
    assert data["time_analytics"]["bars_held"]["6-10"]["count"] == 1
    assert data["data_quality"]["bars_held"]["coverage_pct"] == 100.0
    assert not data["symbol_config"]["observed_not_configured"]
    assert data["config_audit"]["status"] == "PASS"

    health = client.get("/api/health")
    assert health.status_code == 200
    health_data = health.get_json()
    assert health_data["phase"] == 6
    assert health_data["read_only"] is True
    assert client.get("/api/diagnostics/unknown").status_code == 404
    assert client.post(
        "/api/manager/okx/action",
        json={"action": "close", "symbol": "BTC/USDT:USDT"},
    ).status_code == 403
    print("Phase 6 final diagnostics tests: OK")


if __name__ == "__main__":
    main()
