import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { TrendChart } from "../components/Charts.jsx";
import { formatMoney, growthText, growthTone } from "../format.js";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function Overview({ data, onNavigate, user }) {
  const o = data.summary.overview;

  return (
    <section className="page active">
      <PageHeading
        eyebrow="BUSINESS OVERVIEW"
        title={<>{greeting()}, {user?.full_name || "there"}<br />Here’s your business pulse</>}
        subtext="Performance, collections, stock and risks in one view."
      />

      <KpiGrid>
        <Kpi label="NET SALES" value={formatMoney(o.net_sales)} detail={growthText(o.growth)} tone={growthTone(o.growth)} spark={o.trend.net} />
        <Kpi
          label="SALES LESS PURCHASES"
          value={formatMoney(o.sales_less_purchases)}
          detail={`${o.margin_pct}% of net sales (margin proxy, no cost data)`}
          tone={o.sales_less_purchases >= 0 ? "positive" : "negative"}
        />
        <Kpi label="RECEIVABLES" value={formatMoney(o.receivables)} detail={`${formatMoney(o.overdue)} overdue`} tone="warning" />
        <Kpi label="STOCK VALUE" value={formatMoney(o.stock_value)} detail={`${o.replenishment_risks} replenishment risks`} tone="warning" />
      </KpiGrid>

      <div className="two-col">
        <article className="card">
          <div className="card-header">
            <div><p className="card-label">SALES TREND</p><h2>Net sales by month</h2></div>
            <button className="ghost-button" onClick={() => onNavigate("sales")}>View sales →</button>
          </div>
          <TrendChart labels={o.trend.labels} series={[{ name: "Net sales", values: o.trend.net }]} />
        </article>

        <article className="card">
          <div className="card-header">
            <div><p className="card-label">PRIORITY RISKS</p><h2>Needs attention</h2></div>
            <button className="ghost-button" onClick={() => onNavigate("alerts")}>All alerts →</button>
          </div>
          {data.alerts.slice(0, 4).map((alert, i) => (
            <div className="compact-list" key={i}>
              <div>
                <span>{alert[1]}<br /><small>{alert[2]}</small></span>
                <StatusBadge value={alert[0]} />
              </div>
            </div>
          ))}
          {data.alerts.length === 0 && <p className="empty">No active alerts.</p>}
        </article>
      </div>
    </section>
  );
}
