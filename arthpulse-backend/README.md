# ArthPulse Backend (tonight's version)

FastAPI + SQLite. Real voucher-shaped data, real aggregation queries,
one working compliance rule (Section 269ST split-cash detection).

## Run it

```
pip install -r requirements.txt
python -m app.seed        # populates arthpulse.db, safe to re-run
uvicorn app.main:app --reload --port 8000
```

Visit http://127.0.0.1:8000/docs for interactive API docs (auto-generated
by FastAPI — good to have open during the review to show it's a real API,
not a screenshot).

## Endpoints

| Endpoint | Returns | Matches frontend variable |
|---|---|---|
| GET /api/sales | array of arrays | `salesData` |
| GET /api/purchases | array of arrays | `purchaseData` |
| GET /api/inventory | array of arrays | `inventoryData` |
| GET /api/payments | array of arrays | `paymentData` |
| GET /api/alerts | array of arrays | `alertData` |

Every array's column order matches the corresponding hardcoded array
already in `app.js` exactly — this was intentional so the frontend swap
is a drop-in, not a rewrite of the render functions.

## Hand this to whoever's doing the frontend

In `app.js`, replace the five `const ...Data = [...]` declarations with:

```javascript
const API_BASE = "http://127.0.0.1:8000";

let salesData = [];
let purchaseData = [];
let inventoryData = [];
let paymentData = [];
let alertData = [];

async function loadData() {
  [salesData, purchaseData, inventoryData, paymentData, alertData] = await Promise.all([
    fetch(`${API_BASE}/api/sales`).then(r => r.json()),
    fetch(`${API_BASE}/api/purchases`).then(r => r.json()),
    fetch(`${API_BASE}/api/inventory`).then(r => r.json()),
    fetch(`${API_BASE}/api/payments`).then(r => r.json()),
    fetch(`${API_BASE}/api/alerts`).then(r => r.json()),
  ]);
}
```

Then wrap whatever currently runs on page load (the initial `renderOverview()`
/ navigation setup) so it runs *after* `await loadData()` instead of
immediately — e.g. wrap the bottom of the file's init code in:

```javascript
loadData().then(() => {
  // existing init/render calls go here
});
```

The backend must be running (`uvicorn ...` above) before the frontend
loads, or the fetch calls will fail. CORS is already open (`allow_origins:
["*"]`) so this works from `python -m http.server` or any local dev server.

## What's real vs. what's still a stub

- **Real:** SQL aggregation over a Tally-shaped voucher table, negative
  stock / low stock / overdue-payment alerts computed from actual data,
  Section 269ST split-cash detection (see `app/rules.py:check_section_269st`).
- **Sample data, not live Tally:** `app/seed.py` hand-written to be
  realistic, not pulled from a live Tally instance — say this plainly in
  the review rather than implying it's a live sync.
- **Not built yet:** GST DRC-01B/C mismatch checks, Section 393 TDS
  tracking, AI recommendation cards, AI chat assistant, role-based views,
  PostgreSQL (swap is one line in `app/database.py` when you're ready).
