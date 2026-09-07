#!/bin/bash
# Start the Takeoff Tool web server
# Usage: ./start.sh

# Ensure Homebrew bin is in PATH (for tesseract, etc.)
export PATH="/opt/homebrew/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/web/backend"

echo "Starting Takeoff AI on http://localhost:8765"
echo "Press Ctrl+C to stop"
echo ""

python3 server.py --host 0.0.0.0 --port 8765