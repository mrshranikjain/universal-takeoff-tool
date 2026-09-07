#!/bin/bash
# Cloudflare Tunnel startup script
export PATH="/opt/homebrew/bin:$PATH"
exec /opt/homebrew/bin/cloudflared tunnel --config /Users/shranikjain/.cloudflared/config.yml run