const SYMBOLS: Record<string, string> = {
  USD: "$", EUR: "€", GBP: "£", INR: "₹", JPY: "¥", AUD: "A$", CAD: "C$", SGD: "S$", AED: "AED ", ZAR: "R",
};

export function compact(v: number, decimals = 1): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(decimals)}K`;
  return v.toLocaleString("en-US", { maximumFractionDigits: a < 100 ? 2 : 0, minimumFractionDigits: 0 });
}

export function fmtValue(v: unknown, unit = "number", currency = "USD", decimals = 2, short = true): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (unit === "pct") return `${v.toFixed(1)}%`;
  if (unit === "percent") return `${(v * 100).toFixed(1)}%`;
  if (unit === "percent_points") return `${v * 100 >= 0 ? "+" : ""}${(v * 100).toFixed(1)} pp`;
  if (unit === "currency") {
    const sym = SYMBOLS[currency] ?? `${currency} `;
    const body = short ? compact(Math.abs(v)) : Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${v < 0 ? "−" : ""}${sym}${body}`;
  }
  if (unit === "count") return short ? compact(v, 1) : Math.round(v).toLocaleString("en-US");
  return short ? compact(v) : v.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

export function fmtPct(v: number | null | undefined, signed = true): string {
  if (v === null || v === undefined) return "—";
  return `${signed && v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
}

export function fmtDate(iso?: string | null, withTime = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", withTime
    ? { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "short", year: "numeric" });
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(iso);
}

export function bytes(n?: number | null): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function cellText(v: unknown, col?: { role?: string; unit?: string; decimals?: number }, currency = "USD"): string {
  if (v === null || v === undefined) return "—";
  if (col?.role === "percent" && typeof v === "number") return `${v.toFixed(1)}%`;
  if (col?.role === "measure" && typeof v === "number") return fmtValue(v, col.unit ?? "number", currency, col.decimals ?? 2, false);
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00/.test(v)) return v.slice(0, 10);
  return String(v);
}
