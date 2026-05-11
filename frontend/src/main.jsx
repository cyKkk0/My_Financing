import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import * as echarts from "echarts";
import { Activity, BarChart3, Brain, CircleDollarSign, Plus, RefreshCw, TrendingUp } from "lucide-react";

import {
  createDcaPlan,
  createTransaction,
  deleteDcaPlan,
  updateDcaPlan,
  deleteTransaction,
  deleteTransactionsBatch,
  getFundNav,
  getFundPerformance,
  getLatestAdvice,
  getPortfolioSummary,
  getSnapshots,
  importAlipayPdf,
  listDcaExecutions,
  listDcaPlans,
  listTransactions,
  listTransactionsPage,
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

function App() {
  const [summary, setSummary] = useState(emptySummary);
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotPeriod, setSnapshotPeriod] = useState("month");
  const [recentTransactions, setRecentTransactions] = useState([]);
  const [dcaPlans, setDcaPlans] = useState([]);
  const [dcaExecutions, setDcaExecutions] = useState([]);
  const [page, setPage] = useState("dashboard");
  const [advice, setAdvice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatingNav, setUpdatingNav] = useState(false);
  const [error, setError] = useState("");
  const [updateResult, setUpdateResult] = useState(null);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [summaryData, snapshotData, transactionData, dcaPlanData, dcaExecutionData, adviceData] = await Promise.all([
        getPortfolioSummary(),
        getSnapshots(snapshotPeriod),
        listTransactions({ limit: 5 }),
        listDcaPlans(),
        listDcaExecutions(),
        getLatestAdvice(),
      ]);
      setSummary(summaryData || emptySummary);
      setSnapshots(snapshotData || []);
      setRecentTransactions(transactionData || []);
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
    getSnapshots(snapshotPeriod).then(setSnapshots).catch(() => {});
  }, [snapshotPeriod]);

  async function updateNavs() {
    const adminToken = window.prompt("请输入后端 ADMIN_TOKEN", localStorage.getItem("my-financing-admin-token") || "");
    if (!adminToken) return;
    setUpdatingNav(true);
    setError("");
    setUpdateResult(null);
    try {
      const result = await runDailyUpdate(adminToken);
      localStorage.setItem("my-financing-admin-token", adminToken);
      setUpdateResult(result);
      await loadData();
    } catch (err) {
      localStorage.removeItem("my-financing-admin-token");
      setError(err.message);
    } finally {
      setUpdatingNav(false);
    }
  }

  if (page === "history") {
    return (
      <HistoryPage
        onBack={async () => {
          setPage("dashboard");
          await loadData();
        }}
        onChanged={loadData}
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
          <button className="icon-button text-button" onClick={updateNavs} disabled={updatingNav} title="从 AKShare 更新基金净值">
            <Activity size={18} />
            {updatingNav ? "更新中" : "更新净值"}
          </button>
        </div>
      </header>

      {error && <div className="alert">后端暂不可用：{error}</div>}
      {updateResult && <UpdateResult result={updateResult} />}

      <section className="metric-grid">
        <Metric icon={<CircleDollarSign />} label="最新市值" value={money(summary.market_value)} hint={summary.latest_nav_date ? `截至 ${summary.latest_nav_date}` : ""} />
        <Metric icon={<TrendingUp />} label="最新持有收益" value={money(summary.holding_profit ?? summary.profit)} tone={Number(summary.holding_profit ?? summary.profit) >= 0 ? "gain" : "loss"} />
        <Metric icon={<Activity />} label="最新累计收益" value={money(summary.cumulative_profit ?? summary.profit)} tone={Number(summary.cumulative_profit ?? summary.profit) >= 0 ? "gain" : "loss"} />
        <Metric icon={<BarChart3 />} label="持仓成本" value={money(summary.total_invested)} />
      </section>

      <section style={{marginBottom: "16px"}}>
        <FundPerformancePanel holdings={summary.holdings} />
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
          <HoldingsTable holdings={summary.holdings} />
        </Panel>
        <Panel title="新增交易">
          <TransactionForm onCreated={loadData} />
        </Panel>
      </section>

      <section className="content-grid" style={{marginTop: "16px"}}>
        <Panel title="定投计划">
          <div className="scroll-panel"><DcaPlanList plans={dcaPlans} loading={loading} onChanged={loadData} /></div>
        </Panel>
        <Panel title="定投执行">
          <div className="scroll-panel"><DcaExecutionList executions={dcaExecutions} loading={loading} /></div>
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
          <ChatPanel advice={advice} />
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

function HistoryPage({ onBack, onChanged }) {
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
        <AlipayImportPanel onImported={handleChanged} />
        <TransactionList
          transactions={transactions}
          loading={loading}
          filters={filters}
          onFilter={applyFilters}
          onChanged={handleChanged}
          pagination={pagination}
          onPageChange={goToPage}
        />
      </Panel>
    </main>
  );
}

function AlipayImportPanel({ onImported }) {
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
      const data = await importAlipayPdf(file, dryRun);
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

function FundPerformancePanel({ holdings }) {
  const [fundCode, setFundCode] = useState("");
  const [range, setRange] = useState("month");
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const ranges = [
    { key: "week", label: "近一周" },
    { key: "month", label: "近一月" },
    { key: "3month", label: "近三月" },
    { key: "6month", label: "近半年" },
    { key: "year", label: "近一年" },
  ];

  useEffect(() => {
    if (!fundCode) {
      setChartData(null);
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await getFundPerformance(fundCode, range);
        if (!cancelled) setChartData(data);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [fundCode, range]);

  const chartRef = useChart((chart) => {
    if (!chartData || !chartData.length) {
      chart.setOption({
        title: { text: fundCode ? "暂无数据" : "请选择基金", left: "center", top: "center", textStyle: { color: "#94a3b8", fontSize: 14 } },
      });
      return;
    }
    const dates = chartData.map((d) => d.nav_date);
    const navs = chartData.map((d) => Number(d.unit_nav));
    const cumulativeReturns = chartData.map((d) => d.cumulative_return != null ? Number(d.cumulative_return) * 100 : 0);
    const growthRates = chartData.map((d) => d.daily_growth_rate != null ? Number(d.daily_growth_rate) * 100 : null);
    // Fund index: normalized to 100 at the first NAV in range
    const baseNav = navs[0];
    const fundIndex = navs.map((n) => baseNav !== 0 ? (n / baseNav) * 100 : 100);
    const minIdx = Math.min(...fundIndex);
    const maxIdx = Math.max(...fundIndex);
    const idxPadding = Math.max((maxIdx - minIdx) * 0.15, 2);

    chart.setOption({
      grid: { left: 16, right: 56, top: 24, bottom: 40 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#ffffff",
        borderColor: "#e8ecf2",
        borderWidth: 1,
        textStyle: { color: "#1a1a2e", fontSize: 13 },
        formatter: function (params) {
          const date = params[0].axisValue;
          let tip = `<div style="font-size:12px;color:#94a3b8;margin-bottom:4px">${date}</div>`;
          params.forEach(function (p) {
            if (p.value == null) return;
            if (p.seriesName === "基金指数") {
              tip += `<div style="font-size:13px">${p.marker} ${p.seriesName} <b style="margin-left:8px">${Number(p.value).toFixed(2)}</b></div>`;
            }
            if (p.seriesName === "累计收益") {
              const v = Number(p.value);
              const color = v >= 0 ? "#dc2626" : "#059669";
              const sign = v >= 0 ? "+" : "";
              tip += `<div style="font-size:13px;color:${color}">${p.marker} ${p.seriesName} <b style="margin-left:8px">${sign}${v.toFixed(2)}%</b></div>`;
            }
          });
          if (params[0].dataIndex > 0 && growthRates[params[0].dataIndex] != null) {
            const g = growthRates[params[0].dataIndex];
            const d = fundIndex[params[0].dataIndex] - fundIndex[params[0].dataIndex - 1];
            const color = g >= 0 ? "#dc2626" : "#059669";
            const sign = g >= 0 ? "+" : "";
            tip += `<div style="font-size:11px;color:${color};margin-top:2px">日涨跌 ${sign}${d.toFixed(2)} (${sign}${g.toFixed(2)}%)</div>`;
          }
          return tip;
        },
      },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#e8ecf2" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#94a3b8",
          fontSize: 11,
          rotate: dates.length > 60 ? 45 : 0,
          formatter: function (v) {
            if (dates.length > 60) return v.slice(5);
            if (dates.length > 30) return v.slice(5).replace("-", "/");
            return v;
          },
        },
      },
      yAxis: [
        {
          type: "value",
          min: minIdx - idxPadding,
          max: maxIdx + idxPadding,
          splitNumber: 4,
          axisLabel: { color: "#2563eb", fontSize: 11, formatter: function (v) { return v.toFixed(1); } },
          splitLine: { lineStyle: { color: "#f1f5f9", type: "dashed" } },
        },
        {
          type: "value",
          splitNumber: 4,
          axisLabel: { color: "#f97316", fontSize: 11, formatter: "{value}%" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "基金指数",
          type: "line",
          yAxisIndex: 0,
          data: fundIndex,
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#2563eb", width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(37,99,235,0.15)" },
              { offset: 1, color: "rgba(37,99,235,0.01)" },
            ]),
          },
        },
        {
          name: "累计收益",
          type: "line",
          yAxisIndex: 1,
          data: cumulativeReturns,
          smooth: false,
          symbol: "none",
          lineStyle: { color: "#f97316", width: 2 },
        },
      ],
    });
  }, [chartData]);

  const fundOptions = holdings.map((h) => ({
    code: h.fund_code,
    name: h.fund_name,
  }));

  return (
    <Panel
      title={
        <span className="panel-title-row">
          业绩走势
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <select
              value={fundCode}
              onChange={(e) => setFundCode(e.target.value)}
              style={{ minHeight: 32, width: 180, fontSize: 13, padding: "0 6px" }}
            >
              <option value="">选择基金</option>
              {fundOptions.map((f) => (
                <option key={f.code} value={f.code}>{f.name}</option>
              ))}
            </select>
            <div className="range-toggle">
              {ranges.map((r) => (
                <button
                  key={r.key}
                  className={range === r.key ? "active" : ""}
                  type="button"
                  onClick={() => setRange(r.key)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </span>
      }
    >
      {error && <p className="chat-error">{error}</p>}
      {loading && <EmptyState text="正在加载..." />}
      {fundCode ? (
        <>
          <div className="chart chart-tall" ref={chartRef} />
          {chartData && chartData.length > 1 && (
            <div className="perf-stats">
              {_renderStat("区间收益", formatPerfReturn(chartData))}
              {_renderStat("最新净值", Number(chartData[chartData.length - 1].unit_nav).toFixed(4))}
              {_renderStat("最高净值", Math.max(...chartData.map(d => Number(d.unit_nav))).toFixed(4))}
              {_renderStat("最低净值", Math.min(...chartData.map(d => Number(d.unit_nav))).toFixed(4))}
            </div>
          )}
        </>
      ) : (
        <div style={{ textAlign: "center", color: "#94a3b8", fontSize: 13, padding: "10px 0 30px" }}>请选择基金查看业绩走势</div>
      )}
    </Panel>
  );
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

function HoldingsTable({ holdings }) {
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
          {holdings.map((item) => (
            <tr key={item.fund_code}>
              <td className="fund-cell">
                <strong>{item.fund_name}</strong>
                <span>{item.fund_code}</span>
              </td>
              <td>{number(item.shares)}</td>
              <td><strong>{item.latest_nav || "-"}</strong></td>
              <td class="market-value-cell">
                <strong>{money(item.market_value)}</strong>
                <small>未确认 {money(Number(item.market_value) - Number(item.confirmed_market_value || 0))}</small>
              </td>
              <td className={Number(item.daily_pnl ?? 0) >= 0 ? "gain" : "loss"}>
                <strong>{item.daily_pnl != null ? money(item.daily_pnl) : "-"}</strong>
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionForm({ onCreated }) {
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
      form.transaction_type !== "dca";
    if (!shouldFetch) return undefined;

    let cancelled = false;
    setNavStatus("正在获取确认净值...");
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
          setNavStatus("未找到该日期净值，可手动填写净值后计算。");
        }
      }
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [form.fund_code, form.trade_date, form.nav, form.transaction_type]);

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
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
        });
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
        });
      }
      setForm((current) => ({ ...current, amount: "", shares: "", nav: "", fee: "", dca_end_date: "", initiated_time: "", note: "" }));
      await onCreated();
    } finally {
      setSaving(false);
    }
  }

  function update(key, value) {
    if (key === "amount" || key === "shares") {
      setLastEdited(key);
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
                {item.status === "pending" && <span className="pending-badge">待确认</span>}
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

function TransactionList({ transactions, loading, filters, onFilter, onChanged, pagination, onPageChange }) {
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
    const confirmed = window.confirm("确认撤销这笔交易吗？撤销后收益会重新计算。");
    if (!confirmed) return;
    setDeletingId(transactionId);
    try {
      await deleteTransaction(transactionId);
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
      `确认删除匹配的交易？\n条件：${desc}\n\n此操作不可撤销，关联的定投执行记录将重置为待确认状态。`
    );
    if (!confirmed) return;
    setBatchDeleting(true);
    setBatchResult(null);
    try {
      const result = await deleteTransactionsBatch({
        fundCode: fundCode || undefined,
        startDate: batchStart || undefined,
        endDate: batchEnd || undefined,
      });
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
      <div className="batch-delete-bar">
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
      </div>
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
                  {item.status === "pending" && <span className="pending-badge">待确认</span>}
                </span>
                <span>份额 {number(item.shares)} · 净值 {item.nav || "-"} · 手续费 {money(item.fee)}</span>
                {(item.initiated_at || item.confirmed_at) && (
                  <span style={{fontSize: "0.8em", color: "#888"}}>发起 {timeStr(item.initiated_at)} · 确认 {timeStr(item.confirmed_at)}</span>
                )}
              </div>
              <div className="transaction-actions">
                <b>{money(item.amount)}</b>
                <button
                  className="danger-button"
                  type="button"
                  disabled={deletingId === item.id}
                  onClick={() => removeTransaction(item.id)}
                >
                  {deletingId === item.id ? "撤销中" : "撤销"}
                </button>
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

function DcaPlanList({ plans, loading, onChanged }) {
  const [deletingId, setDeletingId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  async function removePlan(planId) {
    if (!window.confirm("确认删除该定投计划？关联的执行记录将被清除，已生成的交易不受影响。")) return;
    setDeletingId(planId);
    try {
      await deleteDcaPlan(planId);
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
      await updateDcaPlan(planId, payload);
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
                <button className="ghost-button compact" type="button" onClick={() => startEdit(item)} style={{fontSize: "0.75em", padding: "2px 6px"}}>编辑</button>
                <button
                  className="danger-button"
                  type="button"
                  disabled={deletingId === item.id}
                  onClick={() => removePlan(item.id)}
                  style={{fontSize: "0.75em", padding: "2px 6px"}}
                >删除</button>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function DcaExecutionList({ executions, loading }) {
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
          <b>{money(item.amount)}</b>
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

function ChatPanel({ advice }) {
  const [adminToken, setAdminToken] = useState(() => localStorage.getItem("my-financing-admin-token") || "");
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
    if (!input.trim() || !adminToken.trim()) return;

    const nextMessages = [...messages, { role: "user", content: input.trim() }];
    setMessages([...nextMessages, { role: "assistant", content: "" }]);
    setInput("");
    setError("");
    setStreaming(true);

    try {
      await streamAdviceChat(nextMessages.slice(-12), adminToken.trim(), (chunk) => {
        setMessages((current) => {
          const updated = [...current];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, content: last.content + chunk };
          return updated;
        });
      });
      localStorage.setItem("my-financing-admin-token", adminToken.trim());
    } catch (err) {
      localStorage.removeItem("my-financing-admin-token");
      setError(err.message);
      setMessages((current) => current.slice(0, -1));
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="chat-panel">
      <label>
        管理 Token
        <input
          type="password"
          value={adminToken}
          onChange={(event) => setAdminToken(event.target.value)}
          placeholder="后端 ADMIN_TOKEN"
        />
      </label>
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
      <form className="chat-form" onSubmit={submit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="问问当前组合风险、定投节奏或某只基金是否该观察"
        />
        <button className="primary-button" disabled={streaming || !adminToken.trim()}>
          {streaming ? "生成中" : "发送"}
        </button>
      </form>
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

function number(value) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(Number(value || 0));
}

function typeName(type) {
  return { buy: "买入", sell: "卖出", dividend: "分红", fee: "费用" }[type] || type;
}

function frequencyName(frequency) {
  return { daily: "每日", weekly: "每周", monthly: "每月" }[frequency] || frequency;
}

function weekdayName(day) {
  return ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"][Number(day)] || "";
}

function statusName(status) {
  return { pending: "待确认", confirmed: "已确认", skipped: "已跳过" }[status] || status;
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
