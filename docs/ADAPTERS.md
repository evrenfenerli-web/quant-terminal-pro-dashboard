# Adapter Contract

Quantum Terminal Pro connects to bots through files. This keeps the dashboard
portable across Binance, OKX, Bybit, Alpaca, and custom systems.

## Minimum Bot Requirements

A simple bot only needs two files:

| File | Direction | Required | Purpose |
| --- | --- | --- | --- |
| `positions_state.json` | Bot -> Dashboard | Yes | Current open positions |
| `manual_actions.jsonl` | Dashboard -> Bot | Yes for manual control | Queued user actions |

Everything else is optional but improves the product experience.

| File | Direction | Purpose |
| --- | --- | --- |
| `orders_state.json` | Bot -> Dashboard | Open and pending orders |
| `decision_state.json` | Bot -> Dashboard | Entry thesis, confidence, risk explanation |
| `trade_events.jsonl` | Bot -> Dashboard | Timeline events |
| `trade_analytics.jsonl` | Bot -> Dashboard | Closed trade analytics |
| `exit_analytics.jsonl` | Bot -> Dashboard | Exit-layer analytics |
| `rejected_analytics.jsonl` | Bot -> Dashboard | Rejected setup analysis |
| `funding_analytics.jsonl` | Bot -> Dashboard | Funding data for futures |

## Position Schema

`positions_state.json` should be a JSON object keyed by symbol.

```json
{
  "BTC/USDT:USDT": {
    "signal": "LONG",
    "entry": 64217.95,
    "last_price": 64521.80,
    "sl": 63446.87,
    "tp1": 65148.75,
    "tp2": 66222.75,
    "tp3": 67797.96,
    "size": 0.106797,
    "original_size": 0.106797,
    "leverage": 8,
    "regime": "TREND_UP",
    "conf_score": 5.76,
    "bos_type": "CHOCH",
    "open_time": "2026-07-30T09:20:00+00:00"
  }
}
```

Required practical fields:

| Field | Type | Notes |
| --- | --- | --- |
| `signal` | string | `LONG` or `SHORT` |
| `entry` | number | Entry price |
| `size` | number | Current position size |
| `sl` | number | Stop loss, if available |
| `tp1`, `tp2`, `tp3` | number | Optional targets |

## Manual Action Queue

When a user clicks a control button, the dashboard appends one JSON object per
line to `manual_actions.jsonl`.

Example:

```json
{"id":"9f9f...","ts":1785412319.19,"created_at":"2026-07-30T11:31:59Z","market":"okx","action":"close_25","symbol":"BTC/USDT:USDT","close_pct":0.25,"payload":{"action":"close_25","symbol":"BTC/USDT:USDT"}}
```

Supported default actions:

| Action | Meaning |
| --- | --- |
| `close_100` | Close the full position |
| `close_25` | Close 25 percent |
| `close_50` | Close 50 percent |
| `close_75` | Close 75 percent |
| `move_sl` | Move stop loss to `new_sl` |
| `move_tp` | Move take profit to `new_tp` |
| `break_even` | Move stop loss to entry or bot-defined break-even |
| `emergency_close` | Bot-defined emergency close routine |

## Bot-Side Processing Rules

The bot adapter should:

1. Read only new records from `manual_actions.jsonl`.
2. Validate `id`, `action`, `symbol`, and action-specific fields.
3. Confirm the position exists before sending an exchange order.
4. Reject unsupported actions instead of guessing.
5. Write processed results to `manual_actions.processed.jsonl`.
6. Never execute an action twice.

Recommended processed result:

```json
{
  "ts": 1785412271.16,
  "key": "9f9f...",
  "status": "skip",
  "detail": "position_not_found",
  "action": {
    "id": "9f9f...",
    "action": "close_25",
    "symbol": "TEST"
  }
}
```

## Capability Flags

Each market adapter can restrict buttons through `action_capabilities`.

```json
"action_capabilities": [
  "close_100",
  "close_25",
  "move_sl",
  "break_even"
]
```

If a simple bot cannot move TP or emergency close safely, leave those actions
out. The dashboard will disable them.

## Custom Bot Adapter Checklist

1. Make your bot write `positions_state.json`.
2. Add `manual_actions_file` to `dashboard_config.json`.
3. Add a small bot loop that reads `manual_actions.jsonl`.
4. Map supported commands to your existing exchange functions.
5. Test in paper mode with a fake symbol and confirm it writes `skip`.
6. Test with a real paper position.
7. Only then enable live mode.
