import csv
import io
import json
import os
import tempfile

from funding_engine import FundingEngineV2, get_funding_analytics


def test_engine():
    engine = FundingEngineV2(windows=[90, 30, 8], elevated_z=1.5, extreme_z=2.5)
    history = [0.00010, 0.00011, 0.00009, 0.00010, 0.00012, 0.00008, 0.00010, 0.00010]
    normal = engine.analyze("BTC/USDT:USDT", 0.00010, history, side="LONG")
    assert normal["baseline_window"] == 8
    assert normal["funding_class"] == "NORMAL"
    assert normal["crowding"] == "LONGS_PAY"
    assert normal["side_effect"] == "ADVERSE"

    extreme = get_funding_analytics(
        "BTC/USDT:USDT", 0.001, history, side="SHORT",
        config={"windows": [90, 30, 8], "elevated_z": 1.5, "extreme_z": 2.5},
    )
    assert extreme["funding_class"] == "EXTREME"
    assert extreme["side_effect"] == "FAVORABLE"
    series = engine.analyze_series("BTC/USDT:USDT", history)
    assert len(series) == len(history)


def test_dashboard():
    import app
    tmp = tempfile.mkdtemp()
    funding_file = os.path.join(tmp, "funding_analytics.jsonl")
    trade_file = os.path.join(tmp, "trade_analytics.jsonl")
    rates = [0.00010, 0.00011, 0.00009, 0.00010, 0.00012, 0.00008, 0.00010, 0.001]
    with open(funding_file, "w", encoding="utf-8") as handle:
        for index, rate in enumerate(rates):
            handle.write(json.dumps({
                "ts": index + 1, "symbol": "BTC/USDT:USDT", "funding_rate": rate,
            }) + "\n")
    with open(trade_file, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "symbol": "BTC/USDT:USDT", "funding_cost_usd": 1.25,
        }) + "\n")
        handle.write(json.dumps({
            "symbol": "BTC/USDT:USDT", "funding_cost_usd": -0.25,
        }) + "\n")

    app.CONFIG["analytics"] = {"okx": {
        "funding_analytics_file": funding_file,
        "trade_analytics_file": trade_file,
    }}
    app.registry.markets = {
        "okx": {"label": "OKX", "provider": None, "symbols": [], "symbol_map": {},
                "slug_map": {}, "positions_file": ""}
    }
    client = app.app.test_client()
    assert client.get("/funding").status_code == 200
    response = client.get("/api/funding/okx")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["symbols"] == 1
    assert data["summary"]["total_funding_cost_usd"] == 1.0
    assert data["current"]["BTC/USDT:USDT"]["funding_class"] == "EXTREME"
    assert "ETH/USDT:USDT" in data["missing_baseline_symbols"]

    export = client.get("/api/funding/okx/export.csv")
    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.get_data(as_text=True))))
    assert len(rows) == 8
    assert client.get("/api/funding/unknown").status_code == 404


def main():
    test_engine()
    test_dashboard()
    print("Phase 5 Funding Engine v2 tests: OK")


if __name__ == "__main__":
    main()
