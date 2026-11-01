import { useMemo, useState } from "react";
import Kpi, { KpiGrid } from "../components/Kpi.jsx";
import PageHeading from "../components/PageHeading.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { BucketChart } from "../components/Charts.jsx";
import { downloadCsv, formatMoney } from "../format.js";

const columns = [
  { header: "Invoice", cell: r => r[0] },
  { header: "Party", cell: r => <b>{r[1]}</b> },
  { header: "Type", cell: r => r[2] },
  { header: "Due date", cell: r => r[3] },
  { header: "Amount", cell: r => formatMoney(r[4]) },
  { header: "Ageing", cell: r => r[5] },
  { header: "Risk", cell: r => <StatusBadge value={r[6]} /> },
];

export default function CashFlow({ data, notify }) {
  const c = data.summary.cashflow;
  const [selected, setSelected] = useState(new Set());
  const [collected, setCollected] = useState(new Set());

  // NOTE: "collected" is only remembered in this browser session --
  // saving it to the database needs a backend endpoint (planned).
  const rows = useMemo(() => data.payments.filter(r => !collected.has(r[0])), [data.payments, collected]);

  const markCollected = () => {
    if (selected.size === 0) return notify("Select one or more invoices first.");
    setCollected(new Set([...collected, ...selected]));
    notify(`${selected.size} payment record(s) marked as collected.`);
    setSelected(new Set());
  };

  const exportCsv = () => {
    downloadCsv("cashflow", [["Invoice", "Party", "Type", "Due date", "Amount", "Ageing", "Risk"], ...data.payments]);
    notify("cashflow CSV downloaded.");
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="ANALYTICS / CASH FLOW"
        title="Payment & cash-flow dashboard"
        subtext="Receivables, payables, credit exposure, ageing and working capital."
      >
        <button className="primary-button" onClick={exportCsv}>⇩ Export cash-flow CSV</button>
      </PageHeading>

      <KpiGrid>
        <Kpi label="CUSTOMER RECEIVABLES" value={formatMoney(c.receivables)} detail={`${formatMoney(c.overdue_receivables)} overdue`} tone="warning" />
        <Kpi label="SUPPLIER PAYABLES" value={formatMoney(c.payables)} detail={`${formatMoney(c.payables_due_week)} due this week`} tone="warning" />
        <Kpi label="LARGEST DEBTOR" value={formatMoney(c.top_debtor_amount)} detail={`${c.top_debtor} · ${c.top_debtor_share}% of receivables`} tone="negative" />
        <Kpi
          label="NET WORKING CAPITAL"
          value={formatMoney(c.net_working_capital)}
          detail="Receivables + stock − payables"
          tone={c.net_working_capital >= 0 ? "positive" : "negative"}
        />
      </KpiGrid>

      <div className="two-col">
        <article className="card">
          <p className="card-label">RECEIVABLE AGEING</p><h2>Collection priority</h2>
          <BucketChart items={c.ageing} />
        </article>
        <article className="card">
          <p className="card-label">WORKING CAPITAL METRICS</p><h2>Cash conversion cycle</h2>
          <div className="compact-list">
            {c.working_capital.map(item => (
              <div key={item[0]}><span>{item[0]}</span><b>{item[1]}</b></div>
            ))}
          </div>
        </article>
      </div>

      <DataTable
        label="PAYMENT QUEUE"
        title="Due, overdue and credit-limit tracking"
        columns={columns}
        rows={rows}
        placeholder="Search party or invoice"
        selection={{ ids: selected, setIds: setSelected, getId: r => r[0] }}
        action={<button className="ghost-button" onClick={markCollected}>Mark selected collected</button>}
      />
    </section>
  );
}
