export function KpiGrid({ children }) {
  return <div className="kpi-grid">{children}</div>;
}

export default function Kpi({ label, value, detail, tone = "" }) {
  return (
    <article className="kpi">
      <p>{label}</p>
      <strong>{value}</strong>
      <small className={tone}>{detail}</small>
    </article>
  );
}
