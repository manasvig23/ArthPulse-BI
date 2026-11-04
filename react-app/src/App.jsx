import { useCallback, useEffect, useRef, useState } from "react";
import { downloadBinary, getJson, getToken, setToken, useDashboardData } from "./api.js";
import { downloadCsv, formatMoney } from "./format.js";
import { Icon, Logo } from "./components/Kpi.jsx";
import Login from "./pages/Login.jsx";
import Overview from "./pages/Overview.jsx";
import Sales from "./pages/Sales.jsx";
import Purchases from "./pages/Purchases.jsx";
import Inventory from "./pages/Inventory.jsx";
import CashFlow from "./pages/CashFlow.jsx";
import Compliance from "./pages/Compliance.jsx";
import Alerts from "./pages/Alerts.jsx";
import Reports from "./pages/Reports.jsx";
import Access from "./pages/Access.jsx";
import AIChatDrawer from "./components/AIChatDrawer.jsx";
import "./auth.css";

// `area` is the permission a role needs (see ROLES in backend app/auth.py)
const PAGES = {
  overview: { label: "Overview", area: "overview", component: Overview },
  sales: { label: "Sales", area: "sales", component: Sales },
  purchases: { label: "Purchases", area: "purchases", component: Purchases },
  inventory: { label: "Inventory", area: "inventory", component: Inventory },
  cashflow: { label: "Cash Flow", area: "cashflow", component: CashFlow },
  compliance: { label: "Compliance", area: "compliance", component: Compliance },
  alerts: { label: "Alert Centre", area: "alerts", component: Alerts },
  reports: { label: "Reports", area: "reports", component: Reports },
  access: { label: "Access control", area: "users", component: Access },
};

const NAV = [
  { title: "BUSINESS INTELLIGENCE", items: [["overview", "overview"]] },
  { title: "ANALYTICS", items: [["sales", "trend"], ["purchases", "down"], ["inventory", "folder"], ["cashflow", "rupee"]] },
  { title: "WORKSPACE", items: [["compliance", "shield"], ["alerts", "bell"], ["reports", "file"]] },
  { title: "ADMINISTRATION", items: [["access", "gear"]] },
];

const PERIODS = [
  ["monthly", "This month"], ["weekly", "This week"], ["daily", "Today"], ["yearly", "This year"],
];
const PERIOD_AWARE = ["overview", "sales", "purchases", "reports"];

const initials = name => name.split(" ").map(p => p[0]).slice(0, 2).join("").toUpperCase();

// Small status chips shown beside sidebar items, computed from the loaded data.
function navBadges(data) {
  if (!data) return {};
  const s = data.summary || {};
  const out = {};

  const g = s.sales?.growth;
  if (g !== null && g !== undefined && Math.abs(g) <= 500) {
    out.sales = { text: `${g >= 0 ? "+" : ""}${g}%`, tone: g >= 0 ? "good" : "bad" };
  }
  if (s.purchases) out.purchases = { text: formatMoney(s.purchases.total), tone: "plain" };

  const risks = (s.inventory?.low_stock || 0) + (s.inventory?.negative || 0);
  if (s.inventory && risks > 0) out.inventory = { text: `${risks} ${risks === 1 ? "risk" : "risks"}`, tone: "warn" };

  if (s.cashflow) out.cashflow = { dot: (s.cashflow.overdue_receivables || 0) > 0 ? "warn" : "good" };

  if (data.compliance) {
    const n = data.compliance.summary.rules_at_risk;
    out.compliance = n > 0 ? { text: `${n} at risk`, tone: "bad" } : { text: "✓ OK", tone: "good" };
  }
  if (data.alerts.length) out.alerts = { text: String(data.alerts.length), tone: "danger" };
  return out;
}

function UserMenu({ user, dark, onToggleTheme, onSignOut, onOpenAccess }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const closeEsc = e => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeEsc);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeEsc);
    };
  }, [open]);

  return (
    <div className="user-menu" ref={ref}>
      <button className="user-pill" onClick={() => setOpen(o => !o)} aria-haspopup="menu" aria-expanded={open}>
        <span className="avatar">{initials(user.full_name)}</span>
        <span className="user-meta"><strong>{user.full_name}</strong><small>{user.role_label}</small></span>
        <Icon name="chevron" size={16} />
      </button>

      {open && (
        <div className="menu" role="menu">
          <div className="menu-head"><strong>{user.full_name}</strong><small>@{user.username} · {user.role_label}</small></div>
          {onOpenAccess && (
            <button role="menuitem" onClick={() => { setOpen(false); onOpenAccess(); }}>
              <Icon name="key" size={16} /> Access control
            </button>
          )}
          <button role="menuitem" onClick={() => { onToggleTheme(); setOpen(false); }}>
            <Icon name={dark ? "sun" : "moon"} size={16} /> {dark ? "Light theme" : "Dark theme"}
          </button>
          <button role="menuitem" className="danger" onClick={onSignOut}>
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ root
export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(() => !!getToken());

  // returning visitor: confirm the saved token is still good
  useEffect(() => {
    if (!getToken()) return;
    getJson("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setChecking(false));
  }, []);

  // re-reads the signed-in user (e.g. after they change their own password)
  const refreshUser = useCallback(() => {
    getJson("/api/auth/me").then(setUser).catch(() => {});
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    window.history.replaceState(null, "", window.location.pathname);
  }, []);

  if (checking) return <div className="login-shell"><p className="subtext">Loading…</p></div>;
  if (!user) return <Login onSignedIn={setUser} />;
  return <Dashboard user={user} onSignOut={signOut} onUserChanged={refreshUser} />;
}

// ------------------------------------------------------------- dashboard
function Dashboard({ user, onSignOut, onUserChanged }) {
  const allowed = Object.keys(PAGES).filter(id => user.areas.includes(PAGES[id].area));
  const pageFromHash = () => {
    const id = window.location.hash.replace("#", "");
    return allowed.includes(id) ? id : allowed[0];
  };

  const [page, setPage] = useState(pageFromHash);
  const [period, setPeriod] = useState("monthly");
  const [dark, setDark] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [confirmOut, setConfirmOut] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const toastTimer = useRef(null);

  const { data, loading, error, reload } = useDashboardData(period, user.areas, onSignOut);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }); // re-bound each render so it always sees the current allowed list

  useEffect(() => { document.body.classList.toggle("dark", dark); }, [dark]);

  const notify = useCallback(message => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2600);
  }, []);

  const navigate = id => {
    if (!allowed.includes(id)) return notify("Your role cannot open that section.");
    window.location.hash = id;
    setPage(id);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const exportCurrent = () => {
    if (!data) return notify("Nothing to export yet.");
    const o = data.summary?.overview;
    const sources = {
      overview: o && [
        ["Metric", "Value"], ["Period", data.summary.label], ["Net sales", o.net_sales],
        ["Sales less purchases", o.sales_less_purchases], ["Receivables", o.receivables],
        ["Overdue receivables", o.overdue], ["Stock value", o.stock_value],
      ],
      sales: data.sales, purchases: data.purchases, inventory: data.inventory,
      cashflow: data.payments, alerts: data.alerts,
      compliance: data.compliance && [
        ["Rule", "Severity", "Party", "Finding", "Amount flagged", "Recommended action"],
        ...data.compliance.rules.flatMap(r => r.findings.map(f =>
          [r.name, f.severity, f.party, f.title, f.exposure, f.action])),
      ],
    };
    const rows = sources[page];
    if (!rows) return notify("Nothing to export on this page.");
    downloadCsv(page, rows);
    notify(`${PAGES[page].label} CSV downloaded.`);
  };

  const exportExcel = async () => {
    try {
      await downloadBinary(`/api/export/excel?period=${period}`, `arthpulse-${period}.xlsx`);
      notify("Excel workbook downloaded.");
    } catch (e) { notify(e.message); }
  };
  const exportPdf = async () => {
    try {
      await downloadBinary(`/api/export/pdf?period=${period}`, `arthpulse-${period}.pdf`);
      notify("PDF report downloaded.");
    } catch (e) { notify(e.message); }
  };

  const onPeriodChange = value => {
    setPeriod(value);
    notify(`Dashboard updated for ${PERIODS.find(p => p[0] === value)[1].toLowerCase()}.`);
  };

  const Page = PAGES[page].component;
  const needsData = page !== "access";
  const badges = navBadges(data);
  const alertCount = data ? data.alerts.length : 0;

  const insight = (() => {
    if (!data) return "Reading your data…";
    const c = data.compliance?.summary;
    if (c && c.findings > 0) {
      return `${c.findings} compliance ${c.findings === 1 ? "finding needs" : "findings need"} review. ${formatMoney(c.amount_flagged)} flagged.`;
    }
    if (alertCount > 0) return `${alertCount} ${alertCount === 1 ? "alert needs" : "alerts need"} your attention.`;
    return "No open risks right now.";
  })();
  const insightTarget = allowed.includes("compliance") ? "compliance" : allowed.includes("alerts") ? "alerts" : allowed[0];

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="workspace-pulse">
          <span>WORKSPACE PULSE</span>
          <em className={`live ${error ? "off" : ""}`}><i />{error ? "OFFLINE" : "CONNECTED"}</em>
        </div>

        <nav className="nav">
          {NAV.map(group => {
            const items = group.items.filter(([id]) => allowed.includes(id));
            if (!items.length) return null;
            return (
              <div key={group.title}>
                <p className="nav-title">{group.title}</p>
                {items.map(([id, icon]) => {
                  const badge = badges[id];
                  return (
                    <button key={id} className={`nav-link ${page === id ? "active" : ""}`} onClick={() => navigate(id)}>
                      <Icon name={icon} size={18} />
                      <span className="nav-label">{PAGES[id].label}</span>
                      {badge?.text && <b className={`chip ${badge.tone}`}>{badge.text}</b>}
                      {badge?.dot && <i className={`status-dot ${badge.dot}`} />}
                      {!badge && page === id && <i className="status-dot active-dot" />}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div className="copilot">
          <div className="copilot-head">
            <span className="copilot-icon"><Icon name="spark" size={14} /></span>
            <strong>Arth AI Copilot</strong>
          </div>
            <p>{insight}</p>
            <button onClick={() => setChatOpen(true)}>Ask AI Assistant <Icon name="arrow" size={14} /></button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMenuOpen(o => !o)} aria-label="Open menu">☰</button>
          <a className="brand-pill" href={`#${allowed[0]}`} onClick={() => setMenuOpen(false)}>
            <Logo size={38} />
            <span>Arth<b>Pulse</b></span>
          </a>

          <div className="top-actions">
            {PERIOD_AWARE.includes(page) && (
              <select value={period} onChange={e => onPeriodChange(e.target.value)} aria-label="Select reporting period">
                {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
            {needsData && (
              <>
                <button className="secondary-button" onClick={exportExcel}>Excel</button>
                <button className="secondary-button" onClick={exportPdf}>PDF</button>
                <button className="primary-button" onClick={exportCurrent}>⇩ CSV</button>
              </>
            )}
            <button
              className="bell"
              aria-label={`Alerts (${alertCount})`}
              onClick={() => navigate(allowed.includes("alerts") ? "alerts" : allowed[0])}
            >
              <Icon name="bell" size={18} />
              {alertCount > 0 && <i className="bell-dot" />}
            </button>
            <UserMenu
              user={user}
              dark={dark}
              onToggleTheme={() => setDark(d => !d)}
              onSignOut={() => setConfirmOut(true)}
              onOpenAccess={allowed.includes("access") ? () => navigate("access") : null}
            />
            <button className="signout-button" onClick={() => setConfirmOut(true)} title="Sign out">
              <Icon name="logout" size={16} /><span>Sign out</span>
            </button>
          </div>
        </header>

        {user.default_password && (
          <div className="default-banner">
            <span>⚠ You are still using the default administrator password. Anyone who knows it can sign in as admin.</span>
            <button className="secondary-button" onClick={() => navigate("access")}>Change it now</button>
          </div>
        )}

        {data?.quality?.warnings?.length > 0 && (
          <div className="default-banner">
            <span>{data.quality.warnings[0]} Last update: {data.sync?.last?.finished_at || data.sync?.last?.started_at || "never"} ({data.sync?.last?.source || "unknown source"}).</span>
            {allowed.includes("access") && (
              <button className="secondary-button" onClick={() => navigate("access")}>Tally sync</button>
            )}
          </div>
        )}

        {needsData && error && (
          <div className="page active" style={{ paddingBottom: 0 }}>
            <div className="state-banner error">
              <span>
                {error instanceof TypeError
                  ? <>Could not reach the backend. Is <code>uvicorn app.main:app --port 8000</code> running?</>
                  : error.message}
              </span>
              <button className="secondary-button" onClick={reload}>Retry</button>
            </div>
          </div>
        )}

        {needsData && !data && loading && (
          <div className="page active"><div className="state-banner loading">Loading dashboard…</div></div>
        )}

        {(data || !needsData) && <Page data={data} notify={notify} onNavigate={navigate} user={user} onUserChanged={onUserChanged} />}
      </main>

      {confirmOut && (
        <div className="modal-backdrop" onClick={() => setConfirmOut(false)}>
          <div className="modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
            <h3>Log out?</h3>
            <p>Are you sure you want to log out?</p>
            <div className="modal-actions">
              <button className="secondary-button" autoFocus onClick={() => setConfirmOut(false)}>Cancel</button>
              <button className="danger-button" onClick={onSignOut}>Yes, log out</button>
            </div>
          </div>
        </div>
      )}

      {chatOpen && <AIChatDrawer onClose={() => setChatOpen(false)} period={period} />}

      <div className={`toast ${toast ? "show" : ""}`}>{toast}</div>
    </div>
  );
}