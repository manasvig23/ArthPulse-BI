"""Rule-based recommendation cards with optional SHAP factor notes. Persist feedback."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from . import compliance, forecasts, summaries
from .explainability import explain_sales_drivers
from .models import InventoryItem, PartyMaster, Recommendation, Voucher
from .rules import REFERENCE_DATE, get_alerts


def _upsert(db, rec_key, **fields) -> Recommendation:
    row = db.query(Recommendation).filter(Recommendation.rec_key == rec_key).first()
    if row is None:
        row = Recommendation(rec_key=rec_key, **fields)
        db.add(row)
    else:
        for k, v in fields.items():
            if k in ("status", "feedback") and getattr(row, k):
                continue
            if k not in ("status", "feedback"):
                setattr(row, k, v)
    return row


def refresh_recommendations(db: Session, period="monthly") -> list[dict]:
    summary = summaries.build_summary(db, period)
    shap = explain_sales_drivers(db)
    as_of = REFERENCE_DATE.isoformat()
    label = summary["label"]
    window = f"{summary['window']['start']} to {summary['window']['end']}"

    # 1. Customer recovery / inactivity
    sales = db.query(Voucher).filter(Voucher.voucher_type == "Sales").all()
    by_party = {}
    for v in sales:
        by_party.setdefault(v.party_name, []).append(v)
    for party, rows in by_party.items():
        last = max(v.voucher_date for v in rows)
        days = (REFERENCE_DATE - last).days
        seg = rows[0].segment
        if days >= 60 or seg == "Inactive":
            _upsert(db, f"inactive:{party}",
                    kind="customer_recovery",
                    title=f"Review {party} — no purchase for {days} days",
                    reason=f"{party} is marked {seg or 'inactive'}. Last invoice {last.isoformat()}.",
                    party=party, amount=sum(v.amount for v in rows),
                    period_label=label, data_as_of=as_of,
                    evidence_json=json.dumps({"last_invoice": last.isoformat(), "days": days, "segment": seg}),
                    action="Call the buyer and check stock, price or a competitor win.")
        if seg == "Declining":
            _upsert(db, f"decline:{party}",
                    kind="customer_recovery",
                    title=f"{party} sales are declining",
                    reason="Recent 90-day sales are more than 15% below the prior 90 days.",
                    party=party, amount=sum(v.amount for v in rows),
                    period_label=label, data_as_of=as_of,
                    shap_json=json.dumps(shap.get("plain_english")),
                    evidence_json=json.dumps({"segment": "Declining", "period": window}),
                    action="Review discount, fill-rate and whether a core SKU was out of stock.")

    # 2. Cross-sell
    for row in (summary.get("sales") or {}).get("cross_sell") or []:
        _upsert(db, f"cross:{row[0]}",
                kind="cross_sell", title=f"{row[0]}: {row[1]}",
                reason="This customer buys from you but not the product similar customers buy most.",
                party=row[0], period_label=label, data_as_of=as_of,
                evidence_json=json.dumps({"suggestion": row[1], "order_value": row[2]}),
                action="Offer the missing SKU on the next order.")

    # 3. Slow stock / reorder
    for it in db.query(InventoryItem).all():
        if it.movement == "Non-moving" or it.movement == "Slow-moving":
            _upsert(db, f"slow:{it.sku}",
                    kind="slow_stock",
                    title=f"Clear or pause buying {it.product}",
                    reason=f"{it.product} is {it.movement} at {it.branch} (value ₹{it.value:,.0f}).",
                    product=it.product, amount=it.value,
                    period_label=label, data_as_of=as_of,
                    evidence_json=json.dumps({"sku": it.sku, "qty": it.quantity, "movement": it.movement}),
                    action="Reduce the next purchase order or run a clearance at this godown.")
        if it.quantity < it.reorder_level:
            _upsert(db, f"reorder:{it.sku}",
                    kind="reorder",
                    title=f"Reorder {it.product}",
                    reason=f"On-hand {it.quantity} is below reorder {it.reorder_level}. Lead time {it.lead_time_days or '—'} days.",
                    product=it.product, amount=it.value,
                    period_label=label, data_as_of=as_of,
                    evidence_json=json.dumps({"sku": it.sku, "on_hand": it.quantity, "reorder": it.reorder_level,
                                              "lead_time": it.lead_time_days, "safety": it.safety_stock}),
                    action="Place a PO covering lead time plus safety stock.")

    # 4. Collections
    for a in get_alerts(db):
        if a[3] == "cashflow" and "Receivable" in a[1]:
            _upsert(db, f"collect:{a[2][:40]}",
                    kind="collection", title=a[1], reason=a[2],
                    period_label=label, data_as_of=as_of,
                    evidence_json=json.dumps({"alert": a}),
                    action="Follow up on the oldest invoice first.")

    # 5. Working capital
    wc = (summary.get("cashflow") or {}).get("working_capital") or []
    rec_days = next((w[1] for w in wc if w[0].startswith("Receivable")), None)
    _upsert(db, "wc:receivable-days",
            kind="working_capital",
            title="Review receivable days",
            reason=f"Receivable days are {rec_days}. Collection delay ties up cash.",
            period_label=label, data_as_of=as_of,
            evidence_json=json.dumps({"working_capital": wc}),
            shap_json=json.dumps(shap.get("plain_english")),
            action="Prioritise overdue accounts above 60 days.")

    # 6. Compliance → recommendation
    for rule in compliance.build_compliance(db)["rules"]:
        for f in rule["findings"][:3]:
            _upsert(db, f"comp:{rule['id']}:{f['party']}",
                    kind="compliance",
                    title=f"{rule['name']}: {f['title']}",
                    reason=f["summary"],
                    party=f["party"], amount=f["exposure"],
                    period_label=label, data_as_of=as_of,
                    evidence_json=json.dumps(f.get("evidence")),
                    action=f["action"])

    fc = forecasts.build_forecasts(db)
    if fc["sales"]["forecast"] is not None:
        _upsert(db, "forecast:sales",
                kind="forecast",
                title=f"Next month sales may be around ₹{fc['sales']['forecast']:,.0f}",
                reason=fc["sales"]["method"],
                period_label=fc["sales"]["next_month"], data_as_of=as_of,
                evidence_json=json.dumps(fc["sales"]),
                action="If the trend holds, plan collections and purchase cover for that level.")

    db.commit()
    return list_recommendations(db)


def list_recommendations(db: Session, include_dismissed=False) -> list[dict]:
    q = db.query(Recommendation).order_by(Recommendation.id.desc())
    rows = q.all()
    out = []
    for r in rows:
        if not include_dismissed and r.status == "dismissed":
            continue
        out.append({
            "id": r.rec_key,
            "kind": r.kind,
            "title": r.title,
            "reason": r.reason,
            "party": r.party,
            "product": r.product,
            "amount": r.amount,
            "period": r.period_label,
            "data_as_of": r.data_as_of,
            "action": r.action,
            "status": r.status,
            "feedback": r.feedback,
            "shap": json.loads(r.shap_json) if r.shap_json else None,
            "evidence": json.loads(r.evidence_json) if r.evidence_json else None,
        })
    return out[:40]


def set_feedback(db: Session, rec_key: str, action: str) -> dict:
    row = db.query(Recommendation).filter(Recommendation.rec_key == rec_key).first()
    if row is None:
        raise KeyError(rec_key)
    if action in ("saved", "dismissed"):
        row.status = action
    elif action in ("useful", "not_useful"):
        row.feedback = action
        if action == "not_useful":
            row.status = "dismissed"
    else:
        raise ValueError("Unknown action")
    db.commit()
    return {"id": row.rec_key, "status": row.status, "feedback": row.feedback}
