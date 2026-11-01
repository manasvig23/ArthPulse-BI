import PageHeading from "../components/PageHeading.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

export default function Alerts({ data }) {
  return (
    <section className="page active">
      <PageHeading
        eyebrow="WORKSPACE / ALERTS"
        title="Alerts that deserve attention."
        subtext="Stock, supplier, payment, compliance and customer-credit risks."
      />
      <div className="alert-list">
        {data.alerts.length === 0 && <p className="empty">No active alerts.</p>}
        {data.alerts.map((alert, i) => (
          <article className="alert" key={i}>
            <i />
            <div>
              <strong>{alert[1]}</strong>
              <p>{alert[2]}</p>
            </div>
            <StatusBadge value={alert[0]} />
          </article>
        ))}
      </div>
    </section>
  );
}
