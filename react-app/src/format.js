export const formatMoney = value => {
  const v = Math.round(value || 0);
  return Math.abs(v) >= 100000
    ? `₹${(v / 100000).toFixed(1)}L`
    : `₹${v.toLocaleString("en-IN")}`;
};

// "↗ 7% vs previous period", or a plain note when there is nothing to compare
export const growthText = g => {
  if (g === null || g === undefined) return "No prior-period data";
  if (Math.abs(g) > 500) return "Sharp change vs a very small prior period";
  return `${g >= 0 ? "↗" : "↘"} ${Math.abs(g)}% vs previous period`;
};

export const growthTone = g =>
  g === null || g === undefined ? "" : g >= 0 ? "positive" : "negative";

export const statusType = value =>
  /^high$|negative|overdue|breach|delayed/i.test(value)
    ? "risk"
    : /^medium$|low|due|warning|transit/i.test(value)
      ? "warning"
      : "";

// 1234567 -> "₹12,34,567" (always the full figure, for exposure amounts)
export const formatInr = value => `₹${Math.round(value || 0).toLocaleString("en-IN")}`;

function triggerDownload(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function downloadCsv(name, rows) {
  const csv = rows
    .map(row => row.map(v => `"${String(v).replaceAll('"', '""')}"`).join(","))
    .join("\n");
  triggerDownload(new Blob([csv], { type: "text/csv" }), `arthpulse-${name}.csv`);
}

export function downloadText(filename, text) {
  triggerDownload(new Blob([text], { type: "text/plain" }), filename);
}