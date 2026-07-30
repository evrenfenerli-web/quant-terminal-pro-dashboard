import json, os, tempfile

def main():
    import app
    tmp = tempfile.mkdtemp()
    positions = os.path.join(tmp, "positions.json")
    orders = os.path.join(tmp, "orders.json")
    decisions = os.path.join(tmp, "decisions.json")
    events = os.path.join(tmp, "events.jsonl")
    actions = os.path.join(tmp, "manual_actions.jsonl")

    with open(positions, "w") as f:
        json.dump({"BTC/USDT:USDT":{
            "entry":100,"sl":95,"tp1":103,"tp2":107,"tp3":112,"size":2,
            "signal":"LONG","regime":"TREND_UP","conf_score":7.2,"bos_type":"BOS",
            "has_sweep":True,"leverage":4,"open_time":"2026-07-29T20:00:00+00:00"
        }}, f)
    with open(orders, "w") as f:
        json.dump([{"id":"o1","symbol":"BTC/USDT:USDT","side":"sell","type":"stop","price":95,"status":"open"}], f)
    with open(decisions, "w") as f:
        json.dump({"BTC/USDT:USDT":{
            "risk_level":"LOW","current_thesis":"Trend intact",
            "entry_factors":{"BOS":{"score":10,"max":10}},
            "exit_layers":{"K4":{"score":2,"max":10,"active":False}}
        }}, f)
    with open(events, "w") as f:
        f.write(json.dumps({"ts":1,"symbol":"BTC/USDT:USDT","event":"ENTRY","detail":"test"})+"\n")

    class Provider:
        def get_last_price(self, symbol): return 104.0

    app.registry.markets = {"okx":{
        "label":"OKX","provider":Provider(),"symbols":["BTC/USDT:USDT"],
        "symbol_map":{"BTC-USDT-USDT":"BTC/USDT:USDT"},
        "slug_map":{"BTC/USDT:USDT":"BTC-USDT-USDT"},
        "positions_file":positions,"orders_file":orders,
        "decision_file":decisions,"trade_events_file":events,
        "manual_actions_file":actions,
        "action_capabilities":["close_100","close_25","close_50","close_75","move_sl","move_tp","break_even","emergency_close"],
    }}
    app.CONFIG["phase2"]["manual_actions_enabled"] = True
    client = app.app.test_client()
    assert client.get("/manager").status_code == 200
    r = client.get("/api/manager/okx")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert len(data["positions"]) == 1
    assert len(data["orders"]) == 1
    assert data["positions"][0]["explanation"]["risk_level"] == "LOW"
    queued = client.post("/api/manager/okx/action", json={"action":"close_25","symbol":"BTC/USDT:USDT"})
    assert queued.status_code == 200
    assert queued.get_json()["status"] == "queued"
    with open(actions, encoding="utf-8") as handle:
        row = json.loads(handle.readline())
    assert row["action"] == "close_25"
    assert row["close_pct"] == 0.25
    print("Phase 2 manager action tests: OK")

if __name__ == "__main__":
    main()
