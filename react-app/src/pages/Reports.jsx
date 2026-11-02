import { useState } from "react";
import PageHeading from "../components/PageHeading.jsx";
import { downloadText, formatMoney } from "../format.js";

const ALL_OPTIONS = ["Sales performance", "Purchase health", "Inventory health", "Cash flow", "Risks and alerts"];

export default function Reports({ data, notify, user }) {
  const { summary, alerts } = data;
  const s = summary.sales, p = summary.purchases, i = summary.inventory, c = summary.cashflow;

  // a role only sees the report blocks for the areas it may open
  const available = {
    "Sales performance": !!s, "Purchase health": !!p, "Inventory health": !!i,
    "Cash flow": !!c, "Risks and alerts": !!user?.areas?.includes("alerts"),
  };
  const OPTIONS = ALL_OPTIONS.filter(o => available[o]);
  const [selected, setSelected] = useState(OPTIONS.slice(0, 4));
  const descriptions = {
    "Sales performance": s && `Net sales ${formatMoney(s.net)} (${s.growth === null ? "no prior-period data" : s.growth + "% vs previous period"}) for ${summary.label.toLowerCase()}.`,
    "Purchase health": p && `${formatMoney(p.total)} purchases; ${p.top_supplier} is ${p.top_share}% of spend.`,
    "Inventory health": i && `${formatMoney(i.stock_value)} stock value, ${i.low_stock} low-stock and ${i.negative} negative-stock risk(s).`,
    "Cash flow": c && `${formatMoney(c.receivables)} receivables, ${formatMoney(c.payables)} payables, cash conversion cycle ${c.working_capital[3][1]}.`,
    "Risks and alerts": `${alerts.length} active alerts need review.`,
  };

  const toggle = option =>
    setSelected(cur => (cur.includes(option) ? cur.filter(o => o !== option) : [...cur, option]));

  const download = () => {
    const body = OPTIONS.filter(o => selected.includes(o)).map(o => `${o}\n  ${descriptions[o]}`).join("\n\n");
    downloadText("arthpulse-executive-report.txt",
      `ARTHPULSE EXECUTIVE REPORT (${summary.label}, ${summary.window.start} to ${summary.window.end})\n\n${body}\n`);
    notify("Executive report downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="WORKSPACE / REPORTS"
        title="Executive reports"
        subtext="Select report blocks and download an operating summary."
      >
        <div className="report-actions">
          <button className="secondary-button" onClick={() => window.print()}>🖶 Print / save as PDF</button>
          <button className="primary-button" onClick={download}>⇩ Download report</button>
        </div>
      </PageHeading>

      <div className="card report-builder">
        <div><p className="card-label">REPORT BUILDER</p><h2>Choose content</h2></div>
        <div className="report-options">
          {OPTIONS.map(option => (
            <label key={option}>
              <input type="checkbox" checked={selected.includes(option)} onChange={() => toggle(option)} /> {option}
            </label>
          ))}
        </div>
      </div>

      <div className="card report-preview">
        <p className="card-label">EXECUTIVE REPORT PREVIEW</p>
        <h2>Business performance summary</h2>
        <div>
          {OPTIONS.filter(o => selected.includes(o)).map(option => (
            <article key={option}><strong>{option}</strong><span>{descriptions[option]}</span></article>
          ))}
        </div>
      </div>
    </section>
  );
}
