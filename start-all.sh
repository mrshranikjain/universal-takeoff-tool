#!/bin/bash
# Start both the Cloudflare tunnel and Takeoff AI server
# This script is called by the launch agent on login

export PATH="/opt/homebrew/bin:$PATH"

# Start Cloudflare Tunnel (background, auto-restart by launchd)
/opt/homebrew/bin/cloudflared tunnel --config /Users/shranikjain/.cloudflared/config.yml run &

# Wait for tunnel to initialize
sleep 3

# Start Takeoff AI server
cd /Users/shranikjain/Desktop/openclaw/takeoff-tool/web/backend
python3 server.py --host 0.0.0.0 --port 8765 &

# Wait for both
wait