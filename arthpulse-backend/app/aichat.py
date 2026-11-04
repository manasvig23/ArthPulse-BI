"""Grounded assistant: answers only from dashboard JSON. Gemini if a key exists, else rules."""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

from . import compliance, forecasts, quality, recommendations, summaries
from .database import SessionLocal
from .explainability import explain_sales_drivers
from .tally_sync import last_sync

load_dotenv()


def _context(period: str) -> dict:
    db = SessionLocal()
    try:
        summary = summaries.build_summary(db, period)
        recs = recommendations.list_recommendations(db)
        shap = explain_sales_drivers(db, period)
        q = quality.build_quality(db)
        fc = forecasts.build_forecasts(db)
        comp = compliance.build_compliance(db)
        sync = last_sync(db)
        return {
            "period": period,
            "window": summary.get("window"),
            "label": summary.get("label"),
            "last_sync": sync,
            "quality_warnings": q.get("warnings"),
            "overview": summary.get("overview"),
            "sales": {k: v for k, v in (summary.get("sales") or {}).items() if k != "trend"},
            "purchases": summary.get("purchases"),
            "inventory": summary.get("inventory"),
            "cashflow": summary.get("cashflow"),
            "compliance_summary": comp.get("summary"),
            "compliance_headlines": [r["headline"] for r in comp.get("rules", [])],
            "recommendations": [{"title": r["title"], "reason": r["reason"]} for r in recs[:8]],
            "forecast": {
                "next_month_sales": fc["sales"]["forecast"],
                "method": fc["sales"]["method"],
                "expected_cash_in": fc["cash"]["expected_in"],
                "expected_cash_out": fc["cash"]["expected_out"],
            },
            "drivers": shap,
        }
    finally:
        db.close()


def _needs_followup(question: str) -> str | None:
    q = question.strip().lower()
    if len(q) < 8:
        return "Which period, customer, product or invoice should I look at?"
    if q in {"help", "hi", "hello", "hey"}:
        return "Ask about sales, slow stock, overdue invoices, GST, or what to do next this month."
    return None


def _rule_answer(question: str, ctx: dict) -> str:
    q = question.lower()
    o = ctx.get("overview") or {}
    window = ctx.get("window") or {}
    as_of = (ctx.get("last_sync") or {}).get("finished_at") or ctx.get("drivers", {}).get("as_of")
    footer = f"\n\nPeriod: {ctx.get('label')} ({window.get('start')} to {window.get('end')}). Data as of {as_of or 'the demo reference date'}."
    warnings = ctx.get("quality_warnings") or []
    if warnings:
        footer += " Note: " + warnings[0]

    def inr(n):
        try:
            return f"₹{round(n):,}"
        except Exception:
            return "—"

    if "why" in q and "sales" in q:
        g = o.get("growth")
        d = (ctx.get("drivers") or {}).get("plain_english")
        return (f"Net sales this period are {inr(o.get('net_sales'))}"
                f"{'' if g is None else f', {g}% versus the previous period'}. {d}" + footer)
    if "not purchased" in q or "60 days" in q or "inactive" in q:
        recs = [r for r in ctx.get("recommendations") or [] if "no purchase" in r["title"].lower() or "declin" in r["title"].lower()]
        if not recs:
            return "No inactive-customer recommendations are open right now." + footer
        lines = "\n".join(f"- {r['title']}" for r in recs[:6])
        return "Customers to review:\n" + lines + footer
    if "slow" in q or "non-moving" in q:
        inv = ctx.get("inventory") or {}
        return (f"Stock value is {inr(inv.get('stock_value'))}. "
                f"See inventory efficiency: {inv.get('efficiency')}. "
                "Non-moving and slow-moving items are listed on the Inventory page." + footer)
    if "overdue" in q or "invoice" in q:
        c = ctx.get("cashflow") or {}
        return (f"Receivables {inr(c.get('receivables'))}, of which overdue "
                f"{inr(c.get('overdue_receivables'))}. Largest debtor: {c.get('top_debtor')}." + footer)
    if "supplier" in q and ("price" in q or "rate" in q):
        p = ctx.get("purchases") or {}
        moves = p.get("price_moves") or []
        if not moves:
            return "Not enough repeat purchases to show a supplier rate change." + footer
        lines = "\n".join(f"- {m[0]} / {m[2]}: {m[1]}" for m in moves)
        return "Supplier price movement:\n" + lines + footer
    if "stock" in q and "review" in q or "reorder" in q:
        recs = [r for r in ctx.get("recommendations") or [] if r["title"].lower().startswith("reorder") or "clear" in r["title"].lower()]
        lines = "\n".join(f"- {r['title']}" for r in recs[:6]) or "No reorder cards are open."
        return lines + footer
    if "gst" in q or "tds" in q or "compliance" in q or "269" in q:
        heads = ctx.get("compliance_headlines") or []
        s = ctx.get("compliance_summary") or {}
        return (f"{s.get('findings', 0)} findings, {inr(s.get('amount_flagged'))} flagged.\n"
                + "\n".join(f"- {h}" for h in heads) + footer)
    if "forecast" in q or "next month" in q or "may happen" in q:
        f = ctx.get("forecast") or {}
        if f.get("next_month_sales") is None:
            return "There is not enough history for a sales forecast." + footer
        return (f"Moving-average sales for next month: {inr(f['next_month_sales'])}. {f.get('method')} "
                f"Expected cash in {inr(f.get('expected_cash_in'))}, out {inr(f.get('expected_cash_out'))}." + footer)

    return (f"Net sales {inr(o.get('net_sales'))}, receivables {inr(o.get('receivables'))}, "
            f"stock {inr(o.get('stock_value'))}. Ask about sales, stock, overdue invoices or compliance." + footer)


def answer_query(user_prompt: str, period: str = "monthly") -> dict:
    follow = _needs_followup(user_prompt)
    ctx = _context(period)
    if follow:
        return {
            "status": "followup",
            "answer": follow,
            "period": period,
            "window": ctx.get("window"),
            "data_as_of": (ctx.get("last_sync") or {}).get("finished_at"),
            "grounded_in_data": True,
            "links": ["overview"],
        }

    grounded = _rule_answer(user_prompt, ctx)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "success",
            "answer": grounded,
            "period": period,
            "window": ctx.get("window"),
            "data_as_of": (ctx.get("last_sync") or {}).get("finished_at"),
            "grounded_in_data": True,
            "engine": "rules",
            "links": ["overview", "alerts"],
        }

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = f"""You are ArthPulse. Answer ONLY from CONTEXT. If the number is not in CONTEXT, say the data is missing.
Never invent a rupee figure. Never mention SHAP, XGBoost or model scores; speak as a business manager.
State the period and data timestamp. Use line breaks and dashes for lists.

CONTEXT:
{json.dumps(ctx, default=str)[:12000]}

QUESTION: {user_prompt}
"""
        response = model.generate_content(prompt, generation_config={"temperature": 0.15, "max_output_tokens": 700})
        text = (response.text or "").strip() or grounded
        if ctx.get("quality_warnings") and not ctx.get("quality_warnings")[0][:12] in text:
            text += "\n\n" + ctx["quality_warnings"][0]
        return {
            "status": "success",
            "answer": text,
            "period": period,
            "window": ctx.get("window"),
            "data_as_of": (ctx.get("last_sync") or {}).get("finished_at"),
            "grounded_in_data": True,
            "engine": "gemini+context",
            "links": ["overview"],
        }
    except Exception:
        return {
            "status": "success",
            "answer": grounded,
            "period": period,
            "window": ctx.get("window"),
            "data_as_of": (ctx.get("last_sync") or {}).get("finished_at"),
            "grounded_in_data": True,
            "engine": "rules-fallback",
            "links": ["overview"],
        }


class ArthPulseAIService:
    def answer_query(self, user_prompt: str, period: str = "monthly"):
        return answer_query(user_prompt, period)


ai_service = ArthPulseAIService()
