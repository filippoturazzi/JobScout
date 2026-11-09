// Pure formatting helpers for jobs and runs. No DOM, no fetch.

// A posting link only for http(s); anything else (javascript:, data:, garbage) gets no link.
export function safeUrl(url) {
  if (typeof url !== "string" || !url) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch (e) {
    return null;
  }
  return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : null;
}

// The API writes naive UTC timestamps; read them as UTC.
function parseUtc(iso) {
  if (typeof iso !== "string" || !iso) return null;
  const zoned = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  const ms = Date.parse(zoned);
  return Number.isNaN(ms) ? null : ms;
}

export function timeAgo(iso, now, t) {
  const then = parseUtc(iso);
  if (then === null) return null;
  const minutes = Math.floor((now.getTime() - then) / 60000);
  if (minutes < 1) return t("ago_now");
  if (minutes < 60) return t("ago_m", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("ago_h", { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t("ago_d", { n: days });
  return t("ago_w", { n: Math.floor(days / 7) });
}

const SYMBOLS = { BRL: "R$ ", USD: "$", EUR: "€", GBP: "£" };

// "R$ 6–8 mil", "$40–55k"; null when the posting gave no salary (never invent one).
export function salary(job, locale) {
  const bounds = [job.salary_min, job.salary_max].filter((v) => typeof v === "number");
  if (bounds.length === 0) return null;
  const values = bounds.length === 2 && bounds[0] === bounds[1] ? [bounds[0]] : bounds;
  const currency = job.salary_currency || null;
  const thousands = values.every((v) => v >= 1000);
  const number = new Intl.NumberFormat(locale === "pt-BR" ? "pt-BR" : "en", { maximumFractionDigits: 1 });
  const range = values.map((v) => number.format(thousands ? v / 1000 : v)).join("–");
  const suffix = !thousands ? "" : locale === "pt-BR" || currency === "BRL" ? " mil" : "k";
  const symbol = currency ? (SYMBOLS[currency] ?? `${currency} `) : "";
  return `${symbol}${range}${suffix}`;
}

export function scoreLabel(score) {
  return typeof score === "number" ? `${Math.round(score)}%` : null;
}

const SOURCE_NAMES = { linkedin: "LinkedIn" };

export function sourceName(id) {
  const name = String(id || "");
  return SOURCE_NAMES[name] || name.charAt(0).toUpperCase() + name.slice(1);
}
