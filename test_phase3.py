def main():
    import app

    class Provider:
        def get_ohlcv(self, symbol, timeframe, limit=200):
            import pandas as pd, numpy as np
            from datetime import datetime, timezone
            n=max(limit,80)
            t=pd.date_range(end=datetime.now(timezone.utc),periods=n,freq="15min",tz="UTC")
            price=100+np.linspace(0,8,n)+np.sin(np.arange(n)/7)
            return pd.DataFrame({
                "timestamp":t,"open":price-.1,"high":price+.4,"low":price-.5,
                "close":price,"volume":np.full(n,5000.0)
            })
        def get_last_price(self,symbol): return 108.0

    app.registry.markets={"okx":{
        "label":"OKX","provider":Provider(),"symbols":["BTC/USDT:USDT","ETH/USDT:USDT"],
        "symbol_map":{"BTC-USDT-USDT":"BTC/USDT:USDT","ETH-USDT-USDT":"ETH/USDT:USDT"},
        "slug_map":{"BTC/USDT:USDT":"BTC-USDT-USDT","ETH/USDT:USDT":"ETH-USDT-USDT"},
        "positions_file":"","orders_file":"","decision_file":"","trade_events_file":""
    }}
    c=app.app.test_client()
    assert c.get("/workspace").status_code==200
    r=c.get("/api/market-map?timeframe=15m")
    assert r.status_code==200
    assert len(r.get_json()["items"])==2
    r=c.get("/api/correlation/okx?timeframe=15m")
    assert r.status_code==200
    assert len(r.get_json()["symbols"])==2
    print("Phase 3 workspace tests: OK")

if __name__=="__main__":
    main()
