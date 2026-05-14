import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import * as echarts from "echarts";
import { Activity, ArrowLeft, BarChart3, Brain, CircleDollarSign, Clock3, LogIn, LogOut, Plus, RefreshCw, TrendingUp } from "lucide-react";

import {
  createDcaPlan,
  createTransaction,
  deleteDcaExecution,
  deleteDcaPlan,
  updateDcaPlan,
  deleteTransaction,
  deleteTransactionsBatch,
  getFundEstimate,
  getFundNav,
  getFundPerformance,
  getLatestAdvice,
  getPortfolioSummary,
  getSnapshots,
  getAdminMe,
  importAlipayPdf,
  listDcaExecutions,
  listDcaPlans,
  listTransactionsPage,
  loginAdmin,
  logoutAdmin,
  runDailyUpdate,
  streamAdviceChat,
} from "./api";
import "./styles.css";

const emptySummary = {
  market_value: "0",
  total_invested: "0",
  realized_cash: "0",
  profit: "0",
  profit_rate: "0",
  holding_profit: "0",
  cumulative_profit: "0",
  holdings: [],
};

const ADMIN_SESSION_KEY = "my-financing-admin-session";

function readStoredAdminSession() {
  try {
    const raw = sessionStorage.getItem(ADMIN_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    sessionStorage.removeItem(ADMIN_SESSION_KEY);
    return null;
  }
}

function App() {
  const [summary, setSummary] = useState(emptySummary);
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotPeriod, setSnapshotPeriod] = useState("month");
  const [recentTransactions, setRecentTransactions] = useState([]);
  const [dcaPlans, setDcaPlans] = useState([]);
  const [dcaExecutions, setDcaExecutions] = useState([]);
  const [page, setPage] = useState("dashboard");
  const [selectedFund, setSelectedFund] = useState(null);
  const [advice, setAdvice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatingNav, setUpdatingNav] = useState(false);
  const [error, setError] = useState("");
  const [errorTitle, setErrorTitle] = useState("数据读取失败");
  const [updateResult, setUpdateResult] = useState(null);
  const [adminSession, setAdminSession] = useState(() => readStoredAdminSession());
  const adminToken = adminSession?.token || "";
  const isAdmin = Boolean(adminToken);

  async function loadData() {
    setLoading(true);
    setError("");
    setErrorTitle("数据读取失败");
    try {
      const [summaryData, snapshotData, transactionData, dcaPlanData, dcaExecutionData, adviceData] = await Promise.all([
        getPortfolioSummary(),
        getSnapshots(snapshotPeriod),
        listTransactionsPage({ page: 1, pageSize: 5 }),
        listDcaPlans(),
        listDcaExecutions(),
        getLatestAdvice(),
      ]);
      setSummary(summaryData || emptySummary);
      setSnapshots(snapshotData || []);
      setRecentTransactions(transactionData?.items || []);
      setDcaPlans(dcaPlanData || []);
      setDcaExecutions(dcaExecutionData || []);
      setAdvice(adviceData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (!adminToken) return undefined;
    let cancelled = false;
    getAdminMe(adminToken)
      .then((me) => {
        if (cancelled) return;
        const nextSession = { ...adminSession, username: me.username, expires_at: me.expires_at };
        setAdminSession(nextSession);
        sessionStorage.setItem(ADMIN_SESSION_KEY, JSON.stringify(nextSession));
      })
      .catch(() => {
        if (cancelled) return;
        sessionStorage.removeItem(ADMIN_SESSION_KEY);
        setAdminSession(null);
      });
    return () => {
      cancelled = true;
    };
  }, [adminToken]);

  useEffect(() => {
    getSnapshots(snapshotPeriod).then(setSnapshots).catch(() => {});
  }, [snapshotPeriod]);

  async function updateNavs() {
    if (!adminToken) {
      setErrorTitle("需要管理权限");
      setError("请先登录管理模式。");
      return;
    }
    setUpdatingNav(true);
    setError("");
    setErrorTitle("更新净值失败");
    setUpdateResult(null);
    try {
      const result = await runDailyUpdate(adminToken);
      setUpdateResult(result);
      await loadData();
    } catch (err) {
      if (err.status === 401) {
        sessionStorage.removeItem(ADMIN_SESSION_KEY);
        setAdminSession(null);
        setError("登录已失效，请重新进入管理模式。");
      } else {
        setError(err.message);
      }
    } finally {
      setUpdatingNav(false);
    }
  }

  function handleLoggedIn(session) {
    setAdminSession(session);
    sessionStorage.setItem(ADMIN_SESSION_KEY, JSON.stringify(session));
    setError("");
  }

  async function handleLogout() {
    const token = adminToken;
    sessionStorage.removeItem(ADMIN_SESSION_KEY);
    setAdminSession(null);
    if (token) {
      try {
        await logoutAdmin(token);
      } catch {
        // Session is already cleared locally; server-side revoke is best effort.
      }
    }
  }

  if (page === "history") {
    return (
      <HistoryPage
        isAdmin={isAdmin}
        adminToken={adminToken}
        onBack={async () => {
          setPage("dashboard");
          await loadData();
        }}
        onChanged={loadData}
      />
    );
  }

  if (page === "fund-detail" && selectedFund) {
    return (
      <FundDetailPage
        holding={selectedFund}
        onBack={async () => {
          setPage("dashboard");
          setSelectedFund(null);
          await loadData();
        }}
      />
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Fund Portfolio</p>
          <h1>My Financing</h1>
        </div>
        <div className="topbar-actions">
          <button className="icon-button text-button" onClick={loadData} title="刷新页面数据">
            <RefreshCw size={18} />
            刷新
          </button>
          {isAdmin && (
            <button className="icon-button text-button" onClick={updateNavs} disabled={updatingNav} title="从 AKShare 更新基金净值">
              <Activity size={18} />
              {updatingNav ? "更新中" : "更新净值"}
            </button>
          )}
          <AdminModeControl session={adminSession} onLoggedIn={handleLoggedIn} onLogout={handleLogout} />
        </div>
      </header>

      {error && <div className="alert">{errorTitle}：{error}</div>}
      {updateResult && <UpdateResult result={updateResult} />}

      <section className="metric-grid">
        <Metric icon={<CircleDollarSign />} label="最新市值" value={money(summary.market_value)} hint={summary.latest_nav_date ? `截至 ${summary.latest_nav_date}` : ""} />
        <Metric icon={<TrendingUp />} label="最新持有收益" value={money(summary.holding_profit ?? summary.profit)} tone={Number(summary.holding_profit ?? summary.profit) >= 0 ? "gain" : "loss"} />
        <Metric icon={<Activity />} label="最新累计收益" value={money(summary.cumulative_profit ?? summary.profit)} tone={Number(summary.cumulative_profit ?? summary.profit) >= 0 ? "gain" : "loss"} />
        <Metric icon={<BarChart3 />} label="持仓成本" value={money(summary.total_invested)} />
      </section>

      <section className="dashboard-grid">
        <Panel title="资产走势">
          <PortfolioChart snapshots={snapshots} period={snapshotPeriod} onPeriodChange={setSnapshotPeriod} />
        </Panel>
        <Panel title="持仓分布">
          <HoldingChart holdings={summary.holdings} />
        </Panel>
      </section>

      <section className="content-grid equal-height">
        <Panel title="持仓明细">
          <HoldingsTable
            holdings={summary.holdings}
            onOpenFund={(holding) => {
              setSelectedFund(holding);
              setPage("fund-detail");
            }}
          />
        </Panel>
        <Panel title="新增交易">
          {isAdmin ? <TransactionForm onCreated={loadData} adminToken={adminToken} /> : <GuestNotice size="tall" text="访客模式下只能查看数据。进入管理模式后可新增交易。" />}
        </Panel>
      </section>

      <section className="content-grid" style={{marginTop: "16px"}}>
        <Panel title="定投计划">
          <div className="scroll-panel"><DcaPlanList plans={dcaPlans} loading={loading} onChanged={loadData} isAdmin={isAdmin} adminToken={adminToken} /></div>
        </Panel>
        <Panel title="定投执行">
          <div className="scroll-panel"><DcaExecutionList executions={dcaExecutions} loading={loading} isAdmin={isAdmin} adminToken={adminToken} onChanged={loadData} /></div>
        </Panel>
      </section>

      <section style={{marginTop: "16px"}}>
        <Panel
          title={
            <span className="panel-title-row">
              最近交易
              <button className="ghost-button compact" type="button" onClick={() => setPage("history")}>查看全部</button>
            </span>
          }
        >
          <RecentTransactionList transactions={recentTransactions} loading={loading} onOpenHistory={() => setPage("history")} />
        </Panel>
      </section>

      <section style={{marginTop: "16px"}}>
        <Panel title="AI 实时对话">
          <ChatPanel advice={advice} isAdmin={isAdmin} adminToken={adminToken} />
        </Panel>
      </section>
    </main>
  );
}

function UpdateResult({ result }) {
  const updatedNavs = (result.updated_navs || "").split(";").filter(Boolean);
  return (
    <div className="update-result">
      <strong>净值更新完成：{result.updated_funds} 只基金</strong>
      {result.skipped_funds && <span>跳过：{result.skipped_funds}</span>}
      {updatedNavs.length > 0 && (
        <div className="updated-nav-list">
          {updatedNavs.map((item) => {
            const [code, navDate, unitNav, source] = item.split(":");
            return (
              <span key={item}>
                {code} · {navDate} · {unitNav} · {source}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Metric({ icon, label, value, tone = "", hint = "" }) {
  return (
    <article className="metric">
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
      {hint && <small>{hint}</small>}
    </article>
  );
}

function Panel({ title, children }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function AdminModeControl({ session, onLoggedIn, onLogout }) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [form, setForm] = useState({ username: "cykkk", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await loginAdmin(form);
      onLoggedIn(data);
      setForm((current) => ({ ...current, password: "" }));
      setLoginOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (session?.token) {
    return (
      <div className="admin-mode">
        <span>管理模式 · {session.username}</span>
        <button className="icon-button text-button" type="button" onClick={onLogout} title="退出管理模式">
          <LogOut size={18} />
          退出
        </button>
      </div>
    );
  }

  return (
    <div className="admin-mode">
      <span>访客模式</span>
      {!loginOpen ? (
        <button className="icon-button text-button" type="button" onClick={() => setLoginOpen(true)} title="进入管理模式">
          <LogIn size={18} />
          管理登录
        </button>
      ) : (
        <form className="admin-login-form" onSubmit={submit}>
          <input
            value={form.username}
            onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
            placeholder="用户名"
            autoComplete="username"
          />
          <input
            type="password"
            value={form.password}
            onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            placeholder="密码"
            autoComplete="current-password"
          />
          <button className="secondary-button compact" type="submit" disabled={busy || !form.username || !form.password}>
            {busy ? "登录中" : "登录"}
          </button>
          <button className="ghost-button compact" type="button" onClick={() => { setLoginOpen(false); setError(""); }}>
            取消
          </button>
          {error && <span className="auth-error">{error}</span>}
        </form>
      )}
    </div>
  );
}

function GuestNotice({ text, size = "" }) {
  return <div className={`guest-notice ${size}`}>{text}</div>;
}

function HistoryPage({ onBack, onChanged, isAdmin, adminToken }) {
  const [filters, setFilters] = useState({ fundCode: "", transactionType: "", startDate: "", endDate: "" });
  const [transactions, setTransactions] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pageSize: 10, total: 0, totalPages: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadTransactions(nextFilters = filters, page = pagination.page) {
    setLoading(true);
    setError("");
    try {
      const data = await listTransactionsPage({ ...nextFilters, page, pageSize: 10 });
      setTransactions(data.items || []);
      setPagination({
        page: data.page,
        pageSize: data.page_size,
        total: data.total,
        totalPages: data.total_pages,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTransactions();
  }, []);

  async function applyFilters(nextFilters) {
    setFilters(nextFilters);
    await loadTransactions(nextFilters, 1);
  }

  async function handleChanged() {
    await loadTransactions(filters, pagination.page);
    await onChanged();
  }

  async function goToPage(nextPage) {
    await loadTransactions(filters, nextPage);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Transactions</p>
          <h1>历史交易</h1>
        </div>
        <button className="icon-button text-button" type="button" onClick={onBack}>
          返回主页面
        </button>
      </header>
      {error && <div className="alert">交易读取失败：{error}</div>}
      <Panel title="全部交易">
        {isAdmin && <AlipayImportPanel onImported={handleChanged} adminToken={adminToken} />}
        <TransactionList
          transactions={transactions}
          loading={loading}
          filters={filters}
          onFilter={applyFilters}
          onChanged={handleChanged}
          pagination={pagination}
          onPageChange={goToPage}
          isAdmin={isAdmin}
          adminToken={adminToken}
        />
      </Panel>
    </main>
  );
}

function AlipayImportPanel({ onImported, adminToken }) {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function handleFileChange(event) {
    setFile(event.target.files[0] || null);
    setResult(null);
    setError("");
  }

  async function runImport(dryRun) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const data = await importAlipayPdf(file, dryRun, adminToken);
      setResult(data);
      if (!dryRun) {
        await onImported();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="import-panel">
      <label>
        支付宝 PDF 文件
        <input type="file" accept=".pdf" onChange={handleFileChange} />
      </label>
      <div className="import-actions">
        <button className="secondary-button" type="button" disabled={busy || !file} onClick={() => runImport(true)}>
          解析预览
        </button>
        <button className="primary-button inline-primary" type="button" disabled={busy || !file} onClick={() => runImport(false)}>
          确认导入
        </button>
      </div>
      {error && <p className="chat-error">{error}</p>}
      {result && (
        <div className="calculation-note">
          解析 {result.parsed} 条，新增 {result.created} 条，更新 {result.updated || 0} 条，跳过重复 {result.skipped} 条，失败 {result.failed} 条。
        </div>
      )}
    </div>
  );
}

const PERIOD_OPTIONS = [
  { value: "week", label: "近一周" },
  { value: "month", label: "近一月" },
  { value: "3months", label: "近三月" },
  { value: "6months", label: "近半年" },
  { value: "year", label: "近一年" },
  { value: "all", label: "全部" },
];

function PortfolioChart({ snapshots, period, onPeriodChange }) {
  const ref = useChart((chart) => {
    const data = snapshots.length
      ? snapshots
      : [{ date: "暂无快照", market_value: 0, total_invested: 0, profit: 0 }];
    chart.setOption({
      grid: { left: 42, right: 60, top: 26, bottom: 36 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: data.map((item) => item.date) },
      yAxis: [
        { type: "value", name: "金额", nameTextStyle: { fontSize: 11 } },
        { type: "value", name: "收益", nameTextStyle: { fontSize: 11 } },
      ],
      series: [
        {
          name: "市值",
          type: "line",
          smooth: false,
          data: data.map((item) => Number(item.market_value)),
          areaStyle: { opacity: 0.08 },
          color: "#2563eb",
        },
        {
          name: "投入",
          type: "line",
          smooth: false,
          data: data.map((item) => Number(item.total_invested)),
          color: "#10b981",
        },
        {
          name: "累计收益",
          type: "line",
          yAxisIndex: 1,
          smooth: false,
          data: data.map((item) => Number(item.cumulative_profit ?? item.profit)),
          color: "#f59e0b",
        },
      ],
    });
  }, [snapshots]);
  return (
    <div>
      <div className="period-selector">
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            className={`period-btn ${period === opt.value ? "active" : ""}`}
            onClick={() => onPeriodChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="chart" ref={ref} />
    </div>
  );
}

function HoldingChart({ holdings }) {
  const ref = useChart((chart) => {
    const data = holdings.map((item) => ({
      name: item.fund_name,
      value: Number(item.market_value),
    }));
    chart.setOption({
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["46%", "72%"],
          center: ["50%", "50%"],
          data: data.length ? data : [{ name: "暂无持仓", value: 1 }],
          label: { formatter: "{b}" },
          color: ["#2563eb", "#10b981", "#f97316", "#dc2626", "#7c3aed", "#0891b2"],
        },
      ],
    });
  }, [holdings]);
  return <div className="chart" ref={ref} />;
}

function _renderStat(label, value) {
  const isReturn = label === "区间收益";
  const num = Number(value);
  return (
    <div className="perf-stat" key={label}>
      <span>{label}</span>
      <strong className={isReturn ? (num >= 0 ? "gain" : "loss") : ""}>{value}{isReturn ? "%" : ""}</strong>
    </div>
  );
}

function formatPerfReturn(data) {
  if (!data || data.length < 2) return "0.00";
  // Use the last cumulative_return from the endpoint (already cost-basis aware)
  const last = data[data.length - 1];
  if (last.cumulative_return != null) return (Number(last.cumulative_return) * 100).toFixed(2);
  return "0.00";
}

function FundDetailPage({ holding, onBack }) {
  const [range, setRange] = useState("month");
  const [chartData, setChartData] = useState([]);
  const [estimate, setEstimate] = useState(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [chartError, setChartError] = useState("");
  const [estimateError, setEstimateError] = useState("");
  const [now, setNow] = useState(() => new Date());
  const fundCode = holding.fund_code;
  const ranges = [
    { key: "week", label: "近一周" },
    { key: "month", label: "近一月" },
    { key: "3month", label: "近三月" },
    { key: "6month", label: "近半年" },
    { key: "year", label: "近一年" },
  ];

  const loadEstimate = React.useCallback(async () => {
    setEstimateLoading(true);
    setEstimateError("");
    try {
      const data = await getFundEstimate(fundCode);
      setEstimate(data);
    } catch (err) {
      setEstimate(null);
      setEstimateError(err.message);
    } finally {
      setEstimateLoading(false);
    }
  }, [fundCode]);

  useEffect(() => {
    let cancelled = false;
    async function loadChart() {
      setChartLoading(true);
      setChartError("");
      try {
        const data = await getFundPerformance(fundCode, range);
        if (!cancelled) setChartData(data || []);
      } catch (err) {
        if (!cancelled) setChartError(err.message);
      } finally {
        if (!cancelled) setChartLoading(false);
      }
    }
    loadChart();
    return () => { cancelled = true; };
  }, [fundCode, range]);

  useEffect(() => {
    loadEstimate();
  }, [loadEstimate]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const estimatedNav = Number(estimate?.estimated_nav || 0);
  const latestChartPoint = chartData.length ? chartData[chartData.length - 1] : null;
  const latestOfficialNav = Number(latestChartPoint?.unit_nav || estimate?.published_nav || holding.latest_nav || 0);
  const latestOfficialNavDate = latestChartPoint?.nav_date || holding.nav_date || "-";
  const shares = Number(holding.shares || 0);
  const estimatedMarketValue = estimatedNav > 0 ? estimatedNav * shares : null;
  const estimatedDailyPnl = estimatedNav > 0 && latestOfficialNav > 0 ? (estimatedNav - latestOfficialNav) * shares : null;
  const estimateTone = Number(estimate?.estimated_growth_rate || 0) >= 0 ? "gain" : "loss";
  const estimateUnavailable = estimate?.source === "unavailable";
  const estimateHint = estimateUnavailable
    ? estimate.message || "该基金暂无盘中估值"
    : estimate?.estimate_date
      ? `估值日 ${estimate.estimate_date}`
      : "来自盘中估值源";

  const chartRef = useChart((chart) => {
    const points = (chartData || []).map((item) => ({
      date: item.nav_date,
      nav: Number(item.unit_nav),
      official: true,
    }));
    const estimateDate = estimate?.estimate_date || new Date().toISOString().slice(0, 10);
    if (estimatedNav > 0) {
      const existing = points.find((item) => item.date === estimateDate);
      if (existing) {
        existing.estimate = estimatedNav;
      } else {
        points.push({ date: estimateDate, nav: null, estimate: estimatedNav, official: false });
      }
    }
    points.sort((a, b) => a.date.localeCompare(b.date));

    if (!points.length) {
      chart.setOption({
        title: { text: "暂无净值数据", left: "center", top: "center", textStyle: { color: "#94a3b8", fontSize: 14 } },
      });
      return;
    }

    const dates = points.map((item) => item.date);
    const officialNavs = points.map((item) => item.official ? item.nav : null);
    const estimateNavs = points.map((item) => item.estimate ?? null);
    const values = points.flatMap((item) => [item.nav, item.estimate]).filter((value) => value != null && Number.isFinite(value));
    const minNav = Math.min(...values);
    const maxNav = Math.max(...values);
    const padding = Math.max((maxNav - minNav) * 0.18, 0.01);

    chart.setOption({
      grid: { left: 48, right: 24, top: 32, bottom: 42 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#ffffff",
        borderColor: "#e8ecf2",
        borderWidth: 1,
        textStyle: { color: "#1a1a2e", fontSize: 13 },
        formatter: function (params) {
          const date = params[0].axisValue;
          let tip = `<div style="font-size:12px;color:#94a3b8;margin-bottom:4px">${date}</div>`;
          params.forEach((p) => {
            if (p.value == null || p.value === "-") return;
            tip += `<div>${p.marker} ${p.seriesName} <b style="margin-left:8px">${Number(p.value).toFixed(4)}</b></div>`;
          });
          return tip;
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e8ecf2" } },
        axisTick: { show: false },
        axisLabel: { color: "#94a3b8", fontSize: 11, formatter: (v) => v.slice(5).replace("-", "/") },
      },
      yAxis: {
        type: "value",
        min: minNav - padding,
        max: maxNav + padding,
        axisLabel: { color: "#64748b", fontSize: 11, formatter: (v) => Number(v).toFixed(3) },
        splitLine: { lineStyle: { color: "#f1f5f9", type: "dashed" } },
      },
      series: [
        {
          name: "单位净值",
          type: "line",
          data: officialNavs,
          symbol: "none",
          connectNulls: false,
          lineStyle: { color: "#2563eb", width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(37,99,235,0.12)" },
              { offset: 1, color: "rgba(37,99,235,0.01)" },
            ]),
          },
        },
        {
          name: "盘中估值",
          type: "scatter",
          data: estimateNavs,
          symbolSize: 12,
          itemStyle: { color: "#f97316" },
        },
      ],
    });
  }, [chartData, estimate, estimatedNav]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <button className="ghost-button compact back-button" type="button" onClick={onBack}>
            <ArrowLeft size={16} />
            返回
          </button>
          <p className="eyebrow">Pre-close Watch</p>
          <h1>{holding.fund_name}</h1>
          <p className="fund-detail-subtitle">{fundCode} · 持有 {number(holding.shares)} 份</p>
        </div>
        <div className="topbar-actions">
          <button className="icon-button text-button" type="button" onClick={loadEstimate} disabled={estimateLoading} title="刷新盘中估值">
            <RefreshCw size={18} />
            {estimateLoading ? "刷新中" : "刷新估值"}
          </button>
        </div>
      </header>

      <section className="preclose-grid">
        <Metric icon={<Activity />} label="当前估值" value={estimate?.estimated_nav ? Number(estimate.estimated_nav).toFixed(4) : "-"} hint={estimateHint} />
        <Metric icon={<TrendingUp />} label="估算涨跌幅" value={estimate?.estimated_growth_rate != null ? percentPoint(estimate.estimated_growth_rate) : "-"} tone={estimateTone} />
        <Metric icon={<CircleDollarSign />} label="估算市值" value={estimatedMarketValue != null ? money(estimatedMarketValue) : "-"} />
        <Metric icon={<Clock3 />} label="15:00 前提交" value={countdownToMarketClose(now)} hint="普通场外基金通常以 15:00 为交易日切换点" />
      </section>

      {estimateError && <div className="alert">估值读取失败：{estimateError}</div>}

      <section className="fund-detail-grid">
        <Panel
          title={
            <span className="panel-title-row">
              净值波动
              <div className="range-toggle">
                {ranges.map((r) => (
                  <button key={r.key} className={range === r.key ? "active" : ""} type="button" onClick={() => setRange(r.key)}>
                    {r.label}
                  </button>
                ))}
              </div>
            </span>
          }
        >
          {chartError && <p className="chat-error">{chartError}</p>}
          {chartLoading && <EmptyState text="正在加载净值走势..." />}
          <div className="chart chart-tall" ref={chartRef} />
          {chartData.length > 1 && (
            <div className="perf-stats">
              {_renderStat("区间收益", formatPerfReturn(chartData))}
              {_renderStat("最新净值", Number(chartData[chartData.length - 1].unit_nav).toFixed(4))}
              {_renderStat("最高净值", Math.max(...chartData.map(d => Number(d.unit_nav))).toFixed(4))}
              {_renderStat("最低净值", Math.min(...chartData.map(d => Number(d.unit_nav))).toFixed(4))}
            </div>
          )}
        </Panel>

        <Panel title="赎回参考">
          <div className="decision-list">
            <DecisionRow label="上一净值" value={latestOfficialNav ? latestOfficialNav.toFixed(4) : "-"} />
            <DecisionRow label="净值日期" value={latestOfficialNavDate} />
            <DecisionRow label="持有收益" value={money(holding.holding_profit ?? holding.profit)} tone={Number(holding.holding_profit ?? holding.profit) >= 0 ? "gain" : "loss"} />
            <DecisionRow label="持有收益率" value={percent(holding.holding_profit_rate ?? holding.profit_rate)} tone={Number(holding.holding_profit_rate ?? holding.profit_rate) >= 0 ? "gain" : "loss"} />
            <DecisionRow label="估算当日盈亏" value={estimatedDailyPnl != null ? money(estimatedDailyPnl) : estimateUnavailable ? "暂无估值" : "-"} tone={Number(estimatedDailyPnl || 0) >= 0 ? "gain" : "loss"} />
            <DecisionRow label="估算偏差" value={estimate?.estimate_deviation != null ? Number(estimate.estimate_deviation).toFixed(4) : "-"} />
          </div>
          <p className="decision-note">盘中估值仅用于临近收盘前判断，最终成交净值以基金公司晚间公布为准。</p>
        </Panel>
      </section>
    </main>
  );
}

function DecisionRow({ label, value, tone = "" }) {
  return (
    <div className="decision-row">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function HoldingsTable({ holdings, onOpenFund }) {
  const [estimates, setEstimates] = useState({});
  const estimateCodes = holdings.map((item) => item.fund_code).join("|");

  useEffect(() => {
    if (!holdings.length) {
      setEstimates({});
      return undefined;
    }

    let cancelled = false;
    async function loadEstimates() {
      const entries = await Promise.all(
        holdings.map(async (item) => {
          try {
            return [item.fund_code, await getFundEstimate(item.fund_code)];
          } catch (err) {
            return [item.fund_code, { source: "error", message: err.message }];
          }
        })
      );
      if (!cancelled) setEstimates(Object.fromEntries(entries));
    }

    loadEstimates();
    return () => {
      cancelled = true;
    };
  }, [estimateCodes]);

  if (!holdings.length) return <EmptyState text="录入第一笔交易后，这里会显示持仓、成本和收益。" />;
  return (
    <div className="table-wrap holdings-window">
      <table>
        <thead>
          <tr>
            <th>基金</th>
            <th>份额</th>
            <th>净值</th>
            <th>市值</th>
            <th>当日盈亏</th>
            <th>持有收益</th>
            <th>累计收益</th>
            <th>持有收益率</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((item) => {
            const estimatedDailyPnl = estimateDailyPnlForHolding(item, estimates[item.fund_code]);
            return (
              <tr key={item.fund_code}>
                <td className="fund-cell">
                  <button className="fund-link" type="button" onClick={() => onOpenFund?.(item)} title="查看收盘前决策看板">
                    {item.fund_name}
                  </button>
                  <span>{item.fund_code}</span>
                </td>
                <td>{number(item.shares)}</td>
                <td><strong>{item.latest_nav || "-"}</strong></td>
                <td className="market-value-cell">
                  <strong>{money(item.market_value)}</strong>
                  <small>未确认 {money(item.unconfirmed_amount || 0)}</small>
                </td>
                <td className={Number(item.daily_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                  <strong>{item.daily_pnl != null ? money(item.daily_pnl) : "-"}</strong>
                  <small className={estimatedDailyPnl.className}>今日预估 {estimatedDailyPnl.text}</small>
                </td>
                <td className={Number(item.holding_profit ?? item.profit) >= 0 ? "gain" : "loss"}>
                  <strong>{money(item.holding_profit ?? item.profit)}</strong>
                </td>
                <td className={Number(item.cumulative_profit ?? item.profit) >= 0 ? "gain" : "loss"}>
                  <strong>{money(item.cumulative_profit ?? item.profit)}</strong>
                </td>
                <td className={Number(item.holding_profit_rate ?? item.profit_rate) >= 0 ? "gain" : "loss"}>
                  <strong>{percent(item.holding_profit_rate ?? item.profit_rate)}</strong>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function estimateDailyPnlForHolding(item, estimate) {
  if (!estimate) return { text: "加载中", className: "estimated-daily-pnl" };
  if (estimate.source === "unavailable") return { text: "暂无", className: "estimated-daily-pnl muted" };
  if (estimate.source === "error") return { text: "读取失败", className: "estimated-daily-pnl muted" };

  const estimatedNav = Number(estimate.estimated_nav || 0);
  const baseNav = Number(estimate.published_nav || item.latest_nav || 0);
  const shares = Number(item.shares || 0);
  if (estimatedNav <= 0 || baseNav <= 0 || shares <= 0) {
    return { text: "暂无", className: "estimated-daily-pnl muted" };
  }

  const value = (estimatedNav - baseNav) * shares;
  return {
    text: money(value),
    className: `estimated-daily-pnl ${value >= 0 ? "gain" : "loss"}`,
  };
}

function TransactionForm({ onCreated, adminToken }) {
  const [form, setForm] = useState({
    fund_code: "",
    trade_date: new Date().toISOString().slice(0, 10),
    initiated_time: "",
    transaction_type: "buy",
    amount: "",
    shares: "",
    nav: "",
    fee: "",
    dca_end_date: "",
    frequency: "monthly",
    frequency_day: "",
    note: "",
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [navStatus, setNavStatus] = useState("");
  const [lastEdited, setLastEdited] = useState("amount");
  const calculated = calculateTransactionFields(form, lastEdited);

  useEffect(() => {
    const fundCode = normalizeFundCode(form.fund_code);
    const shouldFetch =
      /^\d{6}$/.test(fundCode) &&
      form.trade_date &&
      !form.nav &&
      form.transaction_type !== "dividend" &&
      form.transaction_type !== "fee" &&
      form.transaction_type !== "dca" &&
      form.transaction_type !== "buy" &&
      form.transaction_type !== "sell";
    if (!shouldFetch) return undefined;

    let cancelled = false;
    setNavStatus("正在获取交易日净值...");
    const timer = window.setTimeout(async () => {
      try {
        const nav = await getFundNav(fundCode, form.trade_date);
        if (cancelled) return;
        setForm((current) => {
          if (current.nav || normalizeFundCode(current.fund_code) !== fundCode) return current;
          return { ...current, nav: nav.unit_nav };
        });
        setNavStatus(`已使用 ${nav.nav_date} 的单位净值 ${nav.unit_nav}`);
      } catch {
        if (!cancelled) {
          setNavStatus("未找到交易日净值，保存后将标记为待确认。");
        }
      }
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [form.fund_code, form.trade_date, form.nav, form.transaction_type]);

  useEffect(() => {
    const fundCode = normalizeFundCode(form.fund_code);
    if (
      /^\d{6}$/.test(fundCode) &&
      form.trade_date &&
      (form.transaction_type === "buy" || form.transaction_type === "sell")
    ) {
      const timeHint = form.initiated_time && form.initiated_time >= "15:00" ? "（15:00后T日顺延）" : "";
      setNavStatus(`将使用T日${timeHint}的单位净值，若净值未公布则标记为待确认。`);
    }
  }, [form.fund_code, form.trade_date, form.initiated_time, form.transaction_type]);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setSaveError("");
    try {
      const fundCode = normalizeFundCode(form.fund_code);
      if (form.transaction_type === "dca") {
        await createDcaPlan({
          fund_code: fundCode,
          amount: form.amount || "0",
          fee: form.fee || "0",
          start_date: form.trade_date,
          end_date: form.dca_end_date || null,
          frequency: form.frequency,
          day_of_month: form.frequency_day ? Number(form.frequency_day) : null,
        }, adminToken);
      } else {
        await createTransaction({
          ...form,
          fund_code: fundCode,
          trade_date: undefined,
          amount: calculated.amount || "0",
          shares: calculated.shares || "0",
          nav: form.nav || null,
          fee: form.fee || "0",
          initiated_at: `${form.trade_date}T${form.initiated_time || "00:00:00"}`,
        }, adminToken);
      }
      setForm((current) => ({ ...current, amount: "", shares: "", nav: "", fee: "", dca_end_date: "", initiated_time: "", note: "" }));
      await onCreated();
    } catch (err) {
      const msg = typeof err === "string" ? err : err?.message || JSON.stringify(err) || "保存失败，请稍后重试";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  function update(key, value) {
    if (key === "amount" || key === "shares") {
      setLastEdited(key);
    }
    if (key === "transaction_type" && value === "sell") {
      setLastEdited("shares");
    }
    setForm((current) => {
      const next = { ...current, [key]: value };
      if ((key === "fund_code" || key === "trade_date" || key === "transaction_type") && current[key] !== value) {
        next.nav = "";
        next.shares = "";
      }
      return next;
    });
  }

  return (
    <form className="transaction-form" onSubmit={submit}>
      <div className="field-row compact-first">
        <label>
          基金代码
          <input
            value={form.fund_code}
            onBlur={() => update("fund_code", normalizeFundCode(form.fund_code))}
            onChange={(event) => update("fund_code", event.target.value)}
            placeholder="例如 000001"
            required
          />
        </label>
      </div>
      <div className="field-row">
        <label>
          {form.transaction_type === "dca" ? "起始日期" : "发起日期"}
          <input type="date" value={form.trade_date} onChange={(event) => update("trade_date", event.target.value)} required />
        </label>
        {form.transaction_type !== "dca" && (
          <label>
            发起时间
            <input type="time" step="1" value={form.initiated_time} onChange={(event) => update("initiated_time", event.target.value)} placeholder="留空为 00:00" />
          </label>
        )}
        <label>
          类型
          <select value={form.transaction_type} onChange={(event) => update("transaction_type", event.target.value)}>
            <option value="buy">买入</option>
            <option value="sell">卖出</option>
            <option value="dividend">分红</option>
            <option value="fee">费用</option>
            <option value="dca">定投</option>
          </select>
        </label>
      </div>
      {form.transaction_type === "dca" && (
        <div className="field-row">
          <label>
            频率
            <select value={form.frequency} onChange={(event) => { update("frequency", event.target.value); update("frequency_day", ""); }}>
              <option value="daily">每日</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
          </label>
          {form.frequency === "weekly" && (
            <label>
              星期
              <select value={form.frequency_day} onChange={(event) => update("frequency_day", event.target.value)}>
                <option value="">自动</option>
                <option value="1">周一</option>
                <option value="2">周二</option>
                <option value="3">周三</option>
                <option value="4">周四</option>
                <option value="5">周五</option>
                <option value="6">周六</option>
                <option value="7">周日</option>
              </select>
            </label>
          )}
          {form.frequency === "monthly" && (
            <label>
              扣款日
              <select value={form.frequency_day} onChange={(event) => update("frequency_day", event.target.value)}>
                <option value="">自动</option>
                {Array.from({length: 28}, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>{d}日</option>
                ))}
              </select>
            </label>
          )}
          <label>
            截止日期
            <input type="date" value={form.dca_end_date} onChange={(event) => update("dca_end_date", event.target.value)} />
          </label>
        </div>
      )}
      {form.transaction_type === "dca" && (
        <div className="field-row">
          <label>
            手续费
            <input type="number" step="0.01" value={form.fee} onChange={(event) => update("fee", event.target.value)} placeholder="0" />
          </label>
        </div>
      )}
      <div className="field-row">
        <label>
          金额
          <input type="number" step="0.01" value={calculated.amount} onChange={(event) => update("amount", event.target.value)} />
        </label>
        {form.transaction_type !== "dca" && (
          <label>
            份额
            <input type="number" step="0.0001" value={calculated.shares} onChange={(event) => update("shares", event.target.value)} />
          </label>
        )}
      </div>
      {form.transaction_type !== "dca" && (
        <div className="field-row">
          <label>
            净值
            <input
              type="number"
              step="0.000001"
              value={form.nav}
              onChange={(event) => {
                setNavStatus("");
                update("nav", event.target.value);
              }}
            />
          </label>
          <label>
            手续费
            <input
              type="number"
              step="0.01"
              value={form.fee}
              onChange={(event) => update("fee", event.target.value)}
              placeholder="留空为 0"
            />
          </label>
        </div>
      )}
      <label>
        备注
        <input value={form.note} onChange={(event) => update("note", event.target.value)} />
      </label>
      {saveError && <div className="alert" style={{marginTop: "8px"}}>{saveError}</div>}
      <div className="calculation-note">
        {form.transaction_type === "dca" ? "定投计划不会立即计入持仓，实际扣款确认后再生成买入交易。" : navStatus || calculated.description}
      </div>
      <button className="primary-button" disabled={saving}>
        <Plus size={18} />
        {saving ? "保存中" : "保存交易"}
      </button>
    </form>
  );
}

function RecentTransactionList({ transactions, loading, onOpenHistory }) {
  if (loading) return <EmptyState text="正在读取最近交易。" />;
  if (!transactions.length) return <EmptyState text="暂无交易记录。" />;
  return (
    <div className="transaction-history">
      <div className="transaction-list">
        {transactions.map((item) => (
          <div className="transaction-item" key={item.id}>
            <div className="fund-cell">
              <strong>{item.fund_name || item.fund_code}</strong>
              <span>
                {item.fund_code} · {item.trade_date} · {typeName(item.transaction_type)}
                {(item.source_label || item.status === "pending") && (
                  <span className="tag-group">
                    {item.source_label && <span className={tagClass(item.source_label)}>{item.source_label}</span>}
                    {item.status === "pending" && <span className="tag tag-pending">待确认</span>}
                  </span>
                )}
              </span>
              {(item.initiated_at || item.confirmed_at) && (
                <span style={{fontSize: "0.8em", color: "#888"}}>发起 {timeStr(item.initiated_at)} · 确认 {timeStr(item.confirmed_at)}</span>
              )}
            </div>
            <b>{money(item.amount)}</b>
          </div>
        ))}
      </div>
      <button className="secondary-button" type="button" onClick={onOpenHistory}>
        查看全部历史交易
      </button>
    </div>
  );
}

function TransactionList({ transactions, loading, filters, onFilter, onChanged, pagination, onPageChange, isAdmin, adminToken }) {
  const [draft, setDraft] = useState(filters);
  const [deletingId, setDeletingId] = useState(null);
  const [batchMode, setBatchMode] = useState(false);
  const [batchFund, setBatchFund] = useState("");
  const [batchStart, setBatchStart] = useState("");
  const [batchEnd, setBatchEnd] = useState("");
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [batchResult, setBatchResult] = useState(null);

  useEffect(() => {
    setDraft(filters);
  }, [filters]);

  async function submit(event) {
    event.preventDefault();
    await onFilter({
      fundCode: normalizeFundCode(draft.fundCode),
      transactionType: draft.transactionType,
      startDate: draft.startDate,
      endDate: draft.endDate,
    });
  }

  async function clearFilters() {
    const empty = { fundCode: "", transactionType: "", startDate: "", endDate: "" };
    setDraft(empty);
    await onFilter(empty);
  }

  async function removeTransaction(transactionId) {
    const confirmed = window.confirm("确认撤销这笔交易吗？撤销后收益会重新计算。定投确认交易会同时取消本次定投执行。");
    if (!confirmed) return;
    setDeletingId(transactionId);
    try {
      await deleteTransaction(transactionId, adminToken);
      await onChanged();
    } finally {
      setDeletingId(null);
    }
  }

  async function removeDcaExecution(executionId) {
    const confirmed = window.confirm("确认撤销本次定投执行吗？撤销后不会再自动确认这一次定投。");
    if (!confirmed) return;
    setDeletingId(`dca-execution-${executionId}`);
    try {
      await deleteDcaExecution(executionId, adminToken);
      await onChanged();
    } finally {
      setDeletingId(null);
    }
  }

  async function batchDelete() {
    const fundCode = normalizeFundCode(batchFund);
    if (!fundCode && !batchStart && !batchEnd) {
      alert("至少需要指定基金代码或日期范围");
      return;
    }
    const desc = [
      fundCode ? `基金 ${fundCode}` : "",
      batchStart ? `从 ${batchStart}` : "",
      batchEnd ? `到 ${batchEnd}` : "",
    ].filter(Boolean).join(" ");
    const confirmed = window.confirm(
      `确认删除匹配的交易？\n条件：${desc}\n\n此操作不可撤销，关联的定投执行记录将标记为已撤销。`
    );
    if (!confirmed) return;
    setBatchDeleting(true);
    setBatchResult(null);
    try {
      const result = await deleteTransactionsBatch({
        fundCode: fundCode || undefined,
        startDate: batchStart || undefined,
        endDate: batchEnd || undefined,
      }, adminToken);
      setBatchResult(`已删除 ${result.deleted} 条交易`);
      await onChanged();
    } catch (error) {
      setBatchResult(`删除失败：${error.message}`);
    } finally {
      setBatchDeleting(false);
    }
  }

  if (loading) return <EmptyState text="正在读取交易记录。" />;
  return (
    <div className="transaction-history">
      <form className="filter-bar" onSubmit={submit}>
        <input
          value={draft.fundCode}
          onChange={(event) => setDraft((current) => ({ ...current, fundCode: event.target.value }))}
          placeholder="基金代码"
        />
        <select
          value={draft.transactionType}
          onChange={(event) => setDraft((current) => ({ ...current, transactionType: event.target.value }))}
        >
          <option value="">全部类型</option>
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
        <input
          type="date"
          value={draft.startDate}
          onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))}
        />
        <input
          type="date"
          value={draft.endDate}
          onChange={(event) => setDraft((current) => ({ ...current, endDate: event.target.value }))}
        />
        <button className="secondary-button" type="submit">筛选</button>
        <button className="ghost-button" type="button" onClick={clearFilters}>清空</button>
      </form>
      {isAdmin && <div className="batch-delete-bar">
        {!batchMode ? (
          <button className="ghost-button compact danger" type="button" onClick={() => setBatchMode(true)}>
            批量删除
          </button>
        ) : (
          <div className="batch-delete-form">
            <input
              value={batchFund}
              onChange={(event) => setBatchFund(event.target.value)}
              placeholder="基金代码"
              className="compact"
            />
            <input
              type="date"
              value={batchStart}
              onChange={(event) => setBatchStart(event.target.value)}
              className="compact"
              title="起始日期"
            />
            <input
              type="date"
              value={batchEnd}
              onChange={(event) => setBatchEnd(event.target.value)}
              className="compact"
              title="截止日期"
            />
            <button
              className="danger-button compact"
              type="button"
              disabled={batchDeleting}
              onClick={batchDelete}
            >
              {batchDeleting ? "删除中" : "确认删除"}
            </button>
            <button
              className="ghost-button compact"
              type="button"
              onClick={() => { setBatchMode(false); setBatchResult(null); }}
            >
              取消
            </button>
            {batchResult && <span className="batch-result">{batchResult}</span>}
          </div>
        )}
      </div>}
      {!transactions.length ? (
        <EmptyState text="暂无交易记录。" />
      ) : (
        <div className="transaction-list">
          {transactions.map((item) => (
            <div className="transaction-item" key={item.id}>
              <div className="fund-cell">
                <strong>{item.fund_name || item.fund_code}</strong>
                <span>
                  {item.fund_code} · {item.trade_date} · {typeName(item.transaction_type)}
                  {(item.source_label || item.status === "pending") && (
                    <span className="tag-group">
                      {item.source_label && <span className={tagClass(item.source_label)}>{item.source_label}</span>}
                      {item.status === "pending" && <span className="tag tag-pending">待确认</span>}
                    </span>
                  )}
                </span>
                <span>份额 {number(item.shares)} · 净值 {item.nav || "-"} · 手续费 {money(item.fee)}</span>
                {(item.initiated_at || item.confirmed_at) && (
                  <span style={{fontSize: "0.8em", color: "#888"}}>发起 {timeStr(item.initiated_at)} · 确认 {timeStr(item.confirmed_at)}</span>
                )}
              </div>
              <div className="transaction-actions">
                <b>{money(item.amount)}</b>
                {isAdmin && (
                  item.is_virtual ? (
                    <button
                      className="danger-button"
                      type="button"
                      disabled={deletingId === item.id}
                      onClick={() => removeDcaExecution(dcaExecutionIdFromVirtualItem(item.id))}
                    >
                      {deletingId === item.id ? "撤销中" : "撤销"}
                    </button>
                  ) : (
                    <button
                      className="danger-button"
                      type="button"
                      disabled={deletingId === item.id}
                      onClick={() => removeTransaction(item.id)}
                    >
                      {deletingId === item.id ? "撤销中" : "撤销"}
                    </button>
                  )
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {pagination && pagination.totalPages > 1 && (
        <div className="pagination-bar">
          <span>
            第 {pagination.page} / {pagination.totalPages} 页 · 共 {pagination.total} 条
          </span>
          <div>
            <button
              className="ghost-button compact"
              type="button"
              disabled={pagination.page <= 1}
              onClick={() => onPageChange(pagination.page - 1)}
            >
              上一页
            </button>
            <button
              className="ghost-button compact"
              type="button"
              disabled={pagination.page >= pagination.totalPages}
              onClick={() => onPageChange(pagination.page + 1)}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DcaPlanList({ plans, loading, onChanged, isAdmin, adminToken }) {
  const [deletingId, setDeletingId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  async function removePlan(planId) {
    if (!window.confirm("确认删除该定投计划？关联的执行记录将被清除，已生成的交易不受影响。")) return;
    setDeletingId(planId);
    try {
      await deleteDcaPlan(planId, adminToken);
      if (onChanged) onChanged();
    } catch (err) {
      alert(err.message);
    } finally {
      setDeletingId(null);
    }
  }

  function startEdit(plan) {
    setEditingId(plan.id);
    setEditForm({
      amount: plan.amount,
      fee: plan.fee || "0",
      frequency: plan.frequency,
      day_of_month: plan.day_of_month || "",
      end_date: plan.end_date || "",
      status: plan.status,
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setEditForm({});
  }

  function updateEditForm(key, value) {
    setEditForm((prev) => ({ ...prev, [key]: value }));
  }

  async function saveEdit(planId) {
    setSaving(true);
    try {
      const payload = {};
      if (editForm.amount !== undefined) payload.amount = editForm.amount;
      if (editForm.fee !== undefined) payload.fee = editForm.fee || "0";
      if (editForm.frequency) payload.frequency = editForm.frequency;
      if (editForm.day_of_month !== undefined) payload.day_of_month = editForm.day_of_month ? Number(editForm.day_of_month) : null;
      if (editForm.end_date !== undefined) payload.end_date = editForm.end_date || null;
      if (editForm.status) payload.status = editForm.status;
      await updateDcaPlan(planId, payload, adminToken);
      setEditingId(null);
      setEditForm({});
      if (onChanged) onChanged();
    } catch (err) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <EmptyState text="正在读取定投计划。" />;
  if (!plans.length) return <EmptyState text="暂无定投计划。" />;
  return (
    <div className="transaction-list">
      {plans.slice(0, 8).map((item) => (
        <div className="transaction-item" key={item.id}>
          {editingId === item.id ? (
            <div className="dca-edit-form">
              <div className="dca-edit-row">
                <label>金额<input type="number" step="0.01" value={editForm.amount} onChange={(e) => updateEditForm("amount", e.target.value)} /></label>
                <label>手续费<input type="number" step="0.01" value={editForm.fee} onChange={(e) => updateEditForm("fee", e.target.value)} /></label>
              </div>
              <div className="dca-edit-row">
                <label>周期
                  <select value={editForm.frequency} onChange={(e) => { updateEditForm("frequency", e.target.value); updateEditForm("day_of_month", ""); }}>
                    <option value="daily">每日</option>
                    <option value="weekly">每周</option>
                    <option value="monthly">每月</option>
                  </select>
                </label>
                {editForm.frequency === "weekly" && (
                  <label>星期
                    <select value={editForm.day_of_month} onChange={(e) => updateEditForm("day_of_month", e.target.value)}>
                      <option value="">自动</option>
                      <option value="1">周一</option>
                      <option value="2">周二</option>
                      <option value="3">周三</option>
                      <option value="4">周四</option>
                      <option value="5">周五</option>
                      <option value="6">周六</option>
                      <option value="7">周日</option>
                    </select>
                  </label>
                )}
                {editForm.frequency === "monthly" && (
                  <label>扣款日
                    <select value={editForm.day_of_month} onChange={(e) => updateEditForm("day_of_month", e.target.value)}>
                      <option value="">自动</option>
                      {Array.from({length: 28}, (_, i) => i + 1).map((d) => (
                        <option key={d} value={d}>{d}日</option>
                      ))}
                    </select>
                  </label>
                )}
                {editForm.frequency === "daily" && <label></label>}
              </div>
              <div className="dca-edit-row">
                <label>截止日期<input type="date" value={editForm.end_date} onChange={(e) => updateEditForm("end_date", e.target.value)} /></label>
                <label>状态
                  <select value={editForm.status} onChange={(e) => updateEditForm("status", e.target.value)}>
                    <option value="active">进行中</option>
                    <option value="paused">已暂停</option>
                  </select>
                </label>
              </div>
              <div className="dca-edit-actions">
                <button className="secondary-button compact" type="button" disabled={saving} onClick={() => saveEdit(item.id)}>{saving ? "保存中" : "保存"}</button>
                <button className="ghost-button compact" type="button" onClick={cancelEdit}>取消</button>
              </div>
            </div>
          ) : (
            <>
              <div className="fund-cell">
                <strong>{item.fund_name || item.fund_code}</strong>
                <span>
                  {item.fund_code}
                  {" · "}{frequencyName(item.frequency)}
                  {item.frequency === "weekly" && item.day_of_month ? `(${weekdayName(item.day_of_month)})` : ""}
                  {item.frequency === "monthly" && item.day_of_month ? `(${item.day_of_month}日)` : ""}
                  {" · "}{item.start_date}
                  {item.end_date ? ` 至 ${item.end_date}` : " 起长期"}
                  {Number(item.fee) > 0 ? ` · 手续费 ${money(item.fee)}` : ""}
                  {item.status === "paused" ? " · 已暂停" : ""}
                </span>
              </div>
              <div style={{display: "flex", alignItems: "center", gap: "8px"}}>
                <b>{money(item.amount)}</b>
                {isAdmin && (
                  <>
                    <button className="ghost-button compact" type="button" onClick={() => startEdit(item)} style={{fontSize: "0.75em", padding: "2px 6px"}}>编辑</button>
                    <button
                      className="danger-button"
                      type="button"
                      disabled={deletingId === item.id}
                      onClick={() => removePlan(item.id)}
                      style={{fontSize: "0.75em", padding: "2px 6px"}}
                    >删除</button>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function DcaExecutionList({ executions, loading, isAdmin, adminToken, onChanged }) {
  const [cancelingId, setCancelingId] = useState(null);

  async function cancelExecution(executionId) {
    if (!window.confirm("确认撤销本次定投执行吗？撤销后不会再自动确认这一次定投。")) return;
    setCancelingId(executionId);
    try {
      await deleteDcaExecution(executionId, adminToken);
      if (onChanged) await onChanged();
    } catch (err) {
      alert(err.message);
    } finally {
      setCancelingId(null);
    }
  }

  if (loading) return <EmptyState text="正在读取定投执行记录。" />;
  if (!executions.length) return <EmptyState text="每日更新命中定投计划后，这里会显示执行状态。" />;
  return (
    <div className="transaction-list">
      {executions.slice(0, 8).map((item) => (
        <div className="transaction-item" key={item.id}>
          <div>
            <strong>{item.fund_code}</strong>
            <span>
              {statusName(item.status)} · 计划 {item.scheduled_date}
              {item.confirmed_date ? ` · 确认 ${item.confirmed_date}` : ""}
            </span>
            {item.nav && <span>净值 {item.nav} · 份额 {item.shares}</span>}
          </div>
          <div className="transaction-actions">
            <b>{money(item.amount)}</b>
            {isAdmin && item.status !== "canceled" && (
              <button
                className="danger-button"
                type="button"
                disabled={cancelingId === item.id}
                onClick={() => cancelExecution(item.id)}
              >
                {cancelingId === item.id ? "撤销中" : "撤销"}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function AdviceCard({ advice }) {
  if (!advice) {
    return (
      <div className="advice-empty">
        <Brain size={28} />
        <p>每日 AI 建议生成后会显示在这里。</p>
      </div>
    );
  }

  return (
    <article className="advice-card">
      <span>{advice.report_date} · {advice.model}</span>
      <p>{advice.content}</p>
    </article>
  );
}

function ChatPanel({ advice, isAdmin, adminToken }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState(() => {
    if (!advice) return [];
    return [
      {
        role: "assistant",
        content: `最近一次日报：\n${advice.content}`,
      },
    ];
  });
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (advice && messages.length === 0) {
      setMessages([
        {
          role: "assistant",
          content: `最近一次日报：\n${advice.content}`,
        },
      ]);
    }
  }, [advice, messages.length]);


  async function submit(event) {
    event.preventDefault();
    if (!input.trim() || !adminToken) return;

    const nextMessages = [...messages, { role: "user", content: input.trim() }];
    setMessages([...nextMessages, { role: "assistant", content: "" }]);
    setInput("");
    setError("");
    setStreaming(true);

    try {
      await streamAdviceChat(nextMessages.slice(-12), adminToken, (chunk) => {
        setMessages((current) => {
          const updated = [...current];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, content: last.content + chunk };
          return updated;
        });
      });
    } catch (err) {
      setError(err.message);
      setMessages((current) => current.slice(0, -1));
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-log">
        {messages.length ? (
          messages.map((message, index) => (
            <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
              <span>{message.role === "user" ? "你" : "AI"}</span>
              <p>{message.content || "正在生成..."}</p>
            </div>
          ))
        ) : (
          <AdviceCard advice={advice} />
        )}
      </div>
      {error && <p className="chat-error">{error}</p>}
      {isAdmin ? (
        <form className="chat-form" onSubmit={submit}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="问问当前组合风险、定投节奏或某只基金是否该观察"
          />
          <button className="primary-button" disabled={streaming || !adminToken}>
            {streaming ? "生成中" : "发送"}
          </button>
        </form>
      ) : (
        <GuestNotice text="访客模式下可查看已有建议。进入管理模式后可继续 AI 对话。" />
      )}
    </div>
  );
}

function EmptyState({ text }) {
  return <p className="empty-state">{text}</p>;
}

function useChart(render, deps) {
  const ref = React.useRef(null);
  const memoDeps = useMemo(() => deps, deps);

  useEffect(() => {
    if (!ref.current) return undefined;
    const chart = echarts.init(ref.current);
    render(chart);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, memoDeps);

  return ref;
}

function money(value) {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value || 0));
}

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function percentPoint(value) {
  const num = Number(value || 0);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
}

function number(value) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(Number(value || 0));
}

function countdownToMarketClose(now) {
  const close = new Date(now);
  close.setHours(15, 0, 0, 0);
  const diffMs = close.getTime() - now.getTime();
  if (diffMs <= 0) return "已过 15:00";
  const totalSeconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}分${String(seconds).padStart(2, "0")}秒`;
}

function typeName(type) {
  return { buy: "买入", sell: "卖出", dividend: "分红", fee: "费用" }[type] || type;
}

function tagClass(label) {
  return { "定投执行": "tag tag-dca-exec", "定投确认": "tag tag-dca-confirm", "支付宝": "tag tag-alipay" }[label] || "tag";
}

function frequencyName(frequency) {
  return { daily: "每日", weekly: "每周", monthly: "每月" }[frequency] || frequency;
}

function weekdayName(day) {
  return ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"][Number(day)] || "";
}

function statusName(status) {
  return { pending: "待确认", confirmed: "已确认", canceled: "已撤销", skipped: "已跳过" }[status] || status;
}

function dcaExecutionIdFromVirtualItem(id) {
  return Number(String(id || "").replace("dca-execution-", ""));
}

function timeStr(value) {
  if (!value) return "-";
  const d = new Date(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function normalizeFundCode(value) {
  const text = String(value || "").trim();
  return /^\d{1,6}$/.test(text) ? text.padStart(6, "0") : text;
}

function calculateTransactionFields(form, lastEdited) {
  const amount = Number(form.amount || 0);
  const shares = Number(form.shares || 0);
  const nav = Number(form.nav || 0);
  const fee = Number(form.fee || 0);
  const canCalculate =
    nav > 0 &&
    form.transaction_type !== "dividend" &&
    form.transaction_type !== "fee" &&
    form.transaction_type !== "dca";

  if (!canCalculate) {
    return {
      amount: form.amount,
      shares: form.shares,
      description: "填写确认净值后，可自动计算金额或份额。",
    };
  }

  if (lastEdited === "amount" && amount > 0) {
    const baseAmount = form.transaction_type === "buy" ? amount - fee : amount + fee;
    const calculatedShares = Math.max(baseAmount / nav, 0);
    return {
      amount: form.amount,
      shares: formatNumber(calculatedShares, 4),
      description: `按 ${form.transaction_type === "buy" ? "买入金额-手续费" : "卖出金额+手续费"} ÷ 净值估算份额。`,
    };
  }

  if (lastEdited === "shares" && shares > 0) {
    const calculatedAmount = form.transaction_type === "buy" ? shares * nav + fee : shares * nav - fee;
    return {
      amount: formatNumber(Math.max(calculatedAmount, 0), 2),
      shares: form.shares,
      description: `按 份额 × 净值 ${form.transaction_type === "buy" ? "+ 手续费" : "- 手续费"} 估算金额。`,
    };
  }

  return {
    amount: form.amount,
    shares: form.shares,
    description: "填写金额或份额后，系统会自动补全另一项。",
  };
}

function formatNumber(value, digits) {
  if (!Number.isFinite(value)) return "";
  return value.toFixed(digits).replace(/\.?0+$/, "");
}

createRoot(document.getElementById("root")).render(<App />);
