# My_Financing

个人基金理财工具：录入基金交易和定投计划，通过 AKShare 更新开放式基金净值，按基金 T+N 规则确认交易，自动计算持仓收益、每日快照和组合表现，并通过 OpenAI-compatible 大模型生成观察建议和支持实时对话。

> 说明：本项目只做个人数据分析和辅助决策，不自动交易，也不构成投资建议。

## 功能概览

- 交易管理：支持买入、卖出、分红、费用记录，支持待确认交易状态。
- 定投管理：维护定投计划，每天 9:30 按计划生成定投执行记录。
- T+N 确认：每天 21:00 按基金确认规则确认所有待确认手动交易和定投执行。
- 净值更新：通过 AKShare 更新基金名称、近期净值和交易确认规则。
- 交易日历：维护数据库中的交易日历；日历距离当天不足 15 天时，自动补未来 3 个月。
- 收益计算：计算当前市值、投入成本、持仓收益、累计收益、确认净值口径收益和日盈亏。
- 每日快照：保存每日组合快照，用于绘制资产走势。
- AI 建议与对话：服务端保管大模型 API Key，前端通过后端代理生成每日观察和实时问答。
- 本机部署：Linux 服务器本机运行前后端，通过 Nginx + Cloudflare Tunnel 发布到 `myfinancing.asia`，定时任务使用 cron。

## 目录结构

```text
.
├── backend/                 # FastAPI + AKShare + SQLite/Postgres
│   ├── app/
│   │   ├── api/             # REST API
│   │   ├── core/            # 配置
│   │   ├── db/              # SQLAlchemy 数据库
│   │   ├── jobs/            # 每日更新和定投任务
│   │   └── services/        # AKShare、收益计算、AI、交易日历
│   └── requirements.txt
├── frontend/                # Vite + React + ECharts
└── deploy/                  # Nginx、systemd、Cloudflare Tunnel 与 cron 部署脚本
```

## 本地开发

### 后端

```bash
cd backend
conda env create -f environment.yml
conda activate my-financing
uvicorn app.main:app --reload
```

API 文档：

```text
http://localhost:8000/docs
```

### 前端

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

前端地址：

```text
http://localhost:5173
```

开发时也可以让前端 API 走同源代理：

```bash
VITE_API_BASE=/api npm run dev -- --host 127.0.0.1 --port 5173
```

## 环境变量

后端 `backend/.env`：

```bash
DATABASE_URL=sqlite:///./finance.sqlite3
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://myfinancing.asia
ADMIN_TOKEN=change-me
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
```

前端 `frontend/.env`：

```bash
VITE_API_BASE=http://localhost:8000/api
```

生产构建时推荐使用同源 API：

```bash
VITE_API_BASE=/api npm run build
```

## 正式部署

目标结构：

```text
https://myfinancing.asia
        |
        v
Cloudflare Tunnel
        |
        v
http://127.0.0.1:80  # Nginx: frontend/dist + /api -> FastAPI:8000
```

### Cloudflare 准备

1. 将 `myfinancing.asia` 加入 Cloudflare，并把域名 NS 切到 Cloudflare。
2. 在 Cloudflare Zero Trust 的 Tunnels 中创建 tunnel。
3. 添加 Public Hostname：
   - Hostname: `myfinancing.asia`
   - Path: 留空
   - Service: `http://127.0.0.1:80`
4. 复制 connector token。不要把 token 提交到代码或发到公开聊天里。

服务器需预先准备这些环境，部署脚本只会验证并使用它们，不会自动安装系统包、Node.js、cloudflared 或 conda 环境：

- Nginx、curl、openssl。
- Node.js >= 20 和 npm。
- cloudflared，并已能在命令行中执行。
- conda 环境 `my-financing`，可通过 `cd backend && conda env create -f environment.yml` 创建。

### 一键部署脚本

在 Linux 服务器项目根目录运行：

```bash
export CLOUDFLARED_TOKEN='你的 tunnel token'
sudo -E deploy/deploy-cloudflare.sh \
  --user cykkk \
  --domain myfinancing.asia
```

也可以通过参数传入 token：

```bash
sudo deploy/deploy-cloudflare.sh \
  --user cykkk \
  --domain myfinancing.asia \
  --cloudflared-token '你的 tunnel token'
```

如果你已经手动运行过 `sudo cloudflared service install <token>`，并且 Cloudflare connector 已显示 connected，可以让脚本复用现有 cloudflared 服务：

```bash
sudo deploy/deploy-cloudflare.sh \
  --user cykkk \
  --domain myfinancing.asia \
  --use-existing-cloudflared
```

脚本会自动完成：

- 验证系统环境：Nginx、curl、openssl、Node.js、npm、cloudflared、conda 环境。
- 写入 `backend/.env`：包含 `ADMIN_TOKEN`、`FRONTEND_ORIGINS` 等基础配置。
- 安装后端依赖：使用 conda 环境 `my-financing` 安装 `backend/requirements.txt`。
- 构建前端：以 `VITE_API_BASE=/api` 生成 `frontend/dist`。
- 配置 Nginx：静态托管前端，并将 `/api/` 反代到 `127.0.0.1:8000`。
- 配置守护进程：创建并启动 `my-financing-api.service`；如果未传 `--use-existing-cloudflared`，也会创建 `cloudflared-tunnel.service`。
- 启动自动任务：安装 21:00 和 9:30 的 cron 定时任务。

常用选项：

```bash
sudo -E deploy/deploy-cloudflare.sh \
  --app-dir /home/cykkk/github_proj/My_Financing \
  --user cykkk \
  --domain myfinancing.asia \
  --api-port 8000 \
  --conda-env my-financing
```

如果只想部署网站和守护进程，不安装定时任务：

```bash
sudo -E deploy/deploy-cloudflare.sh \
  --user cykkk \
  --domain myfinancing.asia \
  --no-scheduled-tasks
```

部署后检查：

```bash
systemctl status my-financing-api nginx cloudflared-tunnel --no-pager
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1/
```

## 代码更新发布

项目代码变化后，推荐使用**冷更新**：重新安装依赖、重新构建前端、重启后端服务、reload Nginx，并确认 Cloudflare Tunnel 和 cron 仍在运行。

原因：

- 前端是静态构建产物，代码变化后需要重新执行 `npm run build`。
- 后端运行在 uvicorn worker 进程中，Python 代码变化后需要重启 `my-financing-api.service`。
- Nginx 只托管静态文件和反代 `/api/`，配置不变时 reload 即可。
- Cloudflare Tunnel 通常不需要重启，但发布脚本会确保 `cloudflared-tunnel.service` 已启用并处于运行状态。
- 自动任务由 cron 触发后端接口，发布脚本会重新安装/更新 cron 块，避免迁移或配置漂移。

已有服务器上发布最新版本：

```bash
sudo deploy/update-release.sh \
  --user cykkk \
  --domain myfinancing.asia
```

脚本默认会执行 `git pull --ff-only`。如果代码已经在服务器工作区中，或者想发布当前未提交改动：

```bash
sudo deploy/update-release.sh \
  --user cykkk \
  --domain myfinancing.asia \
  --skip-git-pull
```

脚本会自动完成：

- 拉取最新代码，除非传入 `--skip-git-pull`。
- 更新后端 Python 依赖，使用 conda 环境 `my-financing`。
- 重新构建前端 `frontend/dist`。
- 检查并 reload Nginx。
- 重启 `my-financing-api.service`。
- 确认 `cloudflared-tunnel.service` 已启用并运行。
- 安装/更新 21:00 和 9:30 的 cron 自动任务。
- 检查本地 API 健康状态和 Nginx 首页。

如果只想更新网站和服务，不碰自动任务：

```bash
sudo deploy/update-release.sh \
  --user cykkk \
  --domain myfinancing.asia \
  --conda-env my-financing \
  --no-scheduled-tasks
```

## 自动任务

完整部署脚本会自动调用 [deploy/install-scheduled-tasks.sh](deploy/install-scheduled-tasks.sh)。也可以单独安装或更新定时任务：

```bash
sudo deploy/install-scheduled-tasks.sh \
  --user cykkk \
  --api-base http://127.0.0.1:8000
```

安装的任务：

```text
0 21 * * * POST /api/jobs/daily-update
30 9 * * * POST /api/jobs/dca-check
```

任务职责：

- 每天北京时间 21:00：更新基金净值，按 T+N 规则确认所有待确认交易，确认待确认定投执行，生成快照并更新收益；如果数据库里的交易日历距离当天不足 15 天，则补充未来 3 个月交易日历。
- 每天北京时间 9:30：依据定投计划创建当天定投执行记录，不做确认。

脚本会优先读取环境变量 `ADMIN_TOKEN`，否则读取 `backend/.env`。移除任务：

```bash
sudo deploy/install-scheduled-tasks.sh --user cykkk --uninstall
```

## 当前机器临时测试

如果在 macOS 或没有 systemd 的机器上测试 Cloudflare Tunnel，不要运行正式部署脚本。可以临时将 Cloudflare Public Hostname 的 Service 改成：

```text
http://127.0.0.1:5173
```

然后启动后端和前端：

```bash
cd backend
conda activate my-financing
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
VITE_API_BASE=/api npm run dev -- --host 127.0.0.1 --port 5173
```

正式迁移到 Linux 服务器后，再把 Cloudflare Public Hostname 的 Service 改回：

```text
http://127.0.0.1:80
```

## 初始使用流程

1. 启动或部署前后端。
2. 在网页里录入基金交易或定投计划。
3. 手动调用 `/api/jobs/daily-update` 可立即更新净值、确认交易并生成快照。
4. 可调用 `/api/advice/daily` 生成 AI 建议。
5. 在网页的「AI 实时对话」里输入后端 `ADMIN_TOKEN`，即可围绕当前组合继续追问。
6. 后续交给 cron 自动执行每日任务。

网页顶部有两个不同动作：

- `刷新`：重新读取数据库里的持仓、快照、交易和 AI 报告。
- `更新净值`：使用 `ADMIN_TOKEN` 调用后端任务，从 AKShare 拉取最新净值、确认交易并生成当天快照。

## AI 对话如何保护 Key

浏览器不能安全地直接调用大模型 API，因为 Key 会被看到。本项目采用后端流式代理：

```text
前端
  |
  | POST /api/advice/chat
  v
FastAPI 后端
  |
  | LLM_API_KEY 环境变量
  v
OpenAI-compatible 大模型 API
```

前端只保存你手动输入的 `ADMIN_TOKEN`，用于证明这是你本人在使用；真正的大模型 API Key 只放在后端环境变量中。

## 下一步可扩展

- 支付宝交易记录导入增强。
- 历史净值补全与 XIRR 年化收益。
- 基金同类排名、回撤、夏普比率。
- 简单登录鉴权或 Cloudflare Access。
- 更细的 AI 提示词：结合风险偏好、目标期限、最大可承受回撤。
