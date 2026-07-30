# Quantum Terminal Pro — Production Checklist

- [ ] `dashboard_config.json` paths match the server.
- [ ] Only the intended adapters have `"enabled": true`.
- [ ] `manual_actions_file` points to the file watched by the bot.
- [ ] `action_capabilities` exposes only actions the bot actually supports.
- [ ] Manual action queue tested in paper mode.
- [ ] Bot writes `manual_actions.processed.jsonl` or an equivalent audit log.
- [ ] `/api/health` returns `HTTP 200`.
- [ ] `/manager` loads and displays the expected market.
- [ ] Diagnostics → Config Audit is `PASS` or only informational.
- [ ] Trade data quality required fields are connected where available.
- [ ] Analytics files are not stale.
- [ ] Dashboard is protected by SSH tunnel, VPN, or nginx HTTPS + auth.
- [ ] EC2 security group limits port `8050` to trusted IPs.
- [ ] Dashboard does not contain exchange withdrawal permissions.
- [ ] Bot adapter rejects unknown symbols and unsupported actions.
- [ ] Backups and log rotation are configured.
