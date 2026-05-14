#!/bin/bash
sudo systemctl stop my-financing-api nginx cloudflared-tunnel 2>/dev/null
sudo pkill -f "uvicorn app.main" 2>/dev/null
echo "stopped"
