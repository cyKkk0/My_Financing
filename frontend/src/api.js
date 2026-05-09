const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

export function getPortfolioSummary() {
  return request("/portfolio/summary");
}

export function getSnapshots() {
  return request("/portfolio/snapshots");
}

export function getLatestAdvice() {
  return request("/advice/latest");
}

export function listTransactions(filters = {}) {
  const params = new URLSearchParams();
  if (filters.fundCode) params.set("fund_code", filters.fundCode);
  if (filters.transactionType) params.set("transaction_type", filters.transactionType);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return request(`/transactions${query ? `?${query}` : ""}`);
}

export function listTransactionsPage(filters = {}) {
  const params = new URLSearchParams();
  if (filters.fundCode) params.set("fund_code", filters.fundCode);
  if (filters.transactionType) params.set("transaction_type", filters.transactionType);
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  params.set("page", String(filters.page || 1));
  params.set("page_size", String(filters.pageSize || 10));
  return request(`/transactions/page?${params.toString()}`);
}

export function listDcaPlans() {
  return request("/dca-plans");
}

export function listDcaExecutions() {
  return request("/dca-executions");
}

export function getFundNav(fundCode, tradeDate) {
  return request(`/funds/${fundCode}/nav?trade_date=${tradeDate}`);
}

export function createTransaction(payload) {
  return request("/transactions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteTransaction(transactionId) {
  return request(`/transactions/${transactionId}`, {
    method: "DELETE",
  });
}

export function deleteTransactionsBatch({ fundCode, startDate, endDate }) {
  const params = new URLSearchParams();
  if (fundCode) params.set("fund_code", fundCode);
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return request(`/transactions?${params.toString()}`, {
    method: "DELETE",
  });
}

export function importAlipayPdf(path, dryRun = true) {
  return request("/transactions/import/alipay-pdf", {
    method: "POST",
    body: JSON.stringify({ path, dry_run: dryRun }),
  });
}

export function createDcaPlan(payload) {
  return request("/dca-plans", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteDcaPlan(planId) {
  return request(`/dca-plans/${planId}`, { method: "DELETE" });
}

export function runDailyUpdate(adminToken) {
  return request("/jobs/daily-update", {
    method: "POST",
    headers: {
      "X-Admin-Token": adminToken,
    },
  });
}

export async function streamAdviceChat(messages, adminToken, onChunk) {
  const response = await fetch(`${API_BASE}/advice/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": adminToken,
    },
    body: JSON.stringify({ messages }),
  });

  if (!response.ok || !response.body) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value, { stream: true }));
  }
}
