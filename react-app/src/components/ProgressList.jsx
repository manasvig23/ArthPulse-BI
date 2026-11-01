import { formatMoney } from "../format.js";

// items: { "South": 963740, "West": 551680, ... }
export default function ProgressList({ items }) {
  const entries = Object.entries(items || {});

  if (!entries.length) return <p className="empty">No data for this period.</p>;

  const maximum = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="progress-list">
      {entries.map(([label, value]) => (
        <div className="progress-item" key={label}>
          <div><span>{label}</span><b>{formatMoney(value)}</b></div>
          <i><em style={{ width: `${Math.max(4, (value / maximum) * 100)}%` }} /></i>
        </div>
      ))}
    </div>
  );
}
