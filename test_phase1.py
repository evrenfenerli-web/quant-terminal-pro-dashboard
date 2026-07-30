import json
import os
import tempfile
from datetime import datetime, timezone

def main():
    import app
    tmp = tempfile.mkdtemp()
    trade_file = os.path.join(tmp, "trade_analytics.jsonl")
    rejected_file = os.path.join(tmp, "rejected_analytics.jsonl")
    exit_file = os.path.join(tmp, "exit_analytics.jsonl")

    trades = [
        {"trade_id":"1","symbol":"BTC/USDT:USDT","signal":"LONG","regime":"TREND_UP","exit_reason":"K4_BLEEDING",
         "exit_r":1.2,"mfe_r":1.8,"mae_r":0.4,"lost_r":0.6,"capture_ratio":0.6667,"closed_at":1},
        {"trade_id":"2","symbol":"SOL/USDT:USDT","signal":"LONG","regime":"TREND_DOWN","exit_reason":"NEAR_TP1",
         "exit_r":-0.4,"mfe_r":0.2,"mae_r":0.8,"lost_r":0.6,"capture_ratio":-2.0,"closed_at":2},
    ]
    with open(trade_file, "w") as f:
        for row in trades: f.write(json.dumps(row)+"\n")
    with open(rejected_file, "w") as f:
        f.write(json.dumps({"symbol":"ETH/USDT:USDT","reason":"low_conf:5.5","regime":"TREND_UP"})+"\n")
    with open(exit_file, "w") as f:
        f.write(json.dumps({"reason":"NEAR_TP1","bars":5,"move_pct":0.4})+"\n")

    app.CONFIG["analytics"] = {"okx":{
        "trade_analytics_file":trade_file,
        "rejected_analytics_file":rejected_file,
        "exit_analytics_file":exit_file,
    }}
    # Keep only okx for deterministic API test
    app.registry.markets = {"okx":{"label":"OKX","provider":None,"symbols":[],"symbol_map":{},"slug_map":{},"positions_file":""}}

    client = app.app.test_client()
    assert client.get("/analytics").status_code == 200
    r = client.get("/api/analytics/okx")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["total_trades"] == 2
    assert data["rejected"]["total"] == 1
    assert data["counter_trend"]["counter"]["count"] == 1
    assert client.get("/api/analytics/okx/export.csv").status_code == 200
    assert client.get("/api/analytics/okx/export.json").status_code == 200
    print("Phase 1 analytics route tests: OK")

if __name__ == "__main__":
    main()
