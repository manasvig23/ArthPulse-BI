import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { DonutChart } from "../components/Charts.jsx";
import { downloadCsv, formatMoney, growthText } from "../format.js";

const columns = [
  { header: "PO no.", cell: r => r[0] },
  { header: "Supplier", cell: r => <b>{r[1]}</b> },
  { header: "Product", cell: r => r[2] },
  { header: "Purchased", cell: r => r[3] },
  { header: "Received", cell: r => r[4] },
  { header: "Variance", cell: r => r[5], className: r => (r[5] < 0 ? "negative" : "positive") },
  { header: "Debit note", cell: r => r[6] },
  { header: "Status", cell: r => <StatusBadge value={r[7]} /> },
];

export default function Purchases({ data, notify }) {
  const p = data.summary.purchases;

  const exportCsv = () => {
    downloadCsv("purchases", [["PO", "Supplier", "Product", "Purchased", "Received", "Variance", "Debit note", "Status"], ...data.purchases]);
    notify("purchases CSV downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="ANALYTICS / PURCHASES"
        title="Purchase dashboard"
        subtext="Supplier dependency, cost movement, returns, debit notes and stock reconciliation."
      >
        <button className="primary-button" onClick={exportCsv}>⇩ Export purchases CSV</button>
      </PageHeading>

      <KpiGrid>
        <Kpi label="TOTAL PURCHASES" value={formatMoney(p.total)} detail={growthText(p.growth)} tone={p.growth > 0 ? "negative" : "positive"} />
        <Kpi label="PURCHASE RETURNS" value={formatMoney(p.debit_note_value)} detail={`Debit notes: ${p.debit_notes}`} tone="warning" />
        <Kpi label="OPEN PURCHASE ORDERS" value={p.open_pos} detail={`${formatMoney(p.open_po_value)} committed`} />
        <Kpi label="SUPPLIER DEPENDENCY" value={`${p.top_share}%`} detail={`${p.top_supplier} share of spend`} tone={p.top_share > 40 ? "warning" : ""} />
      </KpiGrid>

      <div className="two-col">
        <article className="card">
          <p className="card-label">SUPPLIER DEPENDENCY</p><h2>Spend concentration</h2>
          <DonutChart items={p.supplier_spend} />
        </article>
        <article className="card">
          <p className="card-label">PRICE MOVEMENT</p><h2>Supplier price changes</h2>
          <div className="compact-list">
            {p.price_moves.length === 0 && <p className="empty">Not enough purchase history yet.</p>}
            {p.price_moves.map(item => (
              <div key={item[0] + item[2]}>
                <span><strong>{item[0]}</strong><br />{item[2]}</span>
                <b className={item[1].includes("↑") ? "negative" : "positive"}>{item[1]}</b>
              </div>
            ))}
          </div>
        </article>
      </div>

      <DataTable
        label="PURCHASE-TO-STOCK RECONCILIATION"
        title="Purchase order tracking"
        columns={columns}
        rows={data.purchases}
        placeholder="Search supplier, product or PO"
      />
    </section>
  );
}
