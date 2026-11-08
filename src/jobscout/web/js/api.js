// The only place the page talks to the server.

export class ApiError extends Error {
  constructor(status, code, detail, searchId) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.searchId = searchId;
  }
}

function describe(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d.msg === "string" ? d.msg : String(d))).join("; ");
  }
  return "";
}

// Builds an ApiError from FastAPI's {"detail": ...} or this API's {"detail", "code", "search_id"}.
export function apiError(status, body) {
  const b = body && typeof body === "object" ? body : {};
  return new ApiError(status, b.code ?? null, describe(b.detail), b.search_id ?? null);
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let parsed = null;
    try {
      parsed = await res.json();
    } catch (e) {
      parsed = null;
    }
    throw apiError(res.status, parsed);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
};
