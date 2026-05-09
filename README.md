# My_Financing

个人基金理财工具的初步框架：录入基金交易记录，通过 AKShare 更新开放式基金净值，自动计算组合收益，并接入 OpenAI-compatible 大模型接口生成每日理财观察报告。

> 说明：本项目只做个人数据分析和辅助决策，不自动交易，也不构成投资建议。

## 功能框架

- 持仓与交易：手动录入买入、卖出、分红、费用记录。
- 净值更新：后端通过 AKShare 拉取开放式基金最新净值。
- 收益计算：计算当前市值、累计投入、已实现现金流、浮动/总盈亏、收益率。
- 每日快照：保存每日组合快照，用于绘制资产走势。
- AI 建议：通过服务端环境变量配置大模型 API，生成风险提示和观察建议。
- AI 对话：静态前端通过后端流式接口进行实时对话，API Key 不进入浏览器。
- 免费部署：前端支持 GitHub Pages，后端支持 Render，定时任务支持 GitHub Actions。

## 目录结构

```text
.
├── backend/                 # FastAPI + AKShare + SQLite/Postgres
│   ├── app/
│   │   ├── api/             # REST API
│   │   ├── core/            # 配置
│   │   ├── db/              # SQLAlchemy 数据库
│   │   ├── jobs/            # 每日更新任务
│   │   └── services/        # AKShare、收益计算、AI 建议
│   └── requirements.txt
├── frontend/                # Vite + React + ECharts
├── .github/workflows/       # GitHub Pages 与每日 21:00 更新
└── render.yaml              # Render 后端部署配置
```

## 本地运行

### 后端

```bash
cd backend
conda env create -f environment.yml
conda activate my-financing
uvicorn app.main:app --reload
```

后端 API 文档：

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

## 核心环境变量

后端 `backend/.env`：

```bash
DATABASE_URL=sqlite:///./finance.sqlite3
FRONTEND_ORIGINS=http://localhost:5173
ADMIN_TOKEN=change-me
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
```

本地也可以不创建 `.env` 文件，直接在终端导出环境变量。`.env.example` 只是配置模板，不是 Python 运行环境。

前端 `frontend/.env`：

```bash
VITE_API_BASE=http://localhost:8000/api
```

## 免费部署建议

推荐组合：

- 前端：GitHub Pages
- 后端：Render Free Web Service
- 数据库：初期 SQLite，后续迁移 Supabase / Neon Postgres
- 定时任务：GitHub Actions 每天北京时间 21:00 调用后端接口

### GitHub Secrets

部署前端和定时更新需要配置这些 Secrets：

```text
VITE_API_BASE=https://你的后端域名/api
API_BASE_URL=https://你的后端域名
ADMIN_TOKEN=与你后端一致的 ADMIN_TOKEN
```

### Render

仓库根目录已经提供 `render.yaml`。在 Render 创建 Blueprint 后，需要补充：

- `FRONTEND_ORIGINS`：你的 GitHub Pages / Vercel 前端地址
- `LLM_API_KEY`：你的大模型 API Key
- `DATABASE_URL`：可先用 SQLite，长期建议换成 Postgres

## 初始使用流程

1. 启动后端和前端。
2. 在网页里录入第一笔基金买入记录。
3. 调用 `/api/jobs/daily-update` 更新净值并生成快照。
4. 调用 `/api/advice/daily` 生成 AI 建议。
5. 在网页的「AI 实时对话」里输入后端 `ADMIN_TOKEN`，即可围绕当前组合继续追问。
6. 后续交给 GitHub Actions 每天 21:00 自动执行。

网页顶部有两个不同动作：

- `刷新`：重新读取数据库里的持仓、快照、交易和 AI 报告。
- `更新净值`：使用 `ADMIN_TOKEN` 调用后端任务，从 AKShare 拉取最新净值并生成当天快照。

## 静态网页如何实现实时 AI 对话

GitHub Pages 这类静态托管不能安全地直接调用大模型 API，因为浏览器里的 Key 会被看到。本项目采用后端流式代理：

```text
GitHub Pages 静态前端
        |
        | POST /api/advice/chat
        v
FastAPI 后端
        |
        | LLM_API_KEY 环境变量
        v
OpenAI-compatible 大模型 API
```

前端只保存你手动输入的 `ADMIN_TOKEN`，用于证明这是你本人在使用；真正的大模型 API Key 只放在后端平台环境变量中。

## 下一步可扩展

- 支付宝交易记录导入。
- 定投计划表和定投提醒。
- 定投执行会在每日更新任务中处理：到期先生成待确认记录，拿到确认净值后自动生成买入交易。
- 历史净值补全与 XIRR 年化收益。
- 基金同类排名、回撤、夏普比率。
- Supabase Auth 或简单登录鉴权。
- 更细的 AI 提示词：结合风险偏好、目标期限、最大可承受回撤。
