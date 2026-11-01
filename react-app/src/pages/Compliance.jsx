import { useState } from "react";
import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { downloadCsv, formatInr, formatMoney } from "../format.js";
import "../compliance.css";

const STATUS_CLASS = { Flag: "risk", "Minor gap": "warning", OK: "" };

function MiniTable({ columns, rows }) {
  return (
    <div className="table-scroll">
      <table className="mini-table">
        <thead><tr>{columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>
                  {cell in STATUS_CLASS
                    ? <span className={`status ${STATUS_CLASS[cell]}`}>{cell}</span>
                    : cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Finding({ f }) {
  return (
    <article className={`finding ${f.severity}`}>
      <div className="finding-head">
        <div>
          <StatusBadge value={f.severity} /> <strong>{f.title}</strong>
          <span className="finding-party">{f.party}</span>
        </div>
        <div className="exposure">
          <b>{formatInr(f.exposure)}</b>
          <small>{f.exposure_kind}</small>
        </div>
      </div>
      <p className="finding-summary">{f.summary}</p>
      <div className="callout"><strong>RECOMMENDED ACTION</strong>{f.action}</div>
      <details>
        <summary>Evidence ({f.evidence.rows.length} {f.evidence.rows.length === 1 ? "row" : "rows"})</summary>
        <MiniTable columns={f.evidence.columns} rows={f.evidence.rows} />
      </details>
    </article>
  );
}

export default function Compliance({ data, notify }) {
  const report = data.compliance;
  const { summary } = report;
  const [activeId, setActiveId] = useState(
    (report.rules.find(r => r.status === "at_risk") || report.rules[0]).id
  );
  const rule = report.rules.find(r => r.id === activeId) || report.rules[0];

  const exportCsv = () => {
    const rows = report.rules.flatMap(r =>
      r.findings.map(f => [r.name, f.severity, f.party, f.title, f.exposure, f.exposure_kind, f.action]));
    downloadCsv("compliance-findings", [
      ["Rule", "Severity", "Party", "Finding", "Amount flagged", "Type of exposure", "Recommended action"], ...rows,
    ]);
    notify("Compliance findings CSV downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="WORKSPACE / COMPLIANCE"
        title="Compliance engine"
        subtext="Cash limits, GST credit, MSME payments and TDS, checked against your own vouchers."
      >
        <button className="primary-button" onClick={exportCsv}>⇩ Export findings CSV</button>
      </PageHeading>

      <div className="state-banner warn"><span>{report.disclaimer}</span></div>

      <KpiGrid>
        <Kpi label="RULES AT RISK" value={`${summary.rules_at_risk} of ${summary.rules}`} detail="Rules with at least one finding" tone={summary.rules_at_risk ? "negative" : "positive"} />
        <Kpi label="FINDINGS" value={summary.findings} detail="Each has evidence and an action" tone="warning" />
        <Kpi label="HIGH SEVERITY" value={summary.high} detail="Fix these first" tone={summary.high ? "negative" : "positive"} />
        <Kpi label="AMOUNT FLAGGED" value={formatMoney(summary.amount_flagged)} detail="Mixed: penalties, credit, tax, expense" tone="warning" />
      </KpiGrid>

      <div className="rule-tabs">
        {report.rules.map(r => (
          <button key={r.id} className={`rule-tab ${r.id === rule.id ? "active" : ""}`} onClick={() => setActiveId(r.id)}>
            {r.name}<b className={r.status}>{r.findings.length}</b>
          </button>
        ))}
      </div>

      <article className="card">
        <div className="rule-head">
          <div>
            <p className="card-label">{rule.law.toUpperCase()}</p>
            <h2>{rule.name}</h2>
          </div>
          <span className={`status ${rule.status === "at_risk" ? "risk" : ""}`}>
            {rule.status === "at_risk" ? "At risk" : "All clear"}
          </span>
        </div>
        <p className="rule-explain">{rule.explain}</p>
        <p className={`headline ${rule.status}`}>{rule.headline}</p>

        <ul className="settings-list">
          {rule.settings.map(([label, value, kind]) => (
            <li key={label}><span>{label}</span><b>{value}</b><em className={`tag ${kind}`}>{kind}</em></li>
          ))}
        </ul>

        {rule.findings.length > 0 && <p className="section-title">FINDINGS</p>}
        {rule.findings.map((f, i) => <Finding key={i} f={f} />)}

        {rule.watch.length > 0 && (
          <>
            <p className="section-title">CLOSE TO THE LIMIT (NOT FLAGGED)</p>
            <ul className="pill-list watch">{rule.watch.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </>
        )}

        {rule.ok.length > 0 && (
          <>
            <p className="section-title">CHECKED AND CORRECT</p>
            <ul className="pill-list good">{rule.ok.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </>
        )}

        {rule.tables.map(t => (
          <div key={t.title}>
            <p className="section-title">{t.title.toUpperCase()}</p>
            <MiniTable columns={t.columns} rows={t.rows} />
          </div>
        ))}

        {rule.notes.length > 0 && (
          <>
            <p className="section-title">LIMITS OF THIS CHECK</p>
            <ul className="note-list">{rule.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </>
        )}
      </article>

      <article className="card" style={{ marginTop: 18 }}>
        <p className="card-label">NOT COVERED YET</p>
        <ul className="note-list">{report.not_covered.map(n => <li key={n}>{n}</li>)}</ul>
      </article>
    </section>
  );
}