# Security

Quantum Terminal Pro Dashboard can queue trading actions. Treat it as sensitive
infrastructure.

## Required Practices

- Do not expose the dashboard to the public internet without authentication.
- Prefer SSH tunnel, VPN, or nginx with HTTPS and basic auth.
- Keep exchange API keys inside the bot, not inside the dashboard when possible.
- Test all manual actions in paper mode before live mode.
- Restrict EC2 security group access to your own IP.
- Keep `manual_actions.jsonl` writable only by the dashboard user and readable by
  the bot user.

## Live Trading Warning

The dashboard writes commands. Your bot adapter executes them. The adapter must
validate symbols, position state, paper/live mode, and exchange rules before
sending any order.
