# ArthPulse frontend (React + Vite)

Needs the backend running first:  `uvicorn app.main:app --reload --port 8000`

    npm install
    npm run dev          # opens on http://localhost:5173

If the backend is not on http://127.0.0.1:8000, copy `.env.example` to `.env`
and change VITE_API_BASE.

## Layout
    src/api.js            fetches /api/* endpoints (useDashboardData hook)
    src/format.js         money / growth / CSV helpers
    src/App.jsx           sidebar, topbar, page routing, period filter, theme, toasts
    src/pages/            Overview, Sales, Purchases, Inventory, CashFlow, Alerts, Reports
    src/components/       Kpi, DataTable, ProgressList, StatusBadge, Charts (Recharts)
    src/styles.css        same stylesheet as the old HTML version + small additions

## Known gaps
- "Mark selected collected" only hides rows in this browser session (needs a backend endpoint to persist).
- "Download report" is plain text; "Print / save as PDF" uses the browser's print dialog.
- No login / roles yet.
