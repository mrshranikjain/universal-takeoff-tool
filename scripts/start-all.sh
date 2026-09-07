#!/bin/bash
# Combined startup script for tunnel + server
# Called by launchd on boot/login

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/shranikjain"

# Start Cloudflare Tunnel
nohup /opt/homebrew/Cellar/cloudflared/2026.7.3/bin/cloudflared tunnel --config /Users/shranikjain/.cloudflared/config.yml run > /Users/shranikjain/Desktop/openclaw/takeoff-tool/logs/tunnel.log 2>&1 &

# Wait for tunnel to connect
sleep 5

# Start Takeoff AI server
cd /Users/shranikjain/Desktop/openclaw/takeoff-tool/web/backend
exec /opt/homebrew/Cellar/python@3.14/3.14.4_1/Frameworks/Python.framework/Versions/3.14/bin/python3.14 server.py --host 0.0.0.0 --port 8765 > /Users/shranikjain/Desktop/openclaw/takeoff-tool/logs/server.log 2>&1