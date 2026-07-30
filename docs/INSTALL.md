# Installation

This guide assumes Ubuntu on AWS EC2.

## 1. Upload Files

Copy the project folder to:

```bash
/home/ubuntu/quant/dashboard
```

## 2. Install Dependencies

```bash
cd /home/ubuntu/quant/dashboard
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## 3. Configure Adapters

```bash
cp examples/dashboard_config.example.json dashboard_config.json
nano dashboard_config.json
```

Set the bot paths:

```json
"positions_state_file": "/home/ubuntu/quant/positions_state.json",
"manual_actions_file": "/home/ubuntu/quant/manual_actions.jsonl"
```

Enable the market you need:

```json
"enabled": true
```

Disable unused markets:

```json
"enabled": false
```

## 4. Test Locally

```bash
cd /home/ubuntu/quant/dashboard
./venv/bin/python -m py_compile app.py data_providers.py funding_engine.py
./venv/bin/python app.py
```

Open:

```text
http://SERVER_IP:8050/manager
```

## 5. Run as a Service

Edit `quantdash.service` if your path is different, then:

```bash
sudo cp /home/ubuntu/quant/dashboard/quantdash.service /etc/systemd/system/quantdash.service
sudo systemctl daemon-reload
sudo systemctl enable --now quantdash
systemctl status quantdash --no-pager
```

Health check:

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8050/manager
```

Expected:

```text
HTTP 200
```

## 6. Open Firewall

For quick testing, allow TCP `8050` only from your own IP in the EC2 security
group.

For production, use nginx + HTTPS + authentication or an SSH tunnel.

## 7. Manual Action Test

In paper mode, click `Close 25%` on a test position. Confirm the bot writes a
processed row:

```bash
tail -3 /home/ubuntu/quant/manual_actions.processed.jsonl
```

If no position exists, a safe result is:

```text
position_not_found
```
