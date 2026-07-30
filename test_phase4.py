import csv
import io
import json
import os
import tempfile


def main():
    import app

    tmp = tempfile.mkdtemp()
    trade_file = os.path.join(tmp, "trade_analytics.jsonl")
    exit_file = os.path.join(tmp, "exit_analytics.jsonl")
    trades = [
        {
            "trade_id": "1", "symbol": "BTC/USDT:USDT", "exit_reason": "K4_BLEEDING",
            "exit_subreason": "momentum_decay", "exit_r": 1.2, "mfe_r": 2.0,
            "mae_r": 0.2, "tp1_hit": True, "tp2_hit": True, "tp3_hit": False,
            "closed_at": 1,
        },
        {
            "trade_id": "2", "symbol": "ETH/USDT:USDT", "exit_reason": "TP3_HIT",
            "exit_r": 3.0, "mfe_r": 3.2, "mae_r": 0.1, "lost_r": 0.2,
            "capture_ratio": 0.9375, "tp1_hit": True, "tp2_hit": True,
            "tp3_hit": True, "closed_at": 2,
        },
        {
            "trade_id": "3", "symbol": "SOL/USDT:USDT", "exit_reason": "SL_HIT",
            "exit_r": -1.0, "mfe_r": 0.0, "mae_r": 1.0,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "closed_at": 3,
        },
    ]
    with open(trade_file, "w", encoding="utf-8") as handle:
        for row in trades:
            handle.write(json.dumps(row) + "\n")
    with open(exit_file, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"reason": "K4_BLEEDING", "bars": 5, "move_r": 0.4}) + "\n")
        handle.write(json.dumps({"reason": "TP3_HIT", "bars": 10, "move_r": -0.2}) + "\n")

    app.CONFIG["analytics"] = {"okx": {
        "trade_analytics_file": trade_file,
        "exit_analytics_file": exit_file,
        "rejected_analytics_file": "",
    }}
    app.registry.markets = {
        "okx": {"label": "OKX", "provider": None, "symbols": [], "symbol_map": {},
                "slug_map": {}, "positions_file": ""}
    }

    client = app.app.test_client()
    assert client.get("/exit_report").status_code == 200
    response = client.get("/api/exit-report/okx")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["trades"] == 3
    assert data["tp_funnel"]["tp1"]["count"] == 2
    assert data["tp_funnel"]["tp2"]["from_previous"] == 100.0
    assert data["tp_funnel"]["tp3"]["from_previous"] == 50.0
    assert data["trades"][0]["lost_r"] == 0.8
    assert data["trades"][0]["capture_ratio"] == 0.6
    assert data["by_reason"]["K4"]["exit_quality_score"] == 65.0
    assert data["shadow_exit"]["by_bars"]["5"]["continued_pct"] == 100.0

    filtered = client.get("/api/exit-report/okx?last_n=2").get_json()["data"]
    assert filtered["summary"]["trades"] == 2

    csv_response = client.get("/api/exit-report/okx/export.csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.get_data(as_text=True))))
    assert len(rows) == 3
    assert rows[0]["exit_quality_score"] == "65.0"
    assert client.get("/api/exit-report/unknown").status_code == 404
    print("Phase 4 exit intelligence tests: OK")


if __name__ == "__main__":
    main()
