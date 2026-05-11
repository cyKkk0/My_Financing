#!/bin/bash
set -e

echo "=== 1/5 安装 Nginx ==="
apt update && apt install -y nginx

echo "=== 2/5 部署 Nginx 配置 ==="
cp /home/cykkk/github_proj/My_Financing/deploy/nginx/my-financing.conf /etc/nginx/sites-available/my-financing
ln -sf /etc/nginx/sites-available/my-financing /etc/nginx/sites-enabled/my-financing
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== 3/5 部署 systemd 服务 ==="
cp /home/cykkk/github_proj/My_Financing/deploy/systemd/my-financing-api.service /etc/systemd/system/
cp /home/cykkk/github_proj/My_Financing/deploy/systemd/cloudflared-tunnel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now my-financing-api cloudflared-tunnel

echo "=== 4/5 设置每日定时任务 ==="
(crontab -u cykkk -l 2>/dev/null; echo "0 21 * * * curl -s -X POST -H 'X-Admin-Token: change-me' http://127.0.0.1:8000/api/jobs/daily-update") | crontab -u cykkk -

echo "=== 5/6 修复 Nginx 访问权限 ==="
chmod o+x /home/cykkk

echo "=== 6/6 停掉旧进程 ==="
pkill -f 'cloudflared tunnel' 2>/dev/null || true
pkill -f 'uvicorn app.main' 2>/dev/null || true

echo ""
echo "=== 部署完成 ==="
systemctl status nginx my-financing-api cloudflared-tunnel --no-pager
