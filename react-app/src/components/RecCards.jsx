import { sendJson } from "../api.js";
import { formatMoney } from "../format.js";
import StatusBadge from "./StatusBadge.jsx";

export default function RecCards({ items, notify, onChange }) {
  if (!items?.length) return <p className="empty">No open recommendations.</p>;

  const act = async (id, action) => {
    try {
      await sendJson("POST", "/api/ai/recommendation-feedback", { recommendation_id: id, action });
      notify(`Marked ${action.replace("_", " ")}.`);
      onChange?.();
    } catch (e) {
      notify(e.message);
    }
  };

  return (
    <div className="rec-grid">
      {items.slice(0, 6).map(r => (
        <article className="rec-card" key={r.id}>
          <div className="rec-card-head">
            <StatusBadge value={r.kind} />
            <small>{r.period} · as of {r.data_as_of || "—"}</small>
          </div>
          <h3>{r.title}</h3>
          <p>{r.reason}</p>
          {r.party && <p className="rec-meta">Party: {r.party}{r.amount ? ` · ${formatMoney(r.amount)}` : ""}</p>}
          {r.shap && <p className="rec-meta">{typeof r.shap === "string" ? r.shap : r.shap.plain_english || ""}</p>}
          {r.action && <div className="callout"><strong>CONSIDER</strong>{r.action}</div>}
          <div className="rec-actions">
            <button className="ghost-button" onClick={() => act(r.id, "saved")}>Save</button>
            <button className="ghost-button" onClick={() => act(r.id, "useful")}>Useful</button>
            <button className="ghost-button" onClick={() => act(r.id, "not_useful")}>Not useful</button>
            <button className="ghost-button" onClick={() => act(r.id, "dismissed")}>Dismiss</button>
          </div>
        </article>
      ))}
    </div>
  );
}
