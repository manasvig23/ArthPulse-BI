// Small stroke icons, drawn inline so the project needs no icon package.
const PATHS = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  trend: <><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>,
  down: <><path d="M12 4v15" /><path d="M6 13l6 6 6-6" /></>,
  folder: <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />,
  rupee: <><path d="M7 5h11" /><path d="M7 9.5h11" /><path d="M7 5c5 0 7 2 7 4.5S11 14 7 14l8 5" /></>,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6l8-3z" /><path d="M9 12l2.2 2.2L15.5 10" /></>,
  bell: <><path d="M6 9a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6z" /><path d="M10 19a2 2 0 004 0" /></>,
  file: <><path d="M7 3h7l5 5v12a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h6" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" /></>,
  wallet: <><path d="M4 7a2 2 0 012-2h12v4" /><path d="M4 7v10a2 2 0 002 2h13a1 1 0 001-1V9a1 1 0 00-1-1H6a2 2 0 01-2-1z" /><circle cx="16" cy="13.5" r="1.2" /></>,
  coins: <><circle cx="9" cy="9" r="5.5" /><path d="M14.5 6.2A5.5 5.5 0 1118 16" /><path d="M7.5 9h3" /></>,
  cart: <><path d="M3 4h2.5l2 11h10l2-8H7" /><circle cx="9.5" cy="19" r="1.3" /><circle cx="16.5" cy="19" r="1.3" /></>,
  box: <><path d="M3 8l9-5 9 5v8l-9 5-9-5V8z" /><path d="M3 8l9 5 9-5M12 13v8" /></>,
  alert: <><path d="M12 4l9 16H3L12 4z" /><path d="M12 10v4M12 17.2v.1" /></>,
  chart: <><path d="M4 20V10M10 20V4M16 20v-8M22 20H2" /></>,
  logout: <><path d="M10 4H6a2 2 0 00-2 2v12a2 2 0 002 2h4" /><path d="M15 8l4 4-4 4M9 12h10" /></>,
  moon: <path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  chevron: <path d="M6 9l6 6 6-6" />,
  arrow: <path d="M9 6l6 6-6 6" />,
  spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />,
  key: <><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M16 7l3 3" /></>,
};

export function Icon({ name, size = 18, stroke = 1.8 }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name] || PATHS.chart}
    </svg>
  );
}

// A tiny line chart for KPI cards. Draws only the real series it is given.
export function Sparkline({ values, tone = "positive" }) {
  const points = (values || []).filter(v => typeof v === "number");
  if (points.length < 2) return null;

  const W = 84, H = 30, pad = 3;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const x = i => pad + (i * (W - pad * 2)) / (points.length - 1);
  const y = v => H - pad - ((v - min) / span) * (H - pad * 2);

  // smooth the line with midpoints so it reads as a curve, not a zig-zag
  let d = `M ${x(0)} ${y(points[0])}`;
  for (let i = 1; i < points.length; i++) {
    const mx = (x(i - 1) + x(i)) / 2;
    d += ` C ${mx} ${y(points[i - 1])}, ${mx} ${y(points[i])}, ${x(i)} ${y(points[i])}`;
  }

  return (
    <svg className={`sparkline ${tone}`} width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      <path d={d} fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ArthPulse logo (embedded so no separate image file is needed)
const LOGO_SRC = "data:image/png;base64,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";
export function Logo({ size = 34 }) {
  return <img className="logo-img" src={LOGO_SRC} width={size} height={size} alt="ArthPulse" />;
}


export function KpiGrid({ children }) {
  return <div className="kpi-grid">{children}</div>;
}

// Pick an icon from the card's label so every page gets sensible icons
// without each page having to name one.
const ICON_RULES = [
  [/RECEIVE|PAYABLE|OUTSTANDING|COLLECT/, "wallet"],
  [/STOCK|INVENTORY|ITEMS|SKU/, "coins"],
  [/PURCHASE|SUPPLIER/, "cart"],
  [/OVERDUE|RISK|ALERT|FINDING|FLAGGED|BREACH/, "alert"],
  [/COMPLIANCE|GST|TDS|MSME/, "shield"],
  [/CASH|PAYMENT|BANK|WORKING/, "rupee"],
  [/RETURN/, "down"],
  [/SALES|REVENUE|GROWTH|MARGIN|NET/, "trend"],
];

function iconFor(label, tone) {
  const hit = ICON_RULES.find(([re]) => re.test(String(label).toUpperCase()));
  if (hit) return hit[1];
  return tone === "warning" || tone === "negative" ? "alert" : "chart";
}

/**
 * tone: "positive" (green) | "warning" (orange) | "negative" (red) | "" (neutral)
 * spark: optional array of real numbers drawn as a small trend line
 */
export default function Kpi({ label, value, detail, tone = "", icon, spark }) {
  return (
    <article className={`kpi ${tone}`}>
      <div className="kpi-top">
        <span className="kpi-icon"><Icon name={icon || iconFor(label, tone)} size={20} /></span>
        <div className="kpi-text">
          <p>{label}</p>
          <strong>{value}</strong>
        </div>
        {spark && <Sparkline values={spark} tone={tone || "positive"} />}
      </div>
      <small className={`pill ${tone}`}>{detail}</small>
    </article>
  );
}
