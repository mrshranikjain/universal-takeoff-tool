#!/bin/bash
# Takeoff AI server startup script
export PATH="/opt/homebrew/bin:$PATH"
cd /Users/shranikjain/Desktop/openclaw/takeoff-tool/web/backend
exec python3 server.py --host 0.0.0.0 --port 8765