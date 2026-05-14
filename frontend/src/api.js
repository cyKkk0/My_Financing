const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractErrorMessage(payload) {
  if (typeof payload === "string") return payload;
  // FastAPI 422: detail is an array of {loc, msg, type}
  if (Array.isArray(payload)) {
    const parts = payload.map((e) => {
      const loc = (e.loc || []).join(".");
      return loc ? `${loc}: ${e.msg}` : e.msg;
    });
    return parts.join("; ") || "请求数据验证失败";
  }
  if (payload && typeof payload === "object") {
    if (Array.isArray(payload.detail)) return extractErrorMessage(payload.detail);
    if (typeof payload.detail === "string") return payload.detail;
    if (typeof payload.message === "string") return payload.message;
    try {
      return JSON.stringify(payload);
    } catch {
      return "未知错误";
    }
  }
  return String(payload || "请求失败");
}

async function responseError(response) {
  const text = await response.text();
  if (text) {
    try {
      const payload = JSON.parse(text);
      const message = extractErrorMessage(payload.detail !== undefined ? payload.detail : payload);
      return new ApiError(message || `Request failed: ${response.status}`, response.status);
    } catch {
      return new ApiError(text || `Request failed: ${response.status}`, response.status);
    }
  }
  return new ApiError(`Request failed: ${response.status}`, response.status);
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    throw await responseError(response);
  }

  if (response.status === 204) return null;
  return response.json();
}

function authHeaders(adminToken) {
  return adminToken
    ? {
        Authorization: `Bearer ${adminToken}`,
      }
    : {};
}

export function loginAdmin(payload) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAdminMe(adminToken) {
  return request("/auth/me", {
    headers: authHeaders(adminToken),
  });
}

export function logoutAdmin(adminToken) {
  return request("/auth/logout", {
    method: "POST",
    headers: authHeaders(adminToken),
  });
}

export function getPortfolioSummary() {
  return request("/portfolio/summary");
}

export function getSnapshots(period = "month") {
  return request(`/portfolio/snapshots?period=${period}`);
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

export function getFundPerformance(fundCode, range = "month") {
  return request(`/funds/${fundCode}/performance?range=${range}`);
}

export function createTransaction(payload, adminToken) {
  return request("/transactions", {
    method: "POST",
    headers: authHeaders(adminToken),
    body: JSON.stringify(payload),
  });
}

export function deleteTransaction(transactionId, adminToken) {
  return request(`/transactions/${transactionId}`, {
    method: "DELETE",
    headers: authHeaders(adminToken),
  });
}

export function deleteTransactionsBatch({ fundCode, startDate, endDate }, adminToken) {
  const params = new URLSearchParams();
  if (fundCode) params.set("fund_code", fundCode);
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return request(`/transactions?${params.toString()}`, {
    method: "DELETE",
    headers: authHeaders(adminToken),
  });
}

export async function importAlipayPdf(file, dryRun = true, adminToken) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("dry_run", dryRun);

  const response = await fetch(`${API_BASE}/transactions/import/alipay-pdf`, {
    method: "POST",
    headers: authHeaders(adminToken),
    body: formData,
  });

  if (!response.ok) {
    throw await responseError(response);
  }

  return response.json();
}

export function createDcaPlan(payload, adminToken) {
  return request("/dca-plans", {
    method: "POST",
    headers: authHeaders(adminToken),
    body: JSON.stringify(payload),
  });
}

export function updateDcaPlan(planId, payload, adminToken) {
  return request(`/dca-plans/${planId}`, {
    method: "PUT",
    headers: authHeaders(adminToken),
    body: JSON.stringify(payload),
  });
}

export function deleteDcaPlan(planId, adminToken) {
  return request(`/dca-plans/${planId}`, {
    method: "DELETE",
    headers: authHeaders(adminToken),
  });
}

export function deleteDcaExecution(executionId, adminToken) {
  return request(`/dca-executions/${executionId}`, {
    method: "DELETE",
    headers: authHeaders(adminToken),
  });
}

export function confirmPendingTransactions(adminToken) {
  return request("/jobs/confirm-pending-transactions", {
    method: "POST",
    headers: authHeaders(adminToken),
  });
}

export function runDailyUpdate(adminToken) {
  return request("/jobs/daily-update", {
    method: "POST",
    headers: authHeaders(adminToken),
  });
}

export async function streamAdviceChat(messages, adminToken, onChunk) {
  const response = await fetch(`${API_BASE}/advice/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(adminToken),
    },
    body: JSON.stringify({ messages }),
  });

  if (!response.ok || !response.body) {
    throw await responseError(response);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value, { stream: true }));
  }
}
