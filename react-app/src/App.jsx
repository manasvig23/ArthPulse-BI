import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, getToken, setToken, useDashboardData } from "./api.js";
import { downloadCsv } from "./format.js";
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
  { title: "BUSINESS INTELLIGENCE", items: [["overview", "⌘ Overview"]] },
  { title: "ANALYTICS", items: [["sales", "↗ Sales"], ["purchases", "↓ Purchases"], ["inventory", "□ Inventory"], ["cashflow", "₹ Cash Flow"]] },
  { title: "WORKSPACE", items: [["compliance", "⚖ Compliance"], ["alerts", "● Alert Centre"], ["reports", "▤ Reports"]] },
  { title: "ADMINISTRATION", items: [["access", "⚙ Access control"]] },
];

const PERIODS = [
  ["monthly", "This month"], ["weekly", "This week"], ["daily", "Today"], ["yearly", "This year"],
];
const PERIOD_AWARE = ["overview", "sales", "purchases", "reports"];

const initials = name => name.split(" ").map(p => p[0]).slice(0, 2).join("").toUpperCase();

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

  const onPeriodChange = value => {
    setPeriod(value);
    notify(`Dashboard updated for ${PERIODS.find(p => p[0] === value)[1].toLowerCase()}.`);
  };

  const Page = PAGES[page].component;
  const needsData = page !== "access";

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <a className="brand" href={`#${allowed[0]}`} onClick={() => setMenuOpen(false)}>
          <span className="brand-mark">A</span>Arth<span>Pulse</span>
        </a>

        <nav className="nav">
          {NAV.map(group => {
            const items = group.items.filter(([id]) => allowed.includes(id));
            if (!items.length) return null;
            return (
              <div key={group.title}>
                <p className="nav-title">{group.title}</p>
                {items.map(([id, label]) => (
                  <button key={id} className={`nav-link ${page === id ? "active" : ""}`} onClick={() => navigate(id)}>
                    {label}
                    {id === "alerts" && <b>{data ? data.alerts.length : 0}</b>}
                  </button>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <div className="ai-card">✦ <span><strong>Arth AI</strong><small>Coming soon</small></span></div>
          <div className="user-block">
            <span className="avatar">{initials(user.full_name)}</span>
            <span className="user-meta"><strong>{user.full_name}</strong><small>{user.role_label}</small></span>
          </div>
          <div className="user-actions">
            <button onClick={() => setDark(d => !d)}>◐ Theme</button>
            <button onClick={onSignOut}>⎋ Sign out</button>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMenuOpen(o => !o)}>☰</button>
          <div className="breadcrumbs">ArthPulse <span>/</span> <strong>{PAGES[page].label}</strong></div>

          <div className="top-actions">
            {PERIOD_AWARE.includes(page) && (
              <select value={period} onChange={e => onPeriodChange(e.target.value)} aria-label="Select reporting period">
                {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
            {needsData && <button className="primary-button" onClick={exportCurrent}>⇩ Export current view</button>}
          </div>
        </header>

        {user.default_password && (
          <div className="default-banner">
            <span>⚠ You are still using the default administrator password. Anyone who knows it can sign in as admin.</span>
            <button className="secondary-button" onClick={() => navigate("access")}>Change it now</button>
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

      <div className={`toast ${toast ? "show" : ""}`}>{toast}</div>
    </div>
  );
}