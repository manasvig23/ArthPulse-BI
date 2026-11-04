import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import ProgressList from "../components/ProgressList.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { TrendChart } from "../components/Charts.jsx";
import { downloadCsv, formatMoney, growthTone } from "../format.js";

const columns = [
  { header: "Customer", cell: r => <b>{r[0]}</b> },
  { header: "Product", cell: r => r[1] },
  { header: "Territory", cell: r => r[2] },
  { header: "Salesperson", cell: r => r[3] },
  { header: "Net sales", cell: r => formatMoney(r[4] - r[5]) },
  { header: "Returns", cell: r => formatMoney(r[5]), className: r => (r[5] ? "negative" : "") },
  { header: "Segment", cell: r => <StatusBadge value={r[6]} /> },
];

export default function Sales({ data, notify }) {
  const s = data.summary.sales;
  const trend = s.trend;
  const explanation = data.explainability;
  const exportCsv = () => {
    downloadCsv("sales", [["Customer", "Product", "Territory", "Salesperson", "Sales", "Returns", "Segment"], ...data.sales]);
    notify("sales CSV downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="ANALYTICS / SALES"
        title="Sales dashboard"
        subtext="Sales, returns, customers, products, territories and cross-sell opportunities."
      >
        <button className="primary-button" onClick={exportCsv}>⇩ Export sales CSV</button>
      </PageHeading>

      <KpiGrid>
        <Kpi label="TOTAL SALES" value={formatMoney(s.gross)} detail="Gross billed sales" />
        <Kpi label="NET SALES" value={formatMoney(s.net)} detail={`Returns: ${formatMoney(s.returns)}`} tone="positive" />
        <Kpi label="SALES RETURNS" value={formatMoney(s.returns)} detail={`${s.returns_pct}% of gross sales`} tone="warning" />
        <Kpi
          label="GROWTH"
          value={s.growth === null ? "n/a" : Math.abs(s.growth) > 500 ? ">500%" : `${s.growth}%`}
          detail="Net sales vs prior period"
          tone={growthTone(s.growth)}
        />
      </KpiGrid>

      <div className="two-col">
        <article className="card">
          <p className="card-label">GROWTH TREND</p><h2>Gross and net sales</h2>
          <TrendChart
            type="line"
            labels={trend.labels}
            series={[{ name: "Gross sales", values: trend.gross }, { name: "Net sales", values: trend.net }]}
          />
        </article>
        <article className="card">
          <p className="card-label">TERRITORY PERFORMANCE</p><h2>Sales by territory</h2>
          <ProgressList items={s.territories} />
        </article>
      </div>

      <div className="two-col">
        <article className="card">
          <p className="card-label">CUSTOMER SEGMENTATION</p><h2>Customer health</h2>
          <div className="segment-grid">
            {Object.entries(s.segments).map(([name, value]) => (
              <div key={name}><strong>{value}</strong><span>{name} customers</span></div>
            ))}
          </div>
        </article>
        <article className="card">
          <p className="card-label">CROSS-SELL OPPORTUNITIES</p><h2>Products to recommend</h2>
          <div className="compact-list">
            {s.cross_sell.length === 0 && <p className="empty">No cross-sell gaps found.</p>}
            {s.cross_sell.map(item => (
              <div key={item[0]}>
                <span><strong>{item[0]}</strong><br />{item[1]}</span>
                <b>{item[2]}</b>
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="card">
  <div className="card-header">
    <div>
      <p className="card-label">AI / EXPLAINABILITY</p>
      <h2>What influences sales?</h2>
    </div>
    <span className="subtext">
      {explanation?.method === "none"
        ? "Insufficient data"
        : explanation?.method?.startsWith("SHAP")
          ? "SHAP analysis"
          : explanation?.method
            ? "Fallback analysis"
            : "Loading analysis"}
    </span>
  </div>

  {!explanation ? (
    <p className="empty">Sales-driver analysis is not available yet.</p>
  ) : explanation.drivers?.length > 0 ? (
    <>
      <p className="subtext">{explanation.plain_english}</p>

      <div className="compact-list">
        {explanation.drivers.map((driver, index) => (
          <div key={`${driver.factor}-${index}`}>
            <span>
              <strong>{driver.factor}</strong>
              <br />
              <small>Relative importance score</small>
            </span>
            <div style={{ minWidth: 110, textAlign: "right" }}>
  <b>{Number(driver.impact_score).toFixed(3)}</b>
  <div
    style={{
      width: 110,
      height: 5,
      marginTop: 6,
      background: "var(--border, #e5e7eb)",
      borderRadius: 10,
      overflow: "hidden",
    }}
  >
    <div
      style={{
        height: "100%",
        width: `${Math.max(
          0,
          Math.min(100, Number(driver.impact_score) * 100)
        )}%`,
        background: "var(--accent, #64748b)",
        borderRadius: 10,
      }}
    />
    </div>
  </div>
          </div>
        ))}
      </div>

      <p className="subtext" style={{ marginTop: 14 }}>
        Method: {explanation.method}
        {explanation.as_of && ` · Data through ${explanation.as_of}`}
      </p>
      <p className="subtext">
        These scores indicate model importance, not whether a factor
        increases or decreases sales. Associations do not establish causation.
      </p>
    </>
  ) : (
    <p className="empty">
      {explanation.plain_english ||
        "There is not enough sales data to identify reliable drivers for this period."}
    </p>
  )}
</article>

      <DataTable
        label="CUSTOMER & PRODUCT ANALYSIS"
        title="Top and bottom contributors"
        columns={columns}
        rows={data.sales}
        placeholder="Search customer, product or salesperson"
      />
    </section>
  );
}
