import { useMemo, useState } from "react";
import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { downloadCsv, formatMoney } from "../format.js";

const columns = [
  { header: "SKU", cell: r => r[0] },
  { header: "Product", cell: r => <b>{r[1]}</b> },
  { header: "Category", cell: r => r[2] },
  { header: "Branch / Godown", cell: r => r[3] },
  { header: "Quantity", cell: r => r[4], className: r => (r[4] < 0 ? "negative" : "") },
  { header: "Value", cell: r => formatMoney(r[5]) },
  { header: "Movement", cell: r => <StatusBadge value={r[6]} /> },
  { header: "Risk", cell: r => <StatusBadge value={r[7]} /> },
];

export default function Inventory({ data, notify }) {
  const i = data.summary.inventory;
  const [stockState, setStockState] = useState("all");

  const movement = useMemo(() => {
    const counts = {};
    data.inventory.forEach(r => { counts[r[6]] = (counts[r[6]] || 0) + 1; });
    return counts;
  }, [data.inventory]);

  const rows = useMemo(() => data.inventory.filter(r => {
    const healthy = r[7].toLowerCase().includes("healthy");
    return stockState === "all" || (stockState === "risk" ? !healthy : healthy);
  }), [data.inventory, stockState]);

  const exportCsv = () => {
    downloadCsv("inventory", [["SKU", "Product", "Category", "Location", "Quantity", "Value", "Movement", "Risk"], ...data.inventory]);
    notify("inventory CSV downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="ANALYTICS / INVENTORY"
        title="Inventory dashboard"
        subtext="Availability, value, movement, turnover and stock risk across locations."
      >
        <button className="primary-button" onClick={exportCsv}>⇩ Export inventory CSV</button>
      </PageHeading>

      <KpiGrid>
        <Kpi label="STOCK VALUE" value={formatMoney(i.stock_value)} detail="Across all branches and godowns" />
        <Kpi label="LOW-STOCK RISKS" value={i.low_stock} detail="Reorder required" tone="warning" />
        <Kpi label="NEGATIVE STOCK" value={i.negative} detail="Immediate stock correction" tone="negative" />
        <Kpi label="OVERSTOCK VALUE" value={formatMoney(i.overstock_value)} detail="Well above reorder level" tone="warning" />
      </KpiGrid>

      <div className="two-col">
        <article className="card">
          <p className="card-label">MOVEMENT CLASSIFICATION</p><h2>Fast, slow and non-moving</h2>
          <div className="segment-grid">
            {Object.entries(movement).map(([name, value]) => (
              <div key={name}><strong>{value}</strong><span>{name}</span></div>
            ))}
          </div>
        </article>
        <article className="card">
          <p className="card-label">INVENTORY EFFICIENCY</p><h2>Turnover and days of inventory</h2>
          <div className="compact-list">
            {i.efficiency.map(item => (
              <div key={item[0]}><span>{item[0]}</span><b>{item[1]}</b></div>
            ))}
          </div>
        </article>
      </div>

      <DataTable
        label="STOCK REGISTER"
        title="Product and location availability"
        columns={columns}
        rows={rows}
        placeholder="Search SKU, product or branch"
        extra={
          <select value={stockState} onChange={e => setStockState(e.target.value)}>
            <option value="all">All stock states</option>
            <option value="risk">At risk</option>
            <option value="healthy">Healthy</option>
          </select>
        }
      />
    </section>
  );
}
